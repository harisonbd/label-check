#!/usr/bin/env python3
"""Label Check – download the raw sources for build_db.py.

Used by the monthly GitHub Action (.github/workflows/update-db.yml). It does the same as the
browser steps in tools/FETCH.md, but from a server:
  1 EU CosIng (cosmetics)        -> lc-cosing-ingredients.json, lc-cosing-substances.json, lc-cosing-range9.json
  2 EU endocrine disruptor lists -> lc-edlists.json
  3 IARC list of classifications -> copied from tools/iarc/lc-iarc.csv (the IARC site has no file link a
                                    server can use; update that file by hand, see FETCH.md step 3)
  4 EU food additives database   -> lc-fad.json
  5 Open Food Facts taxonomies   -> additives.txt, additives_classes.txt, allergens.txt
It stops with an error if a download looks incomplete, so a bad download never reaches the app.
Run:  python3 tools/fetch_sources.py _sources
"""
import json, os, shutil, sys, time, urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

OUT = sys.argv[1] if len(sys.argv) > 1 else '_sources'
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'label-check-database-update (https://github.com/harisonbd/label-check)'}
NOW = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def get(url, data=None, headers=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # network hiccup: wait and try again
            if i == tries - 1:
                raise RuntimeError(f'Download failed: {url}: {e}')
            time.sleep(10 * (i + 1))


def save(name, obj):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


def check(cond, msg):
    if not cond:
        raise SystemExit('STOP: ' + msg)


# ---------------------------------------------------------------- 1 CosIng
API = ('https://webgate.ec.europa.eu/es/search-api/rest/search'
       '?apiKey=285a77fd-1257-4271-8507-f0c6b2961203&text=*&pageSize={size}&pageNumber={page}')
SKIP = {'url', 'datasource', 'language', 'corporate-search-version', 'reference', 'currentVersion'}


def cosing_query(query, size, page):
    b = '----labelcheck' + str(int(time.time() * 1000))
    body = (f'--{b}\r\nContent-Disposition: form-data; name="query"; filename="blob"\r\n'
            f'Content-Type: application/json\r\n\r\n{json.dumps(query)}\r\n--{b}--\r\n').encode()
    return json.loads(get(API.format(size=size, page=page), data=body,
                          headers={'Content-Type': 'multipart/form-data; boundary=' + b}))


def pick(meta):
    out = {}
    for k, v in (meta or {}).items():
        if k.startswith('es') or k in SKIP:
            continue
        vals = [x for x in (v if isinstance(v, list) else [v]) if x not in ('<empty>', '', '[]', None)]
        if vals:
            out[k] = vals[0] if len(vals) == 1 else vals
    return out


def cosing_all(item_type):
    # The API returns at most 10,000 rows per query, so split by the first digit of substanceId.
    out = []
    for d in range(1, 10):
        rng = {'gte': str(d), 'lt': str(d + 1)} if d < 9 else {'gte': '9', 'lte': '99999999'}
        for page in range(1, 51):
            j = cosing_query({'bool': {'must': [{'term': {'itemType': item_type}}, {'range': {'substanceId': rng}}]}}, 200, page)
            rows = j.get('results') or []
            out += [pick(x.get('metadata')) for x in rows]
            if len(rows) < 200:
                break
    return out


# ---------------------------------------------------------------- 2 ED lists (HTML tables)
ED_URLS = {
    'I': '/the-ed-lists/list-i-substances-identified-as-endocrine-disruptors-by-the-eu',
    'II': '/the-ed-lists/list-ii-substances-under-eu-investigation-endocrine-disruption',
    'III': '/the-ed-lists/list-iii-substances-identified-as-endocrine-disruptors-by-participating-national-authorities',
}


class FirstTable(HTMLParser):
    """Reads the first <table>: header texts, row cell texts, and the first link in each row."""

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.depth, self.done = base, 0, False
        self.part, self.cell, self.row, self.link = None, None, None, None
        self.heads, self.rows = [], []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == 'table':
            self.depth += 1
        elif self.depth and tag in ('thead', 'tbody'):
            self.part = tag
        elif self.depth and tag == 'tr':
            self.row, self.link = [], None
        elif self.depth and tag in ('th', 'td'):
            self.cell = ''
        elif self.depth and tag == 'a' and self.row is not None and self.link is None:
            href = dict(attrs).get('href')
            if href:
                self.link = urljoin(self.base, href)

    def handle_endtag(self, tag):
        if self.done or not self.depth:
            return
        if tag in ('th', 'td') and self.cell is not None:
            if self.part == 'thead':
                self.heads.append(self.cell.strip().split('\n')[0].strip())
            elif self.row is not None:
                self.row.append(' '.join(self.cell.split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.part != 'thead' and self.row:
                o = {h: (self.row[i] if i < len(self.row) else '') for i, h in enumerate(self.heads)}
                if self.link:
                    o['link'] = self.link
                self.rows.append(o)
            self.row = None
        elif tag == 'table':
            self.depth -= 1
            self.done = self.depth == 0

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data


def ed_lists():
    base = 'https://edlists.org'
    out = {'fetched': NOW, 'source': base + '/the-ed-lists', 'lists': {}}
    for k, path in ED_URLS.items():
        p = FirstTable(base + path)
        p.feed(get(base + path).decode('utf-8', 'replace'))
        out['lists'][k] = p.rows
    return out


# ---------------------------------------------------------------- 4 EU food additives
FAD_KEEP = ['policyItemCode', 'policyItemType', 'policyItemStatus', 'identifyingName', 'displayName', 'eNumber',
            'memberOfFADGroup', 'groupMemberRefs', 'policyItemMessageText', 'policyItemNoteText', 'synonyms', 'insNumber']


def flat(node, acc):
    if node.get('valueIdentifier') and node.get('value') is not None:
        acc.setdefault(node['valueIdentifier'], []).append(node['value'])
    for c in node.get('childrenValues') or []:
        flat(c, acc)
    return acc


def fad():
    url = 'https://ec.europa.eu/food/food-feed-portal/backend/api/policy-items?foodDomain=fin&authorisationType=fad_auth'
    items = []
    for it in json.loads(get(url, headers={'Accept': 'application/json'})):
        g, o = flat(it, {}), {}
        for k in FAD_KEEP:
            if g.get(k):
                o[k] = ' | '.join(dict.fromkeys(str(v) for v in g[k]))
        items.append(o)
    return {'fetched': NOW, 'items': items}


# ---------------------------------------------------------------- run
def main():
    os.makedirs(OUT, exist_ok=True)
    fetched = {}

    print('1 CosIng …', flush=True)
    subs, ings = cosing_all('substance'), cosing_all('ingredient')
    print(f'  {len(ings)} ingredients, {len(subs)} substances')
    check(len(ings) > 30000 and len(subs) > 2000, 'CosIng download looks incomplete')
    save('lc-cosing-substances.json', {'fetched': NOW, 'items': subs})
    save('lc-cosing-ingredients.json', {'fetched': NOW, 'items': ings})
    save('lc-cosing-range9.json', {'fetched': NOW, 'substances': [], 'ingredients': []})
    fetched['cosing'] = NOW

    print('2 ED lists …', flush=True)
    ed = ed_lists()
    sizes = {k: len(v) for k, v in ed['lists'].items()}
    print('  ', sizes)
    check(all(n >= 10 for n in sizes.values()), 'an ED list is empty or too short')
    save('lc-edlists.json', ed)
    fetched['ed'] = NOW

    print('3 IARC (kept file) …', flush=True)
    shutil.copyfile(os.path.join(HERE, 'iarc', 'lc-iarc.csv'), os.path.join(OUT, 'lc-iarc.csv'))
    with open(os.path.join(HERE, 'iarc', 'FETCHED.txt'), encoding='utf-8') as f:
        fetched['iarc'] = f.read().strip()

    print('4 EU food additives …', flush=True)
    f = fad()
    print(f'  {len(f["items"])} items')
    check(len(f['items']) > 300, 'food additive download looks incomplete')
    save('lc-fad.json', f)
    fetched['fad'] = NOW

    print('5 Open Food Facts taxonomies …', flush=True)
    raw = 'https://raw.githubusercontent.com/openfoodfacts/openfoodfacts-server/main/taxonomies/'
    for name in ('additives.txt', 'additives_classes.txt', 'allergens.txt'):
        data = get(raw + name)
        check(len(data) > 50000 or (name == 'allergens.txt' and len(data) > 20000), name + ' looks too small')
        with open(os.path.join(OUT, name), 'wb') as fh:
            fh.write(data)
    fetched['off'] = NOW

    save('fetched.json', fetched)
    print('All sources downloaded.')


if __name__ == '__main__':
    main()
