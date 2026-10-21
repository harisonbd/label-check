// Label Check – accuracy check (item 3, v2.8).
// Compares what the app finds in real ingredient lists with the tags that Open Food Facts gives the same products.
// Open Food Facts tags are made by their own text reader, so a difference is something to look at, not proof of an error.
// Use:  node tools/audit.js <folder with Open Food Facts search pages (*.json)> [report.md]
// Open Food Facts blocks GitHub's servers (503), so there is no workflow for this. Get the pages in a normal browser:
// https://world.openfoodfacts.org/api/v2/search?countries_tags_en=austria&page_size=100&sort_by=unique_scans_n&fields=code,lang,
// ingredients_text,ingredients_text_de,ingredients_text_en,ingredients_text_bg,additives_tags,allergens_tags (max 10 searches a minute).
const fs = require('fs');
const path = require('path');
const LCDB = require(path.join(__dirname, '..', 'db.js'));

const LANGS = ['de', 'en', 'bg', 'hu', 'cs', 'sk', 'sl'];
const EU14 = new Set(['gluten', 'crustaceans', 'eggs', 'fish', 'peanuts', 'soybeans', 'milk', 'nuts', 'celery', 'mustard',
  'sesame-seeds', 'sulphur-dioxide-and-sulphites', 'lupin', 'molluscs']);

(async () => {
  const dir = process.argv[2];
  const out = process.argv[3] || 'audit-report.md';
  if (!dir) { console.error('usage: node tools/audit.js <folder> [report.md]'); process.exit(2); }
  await LCDB.load(path.join(__dirname, '..', 'data') + path.sep, async f => JSON.parse(fs.readFileSync(f, 'utf8')));

  const seen = new Set(), products = [];
  for (const f of fs.readdirSync(dir).filter(x => x.endsWith('.json')).sort()) {
    let j;
    try { j = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')); } catch (e) { console.log('skip (not JSON):', f); continue; }
    for (const p of j.products || []) {
      if (!p.code || seen.has(p.code)) continue;
      seen.add(p.code);
      const lang = LANGS.find(l => p['ingredients_text_' + l]);
      const text = lang ? p['ingredients_text_' + lang] : p.ingredients_text;
      if (!text || text.length < 15) continue;
      products.push({ p, text, lang: lang || p.lang || '?' });
    }
  }

  const stat = { products: products.length, addSame: 0, addMissed: 0, addExtra: 0, algSame: 0, algMissed: 0, algExtra: 0 };
  const missed = new Map(), extra = new Map(), algMissed = new Map(), algExtra = new Map(), byLang = {};
  const note = (map, k, code) => { const e = map.get(k) || { n: 0, codes: [] }; e.n++; if (e.codes.length < 3) e.codes.push(code); map.set(k, e); };

  for (const { p, text, lang } of products) {
    const r = LCDB.checkFood(text, 'en');
    const ours = new Set(r.additives.map(a => a.e.toLowerCase()));
    const theirs = new Set((p.additives_tags || []).map(t => (String(t).match(/^en:(e\d{3,4}[a-z]?)/) || [])[1]).filter(Boolean));
    const L = byLang[lang] || (byLang[lang] = { products: 0, missed: 0, extra: 0 });
    L.products++;
    for (const e of theirs) {
      const base = e.replace(/[a-z]$/, '');
      if (ours.has(e) || ours.has(base) || [...ours].some(o => o.startsWith(base))) stat.addSame++;
      else { stat.addMissed++; L.missed++; note(missed, e.toUpperCase(), p.code); }
    }
    for (const e of ours) {
      const base = e.replace(/[a-z]$/, '');
      if (![...theirs].some(t => t === e || t.startsWith(base))) { stat.addExtra++; L.extra++; note(extra, e.toUpperCase() + ' (' + (r.additives.find(a => a.e.toLowerCase() === e) || {}).matched + ')', p.code); }
    }
    const ourA = new Set(r.allergens.map(a => a.id));
    const theirA = new Set((p.allergens_tags || []).map(t => String(t).replace(/^en:/, '')).filter(t => EU14.has(t)));
    for (const a of theirA) { if (ourA.has(a)) stat.algSame++; else { stat.algMissed++; note(algMissed, a + ' [' + lang + ']', p.code); } }
    for (const a of ourA) if (!theirA.has(a)) { stat.algExtra++; note(algExtra, a + ' ("' + r.allergens.find(x => x.id === a).matched + '")', p.code); }
  }

  const top = (map, n) => [...map.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, n)
    .map(([k, v]) => `| ${k} | ${v.n} | ${v.codes.map(c => `[${c}](https://world.openfoodfacts.org/product/${c})`).join(' ')} |`).join('\n') || '| – | 0 | |';
  const pct = (a, b) => (b ? Math.round((a / b) * 100) + ' %' : '–');
  const md = `# Label Check – accuracy check

Date: ${new Date().toISOString().slice(0, 10)} · Products with an ingredient list: **${stat.products}**

Open Food Facts makes its tags with its own text reader. A difference is a thing to look at, not proof of an error.

| | Same | Only Open Food Facts (we missed?) | Only Label Check (wrong hit?) |
|---|---|---|---|
| Additives (E-numbers) | ${stat.addSame} (${pct(stat.addSame, stat.addSame + stat.addMissed)}) | ${stat.addMissed} | ${stat.addExtra} |
| EU allergens | ${stat.algSame} (${pct(stat.algSame, stat.algSame + stat.algMissed)}) | ${stat.algMissed} | ${stat.algExtra} |

## By label language
| Language | Products | Additives missed | Additives extra |
|---|---|---|---|
${Object.entries(byLang).sort((a, b) => b[1].products - a[1].products).map(([l, v]) => `| ${l} | ${v.products} | ${v.missed} | ${v.extra} |`).join('\n')}

## Additives only Open Food Facts found (top 30)
| E-number | Times | Examples |
|---|---|---|
${top(missed, 30)}

## Additives only Label Check found (top 30, with the matched words)
| E-number (words) | Times | Examples |
|---|---|---|
${top(extra, 30)}

## Allergens only Open Food Facts found (top 20)
| Allergen [label language] | Times | Examples |
|---|---|---|
${top(algMissed, 20)}

## Allergens only Label Check found (top 20, with the matched word)
| Allergen (word) | Times | Examples |
|---|---|---|
${top(algExtra, 20)}
`;
  fs.writeFileSync(out, md);
  console.log(JSON.stringify(stat));
})();
