#!/usr/bin/env python3
"""Learning loop (v2.22): turn the files the app sends to Claude into bench material.
Usage: python3 tools/ingest_report.py <report.txt|report.json> [more files] --out <folder>
For each report it writes, into <folder>:
  <id>_1.jpg, <id>_2.jpg ...   the label photos
  <id>.truth.json              what the app read, its verdict, and an empty "truth" list
                               (fill "truth" with the real ingredient names read from the photo)
The photo bench then compares the app's names with "truth"."""
import sys, json, base64, os, re

def load(path):
    raw = open(path, encoding='utf-8').read()
    i = raw.find('{')
    return json.loads(raw[i:])      # the note for Claude sits before the first "{"

def main(argv):
    if '--out' not in argv or len(argv) < 4:
        print(__doc__); return 2
    out = argv[argv.index('--out') + 1]
    files = [a for a in argv[1:] if a != '--out' and a != out]
    os.makedirs(out, exist_ok=True)
    for f in files:
        d = load(f)
        base = re.sub(r'\.(txt|json)$', '', os.path.basename(f)).replace('label-check-for-claude-', 'rep-').replace('label-check-report-', 'rep-')
        n = 0
        for ph in d.get('photos', []) or []:
            m = re.match(r'data:image/\w+;base64,(.*)', ph, re.S)
            if not m: continue
            n += 1
            open(os.path.join(out, '%s_%d.jpg' % (base, n)), 'wb').write(base64.b64decode(m.group(1)))
        info = {k: d.get(k) for k in ('version', 'kind', 'verdict', 'summary', 'known', 'unknown', 'weak', 'noList', 'text', 'name', 'guess')}
        info['rows'] = [r.get('text') for r in d.get('rows', [])]
        info['photos'] = n
        info['truth'] = []
        json.dump(info, open(os.path.join(out, base + '.truth.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('%s: %d photo(s), %d rows' % (base, n, len(info['rows'])))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
