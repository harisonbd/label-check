/* Label Check v2 – offline ingredient database lookup.
   Data: data/db-meta.json, data/db-cosmetics.json, data/db-food.json (built by tools/build_db.py).
   Use:  await LCDB.load('data/');
         LCDB.checkCosmetic(labelText, 'de')  -> rows in label order
         LCDB.checkFood(labelText, 'bg')      -> { additives, allergens, rules }
   Levels: b Banned in EU · c Concern · u Under review · r Restricted · n No concerns found. Never "safe". */
(function (root) {
  'use strict';
  const SEV = { b: 5, c: 4, u: 3, r: 2, n: 1 };
  const COSING_URL = 'https://ec.europa.eu/growth/tools-databases/cosing/reference/annexes/list/';
  let META = null, COS = null, FOOD = null;
  let cosIndex = null, eIndex = null, foodNames = null, allergenNames = null;

  // Lower case, ß -> ss, no accents, keep a-z, 0-9 and Cyrillic. Same rule on both sides of a match.
  function norm(s) {
    return String(s || '').toLowerCase().replace(/ß/g, 'ss').replace(/ё/g, 'е')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9а-я]+/g, ' ').trim();
  }
  const key = s => norm(s).replace(/ /g, '');
  const worst = (a, b) => (SEV[b] > SEV[a] ? b : a);
  const tr = (obj, lang) => (obj && (obj[lang] || obj.en)) || '';
  // Display names where the first synonym in the data is not the usual word (data from Open Food Facts).
  const ALLERGEN_LABEL = { bg: { milk: 'мляко' } };
  // Names missing in the Open Food Facts data (move into build_db.py later).
  const EXTRA_ALLERGEN_NAMES = {
    milk: ['краве масло', 'масло от краве мляко'],
    'sesame-seeds': ['сусам', 'сусамово семе', 'сусамови семена'],
    // HU / CS / SK / SL word forms seen on labels that the data lists only in another form
    gluten: ['búzaliszt', 'pšeničná mouka', 'pšeničná múka', 'pšenična moka', 'pšeničný', 'pšeničná', 'pšenična', 'pšenični'],
    soybeans: ['szója', 'szójalecitin', 'sójový', 'sójová', 'sójový lecitin', 'sójový lecitín', 'sojin', 'sojin lecitin']
  };
  // Additive names seen on real labels but missing in the data (move into build_db.py later).
  const EXTRA_ADDITIVE_NAMES = {
    e464: { bg: ['хипромелоза'] }, e551: { bg: ['силиконов диоксид', 'силициев двуокис'] },
    e322: { hu: ['szójalecitin', 'napraforgó-lecitin'], de: ['sojalecithin', 'sojalecithine', 'sonnenblumenlecithin', 'sonnenblumenlecithine', 'rapslecithin', 'rapslecithine'] },
    e290: { de: ['kohlensäure'] }, e410: { de: ['johannisbrotkernmehl'] }
  };
  // German compound words (v2.9): "Hartweizengrieß", "Vollmilchpulver", "Haselnusskerne" hold an allergen word inside.
  // [stem, words to skip (regex), mode]: 'in' = anywhere in a longer word (default), 'start' = word starts with it,
  // 'edge' = word starts or ends with it. Whole words are found by the normal names (with PLANT_BUTTER).
  // Measured on 342 German Open Food Facts products: missed allergens 95 -> 55, no new wrong finds.
  const ALLERGEN_STEMS = {
    gluten: [['weizen', 'buchweizen'], ['dinkel'], ['roggen'], ['gerste'], ['hafer'], ['grunkern'], ['emmer'], ['kamut'], ['einkorn'], ['triticale']],
    milk: [['milch', 'kokosmilch|mandelmilch|hafermilch|sojamilch|reismilch|cashewmilch|milchsaure'], ['sahne'], ['rahm'],
      ['butter', 'kakaobutter|cacaobutter|sheabutter|erdnussbutter|mandelbutter|nussbutter|kokosbutter|mangobutter'], ['molke'],
      ['kase', 'kasein'], ['kasein'], ['joghurt', 'sojajoghurt|kokosjoghurt|joghurtkultur'], ['quark'], ['laktose', 'laktosefrei'],
      ['lactose', 'lactosefrei'], ['topfen']],
    soybeans: [['soja']],
    eggs: [['eigelb'], ['eiklar'], ['eidotter'], ['vollei'], ['huhnerei'], ['eipulver'], ['trockenei'], ['flussigei'], ['eier', '', 'start']],
    nuts: [['haselnuss'], ['mandel'], ['walnuss'], ['cashew'], ['pistazie'], ['pekannuss'], ['paranuss'], ['macadamia'], ['schalenfrucht']],
    peanuts: [['erdnuss']], celery: [['sellerie']], mustard: [['senf', '', 'edge']], 'sesame-seeds': [['sesam']], lupin: [['lupine']],
    fish: [['fisch', 'tintenfisch']], crustaceans: [['garnele'], ['krabbe'], ['krebs'], ['hummer']], molluscs: [['muschel'], ['tintenfisch'], ['kalmar']]
  };
  const STEM_LIST = Object.entries(ALLERGEN_STEMS).flatMap(([id, list]) => list.map(([s, ex, mode]) => ({ id, s, ex: ex ? new RegExp(ex) : null, mode: mode || 'in' })));
  function stemAllergen(word) {
    for (const x of STEM_LIST) {
      if (word.length <= x.s.length) continue;          // a whole word is found by the normal names
      const ok = x.mode === 'start' ? word.startsWith(x.s) : x.mode === 'edge' ? (word.startsWith(x.s) || word.endsWith(x.s)) : word.includes(x.s);
      if (ok && !(x.ex && x.ex.test(word))) return x;
    }
    return null;
  }
  // "May contain traces" (v2.9): the part of a label after these words lists traces, not ingredients.
  const TRACES_RE = /(kann\s+spuren|kann\s+[^.;]{0,40}?spuren|spuren\s+von|may\s+contain|traces\s+of|can\s+contain\s+traces|може\s+да\s+съдържа|следи\s+от|nyomokban|tartalmazhat|může\s+obsahovat|môže\s+obsahovať|lahko\s+vsebuje|sledi)/i;
  const additiveNames = (a, lang) => (a.n[lang] || []).concat((EXTRA_ADDITIVE_NAMES[a.e] || {})[lang] || []);
  // Plant fats called "butter" are not milk: "cocoa butter" -> "cocoa" before the allergen check.
  const PLANT_BUTTER = / (cocoa|cacao|shea|mango|kokum|illipe|sal|peanut|almond|cashew|hazelnut|nut|seed) butter(?= )/g;
  // Fragrance that the EU list does not mark (move into build_db.py later):
  // essential oils (leaf, flower, peel, bark, root, wood … oil with a fragrance function) and fragrance words on labels.
  const ESSENTIAL_OIL = /\b(LEAF|LEAVES|FLOWER|PEEL|HERB|BARK|ROOT|WOOD|NEEDLE|TWIG|BUD|RESIN|GUM|RHIZOME|STEM|PLANT|TIP|CONE|BRANCH)\b[^,]*\bOIL$/;
  const FATTY_OIL = /\b(SEED|KERNEL|NUT|FRUIT|GERM|BUTTER|BRAN|SPROUT|PULP)\b/;
  const FRAG_FREE = /(^| )(frei|free|ohne|without|без|no)( |$)|frei$|free$/;
  const FRAG_WORDS = new RegExp('(^| )(' + [
    'fragrance', 'fragrances', 'perfume', 'parfum', 'natural fragrance', 'masking fragrance', 'essential oil', 'essential oils',
    'duftstoff', 'duftstoffe', 'parfum', 'atherisches ol', 'atherische ol', 'atherische ole', 'atherischen ole', 'parfumol', 'parfumole',
    'парфюм', 'парфюмна композиция', 'парфюмни композиции', 'аромат', 'ароматизант', 'ароматизатор', 'ароматизатори',
    'етерично масло', 'етерични масла'
  ].join('|') + ')( |$)');
  const PLANT_OIL_WORDS = /(^| )(lavendel|lavendin|zitronen|zitrus|orangen|bergamott|bergamotte|rosmarin|teebaum|pfefferminz|minz|eukalyptus|rosen|ylang ylang|lemongras|patschuli|sandelholz|zedernholz|kamillen|neroli|geranien)ol(e)?( |$)|(^| )(lavender|lemon|orange|bergamot|rosemary|tea tree|peppermint|mint|eucalyptus|rose|ylang ylang|lemongrass|patchouli|sandalwood|cedarwood|chamomile|neroli|geranium) oil( |$)|(^| )(лавандулово|лимоново|портокалово|бергамотово|розмариново|ментово|евкалиптово|розово|иланг иланг|пачули|сандалово|кедрово|лайково) масло( |$)|(^| )масло от (лавандула|лимон|портокал|бергамот|розмарин|чаено дърво|мента|евкалипт|роза|иланг иланг|пачули|сандалово дърво|лайка)( |$)/;
  // Older INCI names seen on labels (move into build_db.py later)
  const EXTRA_COS_ALIASES = { 'CITRUS BERGAMIA PEEL OIL': 'CITRUS AURANTIUM BERGAMIA PEEL OIL', 'CITRUS BERGAMIA FRUIT OIL': 'CITRUS AURANTIUM BERGAMIA FRUIT OIL' };
  const isFragranceWord = seg => { const n = norm(seg); return !FRAG_FREE.test(n) && (FRAG_WORDS.test(n) || PLANT_OIL_WORDS.test(n)); };
  const allergenName = (al, lang) => (ALLERGEN_LABEL[lang] && ALLERGEN_LABEL[lang][al.id]) || (al.n[lang] || al.n.en)[0];

  async function load(base, fetchFn) {
    const get = fetchFn || (async u => (await fetch(u)).json());
    [META, COS, FOOD] = await Promise.all(['db-meta.json', 'db-cosmetics.json', 'db-food.json'].map(f => get(base + f)));
    cosIndex = new Map();
    const fragFn = new Set(META.functions.map((f, i) => (/^(Fragrance|Perfuming)$/.test(f.en) ? i : -1)).filter(i => i >= 0));
    for (const it of COS.items) {
      const fl = it[3] || '';
      if (!fl.includes('f') && / OIL$/.test(it[0]) && ESSENTIAL_OIL.test(it[0]) && !FATTY_OIL.test(it[0]) && (it[1] || []).some(i => fragFn.has(i))) {
        while (it.length < 4) it.push(it.length === 2 ? 'n' : '');
        it[3] = fl + 'f';
      }
      const k = key(it[0]);
      if (!cosIndex.has(k) || (it[3] || '').includes('o') === false) cosIndex.set(k, it);
    }
    for (const [alias, inci] of Object.entries(Object.assign({}, COS.aliases, EXTRA_COS_ALIASES))) {
      const k = key(alias), target = cosIndex.get(key(inci));
      if (target && !cosIndex.has(k)) cosIndex.set(k, target);
    }
    eIndex = new Map(FOOD.additives.map(a => [a.e, a]));
    foodNames = [];
    for (const a of FOOD.additives) {
      for (const lang of Object.keys(a.n)) {      // all label languages in the data (EN DE BG HU CS SK SL)
        for (const n of additiveNames(a, lang)) {
          const t = norm(n);
          if (t.length >= 4) foodNames.push([t, a]);
        }
      }
    }
    foodNames.sort((x, y) => y[0].length - x[0].length);
    allergenNames = [];
    for (const al of FOOD.allergens) {
      const extra = EXTRA_ALLERGEN_NAMES[al.id] || [];
      for (const n of [...Object.values(al.n).flat(), ...extra]) {
        const t = norm(n);
        if (t.length >= 3) allergenNames.push([t, al]);
      }
    }
    allergenNames.sort((x, y) => y[0].length - x[0].length);
    return { version: META.version, cosmetics: COS.items.length, additives: FOOD.additives.length };
  }

  // ---------- label splitting
  function stripLabelWord(text) {
    return String(text || '').replace(/^\s*(ingredients?|ingr[eé]dients?|inci|zutaten|inhaltsstoffe|bestandteile|съставки|състав|composition|összetevők|složení|zloženie|sestavine)\s*[:：]\s*/i, '');
  }
  // Split at , ; • · and new lines that are not inside brackets. A comma between digits (1,3-diol) does not split.
  function splitIngredients(text) {
    const s = stripLabelWord(text), out = [];
    let depth = 0, cur = '';
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if ('([{'.includes(ch)) depth++;
      else if (')]}'.includes(ch)) depth = Math.max(0, depth - 1);
      const digitComma = ch === ',' && /\d/.test(s[i - 1] || '') && /\d/.test(s[i + 1] || '');
      if (depth === 0 && !digitComma && /[,;•·\n]/.test(ch)) {
        if (cur.trim()) out.push(cur.trim());
        cur = '';
      } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  // ---------- reasons
  function src(label, url) { return { label, url }; }
  function reasonsFor(refs, flags, lang, extra) {
    const R = META.reasons, out = [];
    const add = (lv, text, source, details) => out.push({ lv, text, source, details });
    for (const ref of refs || []) {
      if (ref.startsWith('CUR:')) {
        const c = META.curated[ref.slice(4)];
        if (c) add(c.lv, tr(c, lang), c.src);
      } else if (ref.startsWith('ED:')) {
        const e = META.ed[ref.slice(3)];
        if (e) add(e.lv, tr(R[e.k], lang), src('EU endocrine disruptor lists (' + e.l.join(', ') + ')', e.url || 'https://edlists.org/the-ed-lists'),
          { name: e.n, status: e.st, year: e.y });
      } else if (ref.startsWith('IARC:')) {
        const g = META.iarc[ref.slice(5)];
        if (g) {
          let text = tr(R['iarc.' + g.g], lang);
          if (g.ctx) text += ' ' + tr(META.context[g.ctx], lang);
          add('c', text + ' ' + tr(R['iarc.note'], lang), src('IARC Monographs vol. ' + g.vol + ' (' + g.y + '): ' + g.agent, 'https://monographs.iarc.who.int/list-of-classifications/'));
        }
      } else if (ref === 'FOOD:noteu') {
        add('b', tr(R['food.noteu'], lang), src('EU food additives database', 'https://ec.europa.eu/food/food-feed-portal/screen/food-additives/search'));
      } else {
        const adv = ref.startsWith('?'), nanoOnly = ref.startsWith('N:');
        if (nanoOnly && !(extra && extra.nano)) continue;   // nano-only ban: applies only when the label says (nano)
        const r = adv ? ref.slice(1) : nanoOnly ? ref.slice(2) : ref, an = r.split('/')[0], no = r.split('/')[1];
        const a = META.annex[r];
        if (!a) continue;
        const k = nanoOnly ? 'ann.nano' : adv ? 'ann.II.adv' : (an === 'II' ? 'ann.II.' + a.k : 'ann.' + an);
        add(adv ? 'n' : nanoOnly ? 'b' : a.k, tr(R[k], lang).replace('{ref}', no), src('EU CosIng, Annex ' + an + ' entry ' + no + (a.reg ? ' – ' + a.reg : ''), COSING_URL + an),
          { entry: a.t, products: a.pt, max: a.max, conditions: a.cond, warning: a.warn, date: a.d, expert: a.sccs });
      }
    }
    if ((flags || '').includes('a')) add('r', tr(R.allergen, lang), src('Regulation (EU) 2023/1545', 'https://eur-lex.europa.eu/eli/reg/2023/1545/oj'));
    if ((flags || '').includes('h') && extra && extra.efsa) add('n', tr(R['efsa.high'], lang).replace('{y}', (extra.efsa[0] || '').slice(0, 4)), src('EFSA opinion', extra.efsa[1]));
    out.sort((x, y) => SEV[y.lv] - SEV[x.lv]);
    return out;
  }

  // ---------- cosmetics
  function resolveCosmetic(seg) {
    let s = seg.replace(/[*°¹²³†‡]+/g, ' ').trim();
    let nano = false;
    s = s.replace(/[\[(]\s*nano\s*[\])]/ig, () => { nano = true; return ' '; }).trim();
    const tries = [s];
    const outside = s.replace(/\([^)]*\)/g, ' ').trim();
    if (outside && outside !== s) tries.push(outside);
    for (const m of s.matchAll(/\(([^)]*)\)/g)) tries.push(m[1]);
    for (const t of tries.slice()) if (t.includes('/')) tries.push(...t.split('/'));
    for (const t of tries) {
      const it = cosIndex.get(key(t));
      if (it) return { it, nano };
    }
    return { it: null, nano };
  }

  function checkCosmetic(text, lang) {
    lang = lang || 'en';
    const parts = String(text || '').split(/(\[?\(?\+\s*\/\s*-\)?\]?|\bmay contain\b|\bkann enthalten\b|\bpeut contenir\b|може да съдържа)/i);
    const rows = [];
    let mayContain = false, pos = 0;
    for (const p of parts) {
      if (/^(\[?\(?\+\s*\/\s*-\)?\]?|may contain|kann enthalten|peut contenir|може да съдържа)$/i.test(p.trim())) { mayContain = true; continue; }
      for (const seg of splitIngredients(p)) {
        if (!key(seg)) continue;
        pos++;
        const { it, nano } = resolveCosmetic(seg);
        if (!it) { rows.push({ pos, text: seg, found: false, level: 'n', mayContain, nano, fragrance: isFragranceWord(seg) }); continue; }
        const [name, fns, baseLevel = 'n', flags = '', refs = []] = it;
        const level = nano && refs.some(r => r.startsWith('N:')) ? 'b' : baseLevel;
        rows.push({
          pos, text: seg, found: true, name, level, mayContain, nano,
          fragrance: flags.includes('f'), allergen: flags.includes('a'), oldName: flags.includes('o'), envNote: flags.includes('e'),
          allergenRef: flags.includes('a') ? refs.find(r => r.startsWith('III/')) : null,
          functions: fns.map(i => tr(META.functions[i], lang)),
          reasons: reasonsFor(refs, flags, lang, { nano })
        });
      }
    }
    return rows;
  }

  // ---------- food
  function termRegex(term) {
    const t = norm(term.replace(/\*/g, ' zzstarzz ')).replace(/ ?zzstarzz/g, '*');
    const body = t.split('*').map(p => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('[a-z0-9\\u0430-\\u044f]*');
    return new RegExp('(?:^| )' + body + '(?= |$)');
  }
  // Label -> ingredient pieces. The text from the first "may contain traces" words on is cut off first
  // ("Hartweizengrieß. Kann Spuren von Soja …"), so pieces from traceFrom on are traces. The app uses the same pieces.
  function labelSegments(text) {
    const s = String(text || ''), m = TRACES_RE.exec(s);
    const main = splitIngredients(m ? s.slice(0, m.index) : s);
    const traces = m ? splitIngredients(s.slice(m.index)) : [];
    return { segs: main.concat(traces), traceFrom: m ? main.length + 1 : Infinity };
  }

  function checkFood(text, lang) {
    lang = lang || 'en';
    const { segs: rawSegs, traceFrom } = labelSegments(text);
    const segs = rawSegs.map(norm);
    const whole = ' ' + segs.join(' | ') + ' ';
    const posOf = t => { const i = segs.findIndex(s => (' ' + s + ' ').includes(' ' + t + ' ')); return i >= 0 ? i + 1 : null; };
    const found = new Map();
    const raw = String(text || '').toLowerCase();
    for (const m of raw.matchAll(/(?:^|[^a-z0-9])e\s?-?\s?(\d{3,4})\s?([a-z])?(?![a-z0-9])/g)) {
      const k = 'e' + m[1] + (m[2] || '');
      const a = eIndex.get(k) || eIndex.get('e' + m[1]);
      if (a && !found.has(a.e)) found.set(a.e, { a, by: 'e' + m[1] + (m[2] || ''), pos: posOf('e' + m[1] + (m[2] || '')) || posOf(norm(m[0])) });
    }
    // Longest names first. A shorter name that lies fully inside an already matched name is not found again
    // ("sodium hydrogen carbonate" is E500, not also E502 "carbonate" and E949 "hydrogen"). Names that only
    // overlap still count ("Kupferkomplexe der Chlorophylle und Chlorophylline" = E141 and E140).
    const spans = [];
    for (const [t, a] of foodNames) {
      const needle = ' ' + t + ' ';
      let i = whole.indexOf(needle), hit = false;
      while (i >= 0) {
        const s = i + 1, e = i + needle.length - 1;
        if (!spans.some(([s0, e0]) => s >= s0 && e <= e0)) { spans.push([s, e]); hit = true; }
        i = whole.indexOf(needle, i + 1);
      }
      if (hit && !found.has(a.e)) found.set(a.e, { a, by: t, pos: posOf(t) });
    }
    const additives = [...found.values()].map(({ a, by, pos }) => {
      const reasons = reasonsFor(a.refs, a.fl, lang, a);
      if (a.eu && a.lv === 'n') reasons.push({ lv: 'n', text: tr(META.reasons['food.eu'], lang), source: { label: 'EU food additives database', url: 'https://ec.europa.eu/food/food-feed-portal/screen/food-additives/search' } });
      return {
        e: a.e.toUpperCase(), name: (a.n[lang] || a.n.en || [a.e])[0], level: a.lv, matched: by, pos,
        classes: (a.cl || []).map(i => tr(META.foodClasses[i], lang)), vegan: a.vg || null, reasons
      };
    }).sort((x, y) => (x.pos || 999) - (y.pos || 999));
    const allergens = new Map();
    const alById = new Map(FOOD.allergens.map(al => [al.id, al]));
    const addAl = (al, t, pos) => {
      const trace = pos !== null && pos >= traceFrom;
      const old = allergens.get(al.id);
      // An allergen in the ingredients wins over the same allergen in the traces line.
      if (!old || (old.trace && !trace)) allergens.set(al.id, { id: al.id, name: allergenName(al, lang), matched: t, pos, trace });
    };
    const segsA = segs.map(s => (' ' + s + ' ').replace(PLANT_BUTTER, ' $1'));
    for (const [t, al] of allergenNames) {
      segsA.forEach((s, i) => { if (s.includes(' ' + t + ' ')) addAl(al, t, i + 1); });
    }
    // German compound words
    segs.forEach((s, i) => {
      for (const w of s.split(' ')) { const x = stemAllergen(w); if (x && alById.has(x.id)) addAl(alById.get(x.id), w, i + 1); }
    });
    const rules = [];
    for (const r of FOOD.rules) {
      const terms = Object.values(r.terms).flat();
      const hit = terms.find(t => termRegex(t).test(segs.join(' ')));
      if (hit) rules.push({ id: r.id, level: r.lv, matched: hit, reasons: reasonsFor(r.refs, '', lang) });
    }
    return { additives, allergens: [...allergens.values()].sort((x, y) => (x.pos || 999) - (y.pos || 999)), rules, traceFrom };
  }

  // ---------- tick lists for the allergen profile
  // Cosmetics: one entry per EU fragrance-allergen annex entry (Annex III), with all INCI names that point to it.
  function cosAllergens() {
    const byRef = new Map();
    for (const it of COS.items) {
      const flags = it[3] || '';
      if (!flags.includes('a')) continue;
      const ref = (it[4] || []).find(r => r.startsWith('III/'));
      if (!ref) continue;
      const e = byRef.get(ref) || { ref, names: [], main: null, mainOld: true };
      e.names.push(it[0]);
      const old = flags.includes('o');
      if (!e.main || (e.mainOld && !old) || (e.mainOld === old && it[0].length < e.main.length)) { e.main = it[0]; e.mainOld = old; }
      byRef.set(ref, e);
    }
    return [...byRef.values()].map(e => ({ ref: e.ref, name: e.main, names: e.names })).sort((a, b) => a.name.localeCompare(b.name));
  }
  function foodAllergens(lang) {
    return FOOD.allergens.map(a => ({ id: a.id, name: allergenName(a, lang) }));
  }

  // ---------- fix suggestions: a cosmetic name the photo reader got a little wrong ("GLYCERN" -> GLYCERIN)
  // Edit distance to all INCI names and aliases of about the same length. Only one clear best name, never a guess between two.
  let fuzzyByLen = null;
  function lev(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let rowMin = i;
      for (let j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (cur[j] < rowMin) rowMin = cur[j];
      }
      if (rowMin > max) return max + 1;
      prev = cur;
    }
    return prev[b.length];
  }
  const OCR_DIGIT = { 0: 'o', 1: 'i', 5: 's', 8: 'b' };   // the reader sees O as 0, I as 1 ("150PROPYL" = ISOPROPYL)
  function suggestCosmetic(seg) {
    if (!cosIndex) return null;
    // The name before a bracket, without marks like * or °
    const from = String(seg || '').replace(/\s*[\[(].*$/, '').replace(/[\s*°¹²³†‡.:]+$/, '').replace(/^[\s*°.:\-–]+/, '');
    const k = key(from);
    if (k.length < 6 || /[а-я]/.test(k) || cosIndex.has(k)) return null;
    if (!fuzzyByLen) {
      fuzzyByLen = new Map();
      const seen = new Set();
      const add = name => {
        const nk = key(name);
        if (nk.length < 4 || nk.length > 60 || seen.has(nk)) return;
        seen.add(nk);
        if (!fuzzyByLen.has(nk.length)) fuzzyByLen.set(nk.length, []);
        fuzzyByLen.get(nk.length).push([nk, name]);
      };
      for (const it of COS.items) add(it[0]);
      for (const a of Object.keys(Object.assign({}, COS.aliases, EXTRA_COS_ALIASES))) add(a);
    }
    const max = k.length <= 8 ? 1 : Math.max(2, Math.floor(k.length * 0.25));
    const tries = [k];
    const kd = k.replace(/[0158]/g, d => OCR_DIGIT[d]);
    if (kd !== k) tries.push(kd);
    let best = null, tie = false;
    for (const q of tries) {
      for (let len = q.length - max; len <= q.length + max; len++) {
        for (const [nk, name] of fuzzyByLen.get(len) || []) {
          const d = lev(q, nk, best ? Math.min(max, best.d) : max);
          if (d > max) continue;
          if (!best || d < best.d) { best = { d, name, it: cosIndex.get(nk) }; tie = false; }
          else if (d === best.d && cosIndex.get(nk) !== best.it) tie = true;
        }
      }
    }
    if (!best || tie || !best.it) return null;
    return { from, to: best.name, inci: best.it[0], d: best.d };
  }

  // ---------- search one ingredient (name, alias or E-number)
  let cosKeys = null;
  function search(q, limit) {
    limit = limit || 30;
    const nq = norm(q), kq = nq.replace(/ /g, '');
    if (kq.length < 2) return [];
    if (!cosKeys) {
      cosKeys = COS.items.map(it => [key(it[0]), it[0], it[2] || 'n']);
      for (const [alias, inci] of Object.entries(COS.aliases)) {
        const it = cosIndex.get(key(inci));
        if (it) cosKeys.push([key(alias), it[0], it[2] || 'n']);
      }
    }
    const hits = new Map();
    const add = (score, id, kind, name, level) => {
      const k = kind + ':' + id, old = hits.get(k);
      if (!old || score < old.score) hits.set(k, { score, id, kind, name, level });
    };
    const em = kq.match(/^e(\d{3,4}[a-z]?)$/);
    if (em) { const a = eIndex.get('e' + em[1]); if (a) add(0, a.e, 'food', a.e.toUpperCase(), a.lv); }
    for (const a of FOOD.additives) {
      for (const lang of Object.keys(a.n)) for (const n of additiveNames(a, lang)) {
        const t = norm(n), i = t.indexOf(nq);
        if (i >= 0) add(t === nq ? 1 : i === 0 ? 2 : 4, a.e, 'food', a.e.toUpperCase(), a.lv);
      }
    }
    // A full E-number ("e 250") means a food additive: no cosmetic names that only contain the letters ("…peptide-250")
    if (!em) for (const [k, name, level] of cosKeys) {
      const i = k.indexOf(kq);
      if (i >= 0) add(k === kq ? 1 : i === 0 ? 2 : 4, name, 'cosmetic', name, level);
    }
    return [...hits.values()].sort((x, y) => (x.score - y.score) || (x.name.length - y.name.length)).slice(0, limit);
  }

  // ---------- a food additive -> the cosmetic name with the same English name (E901 "beeswax" -> BEESWAX)
  // Used when you teach the app a name: "Bienenwachs" or "пчелен восък" are additive names, and lead to the cosmetic entry.
  function foodToCosmetic(e) {
    const a = eIndex && eIndex.get(String(e || '').toLowerCase());
    if (!a || !cosIndex) return [];
    const out = [];
    for (const n of (a.n && a.n.en) || []) {
      const it = cosIndex.get(key(n));
      if (it && !out.includes(it[0])) out.push(it[0]);
    }
    return out;
  }

  const api = { load, norm, splitIngredients, labelSegments, checkCosmetic, suggestCosmetic, checkFood, cosAllergens, foodAllergens, search, foodToCosmetic, meta: () => META, SEV };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.LCDB = api;
})(typeof window !== 'undefined' ? window : globalThis);
