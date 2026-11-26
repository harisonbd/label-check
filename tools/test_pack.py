"""Checks tools/build_pack.py on a small made-up export (same columns as the real CSV). Run: python3 tools/test_pack.py"""
import gzip, json, os, subprocess, sys, tempfile
HEAD = ['code', 'url', 'creator', 'created_t', 'product_name', 'abbreviated_product_name', 'generic_name', 'quantity', 'brands', 'brands_tags',
        'categories', 'categories_tags', 'countries', 'countries_tags', 'countries_en', 'ingredients_text', 'ingredients_tags', 'allergens', 'allergens_en',
        'traces', 'traces_tags', 'traces_en', 'additives_n', 'additives', 'additives_tags', 'additives_en', 'main_category']
def row(**k):
    return '\t'.join(k.get(h, '') for h in HEAD)
fails = []
def ok(c, m):
    print(('  ok   ' if c else '  FAIL ') + m)
    if not c: fails.append(m)
with tempfile.TemporaryDirectory() as d:
    off = os.path.join(d, 'off.csv.gz'); obf = os.path.join(d, 'obf.csv.gz'); out = os.path.join(d, 'out')
    rows = [
        row(code='9001234567890', product_name='Kekse  Vollkorn', brands='Manner, Neapolitaner', countries_tags='en:austria,en:germany',
            ingredients_text='Weizenmehl, Zucker,\n Palmfett, Emulgator: Lecithine (Soja)', allergens='en:gluten,en:soybeans', traces_tags='en:milk,en:nuts',
            additives_tags='en:e322,en:e322i'),
        row(code='3800123456789', product_name='Лютеница', countries_tags='en:bulgaria'),                                  # name only
        row(code='4000000000017', product_name='Brot', countries_tags='en:germany', ingredients_text='Roggenmehl, Wasser, Salz'),
        row(code='4000000000024', product_name='Nur Name DE', countries_tags='en:germany'),                               # DE without ingredients: left out
        row(code='12ab', product_name='bad code', countries_tags='en:austria', ingredients_text='x'),
        row(code='5900000000000', product_name='Polish only', countries_tags='en:poland', ingredients_text='mąka'),
        row(code='5940000000001', product_name='Biscuiți', countries_tags='en:romania', ingredients_text='făină de grâu, zahăr, ouă', allergens='en:gluten,en:eggs'),
        'only\tthree\tfields',
    ]
    with gzip.open(off, 'wt', encoding='utf-8') as f:
        f.write('\t'.join(HEAD) + '\n' + '\n'.join(r.replace('\n ', ' ') for r in rows) + '\n')
    with gzip.open(obf, 'wt', encoding='utf-8') as f:
        f.write('\t'.join(HEAD) + '\n' + row(code='9008700000000', product_name='Duschgel', countries_tags='en:austria', ingredients_text='Aqua, Sodium Laureth Sulfate, Parfum, Limonene') + '\n')
    env = dict(os.environ, PACK_DATE='2026-12-02')
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'build_pack.py'), off, obf, out], capture_output=True, text=True, env=env)
    ok(r.returncode == 0, 'build_pack.py runs (%s)' % r.stderr.strip()[-200:])
    info = json.load(open(os.path.join(out, 'pack-info.json')))
    ok(info['date'] == '2026-12-02' and 'ODbL' in info['source'], 'pack-info.json: date and licence')
    def load(fn):
        with gzip.open(os.path.join(out, fn), 'rt', encoding='utf-8') as f:
            lines = [json.loads(l) for l in f if l.strip()]
        return lines[0], {x[0]: x for x in lines[1:]}
    hm, main = load('pack-main.ndjson.gz'); hd, de = load('pack-de.ndjson.gz')
    ok(hm == {'v': 1, 'part': 'main', 'date': '2026-12-02', 'n': 4} and sorted(main) == ['3800123456789', '5940000000001', '9001234567890', '9008700000000'], 'main pack: AT, BG, RO + the cosmetic (%s)' % sorted(main))
    k = main['9001234567890']
    ok(k == ['9001234567890', 'f', 'Kekse Vollkorn', 'Manner', 'Weizenmehl, Zucker, Palmfett, Emulgator: Lecithine (Soja)', 'gluten,soybeans', 'milk,nuts', 'e322,e322i'], 'record: spaces tidied, first brand, allergens, traces, additives (%s)' % k)
    ok(main['3800123456789'] == ['3800123456789', 'f', 'Лютеница'], 'name-only product: short record, Cyrillic kept')
    ok(main['9008700000000'][1] == 'c', 'cosmetic from Open Beauty Facts has kind "c"')
    ok(sorted(de) == ['4000000000017'] and hd['n'] == 1, 'Germany pack: only German products with ingredients, not those already in the main pack')
    ok(info['parts']['main']['n'] == 4 and info['parts']['main']['ni'] == 3 and info['parts']['main']['bytes'] > 0 and info['parts']['main']['cosmetic'] == 1, 'pack-info counts (%s)' % info['parts']['main'])
    ok('"bad": 1' in r.stdout, 'a broken line is counted and skipped')
    ok('ODbL' in open(os.path.join(out, 'README.md')).read(), 'README.md names the licence')
print('ALL PASSED' if not fails else '%d FAILED' % len(fails))
sys.exit(1 if fails else 0)
