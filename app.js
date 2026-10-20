/* Label Check v2 – app logic. Plain JavaScript, no libraries.
   Uses LCDB (db.js) for the ingredient database and LC_TEXT (i18n.js) for the screen texts.
   Parts: settings, storage, texts, matching, analysis, product lookup, screens, detail, lists, camera, start. */
'use strict';

(() => {
  // ---------- Settings ----------
  const OFF = 'https://world.openfoodfacts.org';
  const OBF = 'https://world.openbeautyfacts.org';
  const FIELDS = [
    'code', 'product_name', 'product_name_de', 'product_name_en', 'product_name_bg', 'generic_name', 'brands',
    'image_front_small_url', 'image_small_url',
    'ingredients_text', 'ingredients_text_de', 'ingredients_text_en', 'ingredients_text_bg',
    'ingredients_tags', 'additives_tags', 'allergens_tags', 'ingredients_analysis_tags',
    'nutriscore_grade', 'nova_group', 'last_modified_t'
  ].join(',');
  const CACHE_DAYS = 7;
  const MAX_PRODUCTS = 300;
  const MAX_HISTORY = 100;
  const PROMPT =
    'Read the ingredient list on this product label.\n' +
    'Reply with the ingredients only, as plain text, separated by commas, in the language on the label.\n' +
    'If the label is not in English, add one more line that starts with "EN:" and gives the English translation.';

  const QUICK_PICKS = [
    'palm oil, palm fat, palm kernel*, palmöl, palmfett, palmkern*, палмово масло, палмова мазнина, палмов*',
    'glucose-fructose syrup, glukose-fruktose-sirup, isoglucose, глюкозо-фруктозен сироп',
    'alcohol denat, alkohol denat',
    'silicones, dimethicone, *methicone, *siloxane',
    'sodium lauryl sulfate, sodium laureth sulfate, sls, sles'
  ];

  // One order and one colour everywhere: tiles, strip and groups.
  const GROUPS = ['red', 'orange', 'info', 'green'];
  const LEVEL_GROUP = { b: 'red', c: 'orange', u: 'orange', r: 'info', n: 'green' };
  const SEV = { b: 5, c: 4, u: 3, r: 2, n: 1 };
  const VERDICT_DOT = { avoid: 'g-red', check: 'g-orange', ok: 'g-green', unknown: 'g-grey' };
  const LOCALE = { en: 'en-GB', de: 'de-AT', bg: 'bg-BG' };

  // ---------- Storage (stays on this phone) ----------
  const store = {
    get(key, fallback) {
      try {
        const v = localStorage.getItem('lc.' + key);
        return v === null ? fallback : JSON.parse(v);
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem('lc.' + key, JSON.stringify(value)); return true; }
      catch (e) { toast(t('toast.saveFail')); return false; }
    }
  };

  const state = {
    avoid: store.get('avoid', []),           // [{id, text}]
    history: store.get('history', []),       // [{code, name, brand, kind, verdict, time}]
    products: store.get('products', {}),     // {code: product}
    favs: store.get('favs', []),             // [code]
    allergens: Object.assign({ food: [], cos: [] }, store.get('allergens', {})), // ticked ids / annex refs
    avoidFragrance: store.get('avoidFragrance', false),
    lang: store.get('lang', 'auto'),
    theme: store.get('theme', 'auto'),
    bigText: store.get('bigText', false),
    current: null,   // { p, a } shown on the scan tab
    filter: null,    // group shown alone, or null
    open: null       // which groups are open
  };

  // ---------- Texts ----------
  const TEXT = window.LC_TEXT || { en: {} };
  let LANG = 'en';

  function pickLang() {
    if (state.lang !== 'auto' && TEXT[state.lang]) return state.lang;
    for (const l of navigator.languages || [navigator.language || 'en']) {
      const c = String(l).slice(0, 2).toLowerCase();
      if (TEXT[c]) return c;
    }
    return 'en';
  }

  function t(key, vars) {
    let s = TEXT[LANG] && TEXT[LANG][key];
    if (s === undefined) s = TEXT.en[key];
    if (s === undefined) s = key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m));
    return s;
  }
  const tn = (key, n, vars) => t(key + (n === 1 ? '.one' : '.other'), Object.assign({ n }, vars));
  const tr = obj => (obj && (obj[LANG] || obj.en)) || '';
  const levelName = lv => tr(META() && META().levels[lv]);
  const cap = s => (s ? s.charAt(0).toLocaleUpperCase() + s.slice(1) : s);

  // A text with {placeholders} filled by nodes (e.g. links).
  function tNodes(key, nodes) {
    return t(key).split(/(\{\w+\})/).map(part => {
      const m = part.match(/^\{(\w+)\}$/);
      return m && nodes[m[1]] ? nodes[m[1]] : part;
    });
  }

  function applyTexts() {
    document.documentElement.lang = LANG;
    document.querySelectorAll('[data-t]').forEach(n => { n.textContent = t(n.dataset.t); });
    document.querySelectorAll('[data-t-ph]').forEach(n => { n.placeholder = t(n.dataset.tPh); });
    document.querySelector('.tabbar').setAttribute('aria-label', [t('tab.scan'), t('tab.favs'), t('tab.list'), t('tab.history')].join(', '));
    renderCredit();
  }

  // ---------- Text matching (your list) ----------
  // Same rule as the database: lower case, no accents, Cyrillic kept. "E 250" -> "e250".
  const joinE = s => String(s || '').replace(/\b[eE][\s\-‐-―]*(\d{3,4}[a-zA-Z]?)\b/g, 'e$1');
  const nrm = s => (window.LCDB ? LCDB.norm(joinE(s)) : String(s || '').toLowerCase());

  const reCache = new Map();
  // Whole-word match. A * allows any letters there ("palm kernel*", "*siloxane").
  function termRe(term) {
    if (reCache.has(term)) return reCache.get(term);
    const tt = nrm(String(term).replace(/\*/g, ' zzstarzz ')).replace(/ ?zzstarzz ?/g, '*');
    let re = null;
    if (tt.replace(/\*/g, '').trim()) {
      const body = tt.split('*').map(p => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('[a-z0-9\\u0430-\\u044f]*');
      re = new RegExp('(?:^| )' + body + '(?= |$)');
    }
    reCache.set(term, re);
    return re;
  }

  const termsOf = item => item.text.split(',').map(s => s.trim()).filter(Boolean);

  // First item of your list that matches one of the texts -> { item, term }.
  function matchAvoid(texts) {
    const hay = texts.filter(Boolean).map(nrm);
    for (const item of state.avoid) {
      for (const term of termsOf(item)) {
        const re = termRe(term);
        if (re && hay.some(h => re.test(h))) return { item, term, name: termsOf(item)[0] };
      }
    }
    return null;
  }

  // ---------- Names ----------
  const ACRONYMS = new Set(('CI PEG PPG BHT BHA EDTA DMDM MEA DEA TEA MIPA PVP PCA HCL HC DNA UV II III IV VP VA TDI HDI IPDI ' +
    'MDI SD PG TBHQ PABA MI MCI AHA PHA EO PO PHB HEDP GLDA MGDA DTPA PET PTFE PVA PVC PE PP PU SLS SLES ALS TIPA AMP DMAE').split(' '));
  // "SODIUM BENZOATE" -> "Sodium Benzoate", "CI 77891" stays, "PEG-40" stays.
  function niceName(s) {
    return String(s || '').toLowerCase().replace(/[a-z]+/g, w => {
      const u = w.toUpperCase();
      return ACRONYMS.has(u) || w.length === 1 ? u : w[0].toUpperCase() + w.slice(1);
    });
  }
  const cleanSeg = s => cap(String(s || '').replace(/\s+/g, ' ').replace(/[.\s]+$/, '').trim());

  // ---------- Database ----------
  let DBINFO = null;   // null = loading, false = failed, object = ready
  const META = () => (DBINFO ? LCDB.meta() : null);
  const dbReady = (window.LCDB ? LCDB.load('data/') : Promise.reject(new Error('db.js missing')))
    .then(info => { DBINFO = info; return info; })
    .catch(() => { DBINFO = false; return null; });

  // ---------- Analysis ----------
  // Every ingredient becomes a row with a level (b c u r n) and a group (red orange info green).
  function analyze(p) {
    const text = p.ingredientsText || '';
    let rows = p.kind === 'cosmetic' ? analyzeCosmetic(text) : analyzeFood(p, text);

    // Your list: also look in the other texts (e.g. the "EN:" line from Claude).
    const extraTexts = (p.texts || []).filter(x => x && x !== text);
    if (extraTexts.length) {
      for (const item of state.avoid) {
        if (rows.some(r => r.mine && r.mine.item.id === item.id)) continue;
        const hit = matchAvoidItem(item, extraTexts);
        if (hit) rows.push(personalRow(hit));
      }
    }

    rows.sort((x, y) => (x.pos || 999) - (y.pos || 999));
    rows.forEach((r, i) => { r.i = i; });

    const counts = { red: 0, orange: 0, info: 0, green: 0 };
    for (const r of rows) counts[r.group]++;
    const verdict = counts.red ? 'avoid' : counts.orange ? 'check' : rows.length ? 'ok' : 'unknown';
    return {
      verdict, rows, counts,
      summary: summarize(verdict, rows, counts),
      total: rows.filter(r => r.pos).length,
      fragrance: rows.filter(r => r.fragrance || r.allergen).length
    };
  }

  function matchAvoidItem(item, texts) {
    const hay = texts.map(nrm);
    for (const term of termsOf(item)) {
      const re = termRe(term);
      if (re && hay.some(h => re.test(h))) return { item, term, name: termsOf(item)[0] };
    }
    return null;
  }

  function personalRow(mine) {
    return {
      pos: null, kind: 'extra', label: cap(mine.name), text: '', level: 'n', group: 'red', why: 'mine', mine,
      sub: { lvl: { text: t('tag.mine'), g: 'red' }, parts: [t('tag.fromData')] }
    };
  }

  function analyzeCosmetic(text) {
    return LCDB.checkCosmetic(text, LANG).map(r => {
      const mine = matchAvoid([r.text, r.found ? r.name : '']);
      const tickedAllergen = !!(r.allergen && state.allergens.cos.includes(r.allergenRef));
      const fragAvoid = !!(state.avoidFragrance && (r.fragrance || r.allergen));
      const why = r.level === 'b' ? 'b' : mine ? 'mine' : tickedAllergen ? 'allergen' : fragAvoid ? 'fragrance' : null;
      const row = {
        pos: r.pos, kind: 'cosmetic', text: r.text,
        label: r.found ? niceName(r.name) : cleanSeg(r.text),
        level: r.level, group: why ? 'red' : LEVEL_GROUP[r.level] || 'green', why, mine, tickedAllergen, fragAvoid,
        fragrance: r.fragrance, allergen: r.allergen, nano: r.nano, mayContain: r.mayContain, found: r.found, src: r
      };
      row.sub = cosmeticSub(row);
      return row;
    });
  }

  function cosmeticTags(row) {
    const tags = [];
    if (row.allergen) tags.push(t('tag.allergen'));
    else if (row.fragrance) tags.push(t('tag.fragrance'));
    if (row.nano) tags.push(t('tag.nano'));
    if (row.mayContain) tags.push(t('tag.may'));
    if (!row.found) tags.push(t('tag.notFound'));
    return tags;
  }

  function cosmeticSub(row) {
    const r = row.src, tags = cosmeticTags(row);
    const firstReason = r.reasons && r.reasons[0] ? r.reasons[0].text : '';
    if (row.why === 'b') return { lvl: { text: levelName('b'), g: 'red' }, parts: tags.length ? tags : (r.functions || []).slice(0, 1) };
    if (row.why === 'mine') return { lvl: { text: t('tag.mine'), g: 'red' }, parts: tags };
    if (row.why === 'allergen') return { lvl: { text: t('tag.allergenYours'), g: 'red' }, parts: tags };
    if (row.why === 'fragrance') return { lvl: { text: t('tag.fragranceAvoid'), g: 'red' }, parts: tags };
    if (row.group === 'orange') return { lvl: { text: levelName(row.level), g: 'orange' }, parts: [firstReason] };
    if (row.group === 'info') return { lvl: { text: levelName(row.level), g: 'info' }, parts: tags.length ? tags : [firstReason] };
    return { lvl: null, parts: [...new Set(tags.concat((r.functions || []).slice(0, 1)))] };
  }

  const ALLERGEN_TAG = /^en:(gluten|crustaceans|eggs|fish|peanuts|soybeans|milk|nuts|celery|mustard|sesame-seeds|sulphur-dioxide-and-sulphites|lupin|molluscs)$/;

  function analyzeFood(p, text) {
    const segs = LCDB.splitIngredients(text);
    const segN = segs.map(nrm);
    const res = LCDB.checkFood(text, LANG);
    const blank = (pos, txt, label) => ({ pos, kind: 'food', text: txt, label, additives: [], rules: [], allergens: [] });
    const rows = segs.map((s, i) => blank(i + 1, s, cleanSeg(s)));
    const extra = [];
    const at = pos => (pos && rows[pos - 1]) || null;

    for (const a of res.additives) {
      const row = at(a.pos);
      if (row) row.additives.push(a);
      else { const x = blank(null, a.e + ' ' + a.name, cap(a.name) + ' (' + a.e + ')'); x.additives.push(a); extra.push(x); }
    }
    for (const r of res.rules) {
      const re = termRe(r.matched);
      const i = re ? segN.findIndex(s => re.test(s)) : -1;
      if (i >= 0) rows[i].rules.push(r);
      else { const x = blank(null, r.matched, cap(r.matched.replace(/\*/g, ''))); x.rules.push(r); extra.push(x); }
    }
    for (const al of res.allergens) {
      const row = at(al.pos);
      if (row) row.allergens.push(al);
    }

    // Product data from Open Food Facts: additives and allergens the text did not show.
    const seenE = new Set(res.additives.map(a => a.e.toLowerCase()));
    for (const tag of p.tags || []) {
      const m = String(tag).match(/^en:(e\d{3,4}[a-z]?)$/);
      if (!m || seenE.has(m[1])) continue;
      const a = LCDB.checkFood(m[1].toUpperCase(), LANG).additives[0];
      if (!a || seenE.has(a.e.toLowerCase())) continue;
      seenE.add(a.e.toLowerCase());
      const x = blank(null, a.e, cap(a.name) + ' (' + a.e + ')');
      x.additives.push(a); x.fromData = true;
      extra.push(x);
    }
    const foundAl = new Set(res.allergens.map(a => a.id));
    const names = Object.fromEntries(LCDB.foodAllergens(LANG).map(a => [a.id, a.name]));
    for (const tag of p.allergens || []) {
      const m = String(tag).match(ALLERGEN_TAG);
      if (!m || foundAl.has(m[1]) || !state.allergens.food.includes(m[1])) continue;
      foundAl.add(m[1]);
      const x = blank(null, names[m[1]] || m[1], cap(names[m[1]] || m[1]));
      x.allergens.push({ id: m[1], name: names[m[1]] || m[1] }); x.fromData = true;
      extra.push(x);
    }

    return rows.concat(extra).map(row => {
      let level = 'n';
      for (const x of [...row.additives, ...row.rules]) if (SEV[x.level] > SEV[level]) level = x.level;
      const mine = matchAvoid([row.text, ...row.additives.map(a => a.e + ' ' + a.name)]);
      const ticked = row.allergens.filter(a => state.allergens.food.includes(a.id));
      const why = level === 'b' ? 'b' : mine ? 'mine' : ticked.length ? 'allergen' : null;
      row.level = level;
      row.mine = mine;
      row.tickedAllergens = ticked;
      row.why = why;
      row.group = why ? 'red' : level === 'c' || level === 'u' ? 'orange' : level === 'r' || row.allergens.length ? 'info' : 'green';
      row.sub = foodSub(row);
      return row;
    });
  }

  function foodSub(row) {
    const parts = [];
    for (const a of row.additives) parts.push(a.e + ' ' + a.name);
    const al = row.allergens.map(a => t('tag.foodAllergen', { name: cap(a.name) }));
    if (row.fromData) parts.push(t('tag.fromData'));
    if (row.why === 'b') return { lvl: { text: levelName('b'), g: 'red' }, parts };
    if (row.why === 'mine') return { lvl: { text: t('tag.mine'), g: 'red' }, parts: parts.concat(al) };
    if (row.why === 'allergen') return { lvl: { text: t('tag.allergenYours'), g: 'red' }, parts: row.tickedAllergens.map(a => cap(a.name)).concat(parts) };
    if (row.group === 'orange' || (row.group === 'info' && row.level === 'r')) {
      const reason = !row.additives.length && row.rules[0] && row.rules[0].reasons[0] ? [row.rules[0].reasons[0].text] : [];
      return { lvl: { text: levelName(row.level), g: row.group }, parts: parts.concat(al, reason) };
    }
    if (row.group === 'info') return { lvl: null, parts: al.concat(parts) };
    const classes = row.additives.flatMap(a => a.classes || []).slice(0, 1);
    return { lvl: null, parts: parts.concat(classes) };
  }

  // The name used in the one-line summary.
  function shortName(row) {
    if (row.why === 'mine') return cap(row.mine.name);
    if (row.why === 'allergen' && row.kind === 'food') return cap(row.tickedAllergens[0].name);
    if (row.kind === 'food') {
      const a = row.additives.slice().sort((x, y) => SEV[y.level] - SEV[x.level])[0];
      if (a && a.level === row.level) return cap(a.name) + ' (' + a.e + ')';
    }
    return row.label;
  }

  function summarize(verdict, rows, counts) {
    if (verdict === 'unknown') return t('sum.unknown');
    if (verdict === 'avoid') {
      if (counts.red > 1) return t('sum.redN', { n: counts.red });
      const r = rows.find(x => x.group === 'red');
      const key = { b: 'sum.red1.b', mine: 'sum.red1.mine', allergen: 'sum.red1.allergen', fragrance: 'sum.red1.fragrance' }[r.why];
      return t(key, { name: shortName(r) });
    }
    if (verdict === 'check') {
      if (counts.orange > 1) return t('sum.orN', { n: counts.orange });
      const r = rows.find(x => x.group === 'orange');
      return t(r.level === 'u' ? 'sum.or1.u' : 'sum.or1.c', { name: shortName(r) });
    }
    return counts.info ? t('sum.okInfo', { n: counts.info }) : t('sum.ok');
  }

  // ---------- Product lookup ----------
  async function fetchJson(url, ms) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), ms || 9000);
    try {
      const r = await fetch(url, { signal: ctl.signal });
      if (r.status === 404) return { status: 0 };
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function fromApi(p, kind, base, code) {
    const text = p.ingredients_text || p.ingredients_text_de || p.ingredients_text_bg || p.ingredients_text_en || '';
    return {
      code,
      kind,
      source: kind === 'food' ? 'off' : 'obf',
      name: p.product_name || p.product_name_de || p.product_name_bg || p.product_name_en || p.generic_name || '',
      brand: String(p.brands || '').split(',')[0].trim(),
      image: p.image_front_small_url || p.image_small_url || '',
      ingredientsText: text,
      texts: [text, p.ingredients_text_de, p.ingredients_text_bg, p.ingredients_text_en].filter((x, i, all) => x && all.indexOf(x) === i),
      tags: [].concat(p.ingredients_tags || [], p.additives_tags || []),
      allergens: p.allergens_tags || [],
      analysis: p.ingredients_analysis_tags || [],
      nutriscore: /^[a-e]$/.test(p.nutriscore_grade || '') ? p.nutriscore_grade : null,
      nova: p.nova_group || null,
      updated: p.last_modified_t ? p.last_modified_t * 1000 : null,
      fetchedAt: Date.now(),
      url: base + '/product/' + code
    };
  }

  // Asks both databases at the same time. Returns a product, null (not found) or throws (no connection).
  async function fetchProduct(code) {
    const sources = [['food', OFF], ['cosmetic', OBF]];
    const results = await Promise.allSettled(
      sources.map(([, base]) => fetchJson(base + '/api/v2/product/' + code + '.json?fields=' + FIELDS))
    );
    let reached = false;
    for (let i = 0; i < sources.length; i++) {
      const r = results[i];
      if (r.status !== 'fulfilled') continue;
      reached = true;
      const d = r.value;
      if (d && (d.status === 1 || d.status === 'success') && d.product) {
        return fromApi(d.product, sources[i][0], sources[i][1], code);
      }
    }
    if (!reached) throw new Error('offline');
    return null;
  }

  function saveProduct(p) {
    state.products[p.code] = p;
    verdictCache.delete(p.code);
    const codes = Object.keys(state.products).filter(c => !state.favs.includes(c));
    const extra = Object.keys(state.products).length - MAX_PRODUCTS;
    if (extra > 0) {
      codes
        .sort((a, b) => {
          const pa = state.products[a], pb = state.products[b];
          const la = pa.source === 'label' ? 1 : 0, lb = pb.source === 'label' ? 1 : 0;
          return (la - lb) || (pa.fetchedAt - pb.fetchedAt);
        })
        .slice(0, extra)
        .forEach(c => delete state.products[c]);
    }
    store.set('products', state.products);
  }

  function addHistory(p, verdict) {
    state.history = state.history.filter(h => h.code !== p.code);
    state.history.unshift({ code: p.code, name: p.name, brand: p.brand, kind: p.kind, verdict, time: Date.now() });
    state.history = state.history.slice(0, MAX_HISTORY);
    store.set('history', state.history);
    renderHistory();
  }

  async function lookup(raw, forceOnline) {
    const code = String(raw || '').replace(/\D/g, '');
    if (code.length < 8 || code.length > 14) {
      toast(t('err.digits'));
      return;
    }
    hideAll();
    showStatus(t('status.looking', { code }));

    const cached = state.products[code];
    const fresh = cached && !forceOnline &&
      (cached.source === 'label' || Date.now() - cached.fetchedAt < CACHE_DAYS * 864e5);
    if (fresh) { showProduct(cached); return; }

    try {
      const p = await fetchProduct(code);
      if (p) { saveProduct(p); showProduct(p); }
      else if (cached) showProduct(cached, t('status.notOnline'));
      else showNotFound(code);
    } catch (e) {
      if (cached) showProduct(cached, t('status.noConn'));
      else showOffline(code);
    }
  }

  // ---------- Small helpers for the screens ----------
  const $ = id => document.getElementById(id);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return n;
  };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  function icon(d, cls) {
    const s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('aria-hidden', 'true');
    if (cls) s.setAttribute('class', cls);
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', d);
    s.append(p);
    return s;
  }
  const ICON = {
    chev: 'M9 6l6 6-6 6',
    heart: 'M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z',
    share: 'M12 15V4M8 8l4-4 4 4M5 13v5.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V13',
    close: 'M6 6l12 12M18 6L6 18',
    tag: 'M3.5 12.5v-8a1 1 0 0 1 1-1h8l8 8-9 9zM8 8h.01'
  };
  const link = (href, text) => el('a', { href, target: '_blank', rel: 'noopener', text });

  function fmtDate(ms) {
    try { return new Date(ms).toLocaleDateString(LOCALE[LANG], { day: 'numeric', month: 'short', year: 'numeric' }); }
    catch (e) { return ''; }
  }
  const smooth = () => (matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');

  function hideAll() {
    $('result').hidden = true;
    $('labelPanel').hidden = true;
    $('status').hidden = true;
  }

  function showScanner() {
    hideAll();
    $('scanner').hidden = false;
    state.current = null;
    window.scrollTo({ top: 0 });
  }

  function showStatus(text, buttons) {
    const s = $('status');
    s.replaceChildren(el('p', { text, class: 'status-text' }));
    if (buttons && buttons.length) s.append(el('div', { class: 'row' }, buttons));
    s.hidden = false;
  }

  // ---------- History (Back button) ----------
  // States: { tab } · { tab: 'scan', view: 'result', code } · same + { detail: i }.
  function pushState(st, hash) {
    try {
      const cur = history.state || {};
      if (st.view === 'result' && !st.detail && cur.view === 'result' && !cur.detail) history.replaceState(st, '');
      else history.pushState(st, '', hash || undefined);
    } catch (e) { /* ignore */ }
  }

  // ---------- Result screen ----------
  async function showProduct(p, note) {
    if (DBINFO === null) {
      showStatus(t('status.dbLoading'));
      await dbReady;
    }
    if (!DBINFO) {
      hideAll();
      showStatus(t('status.dbFail'));
      return;
    }
    pushState({ tab: 'scan', view: 'result', code: p.code });
    state.filter = null;
    state.open = null;
    const a = renderResult(p, note);
    addHistory(p, a.verdict);
    $('result').scrollIntoView({ behavior: smooth(), block: 'start' });
  }

  function renderResult(p, note) {
    const a = analyze(p);
    state.current = { p, a };
    if (!state.open) state.open = { red: true, orange: true, info: true, green: false };
    hideAll();
    $('scanner').hidden = true;
    if (note) showStatus(note);

    const r = $('result');
    r.replaceChildren(...[
      topCard(a, p),
      productChips(p, a),
      el('div', { id: 'groups' }),
      p.ingredientsText
        ? el('details', { class: 'ingr' },
            el('summary', { text: t('ingredientsTitle') }),
            el('p', { class: 'ingredients', text: p.ingredientsText.replace(/^\s*[\p{L} ]{2,20}[:：]\s*/u, '') }))
        : null,
      dataLine(p),
      el('div', { class: 'actions' },
        el('button', { class: 'btn btn-primary', type: 'button', text: t('btn.scanNext'), onclick: scanNext }),
        el('button', { class: 'btn btn-ghost', type: 'button', text: a.verdict === 'unknown' ? t('btn.readLabel') : t('btn.readAgain'), onclick: () => openLabel(p) }),
        p.source === 'label' && p.code && !p.code.startsWith('label-')
          ? el('button', { class: 'btn btn-ghost', type: 'button', text: t('btn.lookupOnline'), onclick: () => lookup(p.code, true) })
          : null
      )
    ].filter(Boolean));
    renderGroups();
    r.hidden = false;
    return a;
  }

  function topCard(a, p) {
    const card = el('section', { class: 'topcard v-' + a.verdict, 'aria-label': t('v.' + a.verdict) },
      productHead(p, a),
      el('span', { class: 'verdict-word', text: t('v.' + a.verdict) }),
      el('p', { class: 'verdict-sub', text: a.summary })
    );
    if (a.verdict === 'unknown') return card;

    card.append(el('div', { class: 'tiles', id: 'tiles' }, GROUPS.map(g => {
      const n = a.counts[g];
      return el('button', {
        type: 'button', class: 'tile g-' + g + (n ? ' has' : ' zero'), 'data-g': g,
        'aria-pressed': String(state.filter === g), 'aria-disabled': n ? null : 'true',
        onclick: () => { if (n) setFilter(g); }
      }, el('b', { text: String(n) }), el('span', { text: t('tile.' + g) }));
    })));

    const strip = el('div', { class: 'strip' + (a.rows.length > 30 ? ' dense' : ''), role: 'group', 'aria-label': t('strip.aria') },
      a.rows.map(r => el('button', {
        type: 'button', class: 'g-' + r.group + (r.kind === 'cosmetic' && !r.found ? ' nf' : ''),
        title: (r.pos ? '#' + r.pos + ' ' : '') + r.label,
        'aria-label': (r.pos ? '#' + r.pos + ' ' : '') + r.label + ', ' + t('g.' + r.group),
        onclick: e => jumpTo(r.i, e.currentTarget)
      })));
    card.append(strip, el('div', { class: 'strip-ends', 'aria-hidden': 'true' },
      el('span', { text: t('strip.first') }), el('span', { text: t('strip.last') })));
    return card;
  }

  function productHead(p, a) {
    const isFav = state.favs.includes(p.code);
    const meta = [p.brand, t(p.kind === 'cosmetic' ? 'kind.cosmetic' : 'kind.food'), a.total ? tn('ph.ingredients', a.total) : null,
      p.kind === 'cosmetic' && a.rows.length ? t(a.fragrance ? 'chip.fragrance' : 'chip.noFragrance') : null].filter(Boolean).join(' · ');
    return el('div', { class: 'product-head tc-head' },
      el('div', { class: 'thumb' }, icon(ICON.tag), p.image ? el('img', { src: p.image, alt: '', loading: 'lazy', onerror: e => e.target.remove() }) : null),
      el('div', { class: 'grow' },
        el('h2', { text: p.name || t('ph.unnamed') }),
        el('p', { text: meta })
      ),
      el('div', { class: 'acts' },
        el('button', {
          class: 'iconbtn' + (isFav ? ' on' : ''), type: 'button', id: 'favBtn',
          'aria-pressed': String(isFav), 'aria-label': t(isFav ? 'btn.unfav' : 'btn.fav'), title: t(isFav ? 'btn.unfav' : 'btn.fav'),
          onclick: () => toggleFav(p)
        }, icon(ICON.heart)),
        el('button', { class: 'iconbtn', type: 'button', 'aria-label': t('btn.share'), title: t('btn.share'), onclick: shareResult }, icon(ICON.share))
      )
    );
  }

  function productChips(p, a) {
    const chips = [];
    if (p.nutriscore) chips.push(t('chip.nutri', { g: p.nutriscore.toUpperCase() }));
    if (p.nova && [1, 2, 3, 4].includes(+p.nova)) chips.push(t('chip.nova', { n: p.nova, label: t('nova.' + p.nova) }));
    for (const tag of p.analysis || []) if (TEXT.en['an.' + tag]) chips.push(t('an.' + tag));

    let allergenLine = null;
    if (p.kind !== 'cosmetic') {
      const names = Object.fromEntries(LCDB.foodAllergens(LANG).map(x => [x.id, x.name]));
      const ids = new Set();
      a.rows.forEach(r => (r.allergens || []).forEach(x => ids.add(x.id)));
      (p.allergens || []).forEach(tag => { const m = String(tag).match(ALLERGEN_TAG); if (m) ids.add(m[1]); });
      if (ids.size) {
        const parts = [...ids].map(id => {
          const name = cap(names[id] || id);
          return state.allergens.food.includes(id) ? el('strong', { class: 'lvl g-red', text: name }) : name;
        });
        allergenLine = el('p', { class: 'allergen-line' }, el('strong', { text: t('allergens') + ': ' }),
          parts.flatMap((x, i) => (i ? [', ', x] : [x])));
      }
    }
    if (!chips.length && !allergenLine) return null;
    return el('div', {}, chips.length ? el('ul', { class: 'chips' }, chips.map(c => el('li', { text: c }))) : null, allergenLine);
  }

  function dataLine(p) {
    const sourceName = t('src.' + (p.source || 'label'));
    return el('p', { class: 'data-line' },
      p.code && !String(p.code).startsWith('label-') ? t('data.barcode', { code: p.code }) + ' ' : null,
      (t('data.from', { src: sourceName }) +
        (p.updated ? t('data.updated', { date: fmtDate(p.updated) }) : (p.source === 'label' ? t('data.saved', { date: fmtDate(p.fetchedAt) }) : ''))).replace(/\.?$/, '. '),
      p.url ? link(p.url, t('data.open')) : null
    );
  }

  function setFilter(g) {
    state.filter = state.filter === g ? null : g;
    if (state.filter) state.open[g] = true;
    document.querySelectorAll('#tiles .tile').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.g === state.filter)));
    renderGroups();
  }

  function renderGroups() {
    const box = $('groups');
    if (!box || !state.current) return;
    const { a } = state.current;
    if (a.verdict === 'unknown') { box.replaceChildren(); return; }
    const parts = [];
    if (state.filter) {
      parts.push(el('p', { class: 'filterbar' },
        el('button', { class: 'linkbtn', type: 'button', text: t('filter.all'), onclick: () => setFilter(state.filter) })));
    }
    for (const g of GROUPS) {
      if (state.filter && state.filter !== g) continue;
      const list = a.rows.filter(r => r.group === g);
      const id = 'grp-' + g;
      if (!list.length) {
        parts.push(el('section', { class: 'grp empty g-' + g },
          el('div', { class: 'grp-head' },
            el('span', { class: 'dot g-' + g }), el('span', { class: 'ttl', text: t('tile.' + g) }), el('span', { class: 'desc', text: t('gd.' + g) }),
            el('span', { class: 'num', text: t('g.none') }))));
        continue;
      }
      const open = !!state.open[g];
      parts.push(el('section', { class: 'grp g-' + g },
        el('button', {
          class: 'grp-head', type: 'button', 'aria-expanded': String(open), 'aria-controls': id,
          onclick: () => { state.open[g] = !state.open[g]; renderGroups(); }
        },
          el('span', { class: 'dot g-' + g }), el('span', { class: 'ttl', text: t('tile.' + g) }), el('span', { class: 'desc', text: t('gd.' + g) }),
          el('span', { class: 'num', text: String(list.length) }), icon(ICON.chev, 'chev')),
        g === 'green'
          ? el('ul', { class: 'chiplist', id, hidden: !open }, list.map(r => el('li', { 'data-i': r.i },
              el('button', { class: 'gchip' + (r.kind === 'cosmetic' && !r.found ? ' nf' : ''), type: 'button', onclick: e => openDetail(r.i, e.currentTarget) },
                el('small', { text: r.pos ? '#' + r.pos : '–' }), r.label))))
          : el('ul', { class: 'rows', id, hidden: !open }, list.map(rowItem))
      ));
    }
    box.replaceChildren(...parts);
  }

  // Short coloured tag on the right of a row.
  function chipOf(r) {
    const k = r.why === 'b' ? 'chip.b' : r.why === 'mine' ? 'chip.mine' : r.why === 'allergen' ? 'chip.yourAlg' : r.why === 'fragrance' ? 'chip.frag'
      : r.group === 'orange' ? (r.level === 'u' ? 'chip.u' : 'chip.c')
      : r.group === 'info' ? (r.allergen || (r.allergens && r.allergens.length && r.level !== 'r') ? 'chip.alg' : 'chip.r') : null;
    return k ? t(k) : null;
  }
  // One short line: why this row has its colour.
  function whyOf(r) {
    if (r.kind === 'cosmetic') {
      const s = r.src, tags = cosmeticTags(r), fn = (s.functions || [])[0];
      if (r.group === 'orange' && !r.why) return (s.reasons[0] || {}).text || '';
      if (r.group === 'info') {
        if (r.allergen) return t('tag.allergen');
        const an = (((s.reasons[0] || {}).source || {}).label || '').match(/Annex (IV|V|VI)\b/);
        return an ? t('why.annex' + an[1]) : [fn, t('why.limit')].filter(Boolean).join(' · ');
      }
      return (tags.length ? tags : [fn]).filter(Boolean).join(' · ');
    }
    return r.sub ? r.sub.parts.filter(Boolean).join(' · ') : '';
  }

  function rowItem(r) {
    const chip = chipOf(r), why = whyOf(r);
    return el('li', { 'data-i': r.i },
      el('button', { class: 'row-btn', type: 'button', onclick: e => openDetail(r.i, e.currentTarget) },
        el('span', { class: 'pos', text: r.pos ? '#' + r.pos : '–' }),
        el('span', { class: 'main' },
          chip ? el('span', { class: 'chip g-' + r.group, text: chip }) : null,
          el('strong', { text: r.label }),
          why ? el('span', { class: 'why', text: why }) : null),
        icon(ICON.chev, 'chev')
      )
    );
  }

  function jumpTo(i, block) {
    const r = state.current && state.current.a.rows[i];
    if (!r) return;
    if (state.filter && state.filter !== r.group) {
      state.filter = null;
      document.querySelectorAll('#tiles .tile').forEach(b => b.setAttribute('aria-pressed', 'false'));
    }
    state.open[r.group] = true;
    renderGroups();
    document.querySelectorAll('.strip .mark').forEach(b => b.classList.remove('mark'));
    if (block) block.classList.add('mark');
    const li = document.querySelector('#groups li[data-i="' + i + '"]');
    if (li) {
      li.scrollIntoView({ behavior: smooth(), block: 'center' });
      li.classList.remove('flash');
      void li.offsetWidth;
      li.classList.add('flash');
    }
  }

  function showNotFound(code) {
    hideAll();
    showStatus(t('status.notFound', { code }));
    openLabel({ code });
  }

  function showOffline(code) {
    hideAll();
    showStatus(t('status.offline'), [
      el('button', { class: 'btn btn-primary', type: 'button', text: t('btn.tryAgain'), onclick: () => lookup(code) }),
      el('button', { class: 'btn btn-ghost', type: 'button', text: t('btn.readLabel'), onclick: () => openLabel({ code }) })
    ]);
  }

  // From a result: go back to the scanner (the state below a result is always the scanner).
  function scanNext() {
    if (history.state && history.state.view === 'result') { try { history.back(); } catch (e) { /* ignore */ } }
    showScanner();
    startCamera();
  }

  // ---------- Share ----------
  async function shareResult() {
    if (!state.current) return;
    const { p, a } = state.current;
    const lines = [(p.name || t('ph.unnamed')) + (p.brand ? ' – ' + p.brand : ''), t('v.' + a.verdict) + ': ' + a.summary];
    for (const r of a.rows.filter(x => x.group === 'red' || x.group === 'orange').slice(0, 10)) {
      lines.push('• ' + r.label + (r.sub && r.sub.lvl ? ' – ' + r.sub.lvl.text : ''));
    }
    lines.push('', t('share.checked'));
    if (p.url) lines.push(p.url);
    const text = lines.join('\n');
    if (navigator.share) {
      try { await navigator.share({ title: 'Label Check', text }); return; }
      catch (e) { if (e && e.name === 'AbortError') return; }
    }
    toast((await copyText(text)) ? t('toast.shareCopied') : t('toast.copyFail'));
  }

  // ---------- Favourites ----------
  function toggleFav(p) {
    const on = state.favs.includes(p.code);
    state.favs = on ? state.favs.filter(c => c !== p.code) : [p.code, ...state.favs];
    if (!on && !state.products[p.code]) saveProduct(p);
    store.set('favs', state.favs);
    const b = $('favBtn');
    if (b && state.current && state.current.p.code === p.code) {
      b.classList.toggle('on', !on);
      b.setAttribute('aria-pressed', String(!on));
      b.setAttribute('aria-label', t(on ? 'btn.fav' : 'btn.unfav'));
      b.title = t(on ? 'btn.fav' : 'btn.unfav');
    }
    toast(t(on ? 'toast.favRemoved' : 'toast.favAdded'));
    renderFavs();
  }

  // Current verdict of a saved product (settings may have changed since the scan). Cached until a setting changes.
  const verdictCache = new Map();
  function verdictOf(code, fallback) {
    if (verdictCache.has(code)) return verdictCache.get(code);
    const p = state.products[code];
    if (DBINFO && p) {
      try { const a = analyze(p); const v = { verdict: a.verdict, summary: a.summary }; verdictCache.set(code, v); return v; }
      catch (e) { /* use the saved one */ }
    }
    return { verdict: fallback || 'unknown', summary: '' };
  }

  function productListItem(item, opts) {
    const v = verdictOf(item.code, item.verdict);
    const p = state.products[item.code] || item;
    return el('li', {},
      el('span', { class: 'dot ' + VERDICT_DOT[v.verdict], 'aria-hidden': 'true' }),
      el('button', { class: 'open', type: 'button', onclick: () => openSaved(item.code) },
        el('strong', { text: p.name || t('ph.unnamed') }),
        el('span', { class: 'sub', text: [p.brand, t('v.' + v.verdict), opts && opts.time ? fmtDate(opts.time) : null].filter(Boolean).join(' · ') }),
        opts && opts.summary && v.summary ? el('span', { class: 'sub one', text: v.summary }) : null
      ),
      opts && opts.remove ? opts.remove : null
    );
  }

  function renderFavs() {
    const ul = $('favList');
    const list = state.favs.filter(c => state.products[c]);
    ul.replaceChildren(...list.map(code => {
      const p = state.products[code];
      return productListItem({ code }, {
        summary: true,
        remove: el('button', {
          class: 'iconbtn', type: 'button', 'aria-label': t('favs.remove', { name: p.name || t('ph.unnamed') }),
          onclick: () => toggleFav(p)
        }, icon(ICON.close))
      });
    }));
    $('favEmpty').hidden = list.length > 0;
  }

  function renderHistory() {
    $('historyList').replaceChildren(...state.history.map(h => productListItem(h, { time: h.time })));
    $('historyEmpty').hidden = state.history.length > 0;
    $('clearHistory').hidden = state.history.length === 0;
  }

  function openSaved(code) {
    go('scan');
    const p = state.products[code];
    if (p) showProduct(p);
    else lookup(code);
  }

  // ---------- Ingredient detail ----------
  let detailReturn = null;

  function openDetail(i, from) {
    const r = state.current && state.current.a.rows[i];
    if (!r) return;
    detailReturn = from || null;
    renderDetail(r);
    $('detail').hidden = false;
    $('detail').scrollTop = 0;
    document.documentElement.classList.add('noscroll');
    pushState(Object.assign({}, history.state || { tab: 'scan' }, { detail: i + 1 }));
    $('detailBack').focus();
  }

  function hideDetail() {
    if ($('detail').hidden) return;
    $('detail').hidden = true;
    document.documentElement.classList.remove('noscroll');
    if (detailReturn && document.body.contains(detailReturn)) detailReturn.focus();
    detailReturn = null;
  }

  function closeDetail() {
    if (history.state && history.state.detail) { try { history.back(); return; } catch (e) { /* fall through */ } }
    hideDetail();
  }

  function reasonBlock(rs) {
    const d = rs.details || {};
    const items = [];
    const add = (key, val) => { if (val) items.push(el('dt', { text: t(key) }), el('dd', {}, val)); };
    add('d.det.entry', d.entry);
    add('d.det.products', d.products);
    add('d.det.max', d.max);
    add('d.det.conditions', d.conditions);
    add('d.det.warning', d.warning);
    add('d.det.date', d.date);
    if (Array.isArray(d.expert) && d.expert.length) {
      add('d.det.expert', d.expert.map((u, k) => [k ? ', ' : '', link(u, 'SCCS ' + (k + 1))]).flat());
    }
    if (Array.isArray(d.status) && d.status.length) add('d.det.status', d.status.join(' · '));
    add('d.det.year', d.year);
    return el('div', { class: 'reason' },
      el('p', {}, el('span', { class: 'lvl g-' + LEVEL_GROUP[rs.lv], text: levelName(rs.lv) + ': ' }), rs.text),
      rs.source ? el('p', { class: 'src' }, t('d.source') + ': ', rs.source.url ? link(rs.source.url, rs.source.label) : rs.source.label) : null,
      items.length ? el('dl', {}, items) : null
    );
  }

  function studiesLink(name) {
    const tpl = (META() && META().studySearch) || 'https://europepmc.org/search?query=%22{name}%22';
    return el('a', { class: 'btn btn-ghost', href: tpl.replace('{name}', encodeURIComponent(name)), target: '_blank', rel: 'noopener', text: t('d.studies') });
  }

  function badge(group, text) {
    return el('span', { class: 'badge g-' + group }, el('span', { class: 'dot g-' + group }), text);
  }

  function renderDetail(r) {
    const body = [];
    body.push(el('h2', { id: 'detailTitle', text: r.label }));
    body.push(el('p', { class: 'd-meta', text: r.pos ? t('d.pos', { n: r.pos }) : t('d.posNone') }));

    const top = r.why === 'mine' ? t('tag.mine') : r.why === 'allergen' ? t('tag.allergenYours')
      : r.why === 'fragrance' ? t('tag.fragranceAvoid') : levelName(r.level);
    body.push(badge(r.group, top));

    // Personal reasons (your list, allergens, fragrance)
    const mineP = [];
    if (r.mine) mineP.push(el('p', { text: t('d.mineWhy', { term: r.mine.term }) }));
    if (r.why === 'allergen') mineP.push(el('p', { text: t('d.allergenTicked') }));
    if (r.fragAvoid) mineP.push(el('p', { text: t('d.fragranceWhy') }));
    if (mineP.length) body.push(el('div', { class: 'd-card' }, mineP));

    if (r.kind === 'cosmetic') {
      const tags = cosmeticTags(r);
      if (tags.length) body.push(el('ul', { class: 'd-tags' }, tags.map(x => el('li', { text: x }))));
      if (r.found && niceName(r.src.name) !== cleanSeg(r.text)) {
        body.push(el('p', { class: 'd-meta' }, t('d.asOnLabel') + ': ', el('em', { text: r.text })));
      }
      if (r.src.functions && r.src.functions.length) {
        body.push(el('div', { class: 'd-card' }, el('h3', { text: t('d.functions') }), el('p', { text: r.src.functions.join(', ') })));
      }
      const reasons = r.src.reasons || [];
      body.push(el('div', { class: 'd-card' },
        el('h3', { text: t('d.why') }),
        reasons.length ? reasons.map(reasonBlock) : el('p', { text: r.found ? t('d.noReasons') : t('d.notFound') }),
        r.allergen && !r.tickedAllergen ? el('p', { class: 'minor', text: t('d.allergenNot') }) : null,
        reasons.some(x => x.details && (x.details.entry || x.details.conditions)) ? el('p', { class: 'minor', text: t('d.det.engOnly') }) : null
      ));
    } else if (r.kind === 'food') {
      if (cleanSeg(r.text) !== r.label) body.push(el('p', { class: 'd-meta' }, t('d.asOnLabel') + ': ', el('em', { text: r.text })));
      for (const a of r.additives) {
        const en = LCDB.checkFood(a.e, 'en').additives[0];
        body.push(el('div', { class: 'd-card' },
          el('h3', { text: cap(a.name) + ' (' + a.e + ')' }),
          r.additives.length > 1 || a.level !== r.level || r.why ? badge(LEVEL_GROUP[a.level], levelName(a.level)) : null,
          a.classes && a.classes.length ? el('p', {}, el('strong', { text: t('d.classes') + ': ' }), a.classes.join(', ')) : null,
          a.vegan ? el('p', { class: 'minor', text: t('d.vegan.' + a.vegan) }) : null,
          a.reasons.length ? a.reasons.map(reasonBlock) : el('p', { text: t('d.noReasons') }),
          el('div', { class: 'd-actions' }, studiesLink(en ? en.name : a.name))
        ));
      }
      for (const rule of r.rules) {
        body.push(el('div', { class: 'd-card' }, el('h3', { text: t('d.why') }), rule.reasons.map(reasonBlock)));
      }
      const foodAlText = tr(META().reasons['food.allergen']);
      for (const al of r.allergens) {
        const ticked = state.allergens.food.includes(al.id);
        body.push(el('div', { class: 'd-card' },
          el('h3', { text: t('tag.foodAllergen', { name: cap(al.name) }) }),
          el('p', { text: foodAlText }),
          el('p', { class: 'minor', text: t(ticked ? 'd.allergenTicked' : 'd.allergenNot') })
        ));
      }
      if (!r.additives.length && !r.rules.length && !r.allergens.length && !r.mine) body.push(el('div', { class: 'd-card' }, el('p', { text: t('d.plain') })));
    }

    // Actions
    const acts = [];
    const studyName = r.kind === 'cosmetic' ? (r.found ? niceName(r.src.name) : cleanSeg(r.text)) : (r.kind === 'food' && !r.additives.length ? cleanSeg(r.text).replace(/\s*\(.*\)\s*/g, ' ').trim() : null);
    if (studyName) acts.push(studiesLink(studyName));
    if (r.kind !== 'extra') {
      const listName = r.kind === 'cosmetic' && r.found ? [niceName(r.src.name), cleanSeg(r.text)] : [cleanSeg(r.text).replace(/\s*\(.*\)\s*/g, ' ').trim()];
      const already = !!r.mine;
      acts.push(el('button', {
        class: 'btn ' + (already ? 'btn-ghost' : 'btn-primary'), type: 'button', disabled: already,
        text: already ? t('d.onList') : t('d.addList'),
        onclick: e => {
          addAvoid([...new Set(listName.map(x => x.toLowerCase()))].join(', '));
          e.currentTarget.disabled = true;
          e.currentTarget.textContent = t('d.onList');
          e.currentTarget.className = 'btn btn-ghost';
        }
      }));
    }
    if (acts.length) body.push(el('div', { class: 'd-actions' }, acts));
    body.push(el('p', { class: 'minor', style: null, text: t('d.studiesNote') }));

    $('detailBody').replaceChildren(...body.filter(Boolean));
  }

  // ---------- Read a label (free share flow) ----------
  let labelFor = null; // product or {code} the label belongs to

  function openLabel(p) {
    labelFor = p && p.code ? p : null;
    $('result').hidden = true;
    $('scanner').hidden = false;
    const panel = $('labelPanel');
    panel.hidden = false;
    $('labelText').value = '';
    $('labelName').value = (p && p.name) || '';
    const kind = (p && p.kind) || 'food';
    document.querySelectorAll('input[name="kind"]').forEach(i => { i.checked = i.value === kind; });
    $('labelLead').textContent = labelFor && labelFor.code && !String(labelFor.code).startsWith('label-')
      ? t('label.leadFor', { code: labelFor.code }) : t('label.lead');
    panel.scrollIntoView({ behavior: 'auto', block: 'start' });
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) { return false; }
  }

  async function onPhoto(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const copied = await copyText(PROMPT);
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], text: PROMPT });
        toast(copied ? t('toast.qCopied') : t('toast.pickClaude'));
      } catch (err) {
        if (err && err.name !== 'AbortError') toast(t('toast.shareFail'));
      }
    } else {
      toast(t('toast.noShare'));
    }
  }

  async function onPaste() {
    try {
      const txt = await navigator.clipboard.readText();
      if (txt) $('labelText').value = txt.trim();
      else toast(t('toast.clipEmpty'));
    } catch (e) {
      toast(t('toast.pasteBlocked'));
    }
  }

  function parseClaudeAnswer(text) {
    const lines = String(text || '').split(/\r?\n/);
    const main = [], extra = [];
    for (const line of lines) {
      const m = line.match(/^\s*EN\s*:\s*(.*)$/i);
      if (m) extra.push(m[1]);
      else if (line.trim()) main.push(line.trim());
    }
    return { main: main.join(' '), extra: extra.join(' ') };
  }

  function onCheckLabel() {
    const raw = $('labelText').value.trim();
    if (!raw) { toast(t('toast.pasteFirst')); $('labelText').focus(); return; }
    const { main, extra } = parseClaudeAnswer(raw);
    const kind = (document.querySelector('input[name="kind"]:checked') || {}).value || 'food';
    const code = labelFor && labelFor.code ? labelFor.code : 'label-' + Date.now();
    const base = labelFor && labelFor.code ? state.products[labelFor.code] : null;
    const p = {
      code,
      kind,
      source: 'label',
      name: $('labelName').value.trim() || (base && base.name) || '',
      brand: (base && base.brand) || '',
      image: (base && base.image) || '',
      ingredientsText: main,
      texts: [main, extra].filter(Boolean),
      tags: [],
      allergens: [],
      analysis: [],
      nutriscore: (base && base.nutriscore) || null,
      nova: (base && base.nova) || null,
      updated: null,
      fetchedAt: Date.now(),
      url: ''
    };
    saveProduct(p);
    showProduct(p);
  }

  // ---------- Camera ----------
  let stream = null, detector = null, scanTimer = null;

  async function startCamera() {
    if (!('BarcodeDetector' in window)) {
      toast(t('toast.noBarcodeApi'));
      $('codeInput').focus();
      return;
    }
    try {
      const wanted = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];
      let formats = wanted;
      try {
        const supported = await BarcodeDetector.getSupportedFormats();
        formats = wanted.filter(f => supported.includes(f));
      } catch (e) { /* use the default list */ }
      detector = new BarcodeDetector({ formats: formats.length ? formats : wanted });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    } catch (e) {
      stopCamera();
      toast(e && e.name === 'NotAllowedError' ? t('toast.camBlocked') : t('toast.camFail'));
      return;
    }
    const v = $('video');
    v.srcObject = stream;
    v.hidden = false;
    $('vfIdle').hidden = true;
    $('scanline').hidden = false;
    $('stopCam').hidden = false;
    try { await v.play(); } catch (e) { /* autoplay is allowed for muted video */ }
    scanLoop();
  }

  async function scanLoop() {
    if (!stream || !detector) return;
    try {
      const v = $('video');
      if (v.readyState >= 2) {
        const codes = await detector.detect(v);
        const hit = codes.find(c => /^\d{8,14}$/.test(c.rawValue));
        if (hit) {
          if (navigator.vibrate) navigator.vibrate(60);
          stopCamera();
          lookup(hit.rawValue);
          return;
        }
      }
    } catch (e) { /* try again on the next frame */ }
    scanTimer = setTimeout(scanLoop, 200);
  }

  function stopCamera() {
    clearTimeout(scanTimer);
    if (stream) stream.getTracks().forEach(tr2 => tr2.stop());
    stream = null;
    const v = $('video');
    v.srcObject = null;
    v.hidden = true;
    $('scanline').hidden = true;
    $('stopCam').hidden = true;
    $('vfIdle').hidden = false;
  }

  // ---------- My list: avoid list ----------
  function renderAvoid() {
    $('avoidList').replaceChildren(...state.avoid.map(item => {
      const parts = termsOf(item);
      return el('li', {},
        el('span', { class: 'grow' },
          el('strong', { text: parts[0] }),
          parts.length > 1 ? el('span', { class: 'sub', text: t('list.also') + parts.slice(1).join(', ') }) : null
        ),
        el('button', { class: 'btn btn-ghost', type: 'button', text: t('list.remove'), 'aria-label': t('list.remove') + ': ' + parts[0], onclick: () => removeAvoid(item.id) })
      );
    }));
    $('avoidEmpty').hidden = state.avoid.length > 0;

    const have = new Set(state.avoid.map(i => i.text.split(',')[0].trim().toLowerCase()));
    $('picks').replaceChildren(...QUICK_PICKS
      .filter(p => !have.has(p.split(',')[0].trim().toLowerCase()))
      .map(p => el('button', { type: 'button', text: '+ ' + p.split(',')[0], onclick: () => addAvoid(p) })));
  }

  function settingsChanged() {
    verdictCache.clear();
    if (state.current) renderResult(state.current.p);
    renderFavs();
    renderHistory();
  }

  function addAvoid(text) {
    const clean = String(text || '').split(',').map(s => s.trim()).filter(Boolean).join(', ');
    if (!clean) return;
    state.avoid.push({ id: 'a' + Date.now() + Math.random().toString(36).slice(2, 6), text: clean });
    store.set('avoid', state.avoid);
    renderAvoid();
    settingsChanged();
    toast(t('toast.added', { name: clean.split(',')[0] }));
  }

  function removeAvoid(id) {
    state.avoid = state.avoid.filter(i => i.id !== id);
    store.set('avoid', state.avoid);
    renderAvoid();
    settingsChanged();
  }

  // ---------- My list: allergens ----------
  let COS_ALLERGENS = [];

  function tick(id, checked, label, sub, onchange) {
    return el('label', { 'data-search': (label + ' ' + (sub || '')).toLowerCase() },
      el('input', { type: 'checkbox', checked, onchange }),
      el('span', {}, label, sub ? el('span', { class: 'sub', text: ' ' + sub }) : null));
  }

  function renderAllergens() {
    if (!DBINFO) return;
    const food = LCDB.foodAllergens(LANG);
    $('foodAlgList').replaceChildren(...food.map(a => tick(a.id, state.allergens.food.includes(a.id), cap(a.name), null, e => {
      state.allergens.food = state.allergens.food.filter(x => x !== a.id);
      if (e.target.checked) state.allergens.food.push(a.id);
      store.set('allergens', state.allergens);
      updateAllergenCounts();
      settingsChanged();
    })));
    if (!COS_ALLERGENS.length) COS_ALLERGENS = LCDB.cosAllergens();
    const list = $('cosAlgList');
    list.classList.add('long');
    list.replaceChildren(...COS_ALLERGENS.map(a => {
      const others = a.names.filter(n => n !== a.name).map(niceName);
      return tick(a.ref, state.allergens.cos.includes(a.ref), niceName(a.name), others.length ? '(' + others.slice(0, 2).join(', ') + ')' : null, e => {
        state.allergens.cos = state.allergens.cos.filter(x => x !== a.ref);
        if (e.target.checked) state.allergens.cos.push(a.ref);
        store.set('allergens', state.allergens);
        updateAllergenCounts();
        settingsChanged();
      });
    }));
    filterCosAllergens();
    updateAllergenCounts();
  }

  function filterCosAllergens() {
    const q = $('cosAlgSearch').value.trim().toLowerCase();
    $('cosAlgList').querySelectorAll('label').forEach(l => { l.hidden = !!q && !l.dataset.search.includes(q); });
  }

  function updateAllergenCounts() {
    $('foodAlgCount').textContent = state.allergens.food.length ? '(' + t('alg.ticked', { n: state.allergens.food.length }) + ')' : '';
    $('cosAlgCount').textContent = '(' + (state.allergens.cos.length ? t('alg.ticked', { n: state.allergens.cos.length }) + ' / ' : '') + COS_ALLERGENS.length + ')';
    $('cosAlgClear').hidden = state.allergens.cos.length === 0;
  }

  // ---------- My list: what the app checks ----------
  function renderRules() {
    const box = $('rulesBox');
    if (DBINFO === null) { box.replaceChildren(el('p', { class: 'minor', text: t('status.dbLoading') })); return; }
    if (!DBINFO) { box.replaceChildren(el('p', { class: 'minor', text: t('status.dbFail') })); return; }
    const m = META();
    box.replaceChildren(
      el('ul', { class: 'levels' }, m.levelOrder.map(lv => el('li', {},
        el('span', { class: 'dot g-' + LEVEL_GROUP[lv] }),
        el('div', {}, el('strong', { text: levelName(lv) }), el('span', { text: t('rules.lv.' + lv) }))))),
      el('h4', { class: 'rules-sub', text: t('rules.curated') }),
      el('ul', { class: 'rulelist' }, Object.values(m.curated).map(c => el('li', {},
        el('span', { class: 'lvl g-' + LEVEL_GROUP[c.lv], text: levelName(c.lv) + ': ' }), tr(c),
        el('span', { class: 'src' }, t('d.source') + ': ', link(c.src.url, c.src.label))))),
      el('h4', { class: 'rules-sub', text: t('rules.sources') }),
      el('ul', { class: 'rulelist' }, m.sources.map(s => el('li', {},
        link(s.url, s.label),
        s.fetched ? el('span', { class: 'src', text: t('rules.fetched', { date: fmtDate(Date.parse(s.fetched)) }) }) : null))),
      el('p', { class: 'minor', text: t('rules.version', { v: m.version, c: DBINFO.cosmetics.toLocaleString(LOCALE[LANG]), a: DBINFO.additives }) })
    );
  }

  function renderCredit() {
    $('credit').replaceChildren(
      el('p', {}, tNodes('credit.product', {
        off: link('https://world.openfoodfacts.org', 'Open Food Facts'),
        obf: link('https://world.openbeautyfacts.org', 'Open Beauty Facts'),
        odbl: link('https://opendatacommons.org/licenses/odbl/1-0/', 'ODbL')
      })),
      el('p', { text: t('credit.ingredient') }),
      el('p', { text: t('credit.guide') })
    );
  }

  // ---------- My list: settings ----------
  function applyTheme() {
    const root = document.documentElement;
    if (state.theme === 'light' || state.theme === 'dark') root.dataset.theme = state.theme;
    else delete root.dataset.theme;
    const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
    if (bg) $('themeColor').setAttribute('content', bg);
  }

  function applyBig() { document.documentElement.classList.toggle('big', !!state.bigText); }

  function setLanguage(value) {
    state.lang = value;
    store.set('lang', value);
    LANG = pickLang();
    verdictCache.clear();
    applyTexts();
    renderAll();
  }

  function renderAll() {
    renderAvoid();
    renderAllergens();
    renderRules();
    renderFavs();
    renderHistory();
    if (state.current) renderResult(state.current.p);
    if (!$('labelPanel').hidden) $('labelLead').textContent = labelFor && labelFor.code && !String(labelFor.code).startsWith('label-') ? t('label.leadFor', { code: labelFor.code }) : t('label.lead');
  }

  // ---------- Backup ----------
  function exportBackup() {
    const data = {
      app: 'label-check', version: 2, exportedAt: new Date().toISOString(),
      avoid: state.avoid, favs: state.favs, allergens: state.allergens, avoidFragrance: state.avoidFragrance,
      lang: state.lang, theme: state.theme, bigText: state.bigText,
      history: state.history, products: state.products
    };
    const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: 'label-check-backup-' + new Date().toISOString().slice(0, 10) + '.json' });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast(t('toast.backupSaved'));
  }

  async function importBackup(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); }
    catch (err) { toast(t('toast.notBackup')); return; }
    if (!data || data.app !== 'label-check') { toast(t('toast.notBackup')); return; }
    if (!confirm(t('confirm.import'))) return;
    state.avoid = Array.isArray(data.avoid) ? data.avoid.filter(i => i && typeof i.text === 'string') : [];
    state.history = Array.isArray(data.history) ? data.history.slice(0, MAX_HISTORY) : [];
    if (data.products && typeof data.products === 'object') Object.assign(state.products, data.products);
    state.favs = Array.isArray(data.favs) ? data.favs.filter(c => typeof c === 'string') : [];
    if (data.allergens && typeof data.allergens === 'object') {
      state.allergens = {
        food: Array.isArray(data.allergens.food) ? data.allergens.food.filter(x => typeof x === 'string') : [],
        cos: Array.isArray(data.allergens.cos) ? data.allergens.cos.filter(x => typeof x === 'string') : []
      };
    }
    if (typeof data.avoidFragrance === 'boolean') state.avoidFragrance = data.avoidFragrance;
    if (['auto', 'en', 'de', 'bg'].includes(data.lang)) state.lang = data.lang;
    if (['auto', 'light', 'dark'].includes(data.theme)) state.theme = data.theme;
    if (typeof data.bigText === 'boolean') state.bigText = data.bigText;
    for (const k of ['avoid', 'history', 'products', 'favs', 'allergens', 'avoidFragrance', 'lang', 'theme', 'bigText']) store.set(k, state[k]);
    verdictCache.clear();
    syncSettingsControls();
    applyTheme();
    applyBig();
    LANG = pickLang();
    applyTexts();
    renderAll();
    toast(t('toast.imported'));
  }

  function syncSettingsControls() {
    $('fragSwitch').checked = !!state.avoidFragrance;
    $('bigSwitch').checked = !!state.bigText;
    $('langSelect').value = state.lang;
    $('themeSelect').value = state.theme;
  }

  // ---------- Tabs and toast ----------
  // Each tab change is added to the browser history, so the phone's Back button returns to the previous tab.
  const TABS = ['scan', 'favs', 'list', 'history'];
  let currentTab = 'scan';

  function setTab(tab) {
    if (!TABS.includes(tab)) tab = 'scan';
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(s => { s.hidden = s.dataset.tab !== tab; });
    document.querySelectorAll('.tabbar button').forEach(b => {
      if (b.dataset.go === tab) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    if (tab !== 'scan') stopCamera();
    window.scrollTo({ top: 0 });
  }

  function go(tab) {
    hideDetail();
    if (tab === currentTab) {
      // Tapping "Scan" on a result goes back to the scanner.
      if (tab === 'scan' && (!$('result').hidden || !$('labelPanel').hidden)) {
        if (history.state && history.state.view === 'result') { try { history.back(); } catch (e) { /* ignore */ } }
        showScanner();
      }
      return;
    }
    pushState({ tab }, '#' + tab);
    setTab(tab);
  }

  window.addEventListener('popstate', e => {
    const st = e.state || { tab: 'scan' };
    if (!st.detail) hideDetail();
    if (st.tab !== currentTab) setTab(st.tab);
    if (st.tab === 'scan') {
      if (st.view === 'result') {
        if (!state.current || state.current.p.code !== st.code) {
          const p = state.products[st.code];
          if (p && DBINFO) renderResult(p); else showScanner();
        }
      } else if ($('scanner').hidden || !$('result').hidden) {
        showScanner();
      }
    }
  });

  let toastTimer = null;
  function toast(text) {
    const tt = $('toast');
    tt.textContent = text;
    tt.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { tt.hidden = true; }, 3800);
  }

  // ---------- Start ----------
  function init() {
    LANG = pickLang();
    applyTheme();
    applyBig();
    applyTexts();
    syncSettingsControls();

    document.querySelectorAll('.tabbar button').forEach(b => b.addEventListener('click', () => go(b.dataset.go)));
    $('startCam').addEventListener('click', startCamera);
    $('stopCam').addEventListener('click', stopCamera);
    $('manualForm').addEventListener('submit', e => {
      e.preventDefault();
      stopCamera();
      lookup($('codeInput').value);
    });
    $('openLabel').addEventListener('click', () => { hideAll(); openLabel(null); });
    $('photoInput').addEventListener('change', onPhoto);
    $('copyPrompt').addEventListener('click', async () => {
      toast((await copyText(PROMPT)) ? t('toast.qCopied2') : t('toast.copyFail'));
    });
    $('pasteBtn').addEventListener('click', onPaste);
    $('checkLabel').addEventListener('click', onCheckLabel);
    $('avoidForm').addEventListener('submit', e => {
      e.preventDefault();
      addAvoid($('avoidInput').value);
      $('avoidInput').value = '';
    });
    $('fragSwitch').addEventListener('change', e => {
      state.avoidFragrance = e.target.checked;
      store.set('avoidFragrance', state.avoidFragrance);
      settingsChanged();
    });
    $('cosAlgSearch').addEventListener('input', filterCosAllergens);
    $('cosAlgClear').addEventListener('click', () => {
      state.allergens.cos = [];
      store.set('allergens', state.allergens);
      renderAllergens();
      settingsChanged();
    });
    $('langSelect').addEventListener('change', e => setLanguage(e.target.value));
    $('themeSelect').addEventListener('change', e => { state.theme = e.target.value; store.set('theme', state.theme); applyTheme(); });
    $('bigSwitch').addEventListener('change', e => { state.bigText = e.target.checked; store.set('bigText', state.bigText); applyBig(); });
    try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme); } catch (e) { /* old browser */ }
    $('exportBtn').addEventListener('click', exportBackup);
    $('importInput').addEventListener('change', importBackup);
    $('clearHistory').addEventListener('click', () => {
      if (!confirm(t('confirm.clearHist'))) return;
      state.history = [];
      store.set('history', state.history);
      renderHistory();
    });
    $('detailBack').addEventListener('click', closeDetail);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('detail').hidden) closeDetail(); });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
    try { history.replaceState({ tab: 'scan' }, '', location.pathname + location.search); } catch (e) { /* ignore */ }

    renderAvoid();
    renderFavs();
    renderHistory();
    renderRules();
    dbReady.then(() => { renderRules(); renderAllergens(); renderFavs(); renderHistory(); });

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(() => { /* app still works online */ });
    }
  }

  // Small test hook (used only by automated checks).
  window.LC = { analyze, termRe, matchAvoid, niceName, parseClaudeAnswer, state, lookup, showProduct, dbReady, t, setLanguage };

  init();
})();
