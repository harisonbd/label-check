// Label Check v2 – database tests. Run from the repo root:  node tools/test_db.js
const fs = require('fs');
const path = require('path');
const LCDB = require(path.join(__dirname, '..', 'db.js'));

const base = path.join(__dirname, '..', 'data') + path.sep;
let fails = 0;
const ok = (cond, msg) => { if (!cond) { fails++; console.log('  FAIL: ' + msg); } };

(async () => {
  const info = await LCDB.load(base, async f => JSON.parse(fs.readFileSync(f, 'utf8')));
  console.log('Loaded', info);

  const cos = (label, lang) => {
    const rows = LCDB.checkCosmetic(label, lang);
    for (const r of rows) {
      console.log(`  #${r.pos} ${r.level} ${r.found ? r.name : '(not found) ' + r.text}${r.fragrance ? ' [fragrance]' : ''}${r.allergen ? ' [allergen ' + r.allergenRef + ']' : ''}${r.nano ? ' [nano]' : ''}${r.mayContain ? ' [may contain]' : ''}`
        + (r.reasons && r.reasons[0] ? '\n      ' + r.reasons[0].text : ''));
    }
    const by = n => rows.find(r => r.name === n);
    return { rows, by };
  };
  const food = (label, lang) => {
    const res = LCDB.checkFood(label, lang);
    for (const a of res.additives) console.log(`  #${a.pos} ${a.level} ${a.e} ${a.name} (matched "${a.matched}")` + (a.reasons[0] ? '\n      ' + a.reasons[0].text : ''));
    console.log('  allergens:', res.allergens.map(a => a.id + ' ("' + a.matched + '")').join(', '));
    console.log('  rules:', res.rules.map(r => r.id + ' ("' + r.matched + '")').join(', '));
    const e = code => res.additives.find(a => a.e === code);
    return { res, e, al: id => res.allergens.some(a => a.id === id) };
  };

  console.log('\n1 Shower gel (EN)');
  let t = cos('Ingredients: Aqua (Water), Sodium Laureth Sulfate, Cocamidopropyl Betaine, Sodium Chloride, Parfum (Fragrance), Glycerin, Citric Acid, Sodium Benzoate, Limonene, Linalool, CI 19140, CI 42090, Methylisothiazolinone, Butylphenyl Methylpropional', 'en');
  ok(t.by('AQUA') && t.by('AQUA').level === 'n', 'aqua found, no concerns');
  ok(t.by('PARFUM') && t.by('PARFUM').fragrance, 'parfum = fragrance');
  ok(t.by('LIMONENE') && t.by('LIMONENE').allergen && t.by('LIMONENE').level === 'r', 'limonene = labelled allergen, restricted');
  ok(t.by('METHYLISOTHIAZOLINONE').level === 'c', 'MI = concern');
  ok(t.by('BUTYLPHENYL METHYLPROPIONAL').level === 'b', 'lilial = banned');
  ok(t.rows.every(r => r.found), 'all 14 found');
  ok(t.by('CITRIC ACID').level === 'n', 'citric acid not restricted (silver citrate entry skipped)');

  console.log('\n1b Nano-only bans');
  t = cos('Aqua, Styrene/Acrylates Copolymer, Colloidal Gold', 'en');
  ok(t.by('STYRENE/ACRYLATES COPOLYMER').level !== 'b' && t.by('COLLOIDAL GOLD').level !== 'b', 'normal forms not banned');
  t = cos('Aqua, Styrene/Acrylates Copolymer (nano), Colloidal Gold [nano]', 'en');
  ok(t.by('STYRENE/ACRYLATES COPOLYMER').level === 'b' && t.by('COLLOIDAL GOLD').level === 'b', 'nano forms banned');

  console.log('\n2 Sunscreen (EN, nano, comma inside a name)');
  t = cos('AQUA, HOMOSALATE, ETHYLHEXYL SALICYLATE, BUTYL METHOXYDIBENZOYLMETHANE, OCTOCRYLENE, TITANIUM DIOXIDE (NANO), CYCLOPENTASILOXANE, 2-BROMO-2-NITROPROPANE-1,3-DIOL, TALC, PROPYLPARABEN, BHT, ALCOHOL DENAT., TOCOPHEROL', 'en');
  ok(t.rows.length === 13, '13 ingredients (1,3-diol not split), got ' + t.rows.length);
  ok(t.by('TITANIUM DIOXIDE') && t.by('TITANIUM DIOXIDE').nano && t.by('TITANIUM DIOXIDE').level === 'c', 'TiO2 nano, concern');
  ok(t.by('CYCLOPENTASILOXANE').level === 'u', 'D5 under review');
  ok(t.by('2-BROMO-2-NITROPROPANE-1,3-DIOL').level === 'c', 'bronopol concern');
  ok(t.by('PROPYLPARABEN').level === 'u', 'propylparaben under review');
  ok(t.by('ALCOHOL DENAT.').level === 'n', 'alcohol denat. no IARC beverage flag');

  console.log('\n3 Cream (DE label word, may contain)');
  t = cos('Inhaltsstoffe: Aqua, Paraffinum Liquidum, Cetearyl Alcohol, Glycerin, Petrolatum, Phenoxyethanol, Ethylhexylglycerin, Parfum, Benzyl Alcohol, Citral, Hexyl Cinnamal [+/- CI 77891, CI 77491]', 'de');
  ok(t.by('AQUA'), 'label word removed');
  ok(t.by('PETROLATUM').level === 'r', 'petrolatum restricted (refined only)');
  ok(t.by('CI 77891') && t.by('CI 77891').mayContain, 'CI 77891 may contain');
  ok(t.by('CITRAL').allergen, 'citral allergen');
  ok(t.by('PHENOXYETHANOL').reasons[0].text.includes('Anhang V'), 'German reason text');

  console.log('\n4 Shampoo (BG label word, alias, unknown)');
  t = cos('Състав: Aqua, Sodium Lauryl Sulfate, Prunus Amygdalus Dulcis (Sweet Almond) Oil, Zinc Pyrithione, Lilial, Unknownium Extract', 'bg');
  ok(t.by('AQUA'), 'BG label word removed');
  ok(t.rows.filter(r => r.level === 'b').length === 2, 'zinc pyrithione + lilial banned');
  ok(t.by('PRUNUS AMYGDALUS DULCIS OIL'), 'sweet almond oil found');
  ok(t.rows.some(r => !r.found && /unknownium/i.test(r.text)), 'unknown kept as not found');
  ok(/Приложение/.test(t.by('ZINC PYRITHIONE').reasons[0].text), 'Bulgarian reason text');

  console.log('\n5 Biscuits (EN)');
  let f = food('Ingredients: Sugar, wheat flour (gluten), palm oil, cocoa butter, whole milk powder, emulsifier (soy lecithin), E471, raising agents (E450, E500), colour: E129, E102, preservative: sodium nitrite, sweetener: aspartame, partially hydrogenated vegetable oil, titanium dioxide', 'en');
  ok(f.e('E129').level === 'c' && f.e('E102').level === 'c', 'southampton colours concern');
  ok(f.e('E250') && f.e('E250').level === 'c', 'sodium nitrite by name');
  ok(f.e('E951') && f.e('E951').level === 'c', 'aspartame concern');
  ok(f.e('E171') && f.e('E171').level === 'b', 'titanium dioxide banned in food');
  ok(f.e('E450') && f.e('E450').reasons.some(r => r.text.includes('EFSA')), 'E450 EFSA note');
  ok(f.res.rules.some(r => r.id === 'trans-fat'), 'trans fat rule');
  ok(f.al('gluten') && f.al('milk') && f.al('soybeans'), 'allergens gluten, milk, soy');
  ok(f.e('E322'), 'lecithin is E322 (variant merged)');

  console.log('\n6 Sausage (DE)');
  f = food('Zutaten: Schweinefleisch, Nitritpökelsalz (Speisesalz, Konservierungsstoff Natriumnitrit), Dextrose, Antioxidationsmittel: Ascorbinsäure, Gewürze, Senfsaat, Sellerie, Säuerungsmittel Citronensäure, Farbstoff E 120, Geschmacksverstärker Mononatriumglutamat, teilweise gehärtetes Pflanzenfett', 'de');
  ok(f.e('E250') && f.e('E250').level === 'c', 'Natriumnitrit');
  ok(f.e('E300') && f.e('E330') && f.e('E120') && f.e('E621'), 'Ascorbinsäure, Citronensäure, E 120, Glutamat');
  ok(f.al('mustard') && f.al('celery'), 'Senf + Sellerie allergens');
  ok(f.res.rules.some(r => r.id === 'trans-fat'), 'teilweise gehärtet rule');

  console.log('\n7 Chocolate wafer (BG)');
  f = food('Съставки: захар, пшенично брашно, растителна мазнина (палмова), сухо мляко, емулгатор: соев лецитин, лимонена киселина, консервант: калиев сорбат, оцветител: тартразин, подсладител: аспартам, частично хидрогенирани мазнини, лешници', 'bg');
  ok(f.e('E102') && f.e('E102').level === 'c', 'тартразин');
  ok(f.e('E951'), 'аспартам');
  ok(f.e('E202') && f.e('E202').level === 'n', 'калиев сорбат, no concerns (EFSA 2019)');
  ok(f.e('E330'), 'лимонена киселина');
  ok(f.res.rules.some(r => r.id === 'trans-fat'), 'частично хидрогенирани');
  ok(f.al('milk') && f.al('nuts'), 'мляко + лешници');

  console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
  process.exit(fails ? 1 : 0);
})();
