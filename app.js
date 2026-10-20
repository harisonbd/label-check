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

  // Vegan check (food): allergens that always come from animals, and animal ingredient words (EN / DE / BG).
  const ANIMAL_ALLERGENS = ['milk', 'eggs', 'fish', 'crustaceans', 'molluscs'];
  const ANIMAL_TERMS = [
    'meat', 'pork', 'beef', 'veal', 'lamb', 'mutton', 'chicken', 'turkey', 'duck', 'bacon', 'ham', 'salami', 'gelatin', 'gelatine',
    'lard', 'tallow', 'suet', 'honey', 'beeswax', 'anchovy', 'anchovies', 'tuna', 'salmon', 'cod', 'collagen', 'carmine', 'cochineal',
    'shellac', 'isinglass', 'bone*', 'whey', 'casein*', 'cheese',
    'fleisch', 'fleisch*', 'schweinefleisch', 'rindfleisch', 'kalbfleisch', 'lammfleisch', 'putenfleisch', 'hühnerfleisch',
    'geflügelfleisch', 'hackfleisch', 'hähnchen*', 'huhn', 'pute', 'speck', 'schinken', 'schmalz', 'schweineschmalz', 'talg', 'rindertalg',
    'honig', 'bienenwachs', 'sardelle*', 'thunfisch', 'lachs', 'kollagen', 'schellack', 'karmin', 'molke*', 'käse', 'kase',
    'месо', 'свинско', 'свинска', 'телешко', 'говеждо', 'пилешко', 'пилешки', 'пуешко', 'агнешко', 'бекон', 'шунка', 'салам',
    'желатин', 'свинска мас', 'лой', 'пчелен мед', 'пчелен восък', 'аншоа', 'риба тон', 'сьомга', 'колаген', 'кармин', 'суроватка', 'сирене', 'масло краве'
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
    vegan: store.get('vegan', false),
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
    $('langSwitch').setAttribute('aria-label', t('set.lang'));
    $('langSwitch').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === LANG)));
    if ($('labelTitle')) setLabelTitle();
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

  // ---------- Our product list (data/products.json): products the online databases do not have ----------
  // Checked first when a barcode is scanned; works offline. Products without a barcode are found with Search.
  let OWN = [];
  const ownReady = fetch('data/products.json').then(r => r.json())
    .then(j => { OWN = (j.products || []).filter(o => o && o.id && o.ingredients); })
    .catch(() => { OWN = []; });
  const isBarcode = c => /^\d{8,14}$/.test(String(c || ''));
  const ownCode = o => (isBarcode(o.code) ? o.code : 'own-' + o.id);
  function ownProduct(o) {
    return {
      code: ownCode(o), kind: o.kind === 'cosmetic' ? 'cosmetic' : 'food', source: 'own',
      name: o.name || '', brand: o.brand || '', image: '', use: o.use || undefined,
      ingredientsText: o.ingredients, texts: [o.ingredients], tags: [], allergens: [], analysis: [],
      nutriscore: null, nova: null, updated: null, added: Date.parse(o.added) || null, fetchedAt: Date.now(), url: ''
    };
  }
  function ownBy(code) {
    const o = OWN.find(x => ownCode(x) === code);
    return o ? ownProduct(o) : null;
  }
  function ownSearch(q) {
    const nq = LCDB.norm(q);
    return OWN.filter(o => LCDB.norm([o.brand, o.name].join(' ')).includes(nq)).map(ownProduct);
  }
  // A saved product; for products from our list, the newest copy of the list.
  function productBy(code) {
    const p = state.products[code];
    return p && p.source !== 'own' ? p : (ownBy(code) || p || null);
  }

  // ---------- Analysis ----------
  // Every ingredient becomes a row with a level (b c u r n) and a group (red orange info green).
  function analyze(p) {
    const text = p.ingredientsText || '';
    let rows = p.kind === 'cosmetic' ? analyzeCosmetic(text, p.use) : analyzeFood(p, text);

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

  // An EU entry that allows the ingredient only in products that are washed off (rinse-off).
  function rinseOnly(rs) {
    const d = rs.details || {};
    const txt = (d.products || '') + ' ' + (d.max || '');
    return /rinse[- ]?off/i.test(txt) && !/leave[- ]?on|other products|\(b\)|\bb\)/i.test(txt);
  }

  function analyzeCosmetic(text, use) {
    return LCDB.checkCosmetic(text, LANG).map(r => {
      const mine = matchAvoid([r.text, r.found ? r.name : '']);
      const tickedAllergen = !!(r.allergen && state.allergens.cos.includes(r.allergenRef));
      const fragAvoid = !!(state.avoidFragrance && (r.fragrance || r.allergen));
      const useHit = use === 'leave' && (r.reasons || []).some(rinseOnly);
      const why = r.level === 'b' ? 'b' : useHit ? 'use' : mine ? 'mine' : tickedAllergen ? 'allergen' : fragAvoid ? 'fragrance' : null;
      const row = {
        pos: r.pos, kind: 'cosmetic', text: r.text,
        label: r.found ? niceName(r.name) : cleanSeg(r.text),
        level: r.level, group: why ? 'red' : LEVEL_GROUP[r.level] || 'green', why, mine, tickedAllergen, fragAvoid, useHit,
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
    if (row.why === 'use') return { lvl: { text: t('chip.use'), g: 'red' }, parts: [t('use.why')] };
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
    // Name = the part before any bracket ("Nitritpökelsalz (Speisesalz, …)" -> "Nitritpökelsalz"); full text on the detail screen.
    const shortSeg = s => cleanSeg(s.replace(/\s*[([][^)\]]*[)\]]/g, ' ')) || cleanSeg(s);
    const rows = segs.map((s, i) => blank(i + 1, s, shortSeg(s)));
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

    const out = rows.concat(extra).map(row => {
      let level = 'n';
      for (const x of [...row.additives, ...row.rules]) if (SEV[x.level] > SEV[level]) level = x.level;
      const mine = matchAvoid([row.text, ...row.additives.map(a => a.e + ' ' + a.name)]);
      const ticked = row.allergens.filter(a => state.allergens.food.includes(a.id));
      const vg = veganOf(row);
      const veganHit = state.vegan && vg.no.length > 0;
      const why = level === 'b' ? 'b' : mine ? 'mine' : ticked.length ? 'allergen' : veganHit ? 'vegan' : null;
      row.level = level;
      row.mine = mine;
      row.tickedAllergens = ticked;
      row.vegan = vg;
      row.why = why;
      row.group = why ? 'red' : level === 'c' || level === 'u' ? 'orange'
        : level === 'r' || row.allergens.length || (state.vegan && vg.maybe.length) ? 'info' : 'green';
      row.sub = foodSub(row);
      return row;
    });
    // Open Food Facts says "not vegan", but no single ingredient showed it.
    if (state.vegan && (p.analysis || []).includes('en:non-vegan') && !out.some(r => r.vegan && r.vegan.no.length)) {
      const x = blank(null, '', t('tag.notVeganData'));
      Object.assign(x, { level: 'n', mine: null, tickedAllergens: [], vegan: { no: [t('tag.fromData')], maybe: [] }, why: 'vegan', group: 'red', fromData: true });
      x.sub = { lvl: { text: t('chip.vegan'), g: 'red' }, parts: [t('tag.fromData')] };
      out.push(x);
    }
    return out;
  }

  // What in this row comes from animals (no) or may come from animals (maybe).
  function veganOf(row) {
    const no = [], maybe = [];
    for (const a of row.additives) {
      if (a.vegan === 'no') no.push(cap(a.name));
      else if (a.vegan === 'maybe') maybe.push(cap(a.name));
    }
    for (const al of row.allergens) if (ANIMAL_ALLERGENS.includes(al.id)) no.push(cap(al.name));
    if (state.vegan && row.text) {
      const hay = [nrm(row.text)];
      for (const term of ANIMAL_TERMS) {
        const re = termRe(term);
        if (re && hay.some(h => re.test(h))) { no.push(cap(term.replace(/\*/g, ''))); break; }
      }
    }
    return { no: [...new Set(no)], maybe: [...new Set(maybe)] };
  }

  function foodSub(row) {
    const parts = [];
    for (const a of row.additives) parts.push(a.e + ' ' + a.name);
    const al = row.allergens.map(a => t('tag.foodAllergen', { name: cap(a.name) }));
    if (row.fromData) parts.push(t('tag.fromData'));
    if (row.why === 'b') return { lvl: { text: levelName('b'), g: 'red' }, parts };
    if (row.why === 'mine') return { lvl: { text: t('tag.mine'), g: 'red' }, parts: parts.concat(al) };
    if (row.why === 'allergen') return { lvl: { text: t('tag.allergenYours'), g: 'red' }, parts: row.tickedAllergens.map(a => cap(a.name)).concat(parts) };
    if (row.why === 'vegan') {
      const what = row.vegan.no.filter(n => n.toLowerCase() !== row.label.toLowerCase());
      return { lvl: { text: t('chip.vegan'), g: 'red' }, parts: (what.length ? what : [t('tag.animal')]).concat(parts.filter(x => !row.vegan.no.some(n => x.includes(n)))) };
    }
    if (row.group === 'orange' || (row.group === 'info' && row.level === 'r')) {
      const reason = !row.additives.length && row.rules[0] && row.rules[0].reasons[0] ? [row.rules[0].reasons[0].text] : [];
      return { lvl: { text: levelName(row.level), g: row.group }, parts: parts.concat(al, reason) };
    }
    if (row.group === 'info') return { lvl: null, parts: al.concat(parts, state.vegan && row.vegan.maybe.length ? [t('tag.maybeVegan')] : []) };
    const classes = row.additives.flatMap(a => a.classes || []).slice(0, 1);
    return { lvl: null, parts: parts.concat(classes) };
  }

  // The name used in the one-line summary.
  function shortName(row) {
    if (row.why === 'mine') return cap(row.mine.name);
    if (row.why === 'allergen' && row.kind === 'food') return cap(row.tickedAllergens[0].name);
    if (row.why === 'vegan') return row.label;
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
      const key = { b: 'sum.red1.b', mine: 'sum.red1.mine', allergen: 'sum.red1.allergen', fragrance: 'sum.red1.fragrance', vegan: 'sum.red1.vegan', use: 'sum.red1.use' }[r.why];
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
    showChecking(code);
    await ownReady;

    const cached = state.products[code];
    const own = !forceOnline && !(cached && cached.source === 'label') && ownBy(code);
    if (own) { showProduct(own); return; }
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
    $('searchPanel').hidden = true;
    $('status').hidden = true;
  }

  function showScanner() {
    hideAll();
    $('scanner').hidden = false;
    state.current = null;
    window.scrollTo({ top: 0 });
  }

  // Label reading and ingredient search open as their own screen (phone Back returns).
  function showPanel(id) {
    hideAll();
    stopCamera();
    $('scanner').hidden = true;
    $(id).hidden = false;
    window.scrollTo({ top: 0 });
  }

  function closePanel() {
    const v = history.state && history.state.view;
    if (v === 'label' || v === 'search') { try { history.back(); return; } catch (e) { /* fall through */ } }
    showScanner();
  }

  function showStatus(text, buttons) {
    const s = $('status');
    s.className = 'status';
    s.replaceChildren(el('p', { text, class: 'status-text' }));
    if (buttons && buttons.length) s.append(el('div', { class: 'row' }, buttons));
    s.hidden = false;
  }

  // Big "Checking …" card in the place of the result, while a barcode is looked up.
  function showChecking(code) {
    hideAll();
    $('scanner').hidden = true;
    const s = $('status');
    s.className = 'status busy';
    s.replaceChildren(
      el('span', { class: 'spin', 'aria-hidden': 'true' }),
      el('div', {},
        el('strong', { text: t('status.checking') }),
        el('p', { text: t('status.barcode', { code }) }),
        el('p', { class: 'src', text: t('status.searching') })));
    s.hidden = false;
    window.scrollTo({ top: 0 });
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
      $('scanner').hidden = false;
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
      p.kind === 'cosmetic' && a.verdict !== 'unknown' ? useBar(p) : null,
      productChips(p, a),
      el('div', { id: 'groups' }),
      p.ingredientsText
        ? el('details', { class: 'ingr' },
            el('summary', { text: t('ingredientsTitle') }),
            el('p', { class: 'ingredients', text: p.ingredientsText.replace(/^\s*[\p{L} ]{2,20}[:：]\s*/u, '') }))
        : null,
      dbWarn(),
      el('div', { class: 'actions' },
        el('button', { class: 'btn btn-primary', type: 'button', text: t('btn.scanNext'), onclick: scanNext }),
        el('button', { class: 'btn btn-ghost', type: 'button', text: a.verdict === 'unknown' ? t('btn.readLabel') : t('btn.readAgain'), onclick: () => openLabel(p) }),
        p.source === 'label' && isBarcode(p.code)
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

  // Stays on skin / washed off: some EU limits depend on it.
  function useBar(p) {
    const cur = p.use || '';
    return el('div', { class: 'usebar', role: 'group', 'aria-label': t('use.q') },
      el('span', { class: 'lbl', text: t('use.q') }),
      el('div', { class: 'segs' }, ['leave', 'rinse', ''].map(v => el('button', {
        type: 'button', class: 'seg', 'aria-pressed': String(cur === v), text: t('use.' + (v || 'unsure')),
        onclick: () => setUse(p, v)
      }))));
  }

  function setUse(p, v) {
    if (v) p.use = v; else delete p.use;
    if (state.products[p.code]) saveProduct(p);
    verdictCache.delete(p.code);
    const a = renderResult(p);
    state.history.forEach(h => { if (h.code === p.code) h.verdict = a.verdict; });
    store.set('history', state.history);
    renderHistory();
    renderFavs();
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

  // Only when the EU data is more than 6 months old: one orange line (it changes how far a result can be trusted).
  function dbWarn() {
    const built = META() && Date.parse(META().built);
    if (!built || Date.now() - built <= 183 * 864e5) return null;
    return el('p', { class: 'dbage old', text: t('data.eu', { date: fmtDate(built) }) + ' ' + t('data.euOld') });
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
    const k = r.why === 'b' ? 'chip.b' : r.why === 'use' ? 'chip.use' : r.why === 'mine' ? 'chip.mine' : r.why === 'allergen' ? 'chip.yourAlg'
      : r.why === 'fragrance' ? 'chip.frag' : r.why === 'vegan' ? 'chip.vegan'
      : r.group === 'orange' ? (r.level === 'u' ? 'chip.u' : 'chip.c')
      : r.group === 'info' ? (r.level === 'r' ? 'chip.r' : r.allergen || (r.allergens && r.allergens.length) ? 'chip.alg' : 'chip.maybeVegan') : null;
    return k ? t(k) : null;
  }
  // One short line: why this row has its colour.
  function whyOf(r) {
    if (r.kind === 'cosmetic') {
      const s = r.src, tags = cosmeticTags(r), fn = (s.functions || [])[0];
      if (r.why === 'use') return t('use.why');
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
    openLabel({ code }, true);
    renderPick(code);
    window.scrollTo({ top: 0 });
  }

  // Products the user may mean: ours without a barcode first, then Recent, then everything saved.
  function pickPool() {
    const seen = new Set(), out = [];
    const add = (p, where) => {
      if (!p || !p.ingredientsText || seen.has(p.code)) return;
      seen.add(p.code);
      out.push({ p, where });
    };
    OWN.filter(o => !isBarcode(o.code)).forEach(o => add(ownProduct(o), 'own'));
    state.history.forEach(h => add(productBy(h.code), 'recent'));
    Object.values(state.products).forEach(p => add(p, 'saved'));
    OWN.forEach(o => add(ownProduct(o), 'own'));
    return out;
  }

  let pickCode = null, pickQuery = null;
  function renderPick(code) {
    if (code !== undefined) { pickCode = code; pickQuery = null; }
    const box = $('pickBox');
    const pool = pickPool();
    if (!pickCode || !pool.length) { box.hidden = true; setLabelTitle(); return; }
    let items;
    if (pickQuery === null) {
      const own = pool.filter(x => x.where === 'own' && !isBarcode(x.p.code));
      items = own.concat(pool.filter(x => x.where === 'recent').slice(0, 3));
    } else {
      const q = LCDB.norm(pickQuery);
      items = q ? pool.filter(x => LCDB.norm([x.p.brand, x.p.name].join(' ')).includes(q)).slice(0, 8) : [];
    }
    const whereText = x => x.where === 'own' ? (isBarcode(x.p.code) ? t('src.ownShort') : t('pick.own')) : t(x.where === 'recent' ? 'start.recent' : 'pick.saved');
    const row = x => {
      const v = verdictOf(x.p.code, 'unknown').verdict;
      return el('li', {},
        el('span', { class: 'dot ' + VERDICT_DOT[v], 'aria-hidden': 'true' }),
        el('span', { class: 'nm' },
          el('strong', { text: x.p.name || t('ph.unnamed') }),
          el('small', { text: [x.p.brand, whereText(x)].filter(Boolean).join(' · ') })),
        el('button', {
          class: 'btn ' + (x.where === 'own' && !isBarcode(x.p.code) ? 'btn-primary' : 'btn-ghost'), type: 'button',
          text: t('pick.this'), 'aria-label': t('pick.this') + ': ' + (x.p.name || t('ph.unnamed')),
          onclick: () => linkBarcode(pickCode, x.p)
        }));
    };
    const parts = [el('h3', { text: t('pick.title') }), el('p', { class: 'sub', text: t('pick.sub') })];
    if (pickQuery === null) {
      parts.push(el('ul', {}, items.map(row)),
        el('button', { class: 'linkbtn more', type: 'button', text: t('pick.search'), onclick: () => {
          pickQuery = '';
          renderPick();
          const i = $('pickSearch'); if (i) i.focus();
        } }));
    } else {
      const input = el('input', { id: 'pickSearch', type: 'search', autocomplete: 'off', placeholder: t('pick.ph'), 'aria-label': t('pick.search') });
      input.value = pickQuery;
      input.addEventListener('input', () => {
        pickQuery = input.value;
        const pos = input.selectionStart;
        renderPick();
        const n = $('pickSearch'); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } }
      });
      parts.push(input, items.length ? el('ul', {}, items.map(row)) : (pickQuery.trim() ? el('p', { class: 'sub none', text: t('pick.none') }) : null));
    }
    box.replaceChildren(...parts.filter(Boolean));
    box.hidden = false;
    setLabelTitle();
  }

  // The scanned barcode now opens this product (saved on the phone, also offline; part of the backup).
  function linkBarcode(code, src) {
    if (!isBarcode(code) || !src) return;
    const p = Object.assign({}, src, { code, source: 'label', fetchedAt: Date.now(), linkedFrom: src.code });
    saveProduct(p);
    toast(t('toast.linked', { code }));
    showProduct(p);
  }

  function setLabelTitle() {
    $('labelTitle').textContent = t($('pickBox').hidden ? 'label.title' : 'label.titleOr');
  }

  function showOffline(code) {
    hideAll();
    $('scanner').hidden = false;
    showStatus(t('status.offline'), [
      el('button', { class: 'btn btn-primary', type: 'button', text: t('btn.tryAgain'), onclick: () => lookup(code) }),
      el('button', { class: 'btn btn-ghost', type: 'button', text: t('btn.readLabel'), onclick: () => openLabel({ code }, true) })
    ]);
  }

  // From a result: go back to the scanner (the state below a result is always the scanner).
  function scanNext() {
    try { history.replaceState({ tab: 'scan' }, ''); } catch (e) { /* ignore */ }
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
    const p = productBy(code);
    if (DBINFO && p) {
      try { const a = analyze(p); const v = { verdict: a.verdict, summary: a.summary }; verdictCache.set(code, v); return v; }
      catch (e) { /* use the saved one */ }
    }
    return { verdict: fallback || 'unknown', summary: '' };
  }

  function productListItem(item, opts) {
    const v = verdictOf(item.code, item.verdict);
    const p = productBy(item.code) || item;
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
    renderStart();
  }

  // Start screen: what is being checked, and the last 3 products.
  function renderStart() {
    const chips = [t('start.eu')];
    if (state.avoid.length) chips.push(t('start.list', { n: state.avoid.length }));
    const alg = state.allergens.food.length + state.allergens.cos.length;
    if (alg) chips.push(t('start.alg', { n: alg }));
    if (state.avoidFragrance) chips.push(t('start.frag'));
    if (state.vegan) chips.push(t('start.vegan'));
    $('checking').replaceChildren(el('span', { class: 'lbl', text: t('start.checking') }),
      ...chips.map(c => el('button', { class: 'cchip', type: 'button', text: c, onclick: () => go('list') })));
    const items = state.history.slice(0, 3);
    $('recent').hidden = !items.length;
    $('recentList').replaceChildren(...items.map(h => productListItem(h, { summary: true })));
  }

  function openSaved(code) {
    go('scan');
    const p = productBy(code);
    if (p) showProduct(p);
    else lookup(code);
  }

  // ---------- Ingredient detail ----------
  let detailReturn = null;

  function openDetail(i, from) {
    const r = state.current && state.current.a.rows[i];
    if (r) openDetailRow(r, from);
  }

  function openDetailRow(r, from) {
    detailReturn = from || null;
    renderDetail(r);
    $('detail').hidden = false;
    $('detail').scrollTop = 0;
    document.documentElement.classList.add('noscroll');
    pushState(Object.assign({}, history.state || { tab: 'scan' }, { detail: 1 }));
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
    body.push(el('p', { class: 'd-meta', text: r.fromSearch ? t(r.kind === 'cosmetic' ? 'search.kindCos' : 'search.kindFood') : r.pos ? t('d.pos', { n: r.pos }) : t('d.posNone') }));

    const top = r.why === 'mine' ? t('tag.mine') : r.why === 'allergen' ? t('tag.allergenYours')
      : r.why === 'fragrance' ? t('tag.fragranceAvoid') : r.why === 'vegan' ? t('chip.vegan') : r.why === 'use' ? t('chip.use') : levelName(r.level);
    body.push(badge(r.group, top));

    // Personal reasons (your list, allergens, fragrance)
    const mineP = [];
    if (r.mine) mineP.push(el('p', { text: t('d.mineWhy', { term: r.mine.term }) }));
    if (r.why === 'allergen') mineP.push(el('p', { text: t('d.allergenTicked') }));
    if (r.fragAvoid) mineP.push(el('p', { text: t('d.fragranceWhy') }));
    if (r.useHit) mineP.push(el('p', { text: t('d.useWhy') }));
    if (r.vegan && state.vegan && r.vegan.no.length) mineP.push(el('p', { text: t('d.veganNo', { names: r.vegan.no.join(', ') }) }));
    if (r.vegan && state.vegan && r.vegan.maybe.length) mineP.push(el('p', { text: t('d.veganMaybe', { names: r.vegan.maybe.join(', ') }) }));
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

  function openLabel(p, keepStatus) {
    labelFor = p && p.code ? p : null;
    const keep = keepStatus && !$('status').hidden;
    showPanel('labelPanel');
    pickCode = null;
    $('pickBox').hidden = true;
    setLabelTitle();
    if (keep) $('status').hidden = false;
    if (!history.state || history.state.view !== 'label') pushState({ tab: 'scan', view: 'label' });
    const panel = $('labelPanel');
    $('labelText').value = '';
    ocrFile = null;
    $('ocrArea').hidden = true;
    $('claudeBox').open = false;
    ocrStatus('');
    $('labelName').value = (p && p.name) || '';
    const kind = (p && p.kind) || 'food';
    document.querySelectorAll('input[name="kind"]').forEach(i => { i.checked = i.value === kind; });
    $('labelLead').textContent = labelFor && isBarcode(labelFor.code)
      ? t('label.leadFor', { code: labelFor.code }) : t('label.lead');
    panel.scrollIntoView({ behavior: 'auto', block: 'start' });
  }

  // ---------- Find one ingredient (offline) ----------
  let searchTimer = null;

  function openSearch() {
    showPanel('searchPanel');
    if (!history.state || history.state.view !== 'search') pushState({ tab: 'scan', view: 'search' });
    renderSearch();
    $('searchInput').focus();
  }

  // One result -> the same row the result screen uses, with your settings applied.
  function searchRow(hit) {
    const p = hit.kind === 'cosmetic' ? { kind: 'cosmetic', ingredientsText: hit.name } : { kind: 'food', ingredientsText: hit.id.toUpperCase() };
    const row = analyze(p).rows[0];
    if (!row) return null;
    row.fromSearch = true;
    row.pos = null;
    if (hit.kind === 'food' && row.additives && row.additives[0]) row.label = cap(row.additives[0].name) + ' (' + row.additives[0].e + ')';
    return row;
  }

  function renderSearch() {
    const q = $('searchInput').value.trim();
    const list = $('searchList'), info = $('searchInfo');
    if (!DBINFO) { info.textContent = t(DBINFO === null ? 'status.dbLoading' : 'status.dbFail'); list.replaceChildren(); return; }
    if (q.length < 2) { info.textContent = t('search.hint'); list.replaceChildren(); return; }
    const rows = LCDB.search(q, 30).map(searchRow).filter(Boolean);
    const own = ownSearch(q);
    info.textContent = rows.length || own.length ? '' : t('search.none');
    list.replaceChildren(...own.map(ownRow), ...rows.map(r => {
      const chip = chipOf(r);
      const kind = t(r.kind === 'cosmetic' ? 'search.kindCosShort' : 'search.kindFoodShort');
      const detail = r.kind === 'food' && r.additives && r.additives[0] ? (r.additives[0].classes || []).join(', ') : whyOf(r);
      const why = [kind, detail].filter(Boolean).join(' · ');
      return el('li', {},
        el('button', { class: 'row-btn', type: 'button', onclick: e => openDetailRow(r, e.currentTarget) },
          el('span', { class: 'dot g-' + r.group, 'aria-hidden': 'true' }),
          el('span', { class: 'main' },
            chip ? el('span', { class: 'chip g-' + r.group, text: chip }) : null,
            el('strong', { text: r.label }),
            el('span', { class: 'why', text: why })),
          icon(ICON.chev, 'chev')));
    }));
  }

  // A product from our list, on top of the search results.
  function ownRow(p) {
    const v = analyze(p).verdict;
    return el('li', { class: 'own' },
      el('button', { class: 'row-btn', type: 'button', onclick: () => showProduct(p) },
        el('span', { class: 'dot ' + VERDICT_DOT[v], 'aria-hidden': 'true' }),
        el('span', { class: 'main' },
          el('strong', { text: [p.brand, p.name].filter(Boolean).join(' ') }),
          el('span', { class: 'why', text: [t('src.ownShort'), t(p.kind === 'cosmetic' ? 'kind.cosmetic' : 'kind.food'), t('v.' + v)].join(' · ') })),
        icon(ICON.chev, 'chev')));
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) { return false; }
  }

  // ---------- Read a label: offline reader (Tesseract, in ocr/) ----------
  // The reader files load only when you tap "Read text", so barcode scans stay fast.
  const OCR_LANGS = { en: 'eng', de: 'deu', bg: 'bul' };
  let ocrFile = null, ocrWorker = null, ocrSeq = 0, ocrBusy = false, claudeNext = false;
  const ocrWait = {};
  const crop = { x: 0.06, y: 0.3, w: 0.88, h: 0.4 };   // part of the photo, 0..1

  function ocrLang() {
    const v = store.get('ocrLang', null);
    return Object.values(OCR_LANGS).includes(v) ? v : (OCR_LANGS[LANG] || 'eng');
  }
  function renderOcrLang() {
    const cur = ocrLang();
    $('ocrLang').setAttribute('aria-label', t('ocr.lang'));
    $('ocrLang').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.ocr === cur)));
  }
  function drawCrop() {
    const b = $('cropBox').style;
    b.left = crop.x * 100 + '%'; b.top = crop.y * 100 + '%';
    b.width = crop.w * 100 + '%'; b.height = crop.h * 100 + '%';
  }
  function ocrStatus(text, cls) {
    const n = $('ocrStatus');
    n.hidden = !text; n.textContent = text || ''; n.className = 'ocrstatus' + (cls ? ' ' + cls : '');
  }

  function onPhoto(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    ocrFile = file;
    if (claudeNext) { claudeNext = false; shareToClaude(file); }
    const img = $('cropImg');
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    img.dataset.url = URL.createObjectURL(file);
    img.src = img.dataset.url;
    Object.assign(crop, { x: 0.06, y: 0.3, w: 0.88, h: 0.4 });
    drawCrop();
    renderOcrLang();
    ocrStatus('');
    $('ocrArea').hidden = false;
    $('ocrArea').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Drag the box (move) or its corners (resize). Works with finger and mouse.
  function initCrop() {
    const box = $('cropBox'), wrap = $('cropInner');
    let drag = null;
    box.addEventListener('pointerdown', e => {
      const r = wrap.getBoundingClientRect();
      drag = { h: e.target.dataset.h || 'move', x: e.clientX, y: e.clientY, w: r.width, hh: r.height, c: Object.assign({}, crop) };
      box.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    box.addEventListener('pointermove', e => {
      if (!drag) return;
      const dx = (e.clientX - drag.x) / drag.w, dy = (e.clientY - drag.y) / drag.hh, c = drag.c, MIN = 0.08;
      let { x, y, w, h } = c;
      if (drag.h === 'move') {
        x = Math.min(Math.max(0, c.x + dx), 1 - c.w); y = Math.min(Math.max(0, c.y + dy), 1 - c.h);
      } else {
        if (drag.h.includes('w')) { x = Math.min(Math.max(0, c.x + dx), c.x + c.w - MIN); w = c.x + c.w - x; }
        if (drag.h.includes('e')) { w = Math.min(Math.max(MIN, c.w + dx), 1 - c.x); }
        if (drag.h.includes('n')) { y = Math.min(Math.max(0, c.y + dy), c.y + c.h - MIN); h = c.y + c.h - y; }
        if (drag.h.includes('s')) { h = Math.min(Math.max(MIN, c.h + dy), 1 - c.y); }
      }
      Object.assign(crop, { x, y, w, h });
      drawCrop();
    });
    const end = () => { drag = null; };
    box.addEventListener('pointerup', end);
    box.addEventListener('pointercancel', end);
  }

  // Cut out the box, make the text clear (grey + contrast) and send it as PNG.
  async function ocrImage() {
    const bmp = await createImageBitmap(ocrFile, { imageOrientation: 'from-image' });
    const sx = Math.round(crop.x * bmp.width), sy = Math.round(crop.y * bmp.height);
    const sw = Math.max(1, Math.round(crop.w * bmp.width)), sh = Math.max(1, Math.round(crop.h * bmp.height));
    let k = Math.min(2400 / sw, 2400 / sh, 1);       // not too big (speed)
    if (sw < 1400) k = Math.min(2, 1600 / sw);      // small print: make it bigger
    const W = Math.round(sw * k), H = Math.round(sh * k);
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: true });
    cx.imageSmoothingQuality = 'high';
    cx.drawImage(bmp, sx, sy, sw, sh, 0, 0, W, H);
    if (bmp.close) bmp.close();
    const im = cx.getImageData(0, 0, W, H), d = im.data, n = W * H;
    const g = new Uint8ClampedArray(n), hist = new Uint32Array(256);
    let sum = 0;
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      const v = (d[j] * 299 + d[j + 1] * 587 + d[j + 2] * 114) / 1000;
      g[i] = v; hist[g[i]]++; sum += v;
    }
    if (sum / n >= 110) {   // light label: grey + stretch contrast. Dark labels stay in colour (the reader handles them better).
      let lo = 0, hi = 255, acc = 0;
      const cut = n * 0.01;
      while (lo < 255 && (acc += hist[lo]) <= cut) lo++;
      acc = 0;
      while (hi > 0 && (acc += hist[hi]) <= cut) hi--;
      const span = Math.max(1, hi - lo);
      for (let i = 0, j = 0; i < n; i++, j += 4) {
        const v = Math.min(255, Math.max(0, ((g[i] - lo) * 255) / span));
        d[j] = d[j + 1] = d[j + 2] = v;
      }
      cx.putImageData(im, 0, 0);
    }
    const blob = await new Promise(res => cv.toBlob(res, 'image/png'));
    return new Uint8Array(await blob.arrayBuffer());
  }

  function ocrRun(image, lang) {
    if (!ocrWorker) {
      ocrWorker = new Worker('ocr/ocr-worker.js');
      ocrWorker.onmessage = e => {
        const m = e.data, w = ocrWait[m.id];
        if (!w) return;
        if (m.step) { w.step(m.step); return; }
        delete ocrWait[m.id];
        m.error ? w.reject(new Error(m.error)) : w.resolve(m);
      };
      ocrWorker.onerror = e => {
        Object.keys(ocrWait).forEach(id => { ocrWait[id].reject(new Error(e.message || 'worker')); delete ocrWait[id]; });
        ocrWorker = null;
      };
    }
    const id = ++ocrSeq;
    return new Promise((resolve, reject) => {
      ocrWait[id] = { resolve, reject, step: s => ocrStatus(t(s === 'load' ? 'ocr.loading' : 'ocr.reading'), 'busy') };
      ocrWorker.postMessage({ id, image, lang }, [image.buffer]);
    });
  }

  // Reader text -> one line; start at "Ingredients:" when the label has it.
  function cleanOcr(text) {
    let s = String(text || '').replace(/[­]/g, '').replace(/(\p{L})-\s*\n\s*(\p{Ll})/gu, '$1$2');
    s = s.replace(/\s*\n\s*/g, ' ').replace(/[|_]{1,}/g, ' ').replace(/\s{2,}/g, ' ').trim();
    const m = s.match(/(ingredients|ingrédients|ingredienti|ingredientes|zutaten|съставки)\s*[:：]/i);
    if (m && m.index > 0) s = s.slice(m.index);
    return s;
  }

  async function onOcrRead() {
    if (!ocrFile) { toast(t('toast.photoFirst')); return; }
    if (ocrBusy) return;
    ocrBusy = true;
    $('ocrRead').disabled = true;
    const t0 = performance.now();
    ocrStatus(t('ocr.reading'), 'busy');
    try {
      const r = await ocrRun(await ocrImage(), ocrLang());
      const text = cleanOcr(r.text);
      const secs = ((performance.now() - t0) / 1000).toFixed(1).replace('.', LANG === 'en' ? '.' : ',');
      if (text.replace(/[^\p{L}]/gu, '').length < 12 || r.conf < 25) {
        ocrStatus(t('ocr.little'), 'warn');
        if (text) $('labelText').value = text;
      } else {
        $('labelText').value = text;
        ocrStatus(t('ocr.done', { s: secs }));
      }
      $('labelText').scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (err) {
      ocrStatus(t('ocr.fail'), 'warn');
    } finally {
      ocrBusy = false;
      $('ocrRead').disabled = false;
    }
  }

  // Option 2: send the same photo to Claude (old way).
  async function shareToClaude(file) {
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
    const base = labelFor && labelFor.code ? productBy(labelFor.code) : null;
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
    $('scanner').classList.add('scanning');
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
    $('stopCam').hidden = true;
    $('vfIdle').hidden = false;
    $('scanner').classList.remove('scanning');
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
    renderStart();
    if (!$('searchPanel').hidden) renderSearch();
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
      el('p', {}, tNodes('credit.ocr', {
        tess: link('https://github.com/tesseract-ocr/tesseract', 'Tesseract OCR'),
        apache: link('https://www.apache.org/licenses/LICENSE-2.0', 'Apache 2.0')
      })),
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
    if (!$('searchPanel').hidden) renderSearch();
    if (!$('labelPanel').hidden) $('labelLead').textContent = labelFor && isBarcode(labelFor.code) ? t('label.leadFor', { code: labelFor.code }) : t('label.lead');
    if (!$('labelPanel').hidden && !$('pickBox').hidden) renderPick();
  }

  // ---------- Backup ----------
  function exportBackup() {
    const data = {
      app: 'label-check', version: 2, exportedAt: new Date().toISOString(),
      avoid: state.avoid, favs: state.favs, allergens: state.allergens, avoidFragrance: state.avoidFragrance, vegan: state.vegan,
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
    if (typeof data.vegan === 'boolean') state.vegan = data.vegan;
    if (['auto', 'en', 'de', 'bg'].includes(data.lang)) state.lang = data.lang;
    if (['auto', 'light', 'dark'].includes(data.theme)) state.theme = data.theme;
    if (typeof data.bigText === 'boolean') state.bigText = data.bigText;
    for (const k of ['avoid', 'history', 'products', 'favs', 'allergens', 'avoidFragrance', 'vegan', 'lang', 'theme', 'bigText']) store.set(k, state[k]);
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
    $('veganSwitch').checked = !!state.vegan;
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
      if (tab === 'scan' && $('scanner').hidden) {
        try { history.replaceState({ tab: 'scan' }, ''); } catch (e) { /* ignore */ }
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
    if (st.tab !== 'scan') return;
    if (st.view === 'result') {
      const p = state.current && state.current.p.code === st.code ? state.current.p : productBy(st.code);
      if (!p || !DBINFO) showScanner();
      else if ($('result').hidden || !state.current || state.current.p !== p) renderResult(p);
    } else if (st.view === 'search') {
      showPanel('searchPanel');
      renderSearch();
    } else if (st.view === 'label') {
      showPanel('labelPanel');
    } else if ($('scanner').hidden) {
      showScanner();
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
    $('cardScan').addEventListener('click', startCamera);
    $('stopCam').addEventListener('click', stopCamera);
    $('cardLabel').addEventListener('click', () => openLabel(null));
    $('cardSearch').addEventListener('click', openSearch);
    $('recentAll').addEventListener('click', () => go('history'));
    document.querySelectorAll('[data-back]').forEach(b => b.addEventListener('click', closePanel));
    $('searchInput').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(renderSearch, 120); });
    $('manualForm').addEventListener('submit', e => {
      e.preventDefault();
      stopCamera();
      lookup($('codeInput').value);
    });
    $('photoInput').addEventListener('change', onPhoto);
    $('photoPick').addEventListener('change', onPhoto);
    $('ocrRead').addEventListener('click', onOcrRead);
    $('ocrLang').addEventListener('click', e => {
      const b = e.target.closest('button[data-ocr]');
      if (b) { store.set('ocrLang', b.dataset.ocr); renderOcrLang(); }
    });
    $('shareClaude').addEventListener('click', () => { if (ocrFile) shareToClaude(ocrFile); else { claudeNext = true; $('photoInput').click(); } });
    initCrop();
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
    $('veganSwitch').addEventListener('change', e => {
      state.vegan = e.target.checked;
      store.set('vegan', state.vegan);
      settingsChanged();
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
    $('langSwitch').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
      setLanguage(b.dataset.lang);
      syncSettingsControls();
    }));
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
    Promise.all([dbReady, ownReady]).then(() => { renderRules(); renderAllergens(); renderFavs(); renderHistory(); });

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(() => { /* app still works online */ });
    }
  }

  // Small test hook (used only by automated checks).
  window.LC = { analyze, termRe, matchAvoid, niceName, parseClaudeAnswer, state, lookup, showProduct, dbReady, t, setLanguage, openSearch };

  init();
})();
