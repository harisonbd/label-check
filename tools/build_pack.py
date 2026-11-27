"""Build the offline product packs from the Open Food Facts / Open Beauty Facts CSV exports.

Runs once a month in GitHub Actions (.github/workflows/pack.yml). It can also run on a PC:
    python3 tools/build_pack.py off.csv.gz obf.csv.gz out/

Input: the CSV exports (gzip, tab separated, UTF-8), see https://world.openfoodfacts.org/data
Output (in out/):
    pack-main.ndjson.gz  products sold in Austria, Bulgaria, Romania or Slovakia (with and without ingredients)
    pack-de.ndjson.gz    products sold in Germany and not in the main pack (only those with ingredients, to keep it small)
    pack-hu/cz/hr/it.ndjson.gz  the same for Hungary, Czechia, Croatia, Italy (v2.44). A product sold in two of these countries is
                         in both files, so each country file is complete without the others.
    pack-info.json       date, file sizes and counts (the app reads this first)
    README.md            source and licence (ODbL)
File format: line 1 = {"v":1,"part":...,"date":...,"n":...}; every other line = one product:
    [code, kind ("f" food / "c" cosmetic), name, brand, ingredients, allergens, traces, additives]
    allergens / traces = tag ids without "en:" (milk,gluten), additives = e-numbers (e330,e322). Empty fields at the end are left out.
"""
import csv, gzip, io, json, os, re, sys, time

MAIN = {'en:austria', 'en:bulgaria', 'en:romania', 'en:slovakia'}
# v2.44: one file per extra country (only products with ingredients, and not those already in the main pack)
EXTRA = {'de': {'en:germany'}, 'hu': {'en:hungary'}, 'cz': {'en:czech-republic', 'en:czechia'}, 'hr': {'en:croatia'}, 'it': {'en:italy'}}
MAX_INGR = 3000
CODE_RE = re.compile(r'^\d{8,14}$')
TAG_RE = re.compile(r'en:([a-z0-9-]+)')
E_RE = re.compile(r'en:(e\d{3,4}[a-z]?)\b')
WS_RE = re.compile(r'\s+')


def col(header, *names):
    for n in names:
        if n in header:
            return header.index(n)
    return None


def tags(value, rx=TAG_RE):
    seen = []
    for m in rx.findall(value or ''):
        if m not in seen:
            seen.append(m)
    return ','.join(seen)


def read_export(path, kind, packs, stats):
    csv.field_size_limit(1 << 30)
    with gzip.open(path, 'rt', encoding='utf-8', errors='replace', newline='') as f:
        rd = csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE)
        header = next(rd)
        c = {k: col(header, *v) for k, v in {
            'code': ('code',), 'name': ('product_name',), 'generic': ('generic_name',), 'brand': ('brands',),
            'countries': ('countries_tags', 'countries'), 'ingr': ('ingredients_text',),
            'allergens': ('allergens_tags', 'allergens'), 'traces': ('traces_tags', 'traces'), 'additives': ('additives_tags', 'additives')}.items()}
        missing = [k for k in ('code', 'countries', 'ingr') if c[k] is None]
        if missing:
            sys.exit('%s: columns missing: %s\nHeader: %s' % (path, missing, header))
        width = len(header)
        get = lambda row, k: row[c[k]] if c[k] is not None and c[k] < len(row) else ''
        for row in rd:
            stats['rows'] += 1
            if len(row) != width:             # a broken line (stray tab or newline in a field): the columns would be wrong
                stats['bad'] += 1
                continue
            countries = set(TAG_RE.findall(get(row, 'countries')))
            countries = {'en:' + x for x in countries}
            parts = ['main'] if countries & MAIN else [p for p, tags_ in EXTRA.items() if tags_ & countries]
            if not parts:
                continue
            code = get(row, 'code').strip()
            if not CODE_RE.match(code):
                continue
            ingr = WS_RE.sub(' ', get(row, 'ingr')).strip()[:MAX_INGR]
            name = WS_RE.sub(' ', get(row, 'name') or get(row, 'generic')).strip()[:120]
            if parts != ['main'] and not ingr:
                continue
            if not ingr and not name:
                continue
            rec = [code, kind, name, get(row, 'brand').split(',')[0].strip()[:60], ingr,
                   tags(get(row, 'allergens')), tags(get(row, 'traces')), tags(get(row, 'additives'), E_RE)]
            while rec and rec[-1] == '':
                rec.pop()
            for part in parts:
                old = packs[part].get(code)
                # the same barcode twice (food and cosmetic export): keep the one with ingredients
                if old is None or (not (len(old) > 4 and old[4]) and ingr):
                    packs[part][code] = rec
    return stats


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    off, obf, out = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out, exist_ok=True)
    date = os.environ.get('PACK_DATE') or time.strftime('%Y-%m-%d', time.gmtime())
    packs = dict([('main', {})] + [(p, {}) for p in EXTRA])
    stats = {'rows': 0, 'bad': 0}
    read_export(off, 'f', packs, stats)
    if obf and obf != '-' and os.path.exists(obf):
        read_export(obf, 'c', packs, stats)
    for part in EXTRA:
        for code in list(packs[part]):
            if code in packs['main']:
                del packs[part][code]
    info = {'v': 1, 'date': date, 'source': 'Open Food Facts and Open Beauty Facts, Open Database License (ODbL) 1.0', 'parts': {}}
    for part, items in packs.items():
        fn = 'pack-%s.ndjson.gz' % part
        path = os.path.join(out, fn)
        recs = sorted(items.values())
        with gzip.open(path, 'wt', encoding='utf-8', compresslevel=9) as f:
            f.write(json.dumps({'v': 1, 'part': part, 'date': date, 'n': len(recs)}, ensure_ascii=False) + '\n')
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, separators=(',', ':')) + '\n')
        info['parts'][part] = {'file': fn, 'bytes': os.path.getsize(path), 'n': len(recs), 'ni': sum(1 for r in recs if len(r) > 4 and r[4]),
                               'cosmetic': sum(1 for r in recs if r[1] == 'c')}
    with open(os.path.join(out, 'pack-info.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('# Label Check offline product pack (%s)\n\nBuilt by .github/workflows/pack.yml on the main branch. This branch is replaced every month.\n\n'
                'Contains data from Open Food Facts (https://world.openfoodfacts.org) and Open Beauty Facts (https://world.openbeautyfacts.org), '
                'available under the Open Database License (ODbL) 1.0 (https://opendatacommons.org/licenses/odbl/1-0/). '
                'Individual contents: Database Contents License (DbCL) 1.0. This pack is a derived database and is shared under the same licence.\n' % date)
    print(json.dumps({'stats': stats, 'parts': info['parts']}, indent=1))


if __name__ == '__main__':
    main()
