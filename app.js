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
    'nutriscore_grade', 'nova_group', 'last_modified_t', 'nutriments'
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
  const GROUPS = ['red', 'orange', 'info', 'nodata', 'green'];   // nodata (grey): a cosmetic name the app does not know
  const LEVEL_GROUP = { b: 'red', c: 'orange', u: 'orange', r: 'info', n: 'green' };
  const SEV = { b: 5, c: 4, u: 3, r: 2, n: 1 };
  const VERDICT_DOT = { avoid: 'g-red', check: 'g-orange', ok: 'g-green', partial: 'g-grey', unknown: 'g-grey' };
  const PARTIAL_MIN = 0.7;   // cosmetics: fewer known names than this share = "Incomplete result" instead of "No warnings"
  const LOCALE = { en: 'en-GB', de: 'de-AT', bg: 'bg-BG' };
  const KINDS = ['food', 'cosmetic', 'household'];
  const kindKey = k => 'kind.' + (KINDS.includes(k) ? k : 'food');

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
    names: store.get('names', {}),           // {code: name you gave the product}
    taught: store.get('taught', {}),         // {key of a label name: {from, to}} – names you taught the app (v2.12)
    allergens: Object.assign({ food: [], cos: [] }, store.get('allergens', {})), // ticked ids / annex refs
    avoidFragrance: store.get('avoidFragrance', false),
    vegan: store.get('vegan', false),
    lang: store.get('lang', 'auto'),
    theme: store.get('theme', 'auto'),
    bigText: store.get('bigText', false),
    vibrate: store.get('vibrate', true),        // v2.13: buzz on a new result (1 = no warnings, 2 = check, 3 = avoid)
    current: null,   // { p, a } shown on the scan tab
    detailsOpen: false, // "Details" under the answer card
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
    document.querySelectorAll('[data-t-aria]').forEach(n => { n.setAttribute('aria-label', t(n.dataset.tAria)); n.title = t(n.dataset.tAria); });
    document.querySelector('.tabbar').setAttribute('aria-label', [t('tab.scan'), t('tab.list'), t('tab.history')].join(', '));
    if ($('offState')) renderOffline();
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
    .then(info => { DBINFO = info; setTimeout(() => { try { LCDB.suggestCosmetic('Warmup index'); } catch (e) { /* ignore */ } }, 2500); return info; })   // v2.18.1: build the fix-suggestion index while idle, not on the first Cosmetic tap
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
      code: ownCode(o), kind: KINDS.includes(o.kind) ? o.kind : 'food', source: 'own',
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
    return applyName(p && p.source !== 'own' ? p : (ownBy(code) || p || null));
  }
  // A name you gave a product wins over the name from the databases (kept on the phone and in the backup).
  function applyName(p) {
    if (p && p.code && state.names[p.code]) p.name = state.names[p.code];
    return p;
  }

  // ---------- Analysis ----------
  // Every ingredient becomes a row with a level (b c u r n) and a group (red orange info green).
  function analyze(p) {
    const text = p.ingredientsText || '';
    let rows = p.kind === 'cosmetic' || p.kind === 'household' ? analyzeCosmetic(text, p.use, p.kind === 'household') : analyzeFood(p, text);

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

    const counts = { red: 0, orange: 0, info: 0, nodata: 0, green: 0 };
    for (const r of rows) counts[r.group]++;
    // Cosmetics / household: how many names the app knows. With many unknown names "No warnings" would say too much.
    const listed = rows.filter(r => r.kind === 'cosmetic' && r.pos);
    const unknown = listed.filter(isUnknown).length, known = listed.length - unknown;
    const partial = listed.length >= 3 && known / listed.length < PARTIAL_MIN;
    // v2.13: text read from a photo where the app found no ingredients heading ("Zutaten:", "Съставки:" …) may be the
    // wrong text (a nutrition table, another language, no list at all). It is never shown as "No warnings".
    const noList = !!(p.read && p.read.photo && !p.read.list);
    // v2.15: a photo read is "No warnings" only with proof of a full list: at least 3 names and an end that is not cut off.
    const total = rows.filter(r => r.pos).length;
    const weak = p.read && p.read.photo && !noList ? weakRead(text, total, p.read.conf) : '';
    const verdict = counts.red ? 'avoid' : counts.orange ? 'check' : rows.length ? (partial || noList || weak ? 'partial' : 'ok') : 'unknown';
    return {
      verdict, rows, counts, known, unknown, noList, weak,
      summary: summarize(verdict, rows, counts, { n: known, of: listed.length, noList, weak, total }),
      total,
      fragrance: rows.filter(r => r.fragrance || r.allergen).length
    };
  }

  // v2.16: the reader's own confidence for the text. Good reads gave 73-95, garbled ones (Ketozolin) 50-63.
  const READ_SURE = 66;
  function weakRead(text, total, conf) {
    if (total < 3) return 'Few';
    if (typeof conf === 'number' && conf < READ_SURE) return 'Blur';
    const tx = String(text || '').trim();
    const open = (tx.match(/[(\[]/g) || []).length > (tx.match(/[)\]]/g) || []).length;
    return open || /[,;(\[:\-–]$/.test(tx) ? 'Cut' : '';
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

  // Household products (dish soap, detergents): EU labels name groups with a % range ("5–15 % anionic surfactants").
  const DET_TERMS = [
    ['anionic', /anionisch\S* tensid|anionic surfactant|анионн\S* (пав|повърхностно)/],
    ['nonionic', /nicht ?ionisch\S* tensid|non ?ionic surfactant|нейонн\S* (пав|повърхностно)/],
    ['cationic', /kationisch\S* tensid|cationic surfactant|катионн\S* (пав|повърхностно)/],
    ['amphoteric', /amphoter\S* tensid|amphoteric surfactant|амфотерн\S* (пав|повърхностно)/],
    ['soap', /^(seife|soap|сапун)$/],
    ['phosphonates', /phosphonat|фосфонат/],
    ['polycarboxylates', /polycarboxylat|поликарбоксилат/],
    ['zeolites', /zeolit|зеолит/],
    ['enzymes', /^(enzyme|enzymes|ензими)$/],
    ['brighteners', /optische\S* aufheller|optical brightener|оптичн\S* избелител/],
    ['oxygenBleach', /bleichmittel auf sauerstoffbasis|oxygen ?based bleach|белин\S* на кислородна основа|кислородн\S* белин/],
    ['chlorineBleach', /bleichmittel auf chlorbasis|chlorine ?based bleach|белин\S* на хлорна основа|хлорн\S* белин/],
    ['disinfectants', /desinfektionsmittel|disinfectant|дезинфектант/]
  ];
  const DET_RANGE = /(?:<|>|≤|≥|unter|weniger als|less than|under|под|по-малко от)?\s*\d+(?:[.,]\d+)?\s*(?:[-–]\s*\d+(?:[.,]\d+)?)?\s*%/i;
  function detergentTerm(seg) {
    const m = String(seg || '').match(DET_RANGE);
    const name = nrm(String(seg || '').replace(DET_RANGE, ' ')).replace(/^(und|and|и|unter|weniger als|less than|under)\s+/, '');
    const hit = DET_TERMS.find(([, re]) => re.test(name));
    return hit ? { key: hit[0], range: m ? m[0].replace(/\s+/g, ' ').replace(/\s*([-–])\s*/, '–').trim() : '' } : null;
  }

  function analyzeCosmetic(text, use, household) {
    return LCDB.checkCosmetic(text, LANG).map(r => {
      const det = household && !r.found ? detergentTerm(r.text) : null;
      if (det) r = Object.assign({}, r, { found: true, name: null, functions: [t('det.fn') + (det.range ? ' · ' + det.range : '')], reasons: [] });
      // A name you taught the app ("GLYCERN" = Glycerin): checked as that ingredient, the label text stays as it is.
      // An entry without "to" means: you said the app's correction is wrong, so it stays unknown.
      const taught = !r.found && !det ? taughtFor(r.text) : null;
      const asIngredient = name => {
        const k = LCDB.checkCosmetic(name + (r.nano ? ' (nano)' : ''), LANG).find(x => x.found);
        return k ? Object.assign({}, k, { pos: r.pos, text: r.text, mayContain: r.mayContain }) : null;
      };
      if (taught && taught.to) { const k = asIngredient(taught.to); if (k) r = k; }
      const row = cosRow(r, use, household, det);
      row.taught = taught && taught.to && r.found ? taught : null;
      // v2.13: names the photo reader got a little wrong. EU cosmetic labels must use the EU / INCI names, so an
      // unknown name with one clear close name is almost always that name.
      if (isUnknown(row) && !taught) {
        const sug = LCDB.suggestCosmetic(r.text, true);
        if (sug && sug.choices) row.choices = sug.choices;                    // (c) two or more close names: you choose
        else if (sug && sug.inci) {
          const k = asIngredient(sug.inci);
          const cand = k ? cosRow(k, use, household, null) : null;
          if (cand && cand.group !== 'red' && cand.group !== 'orange') {    // (a) no warning: the app corrects it
            cand.auto = { from: sug.from, to: sug.inci };
            cand.sub = cosmeticSub(cand);
            return cand;
          }
          if (cand) {                                                        // (b) a warning: never decided alone
            row.ask = { from: sug.from, to: sug.inci, group: cand.group, level: cand.level, why: cand.why, src: cand.src };
            row.group = 'orange';
            row.label = niceName(sug.inci) + '?';
            row.sub = cosmeticSub(row);
          }
        }
      }
      return row;
    });
  }

  function cosRow(r, use, household, det) {
    // Household: an EU cosmetics ban is shown as orange "not in cosmetics" (detergents have other EU rules).
    const banCos = household && r.level === 'b';
    const level = banCos ? 'c' : r.level;
    const mine = matchAvoid([r.text, r.found && r.name ? r.name : '']);
    const tickedAllergen = !!(r.allergen && state.allergens.cos.includes(r.allergenRef));
    const fragAvoid = !!(state.avoidFragrance && (r.fragrance || r.allergen));
    const useHit = !household && use === 'leave' && (r.reasons || []).some(rinseOnly);
    const why = level === 'b' ? 'b' : useHit ? 'use' : mine ? 'mine' : tickedAllergen ? 'allergen' : fragAvoid ? 'fragrance' : null;
    const row = {
      pos: r.pos, kind: 'cosmetic', text: r.text, household, banCos, det,
      label: det ? t('det.' + det.key) : r.found ? niceName(r.name) : cleanSeg(r.text),
      level, why, mine, tickedAllergen, fragAvoid, useHit,
      fragrance: r.fragrance, allergen: r.allergen, nano: r.nano, mayContain: r.mayContain, found: r.found, src: r
    };
    // Grey "No data": the app knows nothing about the name. Green: a known name with nothing on the EU lists.
    row.group = why ? 'red' : isUnknown(row) ? 'nodata' : LEVEL_GROUP[level] || 'green';
    row.sub = cosmeticSub(row);
    return row;
  }

  // A cosmetic name on the label that is not in our data (fragrance words count as known: the app knows they are fragrance)
  function isUnknown(r) { return r.kind === 'cosmetic' && !!r.pos && !r.found && !r.fragrance; }

  // ---------- Names you taught the app (v2.12, only on this phone) ----------
  // Key = the name before a bracket, without marks like * or ° (the same cut as the fix suggestions in db.js)
  function teachName(seg) {
    return String(seg || '').replace(/\s*[\[(].*$/, '').replace(/[\s*°¹²³†‡.:]+$/, '').replace(/^[\s*°.:\-–]+/, '').trim();
  }
  function teachKey(seg) { return nrm(teachName(seg)); }
  function taughtFor(seg) {
    const k = teachKey(seg);
    return k && Object.prototype.hasOwnProperty.call(state.taught, k) ? state.taught[k] : null;
  }

  function cosmeticTags(row) {
    const tags = [];
    if (row.taught) tags.push(t('tag.taught'));
    if (row.auto) tags.push(t('tag.auto'));
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
    if (row.ask) return { lvl: { text: t('chip.ask'), g: 'orange' }, parts: [t('ask.maybe', { name: niceName(row.ask.to) })] };
    if (row.why === 'b') return { lvl: { text: levelName('b'), g: 'red' }, parts: tags.length ? tags : (r.functions || []).slice(0, 1) };
    if (row.why === 'use') return { lvl: { text: t('chip.use'), g: 'red' }, parts: [t('use.why')] };
    if (row.why === 'mine') return { lvl: { text: t('tag.mine'), g: 'red' }, parts: tags };
    if (row.why === 'allergen') return { lvl: { text: t('tag.allergenYours'), g: 'red' }, parts: tags };
    if (row.why === 'fragrance') return { lvl: { text: t('tag.fragranceAvoid'), g: 'red' }, parts: tags };
    if (row.banCos) return { lvl: { text: t('chip.banCos'), g: 'orange' }, parts: [t('why.banCos')] };
    if (row.group === 'orange') return { lvl: { text: levelName(row.level), g: 'orange' }, parts: [firstReason] };
    if (row.group === 'info') return { lvl: { text: levelName(row.level), g: 'info' }, parts: tags.length ? tags : [firstReason] };
    return { lvl: null, parts: [...new Set(tags.concat((r.functions || []).slice(0, 1)))] };
  }

  const ALLERGEN_TAG = /^en:(gluten|crustaceans|eggs|fish|peanuts|soybeans|milk|nuts|celery|mustard|sesame-seeds|sulphur-dioxide-and-sulphites|lupin|molluscs)$/;

  function analyzeFood(p, text) {
    const { segs, traceFrom } = LCDB.labelSegments(text);   // pieces from traceFrom on are "may contain traces"
    const segN = segs.map(nrm);
    const res = LCDB.checkFood(text, LANG);
    const blank = (pos, txt, label) => ({ pos, kind: 'food', text: txt, label, additives: [], rules: [], allergens: [] });
    // Name = the part before any bracket ("Nitritpökelsalz (Speisesalz, …)" -> "Nitritpökelsalz"); full text on the detail screen.
    const shortSeg = s => cleanSeg(s.replace(/\s*[([][^)\]]*[)\]]/g, ' ')) || cleanSeg(s);
    const rows = segs.map((s, i) => Object.assign(blank(i + 1, s, shortSeg(s)), { trace: i + 1 >= traceFrom }));
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
      row.traceOnly = row.allergens.length > 0 && row.allergens.every(a => a.trace);   // allergens only from "may contain traces"
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
    if (row.trace) return { no, maybe };   // traces are not ingredients
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
    if (row.why === 'allergen') return { lvl: { text: t(row.traceOnly ? 'tag.tracesYours' : 'tag.allergenYours'), g: 'red' }, parts: row.tickedAllergens.map(a => cap(a.name)).concat(parts) };
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

  function summarize(verdict, rows, counts, kn) {
    if (verdict === 'unknown') return t('sum.unknown');
    if (verdict === 'partial' && kn.weak && !kn.noList && !(kn.of && kn.n < kn.of)) return t('sum.weak' + kn.weak, kn);
    if (verdict === 'partial') return t(kn.noList && !(kn.of && kn.n < kn.of) ? 'sum.noList' : 'sum.partial', kn);
    if (verdict === 'avoid') {
      if (counts.red > 1) return t('sum.redN', { n: counts.red });
      const r = rows.find(x => x.group === 'red');
      const key = { b: 'sum.red1.b', mine: 'sum.red1.mine', allergen: 'sum.red1.allergen', fragrance: 'sum.red1.fragrance', vegan: 'sum.red1.vegan', use: 'sum.red1.use' }[r.why];
      return t(key, { name: shortName(r) });
    }
    if (verdict === 'check') {
      if (counts.orange > 1) return t('sum.orN', { n: counts.orange });
      const r = rows.find(x => x.group === 'orange');
      if (r.ask) return t('sum.ask', { name: niceName(r.ask.to) });
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
      nut: kind === 'food' ? nutOf(p.nutriments) : null,
      updated: p.last_modified_t ? p.last_modified_t * 1000 : null,
      fetchedAt: Date.now(),
      url: base + '/product/' + code
    };
  }

  // Fat, saturated fat and protein per 100 g (only when Open Food Facts has them).
  function nutOf(n) {
    if (!n || typeof n !== 'object') return null;
    const num = k => { const v = Number(n[k]); return n[k] !== '' && n[k] !== null && isFinite(v) ? Math.round(v * 10) / 10 : null; };
    const o = { fat: num('fat_100g'), sat: num('saturated-fat_100g'), prot: num('proteins_100g') };
    return o.fat === null && o.prot === null ? null : o;
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
    info: 'M21 12a9 9 0 1 1-18 0a9 9 0 1 1 18 0zM12 11v6M12 7.5h.01',
    again: 'M4 12a8 8 0 0 1 13.7-5.6L20 8.7M20 4v4.7h-4.7M20 12a8 8 0 0 1-13.7 5.6L4 15.3M4 20v-4.7h4.7',
    heart: 'M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z',
    share: 'M12 15V4M8 8l4-4 4 4M5 13v5.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V13',
    close: 'M6 6l12 12M18 6L6 18',
    tag: 'M3.5 12.5v-8a1 1 0 0 1 1-1h8l8 8-9 9zM8 8h.01',
    pen: 'M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3zM14.5 7.5l2 2',
    ok: 'M5 12.5l4.5 4.5L19 7.5'
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
  // v2.13: a new result can be felt without looking: 1 short buzz = no warnings, 2 = check, 3 = avoid (Android).
  let buzzNext = false;
  function buzz(verdict) {
    const pat = { ok: [70], check: [70, 90, 70], avoid: [70, 90, 70, 90, 70] }[verdict];
    if (!pat || !state.vibrate || !navigator.vibrate) return;
    try { navigator.vibrate(pat); } catch (e) { /* not allowed here */ }
  }
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
    applyName(p);
    pushState({ tab: 'scan', view: 'result', code: p.code });
    state.filter = null;
    state.open = null;
    state.detailsOpen = false;
    const a = renderResult(p, note);
    addHistory(p, a.verdict);
    if (buzzNext) { buzzNext = false; buzz(a.verdict); }
    $('result').scrollIntoView({ behavior: smooth(), block: 'start' });
  }

  function renderResult(p, note) {
    applyName(p);
    const a = analyze(p);
    state.current = { p, a };
    if (!state.open) state.open = { red: true, orange: false, info: false, nodata: false, green: false };
    hideAll();
    $('scanner').hidden = true;
    if (note) showStatus(note);

    const r = $('result');
    const known = a.verdict !== 'unknown';
    const grey = a.verdict === 'partial' || a.verdict === 'unknown';
    r.replaceChildren(...[
      answerCard(p, a),
      // v2.14: two doors – more info / photo again – and the next product
      el('div', { class: 'doors' },
        known ? el('button', {
          class: 'btn btn-ghost', id: 'detBtn', type: 'button', 'aria-expanded': String(state.detailsOpen), 'aria-controls': 'details',
          onclick: () => toggleDetails(undefined, true)
        }, icon(ICON.info), el('span', { text: t('qa.details') })) : null,
        el('button', { class: 'btn ' + (grey ? 'btn-primary' : 'btn-ghost'), id: 'againBtn', type: 'button', onclick: () => openLabel(p) },
          icon(ICON.again), el('span', { text: t(p.source === 'label' ? 'btn.again' : 'btn.photoLabel') }))),
      el('button', { class: 'btn ' + (grey ? 'btn-ghost' : 'btn-primary') + ' nextwide', id: 'nextBtn', type: 'button', text: t('btn.nextProduct'), onclick: scanNext }),
      grey && a.verdict !== 'unknown' && p.read && p.read.photo ? el('button', { class: 'btn btn-ghost nextwide', id: 'secondBtn', type: 'button', onclick: () => secondPhoto(p) },
        icon(ICON.again), el('span', { text: t('btn.second') })) : null,
      p.source === 'label' && isBarcode(p.code)
        ? el('button', { class: 'btn btn-ghost nextwide', type: 'button', text: t('btn.lookupOnline'), onclick: () => lookup(p.code, true) })
        : null,
      p.kind === 'cosmetic' && known && needsUse(p, a) ? useBar(p) : null,
      el('div', { id: 'details', class: 'details', hidden: known ? !state.detailsOpen : null }, ...[
        known ? detailsTop(p, a) : null,
        known ? detailsHead(p, a) : null,
        productChips(p, a),
        el('div', { id: 'groups' }),
        p.ingredientsText
          ? el('details', { class: 'ingr' },
              el('summary', { text: t('ingredientsTitle') }),
              el('p', { class: 'ingredients', text: p.ingredientsText.replace(/^\s*[\p{L} ]{2,20}[:：]\s*/u, '') }))
          : null,
        dbWarn()
      ].filter(Boolean))
    ].filter(Boolean));
    renderGroups();
    r.hidden = false;
    return a;
  }

  function toggleDetails(open, scroll) {
    state.detailsOpen = open === undefined ? !state.detailsOpen : !!open;
    const d = $('details'), b = $('detBtn');
    if (d && b) d.hidden = !state.detailsOpen;
    if (b) b.setAttribute('aria-expanded', String(state.detailsOpen));
    if (scroll && d && state.detailsOpen) d.scrollIntoView({ behavior: smooth(), block: 'start' });
  }

  // The answer: one word, why, "instead" and the colour strip. Everything else is under "Details".
  const QA_ICON = {
    avoid: 'M7 7l10 10M17 7L7 17', check: 'M12 6.5v7M12 17.5h.01', ok: 'M6 12.5l4 4L18 8',
    unknown: 'M9.5 9.2a2.6 2.6 0 1 1 3.6 2.4c-.7.3-1.1.9-1.1 1.6v.4M12 17.5h.01'
  };
  QA_ICON.partial = QA_ICON.unknown;
  function answerCard(p, a) {
    const v = a.verdict, word = t('v.' + v);
    const card = el('section', { class: 'qa v-' + v, id: 'answer', 'aria-label': word },
      nameRow(p),
      el('div', { class: 'qw' },
        el('span', { class: 'qi' }, icon(QA_ICON[v])),
        el('b', { class: word.length > 12 ? 'long' : null, text: word })),
      frontLine(a)   // v2.14: one short line; the rest is under "Подробности"
    );
    const alt = v === 'avoid' || v === 'check' ? alternatives(p) : [];
    if (alt.length) {
      card.append(el('p', { class: 'qalt' }, el('b', { text: t('qa.instead') + ':' }),
        alt.map(q => el('button', { class: 'altbtn', type: 'button', text: q.name || t('ph.unnamed'), onclick: () => openSaved(q.code) }))));
    }
    // the strip: not when the photo text may not be the list (it would show colours of the wrong text)
    if (v !== 'unknown' && a.rows.length && !a.noList) {
      card.append(el('div', { class: 'strip' + (a.rows.length > 30 ? ' dense' : ''), role: 'group', 'aria-label': t('strip.aria') },
        a.rows.map(r => el('button', {
          type: 'button', class: 'g-' + r.group,
          title: (r.pos ? '#' + r.pos + ' ' : '') + r.label,
          'aria-label': (r.pos ? '#' + r.pos + ' ' : '') + r.label + ', ' + t('g.' + r.group),
          onclick: e => { toggleDetails(true); jumpTo(r.i, e.currentTarget); }
        }))));
      // v2.15: first name, how many were read, last name – so you do not need to count
      const named = a.rows.filter(r => r.pos);
      if (named.length >= 2) {
        card.append(el('div', { class: 'ends', id: 'endsLine' },
          el('span', { class: 'e1', text: '#1 ' + shortName(named[0]) }),
          el('b', { class: 'en', text: t('qa.read', { n: named.length }) }),
          el('span', { class: 'e2', text: shortName(named[named.length - 1]) + ' #' + named[named.length - 1].pos })));
      }
    }
    if (p.ingredientsText && v !== 'unknown') card.append(typeChip(p));
    return card;
  }

  // v2.15: "Food ▾ tap if wrong" on every card – change the type and the product is checked again.
  function typeChip(p) {
    const k = p.kind || 'food', wrap = el('div', { class: 'typerow', id: 'typeRow' });
    const chip = el('button', { class: 'typechip', type: 'button', id: 'typeChip', 'aria-expanded': 'false' },
      el('b', { text: t(kindKey(k)) + ' ▾' }), el('small', { text: t('qa.typeHint') }));
    chip.onclick = () => {
      chip.setAttribute('aria-expanded', 'true');
      wrap.replaceChildren(el('div', { class: 'segs typesegs', role: 'group', 'aria-label': t('label.kind') },
        ['food', 'cosmetic', 'household'].map(v => el('button', { type: 'button', class: 'seg', 'aria-pressed': String(v === k),
          text: t(kindKey(v)), onclick: () => v === k ? renderResult(p) : setKind(p, v) }))));
    };
    wrap.append(chip);
    return wrap;
  }
  function setKind(p, k) {
    p.kind = k;
    if (k !== 'cosmetic') delete p.use;
    if (state.products[p.code]) saveProduct(p);
    verdictCache.delete(p.code);
    const a = renderResult(p);
    state.history.forEach(h => { if (h.code === p.code) h.verdict = a.verdict; });
    store.set('history', state.history);
    renderHistory();
    renderFavs();
  }

  // v2.14: the one line on the card. Red / orange: only the names; grey: what to do; green: nothing.
  function frontLine(a) {
    const names = list => {
      const n = [...new Set(list)];
      return n.slice(0, 3).join(', ') + (n.length > 3 ? ' ' + t('qa.more', { n: n.length - 3 }) : '');
    };
    let text = null;
    if (a.verdict === 'avoid') {
      const red = a.rows.filter(r => r.group === 'red');
      text = names(red.map(r => shortName(r) + (r.why === 'allergen' && r.traceOnly ? ' (' + t('qa.traceMark') + ')' : '')));
    } else if (a.verdict === 'check') text = names(a.rows.filter(r => r.group === 'orange').map(shortName));
    else if (a.verdict === 'partial') text = t('qa.recheckLine');
    else if (a.verdict === 'unknown') text = a.summary;
    return text ? el('p', { class: 'qy one', id: 'oneLine', text }) : null;
  }

  // v2.14: the top of "Подробности": why, what was checked, how many names are known, what the colours mean.
  function detailsTop(p, a) {
    const legend = a.rows.length && a.verdict !== 'unknown'
      ? el('p', { class: 'legend', id: 'legend' }, GROUPS.filter(g => a.counts[g]).map(g =>
          el('span', {}, el('i', { class: 'g-' + g, 'aria-hidden': 'true' }), el('b', { text: String(a.counts[g]) }), ' ' + t('legend.' + g))))
      : null;
    return el('div', { class: 'dtop', id: 'dtop' }, ...answerLines(a, p), knownLine(p, a), legend);
  }

  // Red: what and why. Orange: what. Green: what was checked. Never "safe".
  function answerLines(a, p) {
    const names = list => {
      const n = [...new Set(list.map(shortName))];
      return n.slice(0, 3).join(', ') + (n.length > 3 ? ' ' + t('qa.more', { n: n.length - 3 }) : '');
    };
    if (a.verdict === 'avoid') {
      const red = a.rows.filter(r => r.group === 'red');
      const trc = red.filter(r => r.why === 'allergen' && r.traceOnly), inn = red.filter(r => !trc.includes(r));
      const whys = [...new Set(red.map(r => t(r.why === 'allergen' && r.traceOnly ? 'qa.why.traces' : 'qa.why.' + r.why)))];
      return [
        inn.length ? el('p', { class: 'qy', text: t('qa.contains', { names: names(inn) }) }) : null,
        trc.length ? el('p', { class: 'qy', text: t('qa.mayContain', { names: names(trc) }) }) : null,
        el('p', { class: 'qr', text: t('qa.reason', { why: whys.join(', ') }) })
      ].filter(Boolean);
    }
    if (a.verdict === 'check') {
      const or = a.rows.filter(r => r.group === 'orange');
      return [el('p', { class: 'qy', text: names(or) }), el('p', { class: 'qr', text: t(or.every(r => r.ask) ? 'qa.orReasonAsk' : or.every(r => r.banCos) ? 'qa.orReasonCos' : 'qa.orReason') })];
    }
    if (a.verdict === 'ok') return [checkedLine(p)];
    if (a.verdict === 'partial' && a.noList && !a.unknown) {
      return [el('p', { class: 'qy', text: t('qa.noListLine') }),
        p ? el('p', { class: 'qkl' }, el('button', { class: 'linkbtn inline', type: 'button', id: 'fixTextBtn2', text: t('qa.fixText'), onclick: () => fixText(p) })) : null];
    }
    if (a.verdict === 'partial' && a.weak && !a.unknown) return [el('p', { class: 'qy', text: t('qa.weak' + a.weak, { n: a.total }) })];
    if (a.verdict === 'partial') return [el('p', { class: 'qy', text: t(a.noList ? 'qa.noListLine' : 'qa.partialLine') })];
    return [el('p', { class: 'qy', text: a.summary })];
  }

  // v2.13: what was checked, in one line of chips (instead of "Nothing from your list, your allergens or the EU lists.")
  function checkedLine(p) {
    const cos = p && (p.kind === 'cosmetic' || p.kind === 'household');
    const chips = [t('chk.eu')];
    if (state.avoid.length) chips.push(t('start.list', { n: state.avoid.length }));
    const alg = cos ? state.allergens.cos.length : state.allergens.food.length;
    if (alg) chips.push(t('start.alg', { n: alg }));
    if (cos && state.avoidFragrance) chips.push(t('start.frag'));
    if (!cos && state.vegan) chips.push(t('start.vegan'));
    return el('p', { class: 'qchk', id: 'chkLine', 'aria-label': t('qa.okLine') },
      el('span', { text: t('chk.label') }), chips.map(c => el('b', { text: '✓ ' + c })));
  }

  // Cosmetics / household: "11 of 14 ingredients recognised", with "See 3 unknown" and "Fix the text".
  function knownLine(p, a) {
    const taughtN = a.rows.filter(r => r.taught).length, autoN = a.rows.filter(r => r.auto).length;
    if (!a.unknown && !taughtN && !autoN) return null;
    // Two causes: the photo reader got a name wrong (the app has a close name), or the name is not in the data.
    const unk = a.rows.filter(isUnknown), mis = unk.filter(misreadOf).length, nod = unk.length - mis;
    const parts = [mis ? tn('qa.misread', mis) : null, nod ? tn('qa.noData', nod) : null, taughtN ? tn('qa.taught', taughtN) : null, autoN ? tn('qa.auto', autoN) : null].filter(Boolean);
    return el('p', { class: 'qk1', id: 'knownLine' },
      el('strong', { class: 'qkn', text: t('qa.known', { n: a.known, of: a.known + a.unknown }) }),
      parts.length ? el('span', { class: 'qks', text: ' · ' + parts.join(' · ') }) : null,
      a.unknown ? [' · ', el('button', { class: 'linkbtn inline', type: 'button', id: 'unkBtn', text: t('qa.see'), 'aria-label': tn('qa.seeUnknown', a.unknown), onclick: showUnknown }),
        ' · ', el('button', { class: 'linkbtn inline', type: 'button', id: 'fixTextBtn', text: t('qa.fixText'), onclick: () => fixText(p) })] : null);
  }
  function misreadOf(r) {
    if (r.fixS === undefined) r.fixS = isUnknown(r) ? LCDB.suggestCosmetic(r.text) : null;
    return r.fixS;
  }
  function showUnknown() {
    const r = state.current && state.current.a.rows.find(isUnknown);
    if (!r) return;
    toggleDetails(true);
    jumpTo(r.i);
  }
  // Open the label form with the saved text, so a wrong name can be corrected (with fix suggestions).
  function fixText(p) {
    openLabel(p);
    $('textFold').open = true;
    $('labelText').value = p.ingredientsText || '';
    renderFixes();
    $('labelText').scrollIntoView({ behavior: smooth(), block: 'center' });
  }

  function nameRow(p) {
    const isFav = state.favs.includes(p.code), nm = p.name || t('ph.unnamed');
    return el('div', { class: 'qn' },
      p.name
        ? el('button', { class: 'nameedit', type: 'button', id: 'nameBtn', 'aria-label': t('name.edit') + ': ' + nm, onclick: () => editName(p) },
            el('span', { text: nm }), p.nameFrom === 'photo' ? el('small', { class: 'fromphoto', text: t('name.fromPhoto') }) : null, icon(ICON.pen))
        : el('button', { class: 'addname', type: 'button', id: 'nameBtn', 'aria-label': t('name.add'), onclick: () => editName(p) },
            el('span', { text: t('name.add') })),
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

  // Name a product after the check: tap the name, type, ✓ (or Enter).
  function editName(p) {
    const row = document.querySelector('#answer .qn');
    if (!row) return;
    const input = el('input', { id: 'nameInput', value: p.name || '', placeholder: t('label.namePh'), 'aria-label': t('label.name'), maxlength: '80', enterkeyhint: 'done', autocomplete: 'off' });
    const save = () => setName(p, input.value);
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); save(); }
      else if (e.key === 'Escape') renderResult(p);
    });
    row.replaceChildren(el('div', { class: 'nameform' }, input,
      el('button', { class: 'ok', type: 'button', id: 'nameSave', 'aria-label': t('name.save'), title: t('name.save'), onclick: save }, icon(ICON.ok))));
    input.focus();
    input.select();
  }

  function setName(p, value) {
    const name = String(value || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    if (name) state.names[p.code] = name; else delete state.names[p.code];
    store.set('names', state.names);
    p.name = name;
    delete p.nameFrom;                                     // you checked or wrote the name yourself
    if (state.products[p.code]) saveProduct(p);
    state.history.forEach(h => { if (h.code === p.code) h.name = name; });
    store.set('history', state.history);
    renderResult(p);
    renderHistory();
    renderFavs();
  }

  // "Instead": your saved products of the same type with "No warnings" (newest first, at most 2).
  function alternatives(p) {
    const out = [], seen = new Set([p.code]);
    for (const code of state.history.map(h => h.code).concat(state.favs)) {
      if (seen.has(code)) continue;
      seen.add(code);
      const q = productBy(code);
      if (!q || !q.name || (q.kind || 'food') !== (p.kind || 'food')) continue;   // v2.15: no unnamed products
      if (verdictOf(code).verdict !== 'ok') continue;
      out.push(q);
      if (out.length === 2) break;
    }
    return out;
  }

  // The "stays on skin / washed off" question only when an ingredient's EU limit depends on it (or you answered it).
  function needsUse(p, a) {
    return !!p.use || a.rows.some(r => r.kind === 'cosmetic' && r.src && (r.src.reasons || []).some(rinseOnly));
  }

  function detailsHead(p, a) {
    const meta = [p.brand, t(kindKey(p.kind)), a.total ? tn('ph.ingredients', a.total) : null,
      p.kind !== 'food' && a.rows.length ? t(a.fragrance ? 'chip.fragrance' : 'chip.noFragrance') : null].filter(Boolean).join(' · ');
    return el('div', { class: 'product-head det-head' },
      el('div', { class: 'thumb' }, icon(ICON.tag), p.image ? el('img', { src: p.image, alt: '', loading: 'lazy', onerror: e => e.target.remove() }) : null),
      el('p', { class: 'grow', text: meta }));
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

  function productChips(p, a) {
    const chips = [];
    if (p.nutriscore) chips.push(t('chip.nutri', { g: p.nutriscore.toUpperCase() }));
    if (p.nova && [1, 2, 3, 4].includes(+p.nova)) chips.push(t('chip.nova', { n: p.nova, label: t('nova.' + p.nova) }));
    for (const tag of p.analysis || []) if (TEXT.en['an.' + tag]) chips.push(t('an.' + tag));

    let allergenLine = null;
    if (p.kind === 'food' || !p.kind) {
      const names = Object.fromEntries(LCDB.foodAllergens(LANG).map(x => [x.id, x.name]));
      const ids = new Set(), inside = new Set();
      a.rows.forEach(r => (r.allergens || []).forEach(x => { ids.add(x.id); if (!x.trace) inside.add(x.id); }));
      (p.allergens || []).forEach(tag => { const m = String(tag).match(ALLERGEN_TAG); if (m) inside.add(m[1]); });
      (p.allergens || []).forEach(tag => { const m = String(tag).match(ALLERGEN_TAG); if (m) ids.add(m[1]); });
      if (ids.size) {
        const parts = [...ids].map(id => {
          const name = cap(names[id] || id) + (inside.has(id) ? '' : ' (' + t('tag.traceShort') + ')');
          return state.allergens.food.includes(id) ? el('strong', { class: 'lvl g-red', text: name }) : name;
        });
        allergenLine = el('p', { class: 'allergen-line' }, el('strong', { text: t('allergens') + ': ' }),
          parts.flatMap((x, i) => (i ? [', ', x] : [x])));
      }
    }
    const nut = (p.kind === 'food' || !p.kind) && p.nut ? nutLine(p.nut) : null;
    if (!chips.length && !allergenLine && !nut) return null;
    return el('div', {}, chips.length ? el('ul', { class: 'chips' }, chips.map(c => el('li', { text: c }))) : null, allergenLine, nut);
  }

  // "Per 100 g: fat 24 g (saturated 9 g) · protein 13 g"
  function nutLine(n) {
    const f = x => String(x).replace('.', LANG === 'en' ? '.' : ',');
    const parts = [];
    if (n.fat !== null && n.fat !== undefined) parts.push(t('nut.fat', { g: f(n.fat) }) + (n.sat !== null && n.sat !== undefined ? ' ' + t('nut.sat', { g: f(n.sat) }) : ''));
    if (n.prot !== null && n.prot !== undefined) parts.push(t('nut.prot', { g: f(n.prot) }));
    return parts.length ? el('p', { class: 'nutline' }, el('strong', { text: t('nut.per') + ' ' }), parts.join(' · ')) : null;
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
    const { a, p } = state.current;
    if (a.verdict === 'unknown') { box.replaceChildren(); return; }
    const cosmeticKind = p.kind === 'cosmetic' || p.kind === 'household';
    const parts = [];
    if (state.filter) {
      parts.push(el('p', { class: 'filterbar' },
        el('button', { class: 'linkbtn', type: 'button', text: t('filter.all'), onclick: () => setFilter(state.filter) })));
    }
    for (const g of GROUPS) {
      if (state.filter && state.filter !== g) continue;
      const list = a.rows.filter(r => r.group === g);
      const id = 'grp-' + g;
      if (!list.length) continue;   // empty groups are not shown
      const open = !!state.open[g];
      parts.push(el('section', { class: 'grp g-' + g },
        el('button', {
          class: 'grp-head', type: 'button', 'aria-expanded': String(open), 'aria-controls': id,
          onclick: () => { state.open[g] = !state.open[g]; renderGroups(); }
        },
          el('span', { class: 'dot g-' + g }), el('span', { class: 'ttl', text: t('tile.' + g) }), el('span', { class: 'desc', text: t('gd.' + g) }),
          el('span', { class: 'num', text: String(list.length) }), icon(ICON.chev, 'chev')),
        // One line that says what the colour means: grey = no data; green = known (cosmetics only: food has no "known" list)
        g === 'nodata' || (g === 'green' && cosmeticKind)
          ? el('p', { class: 'grpnote', hidden: !open, text: t('gn.' + g) }) : null,
        g === 'green' || g === 'nodata'
          ? el('ul', { class: 'chiplist', id, hidden: !open }, list.map(r => el('li', { 'data-i': r.i },
              el('button', { class: 'gchip' + (isUnknown(r) ? ' nf' : ''), type: 'button', onclick: e => openDetail(r.i, e.currentTarget) },
                el('small', { text: r.pos ? '#' + r.pos : '–' }), r.label))))
          : el('ul', { class: 'rows', id, hidden: !open }, list.map(rowItem))
      ));
    }
    box.replaceChildren(...parts);
  }

  // Short coloured tag on the right of a row.
  function chipOf(r) {
    const k = r.ask ? 'chip.ask' : r.why === 'b' ? 'chip.b' : r.why === 'use' ? 'chip.use' : r.why === 'mine' ? 'chip.mine' : r.why === 'allergen' ? (r.traceOnly ? 'chip.traces' : 'chip.yourAlg')
      : r.why === 'fragrance' ? 'chip.frag' : r.why === 'vegan' ? 'chip.vegan' : r.banCos ? 'chip.banCos'
      : r.group === 'orange' ? (r.level === 'u' ? 'chip.u' : 'chip.c')
      : r.group === 'info' ? (r.level === 'r' ? 'chip.r' : r.traceOnly ? 'chip.traces' : r.allergen || (r.allergens && r.allergens.length) ? 'chip.alg' : 'chip.maybeVegan') : null;
    return k ? t(k) : null;
  }
  // EU rules that are only for cosmetics (CosIng annexes, MI and formaldehyde-releaser rules).
  const isCosRule = rs => /^EU CosIng|2016\/1198|2022\/1181/.test(((rs || {}).source || {}).label || '');
  // One short line: why this row has its colour.
  function whyOf(r) {
    if (r.kind === 'cosmetic') {
      const s = r.src, tags = cosmeticTags(r), fn = (s.functions || [])[0];
      const cosRule = rs => (r.household && isCosRule(rs) ? t('hh.cosRule') + ' ' : '');
      if (r.ask) return t('ask.maybeWhy', { name: niceName(r.ask.to), level: levelName(r.ask.level) || '' });
      if (r.why === 'use') return t('use.why');
      if (r.banCos) return t('why.banCos');
      if (r.group === 'orange' && !r.why) return cosRule(s.reasons[0]) + ((s.reasons[0] || {}).text || '');
      if (r.group === 'info') {
        if (r.allergen) return t('tag.allergen');
        const an = (((s.reasons[0] || {}).source || {}).label || '').match(/Annex (IV|V|VI)\b/);
        return an ? cosRule(s.reasons[0]) + t('why.annex' + an[1]) : [fn, t('why.limit')].filter(Boolean).join(' · ');
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
      try { const a = analyze(p); const v = { verdict: a.verdict, summary: a.summary, groups: a.rows.map(r => r.group) }; verdictCache.set(code, v); return v; }
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
        opts && opts.summary && v.summary ? el('span', { class: 'sub one', text: v.summary }) : null,
        // v2.13: the colour strip in small, so products can be compared at a glance (History)
        opts && opts.time && v.groups && v.groups.length ? el('span', { class: 'mstrip' + (v.groups.length > 30 ? ' dense' : ''), 'aria-hidden': 'true' },
          v.groups.map(g => el('i', { class: 'g-' + g }))) : null
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
    // Backup note: everything personal lives only on this phone.
    const last = store.get('lastBackup', 0), later = store.get('backupLater', 0), now = Date.now();
    const due = (state.history.length || state.avoid.length || state.favs.length) && now - last > 30 * 864e5 && now - later > 7 * 864e5;
    $('bkNote').hidden = !due;
    if (due) $('bkTitle').textContent = last ? t('bk.old', { days: Math.floor((now - last) / 864e5) }) : t('bk.never');
    $('bkLast').textContent = last ? t('bk.last', { date: fmtDate(last) }) : '';
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
      : r.why === 'fragrance' ? t('tag.fragranceAvoid') : r.why === 'vegan' ? t('chip.vegan') : r.why === 'use' ? t('chip.use')
      : r.ask ? t('chip.ask') : r.group === 'nodata' ? t('tile.nodata') : levelName(r.level);
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
    if (r.household && !r.det && r.src && (r.src.reasons || []).some(isCosRule)) body.push(el('p', { class: 'minor', text: t('hh.note') }));

    if (r.kind === 'cosmetic') {
      const tags = cosmeticTags(r);
      if (tags.length) body.push(el('ul', { class: 'd-tags' }, tags.map(x => el('li', { text: x }))));
      if (r.taught) body.push(taughtCard(r));
      else if (r.auto) body.push(autoCard(r));
      else if (r.ask && !r.fromSearch) body.push(askCard(r));
      else if (isUnknown(r) && !r.fromSearch) body.push(teachCard(r));
      if (r.found && !r.taught && !r.auto && niceName(r.src.name) !== cleanSeg(r.text)) {
        body.push(el('p', { class: 'd-meta' }, t('d.asOnLabel') + ': ', el('em', { text: r.text })));
      }
      if (r.src.functions && r.src.functions.length) {
        body.push(el('div', { class: 'd-card' }, el('h3', { text: t('d.functions') }), el('p', { text: r.src.functions.join(', ') })));
      }
      const reasons = r.src.reasons || [];
      const unk = isUnknown(r);
      body.push(el('div', { class: 'd-card' },
        el('h3', { text: t(unk ? 'd.knows' : 'd.why') }),
        unk ? el('p', { class: 'd-nothing', id: 'nothingLine' }, el('b', { text: t('d.nothing') }), ' ' + t('d.nodata')) : null,
        unk && misreadOf(r) ? el('p', { class: 'd-maybe', text: t('d.maybeShort', { name: niceName(misreadOf(r).inci) }) }) : null,
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
          al.trace ? el('p', { text: t('d.traces') }) : null,
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
      const listName = r.kind === 'cosmetic' && r.found && r.src.name ? [niceName(r.src.name), cleanSeg(r.text)] : [cleanSeg(r.text).replace(/\s*\(.*\)\s*/g, ' ').trim()];
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

  // ---------- Teach the app (v2.12): "GLYCERN is Glycerin", saved on this phone for all products ----------
  function teachCard(r) {
    const no = (taughtFor(r.text) || {}).no;
    let s = misreadOf(r);
    if (s && (!s.inci || s.inci === no)) s = null;
    const choices = (r.choices || []).filter(n => n !== no);
    return el('div', { class: 'd-card teach', id: 'teachCard' },
      el('h3', { text: t('teach.title') }),
      s ? el('button', { class: 'btn btn-primary', type: 'button', id: 'teachYes', text: t('teach.yes', { name: niceName(s.inci) }), onclick: () => { teach(r.text, s.inci); closeDetail(); } })
        : choices.length ? [el('p', { text: t('teach.choose') }), ...choices.map((n, k) => el('button', { class: 'btn btn-ghost', type: 'button', id: 'teachChoice' + k, text: niceName(n), onclick: () => { teach(r.text, n); closeDetail(); } }))]
        : el('p', { text: t('teach.none') }),
      el('button', { class: 'btn ' + (s ? 'btn-ghost' : 'btn-primary'), type: 'button', id: 'teachOther', text: t(s ? 'teach.other' : 'teach.pick'), onclick: () => openPicker(r) }),
      el('p', { class: 'minor', text: t('teach.note') }));
  }
  // (b) the closest name has a warning: you decide, the app does not
  function askCard(r) {
    const a = r.ask, name = niceName(a.to);
    return el('div', { class: 'd-card teach', id: 'askCard' },
      el('h3', { text: t('ask.title') }),
      el('p', { text: t('ask.text', { from: a.from, name, level: levelName(a.level) || '' }) }),
      el('button', { class: 'btn btn-primary', type: 'button', id: 'askYes', text: t('teach.yes', { name }), onclick: () => { teach(r.text, a.to); closeDetail(); } }),
      el('button', { class: 'btn btn-ghost', type: 'button', id: 'askNo', text: t('ask.no'), onclick: () => openPicker(r) }),
      el('p', { class: 'minor', text: t('teach.note') }),
      (a.src.reasons || []).length ? el('div', { class: 'askif' }, el('h3', { text: t('ask.ifTitle', { name }) }), (a.src.reasons || []).map(reasonBlock)) : null);
  }
  // (a) corrected by the app: you can say it is wrong
  function autoCard(r) {
    return el('div', { class: 'd-card teach', id: 'autoCard' },
      el('p', {}, ...tNodes('d.auto', { from: el('em', { text: r.auto.from }), to: el('b', { text: niceName(r.auto.to) }) })),
      el('button', { class: 'btn btn-ghost', type: 'button', id: 'notThis', text: t('d.notThis'), onclick: () => { noAuto(r.text, r.auto.to); closeDetail(); } }));
  }
  function noAuto(text, to) {
    const k = teachKey(text);
    if (!k) return;
    const from = teachName(text);
    state.taught[k] = { from, to: '', no: to };
    store.set('taught', state.taught);
    renderTaught();
    settingsChanged();
    toast(t('toast.noAuto', { from }));
  }
  function taughtCard(r) {
    return el('div', { class: 'd-card teach', id: 'taughtCard' },
      el('p', {}, ...tNodes('d.taught', { from: el('em', { text: r.taught.from }), to: el('b', { text: niceName(r.src.name) }) })),
      el('button', { class: 'btn btn-ghost', type: 'button', id: 'undoTeach', text: t('d.undo'), onclick: () => { untaught(r.text); closeDetail(); } }));
  }
  function teach(text, inci) {
    const k = teachKey(text);
    if (!k || !inci) return;
    const from = teachName(text);
    state.taught[k] = { from, to: inci };
    store.set('taught', state.taught);
    renderTaught();
    settingsChanged();   // result, History and Favourites are checked again with the new name
    toast(t('toast.taught', { from, to: niceName(inci) }));
  }
  function untaught(text) {
    const k = teachKey(text), item = state.taught[k];
    if (!item) return;
    delete state.taught[k];
    store.set('taught', state.taught);
    renderTaught();
    settingsChanged();
    toast(t('toast.untaught', { from: item.from }));
  }
  // My list: "Taught names" fold
  function renderTaught() {
    const box = $('taughtList');
    if (!box) return;
    const items = Object.entries(state.taught).sort((x, y) => x[1].from.localeCompare(y[1].from));
    $('taughtCount').textContent = '(' + items.length + ')';
    box.replaceChildren(...(items.length ? items.map(([k, v]) => el('div', { class: 'taughtrow' },
      el('div', { class: 'tr-main' }, el('s', { text: v.from }), el('b', { text: v.to ? niceName(v.to) : t('taught.noAuto') })),
      el('button', { class: 'x', type: 'button', 'aria-label': t('taught.del', { from: v.from }), title: t('taught.del', { from: v.from }), text: '✕', onclick: () => untaught(v.from) })))
      : [el('p', { class: 'empty', text: t('taught.empty') })]));
  }
  // "Another ingredient…": the Find screen chooses the ingredient for this label name
  let pickFor = null, pickTyped = false;   // pickTyped: the Find box still holds the label name
  function openPicker(r) {
    pickFor = { text: r.text, from: teachName(r.text) };
    pickTyped = true;
    hideDetail();
    try { history.replaceState({ tab: 'scan', view: 'search', pick: 1, code: state.current && state.current.p.code }, ''); } catch (e) { /* ignore */ }
    showPanel('searchPanel');
    $('searchInput').value = pickFor.from;
    renderSearch();
    $('searchInput').focus();
  }
  // Only cosmetic names. A food additive name in another language leads to its cosmetic name
  // ("Bienenwachs" = E901, whose English name "beeswax" is the cosmetic name BEESWAX).
  function pickHits(hits) {
    const out = [], seen = new Set();
    const add = h => { if (!seen.has(h.name)) { seen.add(h.name); out.push(h); } };
    for (const h of hits) {
      if (h.kind === 'cosmetic') add(h);
      else for (const name of LCDB.foodToCosmetic(h.id)) add({ kind: 'cosmetic', id: name, name, level: 'n' });
    }
    return out;
  }
  function pickChoose(name) {
    const pf = pickFor;
    if (!pf) return;
    pickFor = null;
    teach(pf.text, name);
    if (history.state && history.state.pick) { try { history.back(); } catch (e) { /* ignore */ } }
  }

  // ---------- Read a label (free share flow) ----------
  let labelFor = null; // product or {code} the label belongs to
  let kindTouched = false, kindTimer = null;

  // Food, cosmetic or household? Guessed from the names in the text; you can always change it.
  function guessKind(text) {
    const segs = LCDB.splitIngredients(text).filter(s => /\p{L}{2}/u.test(s));
    if (segs.length < 3) return null;
    const det = segs.filter(s => detergentTerm(s)).length;
    if (det >= 2 || (det >= 1 && DET_RANGE.test(text))) return { kind: 'household', n: det, of: segs.length };
    const rows = LCDB.checkCosmetic(text, LANG);
    let cos = rows.filter(r => r.found || r.fragrance || taughtFor(r.text)).length;
    // A badly read cosmetic list: names that are one or two letters off count too
    if (cos / segs.length < 0.6 && cos / segs.length >= 0.25) cos += rows.filter(r => !r.found && !r.fragrance && LCDB.suggestCosmetic(r.text)).length;
    return cos / segs.length >= 0.6 ? { kind: 'cosmetic', n: cos, of: segs.length } : { kind: 'food', n: cos, of: segs.length };
  }
  function updateKindGuess() {
    const note = $('kindNote');
    if (kindTouched) { note.hidden = true; return; }
    const g = guessKind($('labelText').value);
    if (!g) { note.hidden = true; return; }
    document.querySelectorAll('input[name="kind"]').forEach(i => { i.checked = i.value === g.kind; });
    note.textContent = t('kind.guess.' + g.kind, { n: g.n, of: g.of });
    note.hidden = false;
  }

  // ---------- Fix suggestions: names the photo reader got a little wrong (cosmetics / household) ----------
  let fixTimer = null;
  const labelKind = () => (document.querySelector('input[name="kind"]:checked') || {}).value || 'food';
  function fixList(text) {
    const kind = labelKind();
    if (kind === 'food' || !text.trim()) return [];
    const out = [], seen = new Set();
    for (const r of LCDB.checkCosmetic(text, LANG)) {
      if (r.found || (kind === 'household' && detergentTerm(r.text)) || taughtFor(r.text)) continue;
      const s = LCDB.suggestCosmetic(r.text);
      if (!s || seen.has(s.from)) continue;
      seen.add(s.from);
      // Same style of letters as on the label: "Glycern" -> "Glycerin", "GLYCERN" -> "GLYCERIN"
      const lower = (s.from.match(/\p{Ll}/gu) || []).length, upper = (s.from.match(/\p{Lu}/gu) || []).length;
      s.to = lower > upper ? s.to.toLowerCase().replace(/(^|[\s\-\/(])(\p{L})/gu, (m, a, b) => a + b.toUpperCase()) : s.to;
      out.push(s);
      if (out.length === 12) break;
    }
    return out;
  }
  function renderFixes() {
    const box = $('fixBox');
    if (!box) return;
    const list = DBINFO ? fixList($('labelText').value) : [];
    box.hidden = !list.length;
    if (!list.length) { box.replaceChildren(); return; }
    box.replaceChildren(
      el('p', { class: 'fixhead', text: tn('fix.head', list.length) }),
      el('ul', {}, list.map(f => el('li', {},
        el('span', { class: 'fixpair' }, el('s', { text: f.from }), el('b', { text: f.to })),
        el('button', { class: 'fixok', type: 'button', 'aria-label': t('fix.one', { from: f.from, to: f.to }), title: t('fix.one', { from: f.from, to: f.to }), onclick: () => applyFixes([f]) },
          icon(ICON.ok))))),
      list.length > 1 ? el('button', { class: 'btn btn-ghost fixall', type: 'button', id: 'fixAll', text: t('fix.all', { n: list.length }), onclick: () => applyFixes(list) }) : null
    );
  }
  // Replace the name only where it stands alone (not inside a longer word).
  function replaceWhole(text, from, to) {
    let i = -1;
    while ((i = text.indexOf(from, i + 1)) >= 0) {
      const b = text[i - 1] || ' ', a = text[i + from.length] || ' ';
      if (!/[\p{L}\p{N}]/u.test(b) && !/[\p{L}\p{N}]/u.test(a)) return text.slice(0, i) + to + text.slice(i + from.length);
    }
    return text;
  }
  function applyFixes(list) {
    const ta = $('labelText');
    let v = ta.value;
    for (const f of list) v = replaceWhole(v, f.from, f.to);
    ta.value = v;
    toast(tn('fix.done', list.length));
    renderFixes();
    updateKindGuess();
  }

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
    lastRead = null; prevPart = null; joinNext = false; collect = null; camOpen = false; stopPhotoCam(); clearParts();
    $('photoCam').hidden = true;
    setPhotoMode(false);
    renderFixes();
    ocrFile = null;
    $('ocrArea').hidden = true;
    $('claudeBox').open = false;
    $('textFold').open = false;
    ocrStatus('');
    const kind = (p && p.kind) || 'food';
    document.querySelectorAll('input[name="kind"]').forEach(i => { i.checked = i.value === kind; });
    kindTouched = !!(p && p.kind && p.ingredientsText);   // "Read again" on a known product: keep its type
    $('kindNote').hidden = true;
    $('labelLead').textContent = labelFor && isBarcode(labelFor.code)
      ? t('label.leadFor', { code: labelFor.code }) : t('label.lead');
    panel.scrollIntoView({ behavior: 'auto', block: 'start' });
  }

  // ---------- Find one ingredient (offline) ----------
  let searchTimer = null;

  function openSearch() {
    if (pickFor || pickTyped) { pickFor = null; pickTyped = false; $('searchInput').value = ''; }
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
    const panel = $('searchPanel');
    panel.querySelector('h2').textContent = pickFor ? t('teachPick.title', { name: pickFor.from }) : t('search.title');
    panel.querySelector('.lead').textContent = t(pickFor ? 'teachPick.lead' : 'search.lead');
    if (!DBINFO) { info.textContent = t(DBINFO === null ? 'status.dbLoading' : 'status.dbFail'); list.replaceChildren(); return; }
    if (q.length < 2) { info.textContent = t('search.hint'); list.replaceChildren(); return; }
    const hits = LCDB.search(q, 30);
    const rows = (pickFor ? pickHits(hits) : hits).map(h => { const r = searchRow(h); if (r) r.hitName = h.name; return r; }).filter(Boolean);
    const own = pickFor ? [] : ownSearch(q);
    info.textContent = rows.length || own.length ? '' : t('search.none');
    list.replaceChildren(...own.map(ownRow), ...rows.map(r => {
      const chip = chipOf(r);
      const kind = t(r.kind === 'cosmetic' ? 'search.kindCosShort' : 'search.kindFoodShort');
      const detail = r.kind === 'food' && r.additives && r.additives[0] ? (r.additives[0].classes || []).join(', ') : whyOf(r);
      const why = [kind, detail].filter(Boolean).join(' · ');
      return el('li', {},
        el('button', { class: 'row-btn', type: 'button', onclick: e => (pickFor ? pickChoose(r.hitName) : openDetailRow(r, e.currentTarget)) },
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
          el('span', { class: 'why', text: [t('src.ownShort'), t(kindKey(p.kind)), t('v.' + v)].join(' · ') })),
        icon(ICON.chev, 'chev')));
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) { return false; }
  }

  // ---------- Read a label: offline reader (Tesseract, in ocr/) ----------
  // The reader files load only when you tap "Read text", so barcode scans stay fast.
  const OCR_LANGS = { en: 'eng', de: 'deu', bg: 'bul' };
  const OCR_NAMES = { eng: 'EN', deu: 'DE', bul: 'BG', hun: 'HU', ces: 'CZ', slk: 'SK', slv: 'SL' };
  const OCR_ALL = Object.keys(OCR_NAMES);
  // Heading word on the label -> reader language (used by "Auto").
  const OCR_HEADS = [['eng', /^ingredients?$/], ['deu', /^(zutaten|inhaltsstoffe|bestandteile)$/], ['bul', /^(съставки|състав)$/],
    ['hun', /^osszetevok$/], ['ces', /^slozeni$/], ['slk', /^zlozenie$/], ['slv', /^sestavine$/]];
  const OCR_LOW = 60;   // reader confidence below this: read again with the other alphabet
  const OCR_BAD = 50;   // below this: orange line instead of "Done" (wrong alphabet gave 31–48, good reads 75–95)
  let ocrFile = null, ocrWorker = null, ocrSeq = 0, ocrBusy = false, claudeNext = false;
  // v2.16: a round bottle needs two photos. prevPart = { text, list } of the first photo; the second read is joined to it.
  let prevPart = null, joinNext = false;
  function joinParts(a, b) {
    const norm = w => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
    const A = String(a || '').trim().split(/\s+/).filter(Boolean), B = String(b || '').trim().split(/\s+/).filter(Boolean);
    if (!A.length || !B.length) return [...A, ...B].join(' ');
    const na = A.map(norm), nb = B.map(norm);
    for (let k = Math.min(14, A.length, B.length); k >= 2; k--) {      // the same words twice: the photos overlap
      let same = true;
      for (let i = 0; i < k; i++) if (na[A.length - k + i] !== nb[i] || !nb[i]) { same = false; break; }
      if (same) return [...A.slice(0, A.length - k), ...B].join(' ');   // keep the later read of the shared words (it has the commas)
    }
    const last = A[A.length - 1];
    if (/-$/.test(last) && /^\p{Ll}/u.test(B[0])) { A[A.length - 1] = last.slice(0, -1) + B[0]; return [...A, ...B.slice(1)].join(' '); }   // split word
    if (!/[,;.:]$/.test(last)) A[A.length - 1] = last + ',';
    return [...A, ...B].join(' ');
  }
  function secondPhoto(p) {                    // from the result card or the Check bar: take more photos of the same list
    if (p) {
      openLabel(p);
      $('labelText').value = p.ingredientsText || '';
      prevPart = { text: p.ingredientsText || '', list: !!(p.read && p.read.list), conf: p.read && p.read.conf };
    } else {
      prevPart = { text: $('labelText').value.trim(), list: !!(lastRead && lastRead.list), conf: lastRead && lastRead.conf };
    }
    openCam(true);
  }

  let lastRead = null;   // v2.13: { photo: true, list: heading found } for the text now in the box (null after typing)
  const ocrWait = {};
  const crop = { x: 0.06, y: 0.3, w: 0.88, h: 0.4 };   // part of the photo, 0..1

  // "auto" (default) or one reader language you picked in the menu.
  function ocrChoice() {
    const v = store.get('ocrPick', 'auto');
    return v === 'auto' || OCR_ALL.includes(v) ? v : 'auto';
  }
  function renderOcrLang() { $('ocrLang').value = ocrChoice(); }
  function headingLang(text) {
    for (const m of String(text || '').matchAll(/(\p{L}+)\s*[:：;]/gu)) {
      const w = LCDB.norm(m[1]), hit = OCR_HEADS.find(([, re]) => re.test(w));
      if (hit) return hit[0];
    }
    return null;
  }
  function drawCrop() {
    const b = $('cropBox').style;
    b.left = crop.x * 100 + '%'; b.top = crop.y * 100 + '%';
    b.width = crop.w * 100 + '%'; b.height = crop.h * 100 + '%';
  }
  let partTag = '';     // v2.17: " · photo 2 of 3" while several photos are read
  function ocrStatus(text, cls) {
    const n = $('ocrStatus');
    if (text && cls === 'busy') text += partTag;
    n.hidden = !text; n.textContent = text || ''; n.className = 'ocrstatus' + (cls ? ' ' + cls : '');
  }

  // v2.13: with a photo, "Check" reads and checks in one step; the text part is shown only when something went wrong
  // (or from "Fix the text" on the result).
  // v2.15: with a photo, the top part (take photo, tip, lead, text fold) folds away and a sticky Check bar stays in view.
  // openText = something went wrong: show the text fold open, under the photo.
  function setPhotoMode(on, openText) {
    $('photoStart').hidden = !!on;
    $('againRow').hidden = !on;
    $('labelLead').hidden = !!on;
    $('labelPanel').classList.toggle('photomode', !!on);
    $('checkBar').hidden = !on;
    $('oneNote').hidden = !on;
    $('textFold').hidden = !!on && !openText;
    $('textFold').open = !!openText;
  }

  function onPhoto(e) {
    const files = [...(e.target.files || [])];
    e.target.value = '';
    if (files.length > 1) { openCam(false, files); return; }   // v2.17: several photos chosen: they go to "Your photos"
    if (files[0]) loadPhoto(files[0]);
  }

  // ---------- v2.17: in-app camera: photos (or a slow "sweep") are kept in "Your photos", then read together ----------
  let collect = null, partsList = [], camStream = null, camMode = 'photo', sweep = null, camOpen = false, camFromPhoto = false;
  const camUiOn = () => !$('photoCam').hidden;
  const MAX_PARTS = 8;

  function setCamUi(on, keepBar) {
    $('photoCam').hidden = !on;
    $('labelPanel').classList.toggle('camon', on);
    $('photoStart').hidden = on || !$('againRow').hidden;
    if (on) { $('againRow').hidden = true; $('ocrArea').hidden = true; $('textFold').hidden = true; $('labelLead').hidden = true; }
    $('checkBar').hidden = !(on ? partsList.length > 0 : keepBar);
  }
  function renderParts() {
    const th = $('thumbs'), prev = prevPart && prevPart.text ? LCDB.splitIngredients(prevPart.text).length : 0;
    th.replaceChildren(...partsList.map((p, i) => el('div', { class: 'tn' },
      el('img', { src: p.url, alt: t('parts.photo', { n: i + 1 }) }),
      el('s', { text: String(i + 1) }),
      el('button', { type: 'button', class: 'tx', 'aria-label': t('parts.remove', { n: i + 1 }), text: '✕', onclick: () => { URL.revokeObjectURL(p.url); partsList.splice(i, 1); renderParts(); } }))));
    $('partsHead').textContent = partsList.length ? tn('parts.head', partsList.length) : t('parts.none');
    $('partsSum').textContent = [prev ? t('parts.kept', { n: prev }) : '', partsList.length ? t('parts.next') : t('parts.flat')].filter(Boolean).join(' · ');
    $('checkBar').hidden = !(camUiOn() && partsList.length);
    $('camHint').textContent = sweep ? t('cam.hint.sweep', { n: partsList.length }) : t(camMode === 'sweep' ? 'cam.hint.sweepStart' : 'cam.hint.photo');
  }
  function addPart(file) {
    if (partsList.length >= MAX_PARTS) { toast(t('parts.max', { n: MAX_PARTS })); return false; }
    partsList.push({ file, url: URL.createObjectURL(file) });
    renderParts();
    if (navigator.vibrate) { try { navigator.vibrate(40); } catch (e) { /* ignore */ } }
    return true;
  }
  function clearParts() { partsList.forEach(p => URL.revokeObjectURL(p.url)); partsList = []; }

  async function openCam(keep, files) {
    if (!keep) { clearParts(); }
    camOpen = true;
    $('labelPanel').scrollIntoView({ behavior: 'auto', block: 'start' });
    camFromPhoto = !$('againRow').hidden;                           // came from the photo screen: "Close camera" goes back there
    setCamUi(true);
    if (!(history.state && history.state.view === 'cam')) pushState({ tab: 'scan', view: 'cam' });
    setCamMode('photo');
    if (files && files.length) {                                  // photos chosen from the phone: no live view
      $('camVideo').hidden = true; $('camWide').hidden = true; $('camZoom').hidden = true; $('camTorch').hidden = true;
      $('photoCam').classList.add('nolive');
      files.slice(0, MAX_PARTS).forEach(f => addPart(f));
      return;
    }
    $('photoCam').classList.remove('nolive');
    $('camVideo').hidden = false;
    renderParts();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { closeCam(); $('photoInput').click(); return; }
    try {
      camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 4096 }, height: { ideal: 2160 } }, audio: false });
    } catch (e) {
      closeCam(true);
      toast(e && e.name === 'NotAllowedError' ? t('toast.camBlocked') : t('toast.camFail'));
      return;
    }
    if (!camOpen) { stopPhotoCam(); return; }
    const v = $('camVideo');
    v.srcObject = camStream;
    try { await v.play(); } catch (e) { /* muted video may play */ }
    try {                                                           // sharp pictures: keep focusing; wide lens when the phone allows it
      const tr = camStream.getVideoTracks()[0], caps = tr.getCapabilities ? tr.getCapabilities() : {};
      if (caps.focusMode && caps.focusMode.includes('continuous')) await tr.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
      $('camWide').hidden = !(caps.zoom && caps.zoom.min < 1);
      $('camWide').dataset.min = caps.zoom ? caps.zoom.min : 1;
      const z = $('camZoom');
      z.hidden = !(caps.zoom && caps.zoom.max > caps.zoom.min);
      if (!z.hidden) { z.min = caps.zoom.min; z.max = Math.min(caps.zoom.max, caps.zoom.min * 6); z.step = caps.zoom.step || 0.1; z.value = tr.getSettings().zoom || 1; }
      $('camTorch').hidden = !caps.torch;
      $('camTorch').setAttribute('aria-pressed', 'false');
    } catch (e) { $('camWide').hidden = true; $('camZoom').hidden = true; $('camTorch').hidden = true; }
  }
  function setCamMode(m) {
    camMode = m;
    $('modePhoto').setAttribute('aria-pressed', String(m === 'photo'));
    $('modeSweep').setAttribute('aria-pressed', String(m === 'sweep'));
    $('shutter').classList.toggle('sweep', m === 'sweep');
    renderParts();
  }
  function stopPhotoCam() {
    if (sweep) { clearInterval(sweep.timer); if (sweep.best && sweep.best.bmp.close) sweep.best.bmp.close(); sweep = null; $('shutter').classList.remove('stop'); }
    if (camStream) camStream.getTracks().forEach(x => x.stop());
    camStream = null;
    const v = $('camVideo'); v.srcObject = null;
  }
  function closeCam(noBack) {                                        // leave the camera screen (parts stay if you come back from Check)
    camOpen = false;
    stopPhotoCam();
    if (!camUiOn()) return;
    clearParts();
    setCamUi(false);
    if (camFromPhoto) { setPhotoMode(true); $('ocrArea').hidden = false; }
    else { $('photoStart').hidden = false; $('textFold').hidden = false; $('labelLead').hidden = false; $('againRow').hidden = true; $('checkBar').hidden = true; }
    if (!noBack && history.state && history.state.view === 'cam') { try { history.back(); } catch (e) { /* ignore */ } }
  }

  async function still() {
    const v = $('camVideo'), tr = camStream && camStream.getVideoTracks()[0];
    if (window.ImageCapture && tr) {
      try { const blob = await new ImageCapture(tr).takePhoto(); if (blob && blob.size > 1000) return blob; } catch (e) { /* use the video frame */ }
    }
    const cv = document.createElement('canvas'); cv.width = v.videoWidth; cv.height = v.videoHeight;
    cv.getContext('2d').drawImage(v, 0, 0);
    return new Promise(res => cv.toBlob(res, 'image/jpeg', 0.92));
  }
  async function onShutter() {
    if (!camStream) return;
    if (camMode === 'photo') {
      const blob = await still();
      if (blob) addPart(new File([blob], 'part' + (partsList.length + 1) + '.jpg', { type: 'image/jpeg' }));
      return;
    }
    if (sweep) { endSweep(); return; }
    startSweep();
  }

  // Sweep: every 0.4 s a small copy of the video is scored for sharpness (variance of the Laplacian); in each 1.6 s window the
  // sharpest frame is kept. They become "Your photos" (at most 8).
  function sharpness(v) {
    const W = 240, H = Math.max(2, Math.round(240 * v.videoHeight / v.videoWidth));
    const cv = sharpness.cv || (sharpness.cv = document.createElement('canvas')); cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: true }); cx.drawImage(v, 0, 0, W, H);
    const d = cx.getImageData(0, 0, W, H).data, g = new Float32Array(W * H);
    for (let i = 0, j = 0; i < g.length; i++, j += 4) g[i] = d[j] * 0.299 + d[j + 1] * 0.587 + d[j + 2] * 0.114;
    let sum = 0, sum2 = 0, n = 0;
    for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
      const k = y * W + x, l = 4 * g[k] - g[k - 1] - g[k + 1] - g[k - W] - g[k + W];
      sum += l; sum2 += l * l; n++;
    }
    return sum2 / n - (sum / n) * (sum / n);
  }
  function startSweep() {
    if (partsList.length >= MAX_PARTS) { toast(t('parts.max', { n: MAX_PARTS })); return; }
    const v = $('camVideo');
    sweep = { best: null, tick: 0 };
    $('shutter').classList.add('stop');
    renderParts();
    sweep.timer = setInterval(async () => {
      if (!sweep || v.readyState < 2) return;
      sweep.tick++;
      try {
        const sc = sharpness(v);
        if (!sweep.best || sc > sweep.best.sc) {
          const bmp = await createImageBitmap(v);
          if (sweep.best && sweep.best.bmp.close) sweep.best.bmp.close();
          sweep.best = { bmp, sc };
        }
      } catch (e) { /* skip this frame */ }
      if (sweep && sweep.tick % 4 === 0) await flushSweep();
    }, 400);
  }
  async function flushSweep() {
    const sw = sweep, b = sw && sw.best;
    if (!b) return;
    sw.best = null;
    const cv = document.createElement('canvas'); cv.width = b.bmp.width; cv.height = b.bmp.height;
    cv.getContext('2d').drawImage(b.bmp, 0, 0); if (b.bmp.close) b.bmp.close();
    const blob = await new Promise(res => cv.toBlob(res, 'image/jpeg', 0.92));
    if (blob) addPart(new File([blob], 'sweep' + (partsList.length + 1) + '.jpg', { type: 'image/jpeg' }));
    if (partsList.length >= MAX_PARTS) endSweep(true);
  }
  async function endSweep(already) {
    if (!sweep) return;
    if (!already) await flushSweep();
    if (sweep) clearInterval(sweep.timer);
    sweep = null;
    $('shutter').classList.remove('stop');
    renderParts();
  }
  // Tap to focus: the camera is asked to focus on that point (not every phone allows it in the browser).
  let focusToast = false;
  async function tapFocus(e) {
    if (!camStream || e.target.closest('button')) return;
    const r = $('camView').getBoundingClientRect(), v = $('camVideo');
    const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
    const tr = camStream.getVideoTracks()[0], caps = tr.getCapabilities ? tr.getCapabilities() : {};
    // the picture is cropped to fill the view (object-fit: cover): convert the tap to a point of the real picture
    const vr = v.videoWidth / v.videoHeight, br = r.width / r.height;
    let x = px, y = py;
    if (vr > br) x = 0.5 + (px - 0.5) * (br / vr); else y = 0.5 + (py - 0.5) * (vr / br);
    const ok = !!(caps.focusMode && (caps.focusMode.includes('single-shot') || caps.focusMode.includes('manual')) || caps.pointsOfInterest);
    if (ok) {
      try {
        await tr.applyConstraints({ advanced: [{ focusMode: caps.focusMode && caps.focusMode.includes('single-shot') ? 'single-shot' : 'manual', pointsOfInterest: [{ x, y }] }] });
        const ring = $('focusRing'); ring.hidden = true; void ring.offsetWidth;
        ring.style.left = (px * 100) + '%'; ring.style.top = (py * 100) + '%'; ring.hidden = false;
        setTimeout(() => { ring.hidden = true; }, 900);
        setTimeout(async () => { try { if (camStream && caps.focusMode.includes('continuous')) await tr.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (err) { /* ignore */ } }, 2500);
        return;
      } catch (err) { /* fall through */ }
    }
    if (!focusToast) { focusToast = true; toast(t('cam.noFocus')); }
  }
  function initCam() {
    $('takePhoto').addEventListener('click', () => openCam());
    $('shutter').addEventListener('click', onShutter);
    $('modePhoto').addEventListener('click', () => { if (!sweep) setCamMode('photo'); });
    $('modeSweep').addEventListener('click', () => { if (!sweep) setCamMode('sweep'); });
    $('camClose').addEventListener('click', () => (history.state && history.state.view === 'cam' ? history.back() : closeCam(true)));
    $('camView').addEventListener('click', tapFocus);
    $('camZoom').addEventListener('input', async () => {
      const tr = camStream && camStream.getVideoTracks()[0];
      try { await tr.applyConstraints({ advanced: [{ zoom: +$('camZoom').value }] }); $('camWide').setAttribute('aria-pressed', String(+$('camZoom').value <= +$('camWide').dataset.min)); } catch (e) { /* not possible */ }
    });
    $('camTorch').addEventListener('click', async () => {
      const tr = camStream && camStream.getVideoTracks()[0], b = $('camTorch'), on = b.getAttribute('aria-pressed') !== 'true';
      try { await tr.applyConstraints({ advanced: [{ torch: on }] }); b.setAttribute('aria-pressed', String(on)); } catch (e) { toast(t('toast.torchFail')); }
    });
    $('camWide').addEventListener('click', async () => {
      const tr = camStream && camStream.getVideoTracks()[0], b = $('camWide'), on = b.getAttribute('aria-pressed') !== 'true';
      try { await tr.applyConstraints({ advanced: [{ zoom: on ? +b.dataset.min : 1 }] }); b.setAttribute('aria-pressed', String(on)); if (!$('camZoom').hidden) $('camZoom').value = on ? b.dataset.min : 1; } catch (e) { /* not possible */ }
    });
  }

  // Read every photo (the box finds the list on each), join the texts, check once.
  // The same list read from several pictures comes back with small spelling differences: near-identical names count once.
  function dedupeNames(text) {
    const grams = k => { const g = new Map(); for (let i = 0; i < k.length - 1; i++) g.set(k.slice(i, i + 2), (g.get(k.slice(i, i + 2)) || 0) + 1); return g; };
    const dice = (a, b) => {
      let inter = 0; for (const [k, n] of a.g) inter += Math.min(n, b.g.get(k) || 0);
      return (2 * inter) / Math.max(1, a.len + b.len - 2);
    };
    const kept = [];
    return String(text).split(/(?<=[,;])\s*/).filter(seg => {
      const k = seg.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
      if (k.length < 5) return true;
      const me = { g: grams(k), len: k.length };
      if (kept.some(o => dice(o, me) >= 0.7)) return false;
      kept.push(me); return true;
    }).join(' ');
  }
  async function readParts() {
    if (!partsList.length || ocrBusy) return;
    const files = partsList.map(p => p.file), base = prevPart;
    prevPart = null;
    camOpen = false; stopPhotoCam();
    setCamUi(false, true);
    $('photoStart').hidden = true;
    collect = [];
    try {
      for (let i = 0; i < files.length; i++) {
        partTag = files.length > 1 ? ' · ' + t('parts.of', { i: i + 1, n: files.length }) : '';
        loadPhoto(files[i]);
        if (findTask) await findTask;
        await onOcrRead();
      }
    } finally { partTag = ''; }
    const got = collect; collect = null;
    // frames that are too blurry (a sweep) add only junk: keep reads with confidence 50+ and some text
    const keep = got.filter(x => x.conf >= 50 && x.text.replace(/[^\p{L}]/gu, '').length >= 15);
    const use = keep.length ? keep : got;
    let text = base && base.text ? base.text : '';
    for (const x of use) text = text ? joinParts(text, x.text) : x.text;
    if (use.length + (base && base.text ? 1 : 0) > 1) text = dedupeNames(text);
    const confs = use.map(x => x.conf).concat(base && typeof base.conf === 'number' ? [base.conf] : []);
    lastRead = { photo: true, list: use.some(x => x.list) || !!(base && base.list), conf: confs.length ? Math.round(Math.min(...confs)) : undefined, photos: files.length + (base && base.text ? 1 : 0) };
    clearParts();
    setPhotoMode(true);
    $('labelText').value = text;
    updateKindGuess();
    renderFixes();
    if (text.replace(/[^\p{L}]/gu, '').length < 12) { ocrStatus(t('ocr.little'), 'warn'); setPhotoMode(true, true); return; }
    ocrStatus('');
    buzzNext = true;
    onCheckLabel();
  }
  function loadPhoto(file) {
    ocrFile = file;
    lastRead = null;
    if (collect) { /* several photos: readParts joins them */ } else if (joinNext && prevPart && prevPart.text) joinNext = false; else { joinNext = false; prevPart = null; }
    setPhotoMode(true);
    if (claudeNext) { claudeNext = false; shareToClaude(file); }
    const img = $('cropImg');
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    img.dataset.url = URL.createObjectURL(file);
    img.src = img.dataset.url;
    Object.assign(crop, { x: 0.06, y: 0.3, w: 0.88, h: 0.4 });
    cropTouched = false;
    nameHint = '';
    drawCrop();
    renderOcrLang();
    ocrStatus('');
    $('ocrArea').hidden = false;
    $('ocrArea').scrollIntoView({ behavior: 'smooth', block: 'start' });
    findTask = findList(file).catch(() => null);
  }

  // ---------- v2.10: find the ingredient list (and the product name) on the photo ----------
  // A fast read of the whole photo (1200 px wide) gives the text blocks with their positions. The block with the
  // heading word ("Ingredients", "Zutaten", "INGREDIENTS/SASTOJCI/СЪСТАВКИ" …) gets the box. You can still move it.
  const LIST_HEAD = /^(ingredients?|ingr[eé]dients?|zutaten|inhaltsstoffe|bestandteile|sastojci|съставки|състав|inci|skład|składniki|összetevők|osszetevok|složení|slozeni|zloženie|zlozenie|sestavine|ingrediente|ingredienti|ingredientes|ingrediënten|sastav)$/i;
  const isListHead = w => String(w || '').split(/[\/:|,.;]+/).some(p => LIST_HEAD.test(p.trim()));
  const NOT_NAME = /zutaten|ingredient|inhaltsstoff|nährwert|nahrwert|nutrition|energie|energy|brennwert|хранителна|съставки|mindestens|haltbar|verpackung|recycl|hergestellt|made in|www\.|@/i;
  let cropTouched = false, nameHint = '', findTask = null, lastFind = null;

  // TSV from the reader -> pieces (paragraphs) with their lines, words and box (pixels of the image that was read).
  function tsvPieces(tsv) {
    const pieces = new Map();
    for (const row of String(tsv || '').split('\n')) {
      const c = row.split('\t');
      if (c[0] !== '5' || !c[11] || !c[11].trim()) continue;
      const key = c[2] + '.' + c[3], line = c[4];
      const w = { x: +c[6], y: +c[7], w: +c[8], h: +c[9], conf: +c[10], t: c[11] };
      if (!pieces.has(key)) pieces.set(key, { lines: new Map(), words: [] });
      const p = pieces.get(key);
      p.words.push(w);
      if (!p.lines.has(line)) p.lines.set(line, []);
      p.lines.get(line).push(w);
    }
    return [...pieces.values()].map(p => ({
      words: p.words,
      lines: [...p.lines.values()],
      text: [...p.lines.values()].map(ws => ws.map(w => w.t).join(' ')).join('\n'),
      // v2.16: the word counts as a heading only at the start of a line, with a colon, or in capitals – not inside a
      // sentence ("No active ingredients Chlorhexidine …")
      head: [...p.lines.values()].some(ws => ws.some((w, i) => isListHead(w.t) &&
        (i <= 1 || /[:：]/.test(w.t) || (ws[i + 1] && /^[:：]/.test(ws[i + 1].t)) || (w.t === w.t.toUpperCase() && /\p{L}{4}/u.test(w.t))))),
      box: [Math.min(...p.words.map(w => w.x)), Math.min(...p.words.map(w => w.y)), Math.max(...p.words.map(w => w.x + w.w)), Math.max(...p.words.map(w => w.y + w.h))]
    }));
  }

  // From the piece with the heading to the first piece that ends with a full stop. A "may contain" piece right after
  // stays (traces). Pieces before the heading and other languages after the list are left out.
  function listPieces(pieces) {
    const start = pieces.findIndex(p => p.head);
    if (start < 0) return null;
    const out = [];
    for (let i = start, done = false; i < pieces.length; i++) {
      const tx = pieces[i].text.trim();
      if (!/\p{L}{3}/u.test(tx)) continue;                 // lines, icons, noise
      if (done) { if (LCDB.labelSegments(tx).traceFrom === 1) out.push(pieces[i]); break; }
      out.push(pieces[i]);
      if (/[.!]["'”)]*\s*$/.test(tx) && tx.replace(/[^\p{L}]/gu, '').length > 25) done = true;   // v2.16: a heading alone ("Bestandteile.") does not end the list
    }
    return out;
  }
  function listFromPieces(pieces) {
    const ps = listPieces(pieces);
    return ps ? ps.map(p => p.text.trim()).join('\n') : null;
  }

  // The biggest clear text outside the list is usually the product name ("CRUNCHY WAFERS", "Balea med Ultra Sensitive").
  function nameFromPieces(pieces, listPs) {
    // only text clearly bigger than the normal text on the photo (captions and small print are never the name)
    const hs = pieces.flatMap(p => p.words).filter(w => w.conf >= 50).map(w => w.h).sort((a, b) => a - b);
    const minH = hs.length ? Math.max(hs[Math.floor(hs.length / 2)] * 1.35, hs[Math.floor(hs.length * 0.9)] * 1.25) : 0;
    let best = null;
    for (const p of pieces) {
      if (listPs.includes(p)) continue;
      for (const ws of p.lines) {
        const good = ws.filter(w => w.conf >= 70 && /\p{L}{2}/u.test(w.t));
        if (good.length < ws.length * 0.6) continue;       // too many unsure words: skip the line
        const text = good.map(w => w.t).join(' ').split(/[,.;:!]/)[0].replace(/[^\p{L}\p{N}&'’ -]/gu, '').replace(/\s+/g, ' ').trim();
        const h = Math.max(...good.map(w => w.h));
        const ys = good.map(w => w.y + w.h);                // word bottoms: one line of text has one baseline
        if (Math.max(...ys) - Math.min(...ys) > h * 0.45) continue;
        if (h < minH || text.replace(/[^\p{L}]/gu, '').length < 3 || text.length > 40 || NOT_NAME.test(text) || isListHead(text)) continue;
        if (!best || h > best.h) best = { text, h };
      }
    }
    if (!best) return '';
    const t2 = best.text;
    return t2 === t2.toUpperCase() ? t2.toLowerCase().replace(/(^|[\s-])(\p{L})/gu, (m, a, b) => a + b.toUpperCase()) : t2;
  }

  // The whole photo as PNG, at most `width` px wide; gray = grey with stretched contrast (small or light-on-dark print).
  async function photoPng(bmp, width, gray) {
    const k = Math.min(1, width / bmp.width), W = Math.round(bmp.width * k), H = Math.round(bmp.height * k);
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const cx = cv.getContext('2d', { willReadFrequently: !!gray });
    cx.imageSmoothingQuality = 'high';
    cx.drawImage(bmp, 0, 0, W, H);
    if (gray) {
      const im = cx.getImageData(0, 0, W, H), d = im.data, n = W * H, g = new Uint8ClampedArray(n), hist = new Uint32Array(256);
      for (let i = 0, j = 0; i < n; i++, j += 4) { g[i] = (d[j] * 299 + d[j + 1] * 587 + d[j + 2] * 114) / 1000; hist[g[i]]++; }
      let lo = 0, hi = 255, acc = 0;
      const cut = n * 0.01;
      while (lo < 255 && (acc += hist[lo]) <= cut) lo++;
      acc = 0;
      while (hi > 0 && (acc += hist[hi]) <= cut) hi--;
      const span = Math.max(1, hi - lo);
      for (let i = 0, j = 0; i < n; i++, j += 4) d[j] = d[j + 1] = d[j + 2] = Math.min(255, Math.max(0, ((g[i] - lo) * 255) / span));
      cx.putImageData(im, 0, 0);
    }
    const png = new Uint8Array(await (await new Promise(res => cv.toBlob(res, 'image/png'))).arrayBuffer());
    return { png, W, H };
  }

  async function findList(file) {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    let { png, W, H } = await photoPng(bmp, 1200, false);
    if (file !== ocrFile) { if (bmp.close) bmp.close(); return null; }
    ocrStatus(t('ocr.finding'), 'busy');
    // Auto: a Latin reader first (most labels; it also reads the end of a Latin list right), the Bulgarian reader only
    // when no heading was found. A language you picked in the menu is used alone.
    const latin = store.get('ocrLastLatin', LANG === 'en' ? 'eng' : 'deu');
    const langs = ocrChoice() === 'auto' ? [OCR_ALL.includes(latin) && latin !== 'bul' ? latin : 'deu', 'bul'] : [ocrChoice()];
    let pieces = [], list = null;
    for (const lang of langs) {
      try { pieces = tsvPieces((await ocrRun(png.slice(), lang, { layout: true })).tsv); } catch (e) { pieces = []; }
      if (file !== ocrFile) return null;
      list = listPieces(pieces);
      if (list) break;
    }
    // v2.16: no heading at 1200 px (small print): read the photo once more, bigger
    if (!list) {
      try {
        const big = await photoPng(bmp, 2000, false);
        if (file !== ocrFile) { if (bmp.close) bmp.close(); return null; }
        const p2 = tsvPieces((await ocrRun(big.png.slice(), langs[0], { layout: true })).tsv), l2 = listPieces(p2);
        if (l2) { pieces = p2; list = l2; W = big.W; H = big.H; }
      } catch (e) { /* keep: not found */ }
      if (file !== ocrFile) { if (bmp.close) bmp.close(); return null; }
    }
    if (bmp.close) bmp.close();
    nameHint = nameFromPieces(pieces, list || []);
    lastFind = { W, H, list: (list || []).map(p => ({ box: p.box, text: p.text.slice(0, 60) + ' … ' + p.text.slice(-25) })) };   // for tests
    if (!list) { ocrStatus(t('ocr.notFound'), ''); return null; }
    if (!cropTouched) {
      // all pieces of the list (a short line can end a piece early): one box around them
      const pad = 0.025, x0 = Math.min(...list.map(p => p.box[0])), y0 = Math.min(...list.map(p => p.box[1])),
        x1 = Math.max(...list.map(p => p.box[2])), y1 = Math.max(...list.map(p => p.box[3]));
      const x = Math.max(0, x0 / W - pad), y = Math.max(0, y0 / H - pad);
      Object.assign(crop, { x, y, w: Math.min(1, x1 / W + pad) - x, h: Math.min(1, y1 / H + pad) - y });
      drawCrop();
    }
    ocrStatus(t('ocr.found'), '');
    return list;
  }

  // Drag the box (move) or its corners (resize). Works with finger and mouse.
  function initCrop() {
    const box = $('cropBox'), wrap = $('cropInner');
    let drag = null;
    box.addEventListener('pointerdown', e => {
      cropTouched = true;                                  // the app does not move the box after you moved it
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
    // Grey + stretched contrast for every label. (v2.13: dark labels were kept in colour before; on a real photo of
    // white text on red the reader then found 0 words, in grey it reads the list.)
    {
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

  function ocrRun(image, lang, opts) {
    opts = opts || {};
    if (!ocrWorker) {
      ocrWorker = new Worker('ocr/ocr-worker-2.js');
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
      ocrWait[id] = { resolve, reject, step: s => ocrStatus(t(s === 'load' ? 'ocr.loading' : opts.layout ? 'ocr.finding' : 'ocr.reading'), 'busy') };
      ocrWorker.postMessage({ id, image, lang, psm: opts.psm, layout: !!opts.layout }, [image.buffer]);
    });
  }

  // Ingredient headings in the languages seen on EU labels, by language. Two headings with the same language
  // ("Zutaten Teig / Zutaten Füllung") stay together; a heading in another language starts a new block.
  const HEADS = { en: 'ingredients', fr: 'ingrédients', it: 'ingredienti', es: 'ingredientes', nl: 'ingrediënten', ro: 'ingrediente',
    sv: 'ingredienser', de: 'zutaten|inhaltsstoffe|bestandteile', bg: 'съставки|състав', hr: 'sastojci', sl: 'sestavine', cs: 'složení',
    sk: 'zloženie', hu: 'összetevők', pl: 'składniki', fi: 'ainesosat', ru: 'состав' };
  // A heading can be several words joined by "/" ("INGREDIENTS/SASTOJCI/СЪСТАВКИ:"); group 1 is the first word.
  const HEAD_RE = new RegExp('(?<!\\p{L})(' + Object.values(HEADS).join('|') + ')(?:\\s*\\/\\s*[\\p{L}]+)*\\s*[:：]', 'giu');
  // Words that end an ingredient name: a "-" right after them at a line end is a separator, not a split word.
  const INCI_END = /(oil|acid|alcohol|extract|water|aqua|glycerin|oxide|sulfate|chloride|citrate|benzoate|parfum|butter|wax|gum|ester|glycol|stearate|silica|starch|juice|powder|protein|salt|sugar|e\d{3,4})$/i;
  const SEP = '[·•\\-–:»«°*|]';
  const headLang = w => Object.keys(HEADS).find(k => new RegExp('^(' + HEADS[k] + ')$', 'iu').test(w));

  // Reader text -> one line; start at the first heading ("Zutaten:") and stop at a heading in another language.
  // A dot the reader lost leaves two names in one piece ("GLYCERIN PANTHENOL"). A piece that is not a known
  // ingredient is cut after its longest known start, again for the rest ("GLYCERIN, PANTHENOL, CEIL ALCOHOL").
  function splitKnown(s) {
    const known = x => { const r = LCDB.checkCosmetic(x, 'en'); return r.length === 1 && r[0].found; };
    return s.split(',').map(seg => {
      let rest = seg.trim(); const out = [];
      while (rest && !known(rest)) {
        const w = rest.split(' ');
        let cut = 0;
        for (let i = w.length - 1; i >= 1 && !cut; i--) if (known(w.slice(0, i).join(' '))) cut = i;
        if (!cut) break;
        out.push(w.slice(0, cut).join(' '));
        rest = w.slice(cut).join(' ');
      }
      if (rest) out.push(rest);
      return out.join(', ');
    }).join(', ');
  }

  function cleanOcr(text) {
    let s = String(text || '').replace(/[­]/g, '').replace(/(\p{L})-\s*\n\s*(\p{Ll})/gu, '$1$2');
    // Lists with dots between the names ("AQUA · GLYCERIN"): the reader turns the dots into - : » ° and so on.
    // When there are almost no commas but many such marks between words, they become commas (also at line ends).
    const sepMode = (s.match(/,/g) || []).length < 3 && (s.match(new RegExp('\\s' + SEP + '\\s', 'g')) || []).length >= 3;
    if (sepMode) {
      s = s.replace(/(\p{L}+)[-*~]\s*\n\s*(\p{Lu})/gu, (m, a, b) => (INCI_END.test(a) ? a + ', ' + b : a + b));   // ISO-\nPROPYL -> ISOPROPYL
      s = s.replace(new RegExp('\\s' + SEP + '\\s*\\n\\s*', 'g'), ', ').replace(new RegExp('\\n\\s*' + SEP + '\\s*', 'g'), ', ');
      s = s.replace(new RegExp('\\s' + SEP + '(?=\\s)', 'g'), ',');
      s = splitKnown(s.replace(/\s*\n\s*/g, ' '));
    }
    s = s.replace(/\s*\n\s*/g, ' ').replace(/[|_]{1,}/g, ' ').replace(/\s{2,}/g, ' ').replace(/\s+,/g, ',').trim();
    let heads = [...s.matchAll(HEAD_RE)];
    if (!heads.length) return s;
    if (heads[0].index > 0) { s = s.slice(heads[0].index); heads = [...s.matchAll(HEAD_RE)]; }
    const first = headLang(heads[0][1]), start = heads[0][0].length;
    // A joined heading ("INGREDIENTS/SASTOJCI/СЪСТАВКИ:") is taken away, so the list starts with the first name.
    const joined = heads[0][0].includes('/');
    for (const h of heads.slice(1)) {
      const between = s.slice(start, h.index).replace(/[^\p{L}]/gu, '');
      if (between.length >= 15 && headLang(h[1]) !== first) { s = s.slice(0, h.index).trim(); break; }
    }
    return joined ? s.slice(start).trim() : s;
  }

  async function onOcrRead() {
    if (!ocrFile) { toast(t('toast.photoFirst')); return; }
    if (ocrBusy) return;
    ocrBusy = true;
    $('ocrRead').disabled = true;
    const t0 = performance.now();
    ocrStatus(t('ocr.reading'), 'busy');
    try {
      if (findTask) await findTask;                        // the box may still move onto the list
      ocrStatus(t('ocr.reading'), 'busy');
      const image = await ocrImage(), pick = ocrChoice(), auto = pick === 'auto';
      const lastLatin = store.get('ocrLastLatin', LANG === 'en' ? 'eng' : 'deu');
      let lang = auto ? store.get('ocrLast', OCR_LANGS[LANG] || 'eng') : pick;
      if (!OCR_ALL.includes(lang)) lang = 'eng';
      let r = await ocrRun(image.slice(), lang), used = lang, switched = false;
      // Low confidence: probably the wrong alphabet (a Latin label read as BG, or the reverse).
      // Read once more with the other alphabet and keep the better text.
      if (r.conf < OCR_LOW) {
        const other = lang === 'bul' ? (OCR_ALL.includes(lastLatin) ? lastLatin : 'deu') : 'bul';
        try {
          const r2 = await ocrRun(image.slice(), other);
          if (r2.conf > r.conf) { r = r2; used = other; switched = true; }
        } catch (e) { /* other language not on the phone yet and no internet: keep the first text */ }
      }
      // Auto, Latin letters: the heading word ("Zutaten:", "Összetevők:") tells the language. Read once more with it.
      if (auto && used !== 'bul') {
        const h = headingLang(r.text);
        if (h && h !== used && h !== 'bul') {
          try {
            const r3 = await ocrRun(image.slice(), h);
            if (r3.conf >= r.conf - 5) { r = r3; used = h; }
          } catch (e) { /* that reader is not on the phone yet and no internet */ }
        }
      }
      if (auto) { store.set('ocrLast', used); if (used !== 'bul') store.set('ocrLastLatin', used); }
      const fromList = listFromPieces(tsvPieces(r.tsv));
      let text = cleanOcr(fromList || r.text);
      // The list was found when the read text has its heading (in the read box, or as "Zutaten:" in the text)
      lastRead = { photo: true, list: !!fromList || new RegExp(HEAD_RE.source, 'iu').test(r.text), conf: Math.round(r.conf) };
      if (collect) {                                                    // v2.17: one of several photos: keep the text, check later
        collect.push({ text, conf: r.conf, list: lastRead.list });
        return;
      }
      if (prevPart) {                                                   // v2.16: second photo: join with the first
        text = joinParts(prevPart.text, text);
        lastRead.list = lastRead.list || prevPart.list;
        lastRead.photos = 2;
        if (typeof prevPart.conf === 'number') lastRead.conf = Math.min(lastRead.conf, prevPart.conf);
        prevPart = null;
      }
      const secs = ((performance.now() - t0) / 1000).toFixed(1).replace('.', LANG === 'en' ? '.' : ',');
      let good = false;
      if (text.replace(/[^\p{L}]/gu, '').length < 12 || r.conf < OCR_BAD) {
        ocrStatus(t('ocr.little'), 'warn');
        if (text) $('labelText').value = text;
      } else {
        $('labelText').value = text;
        ocrStatus(t('ocr.done', { s: secs }) + (auto ? ' ' + t('ocr.readAs', { lang: OCR_NAMES[used] })
          : switched ? ' ' + t('ocr.switched', { lang: OCR_NAMES[used] }) : ''));
        good = true;
      }
      updateKindGuess();
      renderFixes();
      if (good) { buzzNext = true; onCheckLabel(); return; }   // one step: straight to the answer
      setPhotoMode(true, true);                                // little text: show it, you can fix or paste it
      $('labelText').scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (err) {
      ocrStatus(t('ocr.fail'), 'warn');
      setPhotoMode(true, true);
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
      if (txt) { $('labelText').value = txt.trim(); updateKindGuess(); renderFixes(); }
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
      name: (base && base.name) || (ocrFile && nameHint) || '',
      nameFrom: !(base && base.name) && ocrFile && nameHint ? 'photo' : undefined,
      brand: (base && base.brand) || '',
      image: (base && base.image) || '',
      ingredientsText: main,
      read: ocrFile && lastRead ? lastRead : undefined,   // v2.13: how the text was read (photo, list heading found)
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
    buzzNext = true;   // a new answer: you can feel it (vibration)
    showProduct(p);
  }

  // ---------- Camera ----------
  let stream = null, detector = null, scanTimer = null;

  async function startCamera() {
    if (!('BarcodeDetector' in window)) {
      toast(t('toast.noBarcodeApi'));
      showCodeForm(true);
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
    // Torch button only when the phone camera has a light that the browser can switch.
    try {
      const track = stream.getVideoTracks()[0], caps = track && track.getCapabilities ? track.getCapabilities() : {};
      $('torchBtn').hidden = !caps.torch;
    } catch (e) { $('torchBtn').hidden = true; }
    scanLoop();
  }

  async function toggleTorch() {
    const track = stream && stream.getVideoTracks()[0], b = $('torchBtn');
    if (!track) return;
    const on = b.getAttribute('aria-pressed') !== 'true';
    try {
      await track.applyConstraints({ advanced: [{ torch: on }] });
      b.setAttribute('aria-pressed', String(on));
      b.classList.toggle('on', on);
    } catch (e) { toast(t('toast.torchFail')); }
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
          buzzNext = true;
          lookup(hit.rawValue);
          return;
        }
      }
    } catch (e) { /* try again on the next frame */ }
    scanTimer = setTimeout(scanLoop, 200);
  }

  function stopCamera() {
    if (camOpen || camStream) closeCam(true);
    clearTimeout(scanTimer);
    if (stream) stream.getTracks().forEach(tr2 => tr2.stop());
    stream = null;
    const v = $('video');
    v.srcObject = null;
    v.hidden = true;
    $('stopCam').hidden = true;
    $('torchBtn').hidden = true;
    $('torchBtn').setAttribute('aria-pressed', 'false');
    $('torchBtn').classList.remove('on');
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
    // First chip = "I avoid fragrance" (same as the old switch: perfume + the fragrance allergens turn red)
    const frag = el('button', { type: 'button', class: 'frag-chip', 'aria-pressed': String(!!state.avoidFragrance), 'aria-label': t('frag.label'),
      text: (state.avoidFragrance ? '✓ ' : '+ ') + t('frag.chip'), onclick: () => setFragrance(!state.avoidFragrance) });
    $('picks').replaceChildren(frag, ...QUICK_PICKS
      .filter(p => !have.has(p.split(',')[0].trim().toLowerCase()))
      .map(p => el('button', { type: 'button', text: '+ ' + p.split(',')[0], onclick: () => addAvoid(p) })));
  }

  function setFragrance(on) {
    state.avoidFragrance = on;
    store.set('avoidFragrance', on);
    renderAvoid();
    settingsChanged();
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
    renderTaught();
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
      avoid: state.avoid, favs: state.favs, names: state.names, taught: state.taught, allergens: state.allergens, avoidFragrance: state.avoidFragrance, vegan: state.vegan,
      lang: state.lang, theme: state.theme, bigText: state.bigText, vibrate: state.vibrate,
      history: state.history, products: state.products
    };
    const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: 'label-check-backup-' + new Date().toISOString().slice(0, 10) + '.json' });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    store.set('lastBackup', Date.now());
    renderStart();
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
    if (data.names && typeof data.names === 'object') {
      for (const [c, n] of Object.entries(data.names)) if (typeof n === 'string' && n.trim()) state.names[c] = n.trim().slice(0, 80);
    }
    if (data.taught && typeof data.taught === 'object') {
      for (const [k, v] of Object.entries(data.taught)) {
        if (v && typeof v.from === 'string' && typeof v.to === 'string' && v.from.trim()) {
          state.taught[k] = { from: v.from.slice(0, 120), to: v.to.slice(0, 200) };
          if (!v.to.trim() && typeof v.no === 'string') state.taught[k].no = v.no.slice(0, 200);
        }
      }
    }
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
    if (typeof data.vibrate === 'boolean') state.vibrate = data.vibrate;
    for (const k of ['avoid', 'history', 'products', 'favs', 'names', 'taught', 'allergens', 'avoidFragrance', 'vegan', 'lang', 'theme', 'bigText', 'vibrate']) store.set(k, state[k]);
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
    $('veganSwitch').checked = !!state.vegan;
    $('bigSwitch').checked = !!state.bigText;
    $('vibSwitch').checked = !!state.vibrate;
    $('langSelect').value = state.lang;
    $('themeSelect').value = state.theme;
  }

  // ---------- Tabs and toast ----------
  // Each tab change is added to the browser history, so the phone's Back button returns to the previous tab.
  const TABS = ['scan', 'list', 'history'];
  let currentTab = 'scan';

  // Favourites are a filter inside History (v2.8). Old links to "favs" open History with the filter on.
  function setHistFilter(f) {
    document.querySelectorAll('#histFilter button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.f === f)));
    $('histAll').hidden = f === 'favs';
    $('histFavs').hidden = f !== 'favs';
  }

  // The barcode number box opens from a link (it is not needed often).
  function showCodeForm(focus, fromHistory) {
    $('manualForm').hidden = false;
    $('codeLink').setAttribute('aria-expanded', 'true');
    $('codeLink').parentElement.hidden = true;
    if (focus && !fromHistory && !(history.state && history.state.view === 'code')) pushState({ tab: 'scan', view: 'code' });   // v2.15: Back closes the box
    if (focus) $('codeInput').focus();
  }
  function hideCodeForm() {
    $('manualForm').hidden = true;
    $('codeLink').setAttribute('aria-expanded', 'false');
    $('codeLink').parentElement.hidden = false;
    $('codeInput').blur();
  }
  function closeCodeForm() {                        // the ✕ button: go back one step so the history stays tidy
    if (history.state && history.state.view === 'code') { try { history.back(); return; } catch (e) { /* fall through */ } }
    hideCodeForm();
  }

  function setTab(tab) {
    if (tab === 'favs') { tab = 'history'; setHistFilter('favs'); }
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
    if (st.view !== 'code' && !$('manualForm').hidden) hideCodeForm();
    if (!st.detail) hideDetail();
    if (st.tab !== currentTab) setTab(st.tab);
    if (st.tab !== 'scan') return;
    if (st.view === 'result') {
      const p = state.current && state.current.p.code === st.code ? state.current.p : productBy(st.code);
      if (!p || !DBINFO) showScanner();
      else if ($('result').hidden || !state.current || state.current.p !== p) renderResult(p);
    } else if (st.view === 'search') {
      if (!st.pick) pickFor = null;
      showPanel('searchPanel');
      renderSearch();
    } else if (st.view === 'label' || st.view === 'cam') {
      showPanel('labelPanel');
      if (st.view === 'label' && camUiOn()) closeCam(true);
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
    // The Find screen lives on the Scan tab: switch there first (from My list / History it stayed hidden)
    $('topSearch').addEventListener('click', () => { stopCamera(); if (currentTab !== 'scan') go('scan'); openSearch(); });
    $('codeLink').addEventListener('click', () => showCodeForm(true));
    $('codeClose').addEventListener('click', closeCodeForm);
    $('againPhoto').addEventListener('click', () => { prevPart = null; openCam(); });
    $('secondPhoto').addEventListener('click', () => secondPhoto(null));
    initCam();
    $('torchBtn').addEventListener('click', toggleTorch);
    document.querySelectorAll('#histFilter button').forEach(b => b.addEventListener('click', () => setHistFilter(b.dataset.f)));
    $('offGet').addEventListener('click', getOfflineReaders);
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
    $('ocrRead').addEventListener('click', () => (partsList.length && camUiOn() ? readParts() : onOcrRead()));
    $('ocrLang').addEventListener('change', e => store.set('ocrPick', e.target.value));
    document.querySelectorAll('input[name="kind"]').forEach(i => i.addEventListener('change', () => { kindTouched = true; $('kindNote').hidden = true; renderFixes(); }));
    $('labelText').addEventListener('input', () => {
      lastRead = null; prevPart = null;   // you typed or pasted: it is your text now
      clearTimeout(kindTimer); kindTimer = setTimeout(updateKindGuess, 400);
      clearTimeout(fixTimer); fixTimer = setTimeout(renderFixes, 700);
    });
    $('bkSave').addEventListener('click', exportBackup);
    $('bkLater').addEventListener('click', () => { store.set('backupLater', Date.now()); renderStart(); });
    $('updReload').addEventListener('click', () => location.reload());
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
    $('vibSwitch').addEventListener('change', e => { state.vibrate = e.target.checked; store.set('vibrate', state.vibrate); if (state.vibrate) buzz('ok'); });
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
    Promise.all([dbReady, ownReady]).then(() => { renderRules(); renderAllergens(); renderTaught(); renderFavs(); renderHistory(); });

    if ('serviceWorker' in navigator) {
      // A new version took over (after a push): offer a reload. Not on the very first install.
      const hadController = !!navigator.serviceWorker.controller;
      navigator.serviceWorker.addEventListener('controllerchange', () => { if (hadController) $('updBar').hidden = false; });
      navigator.serviceWorker.register('sw.js').catch(() => { /* app still works online */ });
    }
    // Ask the browser to keep the saved data (it may otherwise clear it when the phone is short of space).
    try { if (navigator.storage && navigator.storage.persist) navigator.storage.persisted().then(ok => ok || navigator.storage.persist()).catch(() => {}); } catch (e) { /* old browser */ }
    openFromUrl();
  }

  // ---------- Label reader without internet (all 7 languages on the phone) ----------
  const OCR_MB = { eng: 2.0, deu: 0.9, bul: 0.8, hun: 2.4, ces: 1.7, slk: 1.9, slv: 1.2 };
  const hasSimd = () => { try { return WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11])); } catch (e) { return false; } };
  const ocrCore = () => { const c = hasSimd() ? 'tesseract-core-simd-lstm' : 'tesseract-core-lstm'; return ['ocr/ocr-worker-2.js', 'ocr/' + c + '.js', 'ocr/' + c + '.wasm']; };
  async function offlineMissing() {
    if (!('caches' in window)) return null;
    const files = ocrCore().concat(OCR_ALL.map(l => 'ocr/lang/' + l + '.traineddata.gz')), missing = [];
    for (const f of files) if (!(await caches.match(f))) missing.push(f);
    return missing;
  }
  let offBusy = false;
  async function renderOffline() {
    if (offBusy) return;
    let missing = null;
    try { missing = await offlineMissing(); } catch (e) { /* caches blocked */ }
    const st = $('offState'), btn = $('offGet');
    if (!missing) { st.textContent = t('off.noCache'); btn.hidden = true; return; }
    const have = OCR_ALL.filter(l => !missing.includes('ocr/lang/' + l + '.traineddata.gz'));
    st.textContent = have.length === OCR_ALL.length && missing.length === 0 ? t('off.all')
      : t('off.have', { list: have.length ? have.map(l => OCR_NAMES[l]).join(', ') : t('off.none'), n: have.length, of: OCR_ALL.length });
    const mb = missing.reduce((s, f) => s + (OCR_MB[(f.match(/lang\/(\w+)\./) || [])[1]] || (f.endsWith('.wasm') ? 2.9 : 0.1)), 0);
    btn.hidden = missing.length === 0;
    btn.disabled = false;
    btn.textContent = t('off.get', { mb: Math.max(1, Math.round(mb)) });
  }
  async function getOfflineReaders() {
    const missing = await offlineMissing();
    if (!missing || !missing.length) { renderOffline(); return; }
    offBusy = true;
    const btn = $('offGet');
    btn.disabled = true;
    try {
      for (let i = 0; i < missing.length; i++) {
        btn.textContent = t('off.busy', { i: i + 1, n: missing.length });
        const r = await fetch(missing[i]);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        await r.arrayBuffer();          // the service worker keeps the file on the phone
      }
    } catch (e) { toast(t('off.fail')); }
    offBusy = false;
    await renderOffline();
    const left = await offlineMissing();
    if (left && !left.length) toast(t('off.done'));
    else if (left && left.length && !navigator.serviceWorker?.controller) toast(t('off.fail'));
  }

  // Long-press menu of the app icon (?go=…) and photos shared to the app (?shared=1).
  function openFromUrl() {
    const q = new URLSearchParams(location.search);
    const goTo = q.get('go'), shared = q.get('shared');
    if (!goTo && !shared) return;
    try { history.replaceState({ tab: 'scan' }, '', location.pathname); } catch (e) { /* ignore */ }
    if (shared && 'caches' in window) {
      caches.open('lc-share').then(async c => {
        const res = await c.match('shared-photo');
        await caches.delete('lc-share');
        if (!res) return;
        const blob = await res.blob();
        openLabel(null);
        loadPhoto(new File([blob], 'shared.' + ((blob.type.split('/')[1] || 'jpg').replace('jpeg', 'jpg')), { type: blob.type || 'image/jpeg' }));
      }).catch(() => {});
    } else if (goTo === 'label') openLabel(null);
    else if (goTo === 'search') openSearch();
    else if (goTo === 'scan') startCamera();
  }

  // Small test hook (used only by automated checks).
  window.LC = { analyze, termRe, matchAvoid, niceName, parseClaudeAnswer, state, lookup, showProduct, dbReady, t, setLanguage, openSearch,
    cleanOcr, joinParts, dedupeNames, lastRead: () => lastRead, headingLang, guessKind, lastFind: () => lastFind, nameHint: () => nameHint, detergentTerm, alternatives, setName, renderStart };

  init();
})();
