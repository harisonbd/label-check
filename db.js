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
  let META = null, COS = null, FOOD = null, FOODNAMES = null;
  let cosIndex = null, eIndex = null, foodNames = null, allergenNames = null;

  // Lower case, ß -> ss, no accents, keep a-z, 0-9 and Cyrillic. Same rule on both sides of a match.
  // v2.47: Bulgarian labels often write E-numbers with the Cyrillic letter ("Е621"): it becomes the Latin "e621".
  // Capital "Е" also with a space ("Е 621"); small "е" only right before the digits ("е621"), because "е 100 г" is normal Bulgarian.
  const latinE = s => String(s || '').replace(/(^|[^\p{L}\p{N}])Е(?=[\s‐-―-]?\d{3})/gu, '$1E').replace(/(^|[^\p{L}\p{N}])е(?=-?\d{3})/gu, '$1e');
  function norm(s) {
    return latinE(s).toLowerCase().replace(/ß/g, 'ss').replace(/ё/g, 'е')
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
    milk: ['краве масло', 'масло от краве мляко', 'сирене', 'кашкавал', 'извара', 'сметана'],   // v2.35: Bulgarian cheese words (crackers label: "СИРЕНЕ на прах")
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
  const TRACES_RE = /(kann\s+spuren|kann\s+[^.;]{0,40}?spuren|kann\s+(?=[^.;]{0,300}?\benthalten\b)|spuren\s+von|may\s+contain|traces\s+of|can\s+contain\s+traces|може\s+да\s+съдържа|следи\s+от|nyomokban|tartalmazhat|může\s+obsahovat|môže\s+obsahovať|lahko\s+vsebuje|sledi|poate\s+con[tțţ]ine|urme\s+de)/i;   // v2.35: + Romanian
  const additiveNames = (a, lang) => (a.n[lang] || []).concat((EXTRA_ADDITIVE_NAMES[a.e] || {})[lang] || []);
  // Plant fats called "butter" are not milk: "cocoa butter" -> "cocoa" before the allergen check.
  const PLANT_BUTTER = / (cocoa|cacao|shea|mango|kokum|illipe|sal|peanut|almond|cashew|hazelnut|nut|seed) butter(?= )/g;
  // Fragrance that the EU list does not mark (move into build_db.py later):
  // essential oils (leaf, flower, peel, bark, root, wood … oil with a fragrance function) and fragrance words on labels.
  const ESSENTIAL_OIL = /\b(LEAF|LEAVES|FLOWER|PEEL|HERB|BARK|ROOT|WOOD|NEEDLE|TWIG|BUD|RESIN|GUM|RHIZOME|STEM|PLANT|TIP|CONE|BRANCH)\b[^,]*\bOIL$/;
  const FATTY_OIL = /\b(SEED|KERNEL|NUT|FRUIT|GERM|BUTTER|BRAN|SPROUT|PULP)\b/;
  const FRAG_FREE = /(^| )(frei|free|ohne|without|без|no|fara|bez|senza|sans|sin|zonder|uten|nincs)( |$)|frei$|free$/;   // v2.47: + RO/HR/CS/IT/FR/ES/NL/NO/HU
  const FRAG_WORDS = new RegExp('(^| )(' + [
    'fragrance', 'fragrances', 'perfume', 'parfum', 'natural fragrance', 'masking fragrance', 'essential oil', 'essential oils',
    'duftstoff', 'duftstoffe', 'parfum', 'atherisches ol', 'atherische ol', 'atherische ole', 'atherischen ole', 'parfumol', 'parfumole',
    'парфюм', 'парфюмна композиция', 'парфюмни композиции', 'аромат', 'ароматизант', 'ароматизатор', 'ароматизатори',
    'етерично масло', 'етерични масла'
  ].join('|') + ')( |$)');
  const PLANT_OIL_WORDS = /(^| )(lavendel|lavendin|zitronen|zitrus|orangen|bergamott|bergamotte|rosmarin|teebaum|pfefferminz|minz|eukalyptus|rosen|ylang ylang|lemongras|patschuli|sandelholz|zedernholz|kamillen|neroli|geranien)ol(e)?( |$)|(^| )(lavender|lemon|orange|bergamot|rosemary|tea tree|peppermint|mint|eucalyptus|rose|ylang ylang|lemongrass|patchouli|sandalwood|cedarwood|chamomile|neroli|geranium) oil( |$)|(^| )(лавандулово|лимоново|портокалово|бергамотово|розмариново|ментово|евкалиптово|розово|иланг иланг|пачули|сандалово|кедрово|лайково) масло( |$)|(^| )масло от (лавандула|лимон|портокал|бергамот|розмарин|чаено дърво|мента|евкалипт|роза|иланг иланг|пачули|сандалово дърво|лайка)( |$)/;
  // Older INCI names seen on labels (move into build_db.py later)
  // v2.19: German names of common ingredients (label text in German -> the INCI name the data knows)
  const DE_COS_ALIASES = { 'NATRIUMCHLORID': 'SODIUM CHLORIDE', 'NATRIUMHYDROXID': 'SODIUM HYDROXIDE', 'KALIUMHYDROXID': 'POTASSIUM HYDROXIDE', 'NATRIUMSULFAT': 'SODIUM SULFATE', 'KALIUMSORBAT': 'POTASSIUM SORBATE', 'NATRIUMBENZOAT': 'SODIUM BENZOATE', 'NATRIUMCITRAT': 'SODIUM CITRATE', 'NATRIUMCARBONAT': 'SODIUM CARBONATE', 'NATRIUMHYDROGENCARBONAT': 'SODIUM BICARBONATE', 'NATRIUMLACTAT': 'SODIUM LACTATE', 'NATRIUMSALICYLAT': 'SODIUM SALICYLATE', 'MAGNESIUMSULFAT': 'MAGNESIUM SULFATE', 'CALCIUMCARBONAT': 'CALCIUM CARBONATE', 'KALIUMCHLORID': 'POTASSIUM CHLORIDE', 'ZINKOXID': 'ZINC OXIDE', 'TITANDIOXID': 'TITANIUM DIOXIDE', 'SALZSÄURE': 'HYDROCHLORIC ACID', 'ZITRONENSÄURE': 'CITRIC ACID', 'MILCHSÄURE': 'LACTIC ACID', 'BENZOESÄURE': 'BENZOIC ACID', 'SORBINSÄURE': 'SORBIC ACID', 'SALICYLSÄURE': 'SALICYLIC ACID', 'ASCORBINSÄURE': 'ASCORBIC ACID', 'ESSIGSÄURE': 'ACETIC ACID', 'STEARINSÄURE': 'STEARIC ACID', 'PALMITINSÄURE': 'PALMITIC ACID', 'ÖLSÄURE': 'OLEIC ACID', 'HYALURONSÄURE': 'HYALURONIC ACID', 'PHOSPHORSÄURE': 'PHOSPHORIC ACID', 'GLYCOLSÄURE': 'GLYCOLIC ACID', 'GEREINIGTES WASSER': 'AQUA', 'GLYCEROL': 'GLYCERIN', 'ETHANOL': 'ALCOHOL', 'ALKOHOL': 'ALCOHOL', 'ISOPROPANOL': 'ISOPROPYL ALCOHOL', 'PROPYLENGLYKOL': 'PROPYLENE GLYCOL', 'BUTYLENGLYKOL': 'BUTYLENE GLYCOL', 'PARAFFINÖL': 'PARAFFINUM LIQUIDUM', 'VASELIN': 'PETROLATUM', 'HARNSTOFF': 'UREA', 'VITAMIN E': 'TOCOPHEROL', 'VITAMIN C': 'ASCORBIC ACID', 'KOFFEIN': 'CAFFEINE', 'CAMPHER': 'CAMPHOR', 'BENZYLALKOHOL': 'BENZYL ALCOHOL', 'CETYLALKOHOL': 'CETYL ALCOHOL', 'CETYLSTEARYLALKOHOL': 'CETEARYL ALCOHOL', 'STEARYLALKOHOL': 'STEARYL ALCOHOL', 'DIMETICON': 'DIMETHICONE', 'KOKOSÖL': 'COCOS NUCIFERA OIL', 'SONNENBLUMENÖL': 'HELIANTHUS ANNUUS SEED OIL', 'JOJOBAÖL': 'SIMMONDSIA CHINENSIS SEED OIL', 'SHEABUTTER': 'BUTYROSPERMUM PARKII BUTTER', 'NATRIUMLAURYLSULFAT': 'SODIUM LAURYL SULFATE', 'NATRIUMLAURETHSULFAT': 'SODIUM LAURETH SULFATE', 'COCAMIDOPROPYLBETAIN': 'COCAMIDOPROPYL BETAINE', 'KETOCONAZOL': 'KETOCONAZOLE', 'LIMONEN': 'LIMONENE', 'CUMARIN': 'COUMARIN', 'CITRONELLOL': 'CITRONELLOL', 'MACROGOLGLYCEROLCOCOATE': 'PEG-7 GLYCERYL COCOATE', };
  // v2.47: German medicine labels (Ph.Eur. names, e.g. a ketoconazole shampoo) and food colour E-numbers on cosmetics
  const PHEUR_COS_ALIASES = {
    'DODECYLPOLY(OXYETHYLEN)-2-HYDROGENSULFAT, NATRIUMSALZ': 'SODIUM LAURETH SULFATE', 'DODECYLPOLY(OXYETHYLEN)-2-HYDROGENSULFAT': 'SODIUM LAURETH SULFATE',
    'NATRIUMDODECYLPOLY(OXYETHYLEN)-2-HYDROGENSULFAT': 'SODIUM LAURETH SULFATE', 'NATRIUMDODECYLSULFAT': 'SODIUM LAURYL SULFATE',
    'DODECYLPOLY(OXYETHYLEN)-3-HYDROGENSULFOSUCCINAT, DINATRIUMSALZ': 'DISODIUM LAURETH SULFOSUCCINATE', 'DINATRIUMDODECYLPOLY(OXYETHYLEN)-3-HYDROGENSULFOSUCCINAT': 'DISODIUM LAURETH SULFOSUCCINATE', 'DODECYLPOLY(OXYETHYLEN)-3-HYDROGENSULFOSUCCINAT': 'DISODIUM LAURETH SULFOSUCCINATE',
    'POLY(OXYETHYLEN)-120-METHYL(D-GLUCOPYRANOSID)DIOLEAT': 'PEG-120 METHYL GLUCOSE DIOLEATE', 'MACROGOLGLYCEROLCOCOATE': 'PEG-7 GLYCERYL COCOATE',
    "1,1'-METHYLENBIS[3-(3-HYDROXYMETHYL-2,5-DIOXOIMIDAZOLIDIN-4-YL)HARNSTOFF]": 'IMIDAZOLIDINYL UREA',
    'N,N-BIS(2-HYDROXYETHYL)COCOSFETTSÄUREAMID': 'COCAMIDE DEA', 'COCOSFETTSÄUREDIETHANOLAMID': 'COCAMIDE DEA',
    'CITRONENSÄURE': 'CITRIC ACID', 'NATRIUMEDETAT': 'DISODIUM EDTA', 'DINATRIUMEDETAT': 'DISODIUM EDTA', 'POLYSORBAT 80': 'POLYSORBATE 80',
    'BUTYLHYDROXYTOLUOL': 'BHT', 'METHYL-4-HYDROXYBENZOAT': 'METHYLPARABEN', 'PROPYL-4-HYDROXYBENZOAT': 'PROPYLPARABEN',
    'HOCHDISPERSES SILICIUMDIOXID': 'SILICA', 'WEISSES VASELIN': 'PETROLATUM', 'DICKFLÜSSIGES PARAFFIN': 'PARAFFINUM LIQUIDUM',
    'DÜNNFLÜSSIGES PARAFFIN': 'PARAFFINUM LIQUIDUM', 'XANTHANGUMMI': 'XANTHAN GUM', 'TROMETAMOL': 'TROMETHAMINE', 'TOCOPHEROLACETAT': 'TOCOPHERYL ACETATE',
    'PONCEAU 4R': 'CI 16255', 'E102': 'CI 19140', 'E104': 'CI 47005', 'E110': 'CI 15985', 'E120': 'CI 75470', 'E122': 'CI 14720', 'E124': 'CI 16255',
    'E127': 'CI 45430', 'E129': 'CI 16035', 'E131': 'CI 42051', 'E132': 'CI 73015', 'E133': 'CI 42090', 'E141': 'CI 75810', 'E151': 'CI 28440',
    'E153': 'CI 77266', 'E160A': 'CI 75130', 'E171': 'CI 77891', 'E172': 'CI 77491'
  };
  const EXTRA_COS_ALIASES = { ...DE_COS_ALIASES, ...PHEUR_COS_ALIASES, 'CITRUS BERGAMIA PEEL OIL': 'CITRUS AURANTIUM BERGAMIA PEEL OIL', 'CITRUS BERGAMIA FRUIT OIL': 'CITRUS AURANTIUM BERGAMIA FRUIT OIL' };
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
    // v2.21: plain food names in many languages (Open Food Facts, ODbL). Optional: without the file the app works as before.
    try { const nf = await get(base + 'names-food.json'); FOODNAMES = new Set((nf && nf.names) || []); } catch (e) { FOODNAMES = null; }
    SHORT_FOOD_N = new Set(SHORT_FOOD.map(norm));
    if (FOODNAMES) for (const w of SHORT_FOOD_N) FOODNAMES.add(w);
    return { version: META.version, cosmetics: COS.items.length, additives: FOOD.additives.length, foodNames: FOODNAMES ? FOODNAMES.size : 0 };
  }
  // Is this label name a plain food ingredient the app knows ("Weizenmehl (45 %)", "Манитол")?
  function knownFood(seg) {
    if (!FOODNAMES) return false;
    const base = norm(String(seg || '').replace(/\([^)]*\)|\[[^\]]*\]/g, ' ').replace(/\d+[.,]?\d*\s*%/g, ' '));
    return (base.length >= 4 || SHORT_FOOD_N.has(base)) && FOODNAMES.has(base);
  }
  // v2.35: common food words shorter than 4 letters (the names file has none): salt, honey, yeast, onion, soy, oil, tea, egg …
  const SHORT_FOOD = ['сол', 'мед', 'мая', 'лук', 'соя', 'чай', 'öl', 'ei', 'tee', 'oil', 'tea', 'egg', 'soy', 'rye', 'apă', 'ouă', 'unt', 'ou', 'soľ', 'med', 'čaj', 'sůl', 'sol', 'só'];
  let SHORT_FOOD_N = new Set();

  // ---------- label splitting
  // v2.47: "free from" claims are no ingredients ("Fără parfum, parabeni și coloranți.", "Ohne Parfum", "parfümfrei", "fragrance-free").
  // The claim runs to the end of its sentence. Before, "parfum" in such a claim counted as fragrance.
  const CLAIM_RE = /(^|[.;,]\s*)(?:fără|fara|ohne|frei\s+von|без|bez|senza|sans|sin|free\s+from|without|no\s+added)\s+[^.;]*/giu;
  const CLAIM_WORD_RE = /(^|[.;,]\s*)[\p{L}-]+(?:frei|-free)(?=\s*(?:[.;,]|$))/giu;
  const stripClaims = t => {
    const s = String(t || ''), r = s.replace(CLAIM_RE, '$1').replace(CLAIM_WORD_RE, '$1');
    return r === s ? s : r.replace(/([.;,])(?:\s*[.;,])+/g, '$1').replace(/[\s.;,]+$/, '');   // no ". . ." left where a claim was
  };
  function stripLabelWord(text) {
    return String(text || '').replace(/^\s*(ingredients?|ingr[eé]dients?|inci|zutaten|inhaltsstoffe|bestandteile|hilfsstoffe|excipients?|съставки|състав|помощни вещества|други вещества|composition|összetevők|složení|zloženie|sestavine|ingrediente)\s*[:：]\s*/i, '');
  }
  // Split at , ; • · and new lines that are not inside brackets. A comma between digits (1,3-diol) does not split.
  function splitIngredients(text) {
    const s = stripClaims(stripLabelWord(text)), out = [];
    let depth = 0, cur = '';
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if ('([{'.includes(ch)) depth++;
      else if (')]}'.includes(ch)) depth = Math.max(0, depth - 1);
      const digitComma = ch === ',' && /\d/.test(s[i - 1] || '') && /\d/.test(s[i + 1] || '');
      // v2.47: "N,N-Bis(…)", "O,O'-…": a single N/O/S before and after the comma, then a hyphen = one chemical name
      const atomComma = ch === ',' && /(^|[^\p{L}])[NOS]['’′]?$/u.test(cur) && /^\s?[NOS]['’′]?(,\s?[NOS]['’′]?)*-/.test(s.slice(i + 1));
      // v2.47: "…-hydrogensulfat, Natriumsalz;" (German medicine labels): the salt word belongs to the name before it
      const saltComma = ch === ',' && /^\s*(di|tri)?(natrium|kalium|calcium|magnesium|ammonium|zink)salz\b/i.test(s.slice(i + 1));
      if (depth === 0 && !digitComma && !atomComma && !saltComma && /[,;•·\n]/.test(ch)) {
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
    const bare = s.replace(/\([^)]*\)|\[[^\]]*\]/g, ' ').trim();   // v2.47: also without [ … ]
    if (bare && bare !== s && bare !== outside) tries.push(bare);
    const noPct = bare.replace(/\s*\d+(?:[.,]\d+)?\s*%/g, ' ').trim();   // v2.47: "Salzsäure 10%" -> "Salzsäure"
    if (noPct && noPct !== bare) tries.push(noPct);
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
    // v2.21.3: a piece that is only an amount ("500 MG", "48%", "100 MG)") is a dose table, no ingredient
    const amount = x => /^[\s(\[]*[\d.,]+\s*(mg|mcg|µg|μg|g|kg|ml|l|kcal|kj|iu|ie|%)?[\s)\]]*$/i.test(x);
    const main = splitIngredients(m ? s.slice(0, m.index) : s).filter(x => !amount(x));
    const traces = m ? splitIngredients(s.slice(m.index)).filter(x => !amount(x)) : [];
    return { segs: main.concat(traces), traceFrom: m ? main.length + 1 : Infinity };
  }

  function checkFood(text, lang) {
    lang = lang || 'en';
    const { segs: rawSegs, traceFrom } = labelSegments(text);
    const segs = rawSegs.map(norm);
    const whole = ' ' + segs.join(' | ') + ' ';
    const posOf = t => { const i = segs.findIndex(s => (' ' + s + ' ').includes(' ' + t + ' ')); return i >= 0 ? i + 1 : null; };
    const found = new Map();
    const raw = latinE(text).toLowerCase();
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
      if (!old || (old.trace && !trace)) allergens.set(al.id, { id: al.id, name: allergenName(al, lang), matched: t, pos, trace, posAll: (old ? old.posAll : []).concat(pos ? [pos] : []) });
      else if (pos && !old.posAll.includes(pos)) old.posAll.push(pos);   // v2.47: every place ("Vollmilchpulver" and "Butterreinfett" are both milk)
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
    // v2.35: sulphur dioxide - sulphites (E 220-228, Regulation (EC) 1333/2008 Annex II Part C(5)(g)) are the EU allergen
    // "sulphur dioxide and sulphites" (Regulation (EU) 1169/2011 Annex II, point 12). The data had the allergen only for E220 by name.
    const sulph = alById.get('sulphur-dioxide-and-sulphites');
    if (sulph) for (const a of additives) if (/^E22[0-8]$/.test(a.e)) addAl(sulph, a.matched, a.pos);
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
  function ensureFuzzy() {
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
  }
  function suggestCosmetic(seg, all) {
    if (!cosIndex) return null;
    // The name before a bracket, without marks like * or °
    const from = String(seg || '').replace(/\s*[\[(].*$/, '').replace(/[\s*°¹²³†‡.:]+$/, '').replace(/^[\s*°.:\-–]+/, '');
    const k = key(from);
    if (k.length < 6 || /[а-я]/.test(k) || cosIndex.has(k)) return null;
    ensureFuzzy();
    const max = k.length <= 8 ? 1 : Math.max(2, Math.floor(k.length * 0.25));
    const tries = [k];
    const kd = k.replace(/[0158]/g, d => OCR_DIGIT[d]);
    if (kd !== k) tries.push(kd);
    let best = null, tie = false, ties = [];
    for (const q of tries) {
      for (let len = q.length - max; len <= q.length + max; len++) {
        for (const [nk, name] of fuzzyByLen.get(len) || []) {
          if (nk[0] !== q[0]) continue;   // v2.18.1: the first letter must be right (Natriumchlorid -> Barium Chloride was a wrong guess)
          const d = lev(q, nk, best ? Math.min(max, best.d) : max);
          if (d > max) continue;
          const it = cosIndex.get(nk);
          if (!best || d < best.d) { best = { d, name, it }; tie = false; ties = [it]; }
          else if (d === best.d && it !== best.it) { tie = true; if (it && !ties.includes(it)) ties.push(it); }
        }
      }
    }
    if (!best || !best.it) return null;
    // all: also the case of two or more equally close names (v2.13: the app asks which one it is)
    if (tie) return all ? { from, tie: true, d: best.d, choices: ties.filter(Boolean).slice(0, 3).map(it => it[0]) } : null;
    return { from, to: best.name, inci: best.it[0], d: best.d };
  }


  // v2.22: the closest known names for a name the app could not match (for the "tap the right one" list). [] when nothing is close.
  function closest(seg, n) {
    if (!cosIndex) return [];
    const from = String(seg || '').replace(/\s*[\[(].*$/, '').replace(/[\s*°¹²³†‡.:]+$/, '').replace(/^[\s*°.:\-–]+/, '');
    const k = key(from);
    if (k.length < 6 || /[а-я]/.test(k) || cosIndex.has(k)) return [];
    ensureFuzzy();
    const max = Math.max(2, Math.floor(k.length * 0.3));
    const kd = k.replace(/[0158]/g, c => OCR_DIGIT[c]);
    const best = new Map();   // INCI name -> distance
    for (const q of (kd !== k ? [k, kd] : [k])) {
      for (let len = q.length - max; len <= q.length + max; len++) {
        for (const [nk, name] of fuzzyByLen.get(len) || []) {
          if (nk[0] !== q[0]) continue;
          const dd = lev(q, nk, max);
          if (dd > max) continue;
          const it = cosIndex.get(nk);
          if (!it) continue;
          if (!best.has(it[0]) || best.get(it[0]) > dd) best.set(it[0], dd);
        }
      }
    }
    return [...best.entries()].sort((a, b) => a[1] - b[1] || a[0].length - b[0].length).slice(0, n || 3).map(x => x[0]);
  }

  // v2.33: two Cyrillic words the reader glued together ("лактозамонохидрат" -> "лактоза монохидрат"): split only when the
  // word is not a known word and both parts are known words of the food names (4+ letters each). Not for Latin letters:
  // German joins words on purpose (Weizenmehl).
  let cyrWords = null;
  function splitGlued(text) {
    if (!FOODNAMES) return String(text || '');
    if (!cyrWords) { cyrWords = new Set(); for (const n of FOODNAMES) for (const w of n.split(' ')) if (w.length >= 4 && /^[а-я]+$/.test(w)) cyrWords.add(w); }
    return String(text || '').replace(/[а-яА-Я]{8,}/g, w => {
      const k = w.toLowerCase();
      if (cyrWords.has(k)) return w;
      for (let i = k.length - 4; i >= 4; i--) if (cyrWords.has(k.slice(0, i)) && cyrWords.has(k.slice(i))) return w.slice(0, i) + ' ' + w.slice(i);
      return w;
    });
  }
  // v2.33: names the reader broke into pieces: a word cut short, a word lost in the middle ("Helianthu us sed oil" ->
  // HELIANTHUS ANNUUS SEED OIL, "Caprylic/Capri erde" -> CAPRYLIC/CAPRIC TRIGLYCERIDE). Word by word: the first word must fit
  // well, every read word must fit a later word of the name (the same, 1-2 letters wrong, its start or its end), at most
  // one word of the name may be missing. When two names fit the same, the common one comes first (COMMON_INCI).
  const COMMON_INCI = ('aqua|glycerin|cetearyl alcohol|glyceryl stearate|glyceryl stearate se|cetyl alcohol|stearyl alcohol|stearic acid|dimethicone|' +
    'cyclopentasiloxane|caprylic/capric triglyceride|paraffinum liquidum|petrolatum|isopropyl myristate|isopropyl palmitate|butylene glycol|' +
    'propylene glycol|pentylene glycol|caprylyl glycol|phenoxyethanol|ethylhexylglycerin|sodium benzoate|potassium sorbate|benzyl alcohol|' +
    'dehydroacetic acid|sodium hydroxide|citric acid|lactic acid|sodium chloride|sodium citrate|disodium edta|tetrasodium edta|' +
    'tetrasodium glutamate diacetate|carbomer|xanthan gum|sodium polyacrylate|acrylates/c10-30 alkyl acrylate crosspolymer|' +
    'ammonium acryloyldimethyltaurate/vp copolymer|hydroxyethylcellulose|tocopherol|tocopheryl acetate|panthenol|allantoin|niacinamide|' +
    'sodium hyaluronate|hyaluronic acid|urea|bisabolol|aloe barbadensis leaf juice|butyrospermum parkii butter|cocos nucifera oil|' +
    'helianthus annuus seed oil|prunus amygdalus dulcis oil|simmondsia chinensis seed oil|olea europaea fruit oil|argania spinosa kernel oil|' +
    'ricinus communis seed oil|glycine soja oil|persea gratissima oil|theobroma cacao seed butter|cera alba|lanolin|squalane|triethanolamine|' +
    'peg-100 stearate|peg-40 hydrogenated castor oil|peg-7 glyceryl cocoate|polysorbate 20|polysorbate 60|polysorbate 80|sorbitan stearate|' +
    'sorbitan olivate|cetearyl olivate|ceteareth-20|steareth-2|steareth-21|glyceryl oleate|glycol distearate|glycol stearate|' +
    'sodium laureth sulfate|sodium lauryl sulfate|cocamidopropyl betaine|coco-glucoside|decyl glucoside|lauryl glucoside|' +
    'sodium cocoyl isethionate|disodium laureth sulfosuccinate|sodium lauroyl sarcosinate|cocamide mea|cocamide dea|' +
    'peg-120 methyl glucose dioleate|polyquaternium-10|polyquaternium-7|guar hydroxypropyltrimonium chloride|behentrimonium chloride|' +
    'cetrimonium chloride|amodimethicone|dimethiconol|parfum|limonene|linalool|citronellol|geraniol|coumarin|hexyl cinnamal|' +
    'alpha-isomethyl ionone|benzyl salicylate|benzyl benzoate|citral|eugenol|butylphenyl methylpropional|hydroxycitronellal|isoeugenol|' +
    'cinnamal|farnesol|amyl cinnamal|titanium dioxide|zinc oxide|ci 77891|ci 77491|ci 77492|ci 77499|mica|silica|talc|kaolin|' +
    'magnesium stearate|zinc stearate|ethylhexyl methoxycinnamate|butyl methoxydibenzoylmethane|octocrylene|ethylhexyl salicylate|homosalate|' +
    'bis-ethylhexyloxyphenol methoxyphenyl triazine|diethylamino hydroxybenzoyl hexyl benzoate|ethylhexyl triazone|methylparaben|' +
    'propylparaben|ethylparaben|methylisothiazolinone|methylchloroisothiazolinone|chlorphenesin|sodium pca|betaine|sorbitol|trehalose|' +
    'maltodextrin|hydrolyzed wheat protein|hydrolyzed collagen|retinyl palmitate|ascorbic acid|sodium ascorbyl phosphate|ascorbyl palmitate|' +
    'ceramide np|cholesterol|phytosphingosine|sodium lauroyl lactylate|lecithin|hydrogenated lecithin|caprylyl/capryl glucoside|isohexadecane|' +
    'isononyl isononanoate|dicaprylyl carbonate|dicaprylyl ether|coco-caprylate/caprate|octyldodecanol|c12-15 alkyl benzoate|' +
    'hydrogenated polyisobutene|cyclohexasiloxane|dimethicone crosspolymer|polymethyl methacrylate|nylon-12|aluminum starch octenylsuccinate|' +
    'tapioca starch|zea mays starch|sodium gluconate|sodium phytate|trisodium ethylenediamine disuccinate|pentasodium pentetate|' +
    'aminomethyl propanol|stearamide amp|triolein|hydroxystearic acid|palmitic acid|myristic acid|lauric acid|behenyl alcohol|' +
    'myristyl alcohol|glyceryl caprylate|glyceryl laurate|polyglyceryl-3 diisostearate|sucrose stearate|arachidyl alcohol|' +
    'arachidyl glucoside|cetyl palmitate|hydrogenated castor oil|candelilla cera|copernicia cerifera cera|ozokerite|paraffin|menthol|' +
    'camphor|salicylic acid|glycolic acid|sodium lactate|potassium hydroxide|ammonium lauryl sulfate|sodium myreth sulfate|' +
    'sodium c14-16 olefin sulfonate|lauryl betaine|sodium cocoamphoacetate|disodium cocoamphodiacetate|glyceryl glucoside|propanediol|' +
    'hexylene glycol|dipropylene glycol|1,2-hexanediol|alcohol denat|alcohol|isopropyl alcohol|caprylyl glycol|stearyl alcohol').split('|');
  let byFirst = null, commonKeys = null;
  const words = s => norm(s).split(' ').filter(Boolean);
  function ensureFirst() {
    if (byFirst) return;
    byFirst = new Map(); commonKeys = new Map(COMMON_INCI.map((x, i) => [key(x), COMMON_INCI.length - i]));   // earlier in the list = more common
    for (const it of COS.items) {
      if ((it[3] || '').includes('o')) continue;          // old names are no guess
      const w = words(it[0]);
      if (w.length < 2 || w[0].length < 3) continue;
      const p = w[0].slice(0, 3);
      if (!byFirst.has(p)) byFirst.set(p, []);
      byFirst.get(p).push([w, it[0]]);
    }
  }
  function wordFit(r, t) {
    if (r === t) return 1;
    const m = t.length <= 5 ? 1 : Math.max(1, Math.floor(t.length * 0.25));
    if (r.length >= 3 && lev(r, t, m) <= m) return 0.9;
    if (r.length >= 3 && t.startsWith(r)) return 0.8;
    if (r.length >= 2 && t.length > r.length && t.endsWith(r)) return r.length >= 3 ? 0.7 : 0.5;
    if (r.length >= 4 && t.length > r.length + 1 && Math.min(lev(r, t.slice(-r.length), 1), lev(r, t.slice(-r.length - 1), 1)) <= 1) return 0.6;
    return 0;
  }
  function wordGuess(seg, n) {
    if (!cosIndex) return [];
    const from = String(seg || '').replace(/\s*[\[(].*$/, '').replace(/[\s*°¹²³†‡.:]+$/, '').replace(/^[\s*°.:\-–]+/, '');
    const k = key(from), r = words(from.replace(/[0158]/g, c => OCR_DIGIT[c]));
    if (r.length < 2 || r.length > 8 || k.length < 6 || /[а-я]/.test(k) || cosIndex.has(k) || r[0].length < 3) return [];
    ensureFirst();
    const hits = [];
    for (const [w, name] of byFirst.get(r[0].slice(0, 3)) || []) {
      if (w.length < r.length || w.length > r.length + 1) continue;
      const f0 = wordFit(r[0], w[0]);
      if (f0 < 0.8) continue;
      let sum = f0, j = 1, ok = true;
      for (let i = 1; i < r.length && ok; i++) {
        let best = 0, bj = -1;
        for (let jj = j; jj <= Math.min(w.length - 1, j + (w.length - r.length)); jj++) { const f = wordFit(r[i], w[jj]); if (f > best) { best = f; bj = jj; } }
        if (!best) ok = false; else { sum += best; j = bj + 1; }
      }
      if (!ok || r.join('').length < 0.4 * w.join('').length) continue;
      hits.push({ name, score: sum / w.length, common: commonKeys.get(key(name)) || 0 });
    }
    hits.sort((a, b) => b.score - a.score || b.common - a.common || a.name.length - b.name.length);
    return hits.filter(h => h.score >= 0.6).slice(0, n || 3).map(h => h.name);
  }
  // v2.33: the best guesses for an unclear cosmetic name: close spelling first (closest), then the word-by-word fit.
  // Among equally close spellings the common name comes first.
  function guessCosmetic(seg, n) {
    n = n || 3;
    let a = closest(seg, 6);
    if (a.length > 1) { ensureFirst(); const i = a.findIndex(x => commonKeys.has(key(x))); if (i > 0) a = [a[i]].concat(a.filter((x, j) => j !== i)); }
    const out = [];
    for (const x of a.concat(wordGuess(seg, n))) if (!out.includes(x)) out.push(x);
    return out.slice(0, n);
  }
  // v2.33: a food name the app does not know: the closest food names (Open Food Facts names, any language). [] when nothing is close.
  let foodByLen = null;
  function closestFood(seg, n) {
    if (!FOODNAMES) return [];
    const base = norm(String(seg || '').replace(/\([^)]*\)|\[[^\]]*\]/g, ' ').replace(/\d+[.,]?\d*\s*%/g, ' '));
    if (base.length < 5 || FOODNAMES.has(base) || /\d/.test(base)) return [];
    if (!foodByLen) {
      foodByLen = new Map();
      for (const f of FOODNAMES) { if (f.length < 4 || /\d/.test(f)) continue; if (!foodByLen.has(f.length)) foodByLen.set(f.length, []); foodByLen.get(f.length).push(f); }
    }
    const max = base.length <= 7 ? 1 : Math.max(2, Math.floor(base.length * 0.2));
    const best = [];
    for (let len = base.length - max; len <= base.length + max; len++) {
      for (const f of foodByLen.get(len) || []) {
        if (f[0] !== base[0]) continue;
        const d = lev(base, f, max);
        if (d <= max) best.push([f, d]);
      }
    }
    return best.sort((a, b) => a[1] - b[1] || a[0].length - b[0].length).slice(0, n || 3).map(x => x[0]);
  }

  // v2.25: known names that stand inside running text ("... Gefahr. SODIUM C14-16 OLEFIN SULFONATE. Enthält MENTHA ARVENSIS LEAF OIL. ..."),
  // exact matches only. Long names (12+ letters) count alone; a regulated allergen (Menthol, Limonene) counts from 6 letters.
  function findNames(seg) {
    if (!cosIndex) return [];
    const words = String(seg || '').split(/\s+/).map(w => w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '')).filter(Boolean);
    const keys = words.map(w => key(w)), out = [];
    for (let i = 0; i < words.length;) {
      let hit = null;
      for (let j = Math.min(words.length - 1, i + 5); j >= i && !hit; j--) {
        const k = keys.slice(i, j + 1).join('');
        const rec = k.length >= 6 ? cosIndex.get(k) : null;
        if (rec && (k.length >= 12 || String(rec[3] || '').includes('a'))) hit = { j, name: rec[0] };
      }
      if (hit) { if (!out.includes(hit.name)) out.push(hit.name); i = hit.j + 1; } else i++;
    }
    return out;
  }

  // v2.21.1: a block of text that holds one or more known names with a little noise around them ("ALLA SODIUM CETEARYL SULFF MIC ACID").
  // Returns [{ from, to }] for the names found inside, and "rest" pieces that stay as they are. null when nothing clear is inside.
  function findInside(seg) {
    if (!cosIndex) return null;
    ensureFuzzy();
    const words = String(seg || '').trim().split(/\s+/).filter(Boolean);
    if (words.length < 2) return null;
    const keys = words.map(w => key(w));
    const used = new Array(words.length).fill(false), found = [];
    const tryWin = (i, j) => {
      const k = keys.slice(i, j + 1).join('');
      if (k.length < 8) return null;
      if (cosIndex.has(k)) return cosIndex.get(k)[0];                                  // exact
      const max = k.length >= 15 ? Math.max(2, Math.floor(k.length * 0.18)) : k.length >= 10 ? 1 : 0;
      let best = null, tie = false;
      for (let len = k.length - max; len <= k.length + max; len++) {
        for (const [nk, name] of fuzzyByLen.get(len) || []) {
          if (max && (nk[0] === k[0] || k.length >= 15)) {
            const d = lev(k, nk, max);
            if (d <= max) { const it = cosIndex.get(nk); if (!best || d < best.d) { best = { d, it }; tie = false; } else if (d === best.d && it !== best.it) tie = true; }
          }
        }
      }
      if (best && !tie && best.it) return best.it[0];
      if (k.length >= 10) {                                                            // the start or the end of a name is cut off at the edge of the photo
        const hits = new Set();
        for (const [len, arr] of fuzzyByLen) if (len > k.length) for (const [nk] of arr) if (nk.endsWith(k) || nk.startsWith(k)) { const it = cosIndex.get(nk); if (it) hits.add(it[0]); }
        if (hits.size === 1) return [...hits][0];
      }
      return null;
    };
    for (let len = Math.min(5, words.length); len >= 1; len--) {
      for (let i = 0; i + len <= words.length; i++) {
        if (used.slice(i, i + len).some(Boolean)) continue;
        const to = tryWin(i, i + len - 1);
        if (to) { for (let x = i; x < i + len; x++) used[x] = true; found.push({ at: i, to, from: words.slice(i, i + len).join(' ') }); }
      }
    }
    if (!found.length) return null;
    const total = keys.join('').length, got = found.reduce((n, f) => n + f.from.replace(/[^\p{L}\p{N}]/gu, '').length, 0);
    if (got / Math.max(1, total) < 0.6) return null;
    found.sort((a, b) => a.at - b.at);
    const out = []; let w = 0;
    const rest = (a, b) => { const r = words.slice(a, b).join(' '); if ((r.match(/\p{L}/gu) || []).length >= 5) out.push({ rest: r }); };
    for (const f of found) { rest(w, f.at); out.push({ from: f.from, to: f.to }); w = f.at + f.from.split(/\s+/).length; }
    rest(w, words.length);
    return out;
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

  // ---------- v2.35: suggestions while typing ("Type the ingredients")
  // Exact name first, then names that start with the letters, then names with a word that starts with them; the alphabet
  // of the typed letters first, shorter names first. Food: E-numbers, additive names (all label languages in the data) and the
  // Open Food Facts food names (names-food.json). Cosmetics / household: CosIng names and aliases.
  // Returns [{ name, e }] (e = "E223" for an additive).
  function suggestNames(q, kind, limit, lang) {
    limit = limit || 5;
    const nq = norm(q), kq = nq.replace(/ /g, '');
    if (kq.length < 2 || !FOOD) return [];
    const cyr = /[Ѐ-ӿ]/.test(q), c = [];
    const sc = t => (t === nq ? 0 : t.startsWith(nq) ? 1 : t.includes(' ' + nq) ? 3 : -1);
    const alpha = t => (/[Ѐ-ӿ]/.test(t) === cyr ? 0 : 2);
    if (kind === 'cosmetic' || kind === 'household') {
      for (const h of search(q, 200)) if (h.kind === 'cosmetic') c.push({ name: h.name, s: h.score + h.name.length / 1000 });
    } else {
      const em = kq.match(/^e(\d{0,4}[a-z]?)$/);
      for (const a of FOOD.additives) {
        if (em) {
          if (a.e.startsWith('e' + em[1])) c.push({ name: (a.n[lang] || a.n.en || [a.e])[0], e: a.e.toUpperCase(), s: a.e.length });
          continue;
        }
        let best = null;
        for (const l of Object.keys(a.n)) for (const nm of a.n[l]) {
          const x = sc(norm(nm));
          if (x >= 0 && (!best || x + alpha(nm) < best.s)) best = { name: nm, e: a.e.toUpperCase(), s: x + alpha(nm) + 0.5 };
        }
        if (best) c.push(best);
      }
      if (!em && FOODNAMES) for (const nm of FOODNAMES) {
        const x = sc(nm);
        if (x >= 0) c.push({ name: nm.charAt(0).toUpperCase() + nm.slice(1), s: x + alpha(nm) + nm.length / 1000 });
      }
    }
    const best = new Map();
    for (const x of c) {
      const k = norm(x.name), o = best.get(k);
      if (!o) best.set(k, x);
      else { if (x.s < o.s) { o.s = x.s; o.name = x.name; } if (x.e && !o.e) o.e = x.e; }
    }
    return [...best.values()].sort((a, b) => a.s - b.s).slice(0, limit).map(x => ({ name: x.name, e: x.e || null }));
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

  const api = { load, norm, splitIngredients, labelSegments, checkCosmetic, suggestCosmetic, closest, wordGuess, guessCosmetic, closestFood, splitGlued, findInside, findNames, checkFood, knownFood, suggestNames, cosAllergens, foodAllergens, search, foodToCosmetic, meta: () => META, SEV };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.LCDB = api;
})(typeof window !== 'undefined' ? window : globalThis);
