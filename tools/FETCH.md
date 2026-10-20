# Update the database sources

The EU sites work only in a normal browser (Claude's built-in browser works). Each step saves a file to Downloads.
Then move the files to `_sources/` and run:

```
python3 -I tools/build_db.py _sources data
node tools/test_db.js
```
After a data change, raise `VERSION` in `sw.js`.

## 1. CosIng (cosmetics) – open https://ec.europa.eu/growth/tools-databases/cosing/ and run in the console

```js
const cq = async (query, size, page) => { const fd = new FormData(); fd.append('query', new Blob([JSON.stringify(query)], {type: 'application/json'}));
  return (await fetch(`https://webgate.ec.europa.eu/es/search-api/rest/search?apiKey=285a77fd-1257-4271-8507-f0c6b2961203&text=*&pageSize=${size}&pageNumber=${page}`, {method: 'POST', body: fd})).json(); };
const pick = m => { const o = {}; for (const [k, v] of Object.entries(m)) { if (k.startsWith('es') || ['url','datasource','language','corporate-search-version','reference','currentVersion'].includes(k)) continue;
  const vv = (v || []).filter(s => s !== '<empty>' && s !== '' && s !== '[]'); if (vv.length) o[k] = vv.length === 1 ? vv[0] : vv; } return o; };
const dl = (name, data) => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(data)])); a.download = name; a.click(); };
// The API returns at most 10,000 rows per query, so split by the first digit of substanceId.
const all = async type => { const out = []; for (let d = 1; d <= 9; d++) { const rg = d < 9 ? {gte: '' + d, lt: '' + (d + 1)} : {gte: '9', lte: '99999999'};
  for (let p = 1; p <= 50; p++) { const j = await cq({bool: {must: [{term: {itemType: type}}, {range: {substanceId: rg}}]}}, 200, p);
    const r = j.results || []; r.forEach(x => out.push(pick(x.metadata))); if (r.length < 200) break; } } return out; };
const subs = await all('substance'), ings = await all('ingredient');
dl('lc-cosing-substances.json', {fetched: new Date().toISOString(), items: subs});
dl('lc-cosing-ingredients.json', {fetched: new Date().toISOString(), items: ings});
dl('lc-cosing-range9.json', {fetched: new Date().toISOString(), substances: [], ingredients: []}); // kept for the build script
```
Check: about 33,700 ingredients and 2,400 substances.

## 2. ED lists – open https://edlists.org/the-ed-lists and run

```js
const urls = {I: '/the-ed-lists/list-i-substances-identified-as-endocrine-disruptors-by-the-eu', II: '/the-ed-lists/list-ii-substances-under-eu-investigation-endocrine-disruption', III: '/the-ed-lists/list-iii-substances-identified-as-endocrine-disruptors-by-participating-national-authorities'};
const out = {fetched: new Date().toISOString(), lists: {}};
for (const [k, u] of Object.entries(urls)) { const d = new DOMParser().parseFromString(await (await fetch(u)).text(), 'text/html'); const t = d.querySelector('table');
  const heads = [...t.querySelectorAll('thead th')].map(x => x.textContent.trim().split('\n')[0].trim());
  out.lists[k] = [...t.querySelectorAll('tbody tr')].map(tr => { const c = [...tr.children].map(x => x.textContent.trim().replace(/\s+/g, ' ')); const o = {}; heads.forEach((h, i) => o[h] = c[i]); const a = tr.querySelector('a'); if (a) o.link = a.href; return o; }); }
const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(out)])); a.download = 'lc-edlists.json'; a.click();
```

## 3. IARC – open https://monographs.iarc.who.int/list-of-classifications/ and click "CSV". Rename the file to `lc-iarc.csv`.

## 4. EU food additives – open https://ec.europa.eu/food/food-feed-portal/screen/food-additives/search and run

```js
const j = await (await fetch('/food/food-feed-portal/backend/api/policy-items?foodDomain=fin&authorisationType=fad_auth')).json();
const flat = (n, acc) => { if (n.valueIdentifier && n.value != null) (acc[n.valueIdentifier] = acc[n.valueIdentifier] || []).push(n.value); for (const c of n.childrenValues || []) flat(c, acc); return acc; };
const keep = ['policyItemCode','policyItemType','policyItemStatus','identifyingName','displayName','eNumber','memberOfFADGroup','groupMemberRefs','policyItemMessageText','policyItemNoteText','synonyms','insNumber'];
const items = j.map(it => { const g = flat(it, {}); const o = {}; keep.forEach(k => { if (g[k]) o[k] = [...new Set(g[k])].join(' | '); }); return o; });
const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({fetched: new Date().toISOString(), items})])); a.download = 'lc-fad.json'; a.click();
```

## 5. Open Food Facts – download `additives.txt`, `additives_classes.txt`, `allergens.txt` from
https://github.com/openfoodfacts/openfoodfacts-server/tree/main/taxonomies
