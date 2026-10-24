"""Builds data/names-food.json: plain food ingredient names in several languages (for "does the app know this name?").
Source: Open Food Facts taxonomies (ingredients.txt and additives.txt), licence ODbL: https://world.openfoodfacts.org/data
Run:  python tools/build_names.py <openfoodfacts-server>/taxonomies  data/names-food.json
Names are normalised exactly like norm() in db.js."""
import sys, json, re, unicodedata, os
LANGS = ['en', 'de', 'bg', 'fr', 'it', 'es', 'hr', 'cs', 'sk', 'sl', 'hu', 'ro', 'pl', 'sr', 'mk']
def norm(s):                       # same rule as norm() in db.js
    s = s.lower().replace('ß', 'ss').replace('ё', 'е')
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9а-я]+', ' ', s).strip()
def read(path):
    out = set()
    for line in open(path, encoding='utf-8'):
        m = re.match(r'^([a-z]{2,3}):\s*(.+)$', line.rstrip('\n'))
        if not m or m.group(1) not in LANGS: continue
        for part in m.group(2).split(','):
            part = re.sub(r'\s*\(.*?\)\s*', ' ', part)         # no "(note)" parts
            n = norm(part)
            if len(n) >= 4 and not re.fullmatch(r'[\d ]+', n) and len(n.split()) <= 5 and not re.match(r'^e\d{3}', n):
                out.add(n)
    return out
src, dst = sys.argv[1], sys.argv[2]
names = read(os.path.join(src, 'food', 'ingredients.txt')) if os.path.exists(os.path.join(src, 'food', 'ingredients.txt')) else read(os.path.join(src, 'ingredients.txt'))
names |= read(os.path.join(src, 'additives.txt'))
names = sorted(names)
json.dump({'v': 1, 'source': 'Open Food Facts ingredients and additives taxonomies (ODbL)', 'n': len(names), 'names': names}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(len(names), 'names', os.path.getsize(dst), 'bytes')
