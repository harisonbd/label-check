import re
"""Label Check v2 – app test in a phone-size browser (390 x 844).
Run from the repo root:  python tools/test_app.py
Needs: pip install playwright && playwright install chromium
Starts a local web server, fakes the Open Food Facts answer, and checks the main screens.
Screenshots go to tools/shots/ (not for GitHub)."""
import json, os, re, sys, threading, http.server, functools
from playwright.sync_api import sync_playwright, Page

# v2.15: the text part of "Read a label" sits in a fold. Tests that type text open the fold first, as a person would.
def _wrap(name):
    orig = getattr(Page, name)
    def f(self, sel, *a, **k):
        if isinstance(sel, str) and (sel in ('#labelText', '#checkLabel') or sel.startswith('input[name=kind]')) \
                and self.evaluate("() => { const f = document.getElementById('textFold'); const l = document.getElementById('labelPanel'); return !!f && !l.hidden && !f.open; }"):
            self.evaluate("() => { const f = document.getElementById('textFold'); f.hidden = false; f.open = true; }")
        return orig(self, sel, *a, **k)
    setattr(Page, name, f)
for _n in ('fill', 'check', 'click'): _wrap(_n)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, 'tools', 'shots')
os.makedirs(SHOTS, exist_ok=True)

SHOWER = 'Ingredients: Aqua (Water), Sodium Laureth Sulfate, Cocamidopropyl Betaine, Sodium Chloride, Parfum (Fragrance), Glycerin, Citric Acid, Sodium Benzoate, Limonene, Linalool, CI 19140, CI 42090, Methylisothiazolinone, Butylphenyl Methylpropional'
SAUSAGE = 'Zutaten: Schweinefleisch, Nitritpökelsalz (Speisesalz, Konservierungsstoff Natriumnitrit), Dextrose, Antioxidationsmittel: Ascorbinsäure, Gewürze, Senfsaat, Sellerie, Säuerungsmittel Citronensäure, Farbstoff E 120, Geschmacksverstärker Mononatriumglutamat, teilweise gehärtetes Pflanzenfett'
WAFER = 'Съставки: захар, пшенично брашно, растителна мазнина (палмова), сухо мляко, емулгатор: соев лецитин, лимонена киселина, консервант: калиев сорбат, оцветител: тартразин, подсладител: аспартам, частично хидрогенирани мазнини, лешници'

fails, errors = [], []
def ok(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond: fails.append(msg)

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
    handler = functools.partial(Quiet, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

# v2.29: products with categories and the search answer ("Instead" from the same category)
ALT_SEARCHES = []
ALT_FAIL = {'n': 0}   # the next n searches answer 503, like Open Food Facts under load
def alt_prod(code, name, text, cats, extra=None):
    d = {'code': code, 'product_name': name, 'brands': 'Example', 'ingredients_text': text, 'categories_tags': cats}
    d.update(extra or {}); return d
SAUSAGE_CATS = ['en:meats', 'en:prepared-meats', 'en:sausages', 'de:wurst', 'en:salami']
ALT_PRODUCTS = {
    '9001234500001': alt_prod('9001234500001', 'Salami scharf', 'Schweinefleisch, Speck, Salz, Konservierungsstoff: Natriumnitrit, Gewürze', SAUSAGE_CATS, {'additives_tags': ['en:e250']}),
    '9001234500002': alt_prod('9001234500002', 'Paprikawurst', 'Schweinefleisch, Paprika, Salz, Konservierungsstoff: E250', SAUSAGE_CATS[:4], {'additives_tags': ['en:e250']}),
    '9001234500003': alt_prod('9001234500003', 'Bio Geflügelwurst', 'Putenfleisch 92 %, Wasser, Meersalz, Senf, Gewürze', SAUSAGE_CATS[:4]),
    '9001234500004': alt_prod('9001234500004', 'Leberkäse', '', SAUSAGE_CATS[:4]),
    '9001234500005': alt_prod('9001234500005', 'Bio Geflügelwurst', 'Putenfleisch 90 %, Wasser, Meersalz, Gewürze', SAUSAGE_CATS[:4]),
    '9001234500006': alt_prod('9001234500006', 'Putenwurst natur', 'Putenfleisch 95 %, Wasser, Meersalz, Pfeffer', SAUSAGE_CATS[:4]),
    '9001234500007': alt_prod('9001234500007', 'Kochschinken natur', 'Schweinefleisch 96 %, Wasser, Meersalz', ['en:meats', 'en:prepared-meats', 'en:hams']),
    '9001234500008': alt_prod('9001234500008', 'Schoko Riegel', 'Zucker, Kakaobutter, Konservierungsstoff: Natriumnitrit', ['en:snacks', 'en:sweet-snacks', 'en:chocolates']),
}
def fake_api(route):
    url = route.request.url
    if '/api/v2/search' in url:
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(url).query)
        cat = (q.get('categories_tags') or [''])[0]
        ALT_SEARCHES.append({'host': urlparse(url).hostname, 'cat': cat, 'countries': (q.get('countries_tags_en') or [''])[0], 'sort': (q.get('sort_by') or [''])[0]})
        if ALT_FAIL['n'] > 0:
            ALT_FAIL['n'] -= 1
            route.fulfill(status=503, content_type='text/html', body='<h1>Page temporarily unavailable</h1>')
            return
        hits = [p for p in ALT_PRODUCTS.values() if any(c in p['categories_tags'] for c in cat.split('|'))] if 'openfoodfacts' in url else []
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'count': len(hits), 'page': 1, 'page_count': len(hits), 'page_size': 24, 'skip': 0, 'products': hits}))
        return
    m = re.search(r'/product/(\d+)\.json', url)
    if 'openfoodfacts' in url and m and m.group(1) in ALT_PRODUCTS:
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': 1, 'product': ALT_PRODUCTS[m.group(1)]}))
        return
    if 'openfoodfacts' in url and '9001234567890' in url:
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': 1, 'product': {
            'product_name': 'Extrawurst', 'brands': 'Example', 'ingredients_text': SAUSAGE,
            'additives_tags': ['en:e250', 'en:e451'], 'allergens_tags': ['en:mustard', 'en:celery', 'en:milk'],
            'nutriscore_grade': 'd', 'nova_group': 4, 'nutriments': {'fat_100g': 24, 'saturated-fat_100g': 9.5, 'proteins_100g': 13}}}))
    else:
        route.fulfill(status=200, content_type='application/json', body='{"status":0}')


def force_tess(br):
    """v2.23: the old tests were written for the Tesseract reader; they keep using it. Paddle has its own tests at the end."""
    orig = br.new_context
    def nc(*a, **k):
        c = orig(*a, **k); c.add_init_script("try { localStorage.setItem('lc.ocrEngine', '\"tess\"'); } catch (e) {}"); return c
    br.new_context = nc
    return br

def new_page(browser, base, locale, dark=False, width=390):
    ctx = browser.new_context(viewport={'width': width, 'height': 844}, device_scale_factor=2, locale=locale,
                              color_scheme='dark' if dark else 'light', service_workers='block')
    ctx.route('https://world.openfoodfacts.org/**', fake_api)
    ctx.route('https://world.openbeautyfacts.org/**', fake_api)
    pg = ctx.new_page()
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base)
    pg.evaluate('LC.dbReady')
    return ctx, pg

def read_label(pg, text, kind, name=''):
    pg.click('#cardLabel')
    pg.fill('#labelText', text)
    pg.check('input[name=kind][value=%s]' % kind)
    pg.click('#checkLabel')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    if name: rename(pg, name)
    pg.evaluate('window.scrollTo(0, 0)')

def rename(pg, name):
    # v2.8: name a product after the check (pencil on the answer card)
    pg.click('#nameBtn'); pg.fill('#nameInput', name); pg.press('#nameInput', 'Enter')
    pg.wait_for_selector('#nameBtn')

def open_details(pg):
    # v2.8: tiles, groups, allergens and nutrition are under "Details"; groups other than green open too
    if pg.get_attribute('#detBtn', 'aria-expanded') != 'true': pg.click('#detBtn')
    sel = '#groups .grp:not(.g-green) .grp-head[aria-expanded=false]'
    while pg.locator(sel).count():   # each tap redraws the groups, so look again every time
        pg.locator(sel).first.click()

def show_details(pg):
    # v2.14: "Подробности" (ⓘ) opens the details under the answer
    if pg.get_attribute('#detBtn', 'aria-expanded') != 'true': pg.click('#detBtn')

def menu_pick(pg, sel):
    # v2.34: heart, share, type, "Send to Claude", 2nd photo and "Look up online" are in the ⋯ menu
    if not pg.locator('#moreMenu').count(): pg.click('#moreBtn')
    pg.wait_for_selector('#moreMenu')
    pg.click(sel)
    pg.wait_for_function("!document.getElementById('moreMenu') && !(history.state && history.state.menu)")
    pg.wait_for_timeout(150)

def see_unknown(pg):
    show_details(pg); pg.click('#unkBtn')

def word(pg):
    return pg.inner_text('#answer .qw b')

def type_code(pg, code):
    # v2.8: the barcode number box opens from a link
    if pg.is_hidden('#manualForm'): pg.click('#codeLink')
    pg.fill('#codeInput', code); pg.click('#manualForm button[type=submit]')

def reload_ready(pg):
    # reload and wait until the app and the database are ready (retry once if a late navigation interrupts)
    for i in range(3):
        try:
            pg.reload(wait_until='load'); pg.wait_for_function('window.LC'); pg.evaluate('LC.dbReady'); return
        except Exception:
            pg.wait_for_timeout(500)
    raise RuntimeError('page did not load')

# v2.37: a made-up offline pack, served as if it came from GitHub (raw.githubusercontent.com/.../pack/)
def pack_files(date='2026-12-03'):
    import gzip as _gz
    def nd(part, recs):
        body = json.dumps({'v': 1, 'part': part, 'date': date, 'n': len(recs)}) + '\n' + ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs)
        return _gz.compress(body.encode('utf-8'))
    main = [['0123456789012', 'f', 'UPC product', 'Ex', 'water, sugar'],
            ['3800000000017', 'f', 'Лютеница Тест', 'Тест', 'печени чушки, домати, пшенично брашно, сол', 'gluten'],
            ['3800000000024', 'f', 'Само име'],
            ['9001234500003', 'f', 'Bio Geflügelwurst', 'Example', 'Putenfleisch 92 %, Wasser, Meersalz'],
            ['9008700000000', 'c', 'Duschgel Test', 'Ex', 'Aqua, Sodium Laureth Sulfate, Parfum, Limonene', '', '', '']]
    de = [['4000000000017', 'f', 'Brot', 'Bäcker', 'Roggenmehl, Wasser, Salz']]
    files = {'pack-main.ndjson.gz': nd('main', main), 'pack-de.ndjson.gz': nd('de', de)}
    files['pack-info.json'] = json.dumps({'v': 1, 'date': date, 'source': 'Open Food Facts and Open Beauty Facts, ODbL', 'parts': {
        'main': {'file': 'pack-main.ndjson.gz', 'bytes': len(files['pack-main.ndjson.gz']), 'n': len(main), 'ni': 4},
        'de': {'file': 'pack-de.ndjson.gz', 'bytes': len(files['pack-de.ndjson.gz']), 'n': 1, 'ni': 1}}}).encode()
    return files

def pack_route(ctx, files, hits=None):
    def h(route):
        name = route.request.url.split('/pack/')[-1].split('?')[0]
        if hits is not None: hits.append(name)
        if name in files: route.fulfill(status=200, content_type='application/octet-stream', body=files[name])
        else: route.fulfill(status=404, body='404: Not Found')
    ctx.route('https://raw.githubusercontent.com/harisonbd/label-check/pack/**', h)

def open_card(pg, cid):
    # v2.36: My list topics are cards; open one as the user does (tap its title)
    if not pg.eval_on_selector('#' + cid, 'd => d.open'): pg.click('#%s > summary' % cid); pg.wait_for_timeout(100)

def kb_close(pg):
    # v2.36: the Save bar hides while the keyboard is open; close the keyboard as the user does
    pg.evaluate("document.activeElement && document.activeElement.blur()"); pg.wait_for_timeout(350)

def counts(pg):
    return pg.evaluate('(c => [c.red, c.orange, c.info, c.green])(LC.state.current.a.counts)')

def no_side_scroll(pg):
    return pg.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

def card_fits(pg):
    # The answer word and lines are not cut and do not stick out of the card
    # v2.12.1: also no loose text in the card (a missing legend once showed as the word "null")
    return pg.evaluate('(() => { const c = document.getElementById("answer"); return c.scrollWidth <= c.clientWidth + 1 && [...c.querySelectorAll(".qw b, .qy")].every(e => e.scrollWidth <= e.clientWidth + 1) && [...c.childNodes].every(n => n.nodeType !== 3 || !n.textContent.trim()); })()')

srv = serve()
base = 'http://127.0.0.1:%d/index.html' % srv.server_address[1]
with sync_playwright() as p:
    b = force_tess(p.chromium.launch())

    print('English, cosmetic label')
    ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, SHOWER, 'cosmetic', 'Shower gel')
    ok(word(pg) == 'Avoid', 'verdict Avoid (Lilial is banned)')
    ok(counts(pg) == [1, 1, 5, 7], 'groups 1 / 1 / 5 / 7')
    ok(pg.locator('.tile').count() == 0, 'v2.8: no count squares')
    ok(pg.inner_text('#dtop .qy') == 'Contains: Butylphenyl Methylpropional' and pg.inner_text('#dtop .qr') == 'Reason: banned in the EU', 'v2.8: red answer names the ingredient and the reason')
    ok(pg.is_visible('#nameBtn') and pg.inner_text('#nameBtn') == 'Shower gel', 'product name inside the answer card (renamed with the pencil)')
    ok(pg.is_hidden('#details') and pg.get_attribute('#detBtn', 'aria-expanded') == 'false', 'v2.8: "Details" start closed')
    open_details(pg)
    ok(pg.inner_text('#groups li:has-text("Butylphenyl") .chip') == 'Banned', 'row tag "Banned"')
    ok(pg.inner_text('#groups li:has-text("Sodium Benzoate") .why') == 'Preservative · EU limit', 'why line "Preservative · EU limit"')
    pg.click('#groups .grp.g-green .grp-head')
    ok(pg.locator('#groups .chiplist .gchip').count() == 7, 'Clear group shows 7 name chips')
    ok('Fragrance · Fragrance' not in pg.inner_text('#result'), 'no "Fragrance · Fragrance"')
    ok(pg.locator('.strip-ends').count() == 0 and pg.get_attribute('.strip button:nth-child(14)', 'title').startswith('#14'), 'strip stays in label order (v2.14: no "first / last" words)')
    ok(pg.locator('.strip button').count() == 14, '14 blocks in the strip')
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'en-cosmetic.png'))
    pg.click('.strip button:nth-child(9)')
    ok(pg.locator('#groups li.flash').count() == 1, 'strip block jumps to the ingredient')
    pg.click('#groups li:has-text("Methylisothiazolinone") .row-btn')
    ok(pg.is_visible('#detail') and 'Regulation (EU) 2016/1198' in pg.inner_text('#detailBody'), 'detail shows reason + source')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_hidden('#detail') and pg.is_visible('#result'), 'Back closes the detail')
    ok(pg.locator('#groups .grp.empty').count() == 0, 'v2.8: empty groups are not shown')
    menu_pick(pg, '#favBtn')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_hidden('#labelPanel') and pg.is_hidden('#result') and pg.is_visible('#scanner') and pg.is_visible('#cardScan') and pg.locator('.startcards .scard').count() == 2,
       'v2.49: Back from a label result shows the start screen with the 2 big buttons (one step, not the label screen)')
    ok('Fastest way' in pg.inner_text('#cardScan') and 'No barcode' in pg.inner_text('#cardLabel') and pg.inner_text('.startq') == 'What do you want to check?', 'v2.34: start B: question + 2 tiles with a short line')
    ok(pg.is_hidden('#manualForm') and pg.is_visible('#codeLink') and pg.is_visible('#topSearch'), 'v2.8: barcode numbers behind a link, search icon in the top bar')
    ok(pg.locator('#recentList li').count() == 1 and 'Shower gel' in pg.inner_text('#recent'), 'start screen: Recent shows the product')
    ok('EU lists' in pg.inner_text('#checking'), 'start screen: "Checking" row')

    print('Find one ingredient (offline)')
    pg.click('#topSearch')
    pg.fill('#searchInput', 'phenoxy'); pg.wait_for_timeout(400)
    ok(pg.locator('#searchList li').count() >= 3 and 'Phenoxyethanol' in pg.inner_text('#searchList'), 'search "phenoxy" finds Phenoxyethanol')
    pg.fill('#searchInput', 'e 250'); pg.wait_for_timeout(400)
    ok('E250' in pg.inner_text('#searchList li:first-child') and 'Concern' in pg.inner_text('#searchList li:first-child'), 'search "e 250" -> E250, Concern')
    pg.click('#searchList li:first-child .row-btn')
    ok(pg.is_visible('#detail') and 'Food additive' in pg.inner_text('#detailBody'), 'search result opens the detail screen')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_hidden('#detail') and pg.is_visible('#searchPanel'), 'Back closes the detail, search stays')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#cardScan'), 'Back from search shows the start screen')

    print('Stays on skin / washed off')
    read_label(pg, SHOWER, 'cosmetic', 'Shower gel 2')
    ok(pg.locator('.usebar .seg').count() == 3, 'switch with 3 choices on a cosmetic result')
    pg.click('.usebar .seg:nth-child(1)')
    open_details(pg)
    reds = pg.eval_on_selector_all('#groups .grp.g-red .row-btn strong', 'n => n.map(x => x.textContent)')
    ok('Methylisothiazolinone' in reds, '"Stays on skin" makes Methylisothiazolinone red (rinse-off only)')
    ok(pg.inner_text('#groups li:has-text("Methylisothiazolinone") .chip') == 'Rinse-off only', 'tag "Rinse-off only"')
    pg.click('.usebar .seg:nth-child(3)')
    open_details(pg)
    ok('Methylisothiazolinone' not in pg.eval_on_selector_all('#groups .grp.g-red .row-btn strong', 'n => n.map(x => x.textContent)'), '"Not sure" makes it orange again')
    ok(pg.locator('#result .data-line, #result .dbage').count() == 0, 'v2.4: no source / data line on the result (EU data is new)')
    ok(pg.locator('#tab-scan #credit').count() == 0 and pg.locator('#tab-list #credit').count() == 1, 'v2.4: credits only in My list -> What the app checks')

    print('Barcode lookup (faked), allergen + fragrance settings')
    pg.click('.tabbar button[data-go=scan]')
    ok(pg.is_visible('#cardScan'), 'tapping "Scan" on a result shows the start screen')
    type_code(pg, '9001234567890')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Check', 'sausage: Check (nitrite, trans fat)')
    ok('Instead: Shower gel' not in pg.inner_text('#answer'), '"Instead" only lists products of the same type (food)')
    pg.click('.tabbar button[data-go=list]')
    ok(not pg.eval_on_selector('#foodAlgBox', 'd => d.open') and not pg.eval_on_selector('#avoidCard', 'd => d.open'), 'Profile: "My list and allergens" and the allergen lists start folded (v2.46)')
    open_card(pg, 'avoidCard'); pg.click('#foodAlgBox summary')
    pg.click('#foodAlgList label:has-text("Mustard") input')
    pg.click('#profDiet .pchip[data-p=vegan]')
    pg.click('#profCos .pchip[data-p=frag]')
    ok(pg.eval_on_selector('#profCos .pchip[data-p=frag]', 'b => b.getAttribute("aria-pressed")') == 'true' and pg.inner_text('#profCos .pchip[data-p=frag]').startswith('✓'), 'fragrance chip (Profile) is pressed after a tap')
    pg.click('.tabbar button[data-go=history]')
    ok(pg.locator('#historyList .dot.g-red').count() == 3, 'history: all red after mustard, fragrance and vegan')
    pg.click('#historyList li:has-text("Extrawurst") .open')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    open_details(pg)
    ok('Not vegan' in pg.inner_text('#groups'), 'vegan: Schweinefleisch is "Not vegan"')
    ok(pg.locator('.tabbar button').count() == 3 and pg.locator('.tabbar button[data-go=favs]').count() == 0, 'v2.8: 3 tabs (Favourites are in History)')
    pg.click('.tabbar button[data-go=history]')
    pg.click('#histFilter button[data-f=favs]')
    ok('Shower gel' in pg.inner_text('#favList') and pg.is_hidden('#historyList'), 'favourite listed under History -> ♥ Favourites')
    pg.click('#histFilter button[data-f=favs]')   # v2.34: one ♥ toggle
    ok(pg.is_visible('#historyList') and pg.is_hidden('#favList'), '"All" shows the history again')
    ctx.close()

    print('Our product list (data/products.json)')
    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#topSearch')
    pg.fill('#searchInput', 'magne'); pg.wait_for_timeout(400)
    first = pg.inner_text('#searchList li:first-child')
    ok('MLO Magne Amino Armour' in first and 'Our list' in first and 'Avoid' in first, 'search "magne" shows our product first, Avoid')
    pg.click('#searchList li:first-child .row-btn')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Avoid', 'MLO: Avoid (E171)')
    open_details(pg)
    ok(counts(pg)[0] == 1 and 'Titanium dioxide' in pg.inner_text('#groups .grp.g-red'), 'red group = titanium dioxide')
    es = pg.evaluate('LC.state.current.a.rows.flatMap(r => (r.additives || []).map(a => a.e))')
    ok('E464' in es and 'E551' in es, 'хипромелоза = E464 and силиконов диоксид = E551 are found')
    pg.screenshot(path=os.path.join(SHOTS, 'en-own-product.png'))
    ok(pg.locator('#result .data-line').count() == 0, 'v2.4: no data line on our product')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#searchPanel'), 'Back from our product shows the search again')
    pg.go_back(); pg.wait_for_timeout(200)
    pg.click('#recentList li:first-child .open')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Avoid', 'opens again from Recent (no barcode)')
    ctx.close()
    # A product of our list with a barcode is found by scan, also with no connection.
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB', service_workers='block')
    own = json.load(open(os.path.join(ROOT, 'data', 'products.json'), encoding='utf-8'))
    own['products'].append(dict(own['products'][0], id='test-own', code='4000000000017', name='Test capsules'))
    ctx.route('**/data/products.json', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps(own)))
    ctx.route('https://world.openfoodfacts.org/**', lambda r: r.abort())
    ctx.route('https://world.openbeautyfacts.org/**', lambda r: r.abort())
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('LC.dbReady')
    type_code(pg, '4000000000017')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == 'Test capsules', 'scan finds our product offline')
    ctx.close()

    print('v2.4: checking card, barcode not found -> "checked before", language switch')
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB', service_workers='block')
    hold = []
    def slow_or_none(route):
        if '9001234567899' in route.request.url: hold.append(route)   # never answers: stays "Checking"
        else: route.fulfill(status=200, content_type='application/json', body='{"status":0}')
    ctx.route('https://world.openfoodfacts.org/**', slow_or_none)
    ctx.route('https://world.openbeautyfacts.org/**', slow_or_none)
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('LC.dbReady')
    type_code(pg, '9001234567899')
    pg.wait_for_selector('#status.busy:not([hidden])')
    box = pg.evaluate("() => { const b = document.getElementById('status').getBoundingClientRect(); return [b.top, b.bottom]; }")
    ok(box[0] < 120 and box[1] < 844, 'checking card is at the top of the screen (top %d px)' % box[0])
    ok('Checking' in pg.inner_text('#status') and '9001234567899' in pg.inner_text('#status'), 'checking card says "Checking …" + barcode')
    ok(pg.is_hidden('#scanner'), 'start screen is hidden while checking')
    pg.screenshot(path=os.path.join(SHOTS, 'v24-checking.png'))
    for r in hold: r.abort()          # no connection: the offline message, with the start screen below it
    pg.wait_for_selector('#status:not(.busy):not([hidden])')
    ok(pg.is_visible('#cardScan') and 'No connection' in pg.inner_text('#status'), 'offline: message on top, start screen below')
    # Barcode not found
    type_code(pg, '3800123456781')
    pg.wait_for_selector('#pickBox:not([hidden])')
    st = pg.evaluate("() => document.getElementById('status').getBoundingClientRect().top")
    ok(st >= 0 and st < 150 and 'not in the product databases yet' in pg.inner_text('#status'), 'not-found message is on screen at the top')
    ok('Claude' not in pg.inner_text('#status'), 'not-found message does not send you to Claude')
    first = pg.inner_text('#pickBox li:first-child')
    ok('Magne Amino Armour' in first and 'no barcode yet' in first, 'pick list: our product without a barcode comes first')
    ok(pg.inner_text('#labelTitle') == 'Or read the label', 'label title: "Or read the label"')
    pg.screenshot(path=os.path.join(SHOTS, 'v24-notfound.png'))
    pg.click('#pickBox .more')
    pg.fill('#pickSearch', 'amino'); pg.wait_for_timeout(150)
    ok(pg.locator('#pickBox li').count() == 1 and 'Magne' in pg.inner_text('#pickBox li'), 'search in the pick box finds Magne')
    pg.click('#pickBox li:first-child button')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == 'Magne Amino Armour' and word(pg) == 'Avoid', '"This one" opens Magne (Avoid)')
    ok('linked' in pg.inner_text('#toast'), 'toast: barcode linked')
    ctx.route('https://world.openfoodfacts.org/**', lambda r: r.abort())
    pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '3800123456781')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == 'Magne Amino Armour' and pg.is_hidden('#pickBox'), 'next scan opens Magne directly (offline too)')
    pg.click('.tabbar button[data-go=scan]')
    pg.click('#cardLabel')
    ok(pg.is_hidden('#pickBox') and pg.inner_text('#labelTitle') == 'Read a label', '"Read a label" card: no pick box, normal title')
    pg.click('.tabbar button[data-go=scan]')
    # Language switch
    ok(pg.get_attribute('#langSwitch [data-lang=en]', 'aria-pressed') == 'true', 'switch shows EN')
    pg.click('#langSwitch [data-lang=bg]')
    ok(pg.inner_text('.tabbar button[data-go=scan]') == 'Сканирай' or 'Скан' in pg.inner_text('.tabbar'), 'BG: menu in Bulgarian')
    ok(pg.get_attribute('#langSwitch [data-lang=bg]', 'aria-pressed') == 'true' and pg.input_value('#langSelect') == 'bg', 'BG pressed, settings say bg')
    ok(pg.evaluate("localStorage.getItem('lc.lang')") == '"bg"', 'language is saved')
    pg.screenshot(path=os.path.join(SHOTS, 'v24-bg-start.png'))
    pg.click('#langSwitch [data-lang=en]')
    ok(pg.inner_text('.tabbar button[data-go=scan]') == 'Scan', 'EN again')
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()

    print('v2.4: old EU data shows one orange line')
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB', service_workers='block')
    meta = json.load(open(os.path.join(ROOT, 'data', 'db-meta.json'), encoding='utf-8'))
    meta['built'] = '2025-01-01T00:00:00Z'
    ctx.route('**/data/db-meta.json', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps(meta)))
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('LC.dbReady')
    read_label(pg, SHOWER, 'cosmetic', 'Old data test')
    ok(pg.locator('#result .dbage.old').count() == 1 and 'more than 6 months' in pg.text_content('#result .dbage.old'), 'EU data older than 6 months: warning stays (under Details)')
    ctx.close()

    print('German, dark, 360 px')
    ctx, pg = new_page(b, base, 'de-AT', dark=True, width=360)
    ok(pg.locator('#langSwitch [aria-pressed=true]').count() == 0, 'German: EN | BG switch shows neither')
    ok(no_side_scroll(pg), 'no sideways scroll with the switch at 360 px')
    ok(pg.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()') == '#8AA4FF', 'dark = v2.34 calmer look (blue accent #8AA4FF)')
    ok(pg.get_attribute('#themeColor', 'content').upper() == '#0F1115', 'phone bar colour = v2.34 calmer dark')
    pg.screenshot(path=os.path.join(SHOTS, 'de-dark-start.png'))
    read_label(pg, SHOWER, 'cosmetic', 'Duschgel')
    ok(word(pg) == 'Meiden' and pg.inner_text('#dtop .qr') == 'Grund: in der EU verboten', 'German verdict and reason')
    open_details(pg)
    ok('Anhang' in pg.inner_text('#groups') or 'Grenzwert' in pg.inner_text('#groups'), 'German row texts')
    ok(card_fits(pg), 'German answer card fits at 360 px')
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'de-dark.png'))
    ctx.close()

    print('Bulgarian, food label, 360 px')
    ctx, pg = new_page(b, base, 'bg-BG', width=360)
    read_label(pg, WAFER, 'food', 'Вафла')
    ok(word(pg) == 'Провери', 'Bulgarian verdict')
    ok(counts(pg) == [0, 3, 3, 5], 'groups 0 / 3 / 3 / 5')
    open_details(pg)
    ok('Мляко' in pg.inner_text('.allergen-line'), 'milk allergen named Мляко')
    ok(card_fits(pg), 'Bulgarian answer card fits at 360 px')
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'bg-food.png'))
    ctx.close()
    b.close()

    print('v2.4: camera frame (fake camera)')
    bc = force_tess(p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']))
    for loc, tip in (('en-GB', 'Scan'), ('bg-BG', 'Сканирай'), ('de-AT', 'Scannen')):
        ctx = bc.new_context(viewport={'width': 360, 'height': 740}, locale=loc, service_workers='block', permissions=['camera'])
        ctx.add_init_script("window.BarcodeDetector = class { static async getSupportedFormats() { return ['ean_13']; } async detect() { return []; } };")
        pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(base); pg.evaluate('LC.dbReady')
        pg.click('#cardScan')
        pg.wait_for_function("() => document.getElementById('scanner').classList.contains('scanning')")
        r = pg.evaluate("() => { const b = document.getElementById('viewfinder').getBoundingClientRect(); return [b.width, b.height]; }")
        ok(abs(r[0] - r[1]) < 2, '%s: camera frame is square (%dx%d)' % (loc, r[0], r[1]))
        ok(pg.is_visible('.vf-box') and pg.inner_text('.vf-tip') == tip and pg.locator('.scanline').count() == 0, '%s: corner marks + "%s", no scan line' % (loc, tip))
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(SHOTS, 'v24-camera-%s.png' % loc[:2]))
        ok(pg.is_hidden('#torchBtn'), '%s: no torch button when the camera has no light' % loc)
        pg.click('#stopCam')
        ok(pg.is_visible('#cardScan'), '%s: Stop camera shows the start cards again' % loc)
        ctx.close()
    # v2.8: torch button when the camera has a light
    ctx = bc.new_context(viewport={'width': 390, 'height': 844}, locale='bg-BG', service_workers='block', permissions=['camera'], color_scheme='dark')
    ctx.add_init_script("window.BarcodeDetector = class { static async getSupportedFormats() { return ['ean_13']; } async detect() { return []; } };"
                        "MediaStreamTrack.prototype.getCapabilities = function () { return { torch: true }; };"
                        "MediaStreamTrack.prototype.applyConstraints = function (c) { window.__torch = c.advanced[0].torch; return Promise.resolve(); };")
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('LC.dbReady'); pg.click('#cardScan')
    pg.wait_for_selector('#torchBtn:not([hidden])')
    pg.click('#torchBtn')
    ok(pg.evaluate('window.__torch') is True and pg.get_attribute('#torchBtn', 'aria-pressed') == 'true' and pg.get_attribute('#torchBtn', 'aria-label') == 'Фенерче', 'v2.8: torch button switches the light on (BG label "Фенерче")')
    pg.screenshot(path=os.path.join(SHOTS, 'v28-torch-bg.png'))
    pg.click('#torchBtn')
    ok(pg.evaluate('window.__torch') is False, 'second tap switches it off')
    pg.click('#stopCam')
    ok(pg.is_hidden('#torchBtn'), 'Stop camera hides the torch button')
    ctx.close()
    bc.close()

    print('v2.5: read a label offline (Tesseract in ocr/)')
    from PIL import Image, ImageDraw, ImageFont
    def font(size, bold=False):
        for f in ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf', 'arialbd.ttf' if bold else 'arial.ttf'):
            for d in ('/usr/share/fonts/truetype/dejavu/', 'C:/Windows/Fonts/', ''):
                try: return ImageFont.truetype(d + f, size)
                except OSError: pass
        return ImageFont.load_default()
    LABEL = ['Ingredients: Sugar, wheat flour, palm oil, glucose', 'syrup, emulsifier: soya lecithin, colour:', 'tartrazine, salt, flavouring. May contain', 'traces of milk and hazelnuts.']
    img = Image.new('RGB', (1200, 1600), (250, 248, 240)); dr = ImageDraw.Draw(img)
    dr.text((80, 120), 'CRUNCHY WAFERS', fill=(150, 20, 20), font=font(90, True))
    for i, line in enumerate(LABEL): dr.text((70, 740 + i * 62), line, fill=(25, 25, 25), font=font(46))
    dr.text((80, 1250), 'Nutrition per 100 g   Energy 2002 kJ', fill=(25, 25, 25), font=font(40))
    photo = os.path.join(SHOTS, 'v25-test-label.jpg'); img.rotate(-2, fillcolor=(250, 248, 240)).save(photo, quality=90)

    def drag(pg, sel, tx, ty):
        bb = pg.locator(sel).bounding_box(); pg.mouse.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2)
        pg.mouse.down(); pg.mouse.move(tx, ty, steps=6); pg.mouse.up()
    def read_photo(pg, lang='eng', box=(0.03, 0.44, 0.97, 0.62), file=None):
        if pg.is_hidden('#labelPanel'):            # v2.13: one step shows the answer; open "Read a label" again
            pg.click('.tabbar button[data-go=scan]')
            if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
            pg.click('#cardLabel')
        pg.set_input_files('#photoPick', file or photo)
        pg.wait_for_selector('#ocrArea:not([hidden])')
        pg.evaluate("document.getElementById('cropWrap').scrollIntoView({block: 'center'})")
        r = pg.locator('#cropInner').bounding_box()
        drag(pg, '#cropBox i[data-h="nw"]', r['x'] + box[0] * r['width'], r['y'] + box[1] * r['height'])
        drag(pg, '#cropBox i[data-h="se"]', r['x'] + box[2] * r['width'], r['y'] + box[3] * r['height'])
        if lang: pg.select_option('#ocrLang', lang)
        pg.click('#ocrRead')
        pg.wait_for_function("() => { const s = document.getElementById('ocrStatus'); return !s.hidden && !s.classList.contains('busy'); }", timeout=90000)

    b = force_tess(p.chromium.launch())
    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#cardLabel')
    ok(pg.inner_text('#labelTitle') == 'Read a label' and not pg.is_visible('#ocrArea') and not pg.eval_on_selector('#claudeBox', 'd => d.open'), 'panel: title "Read a label", no photo box yet, Claude part folded')
    ok(pg.evaluate("[...performance.getEntriesByType('resource')].every(e => !e.name.includes('/ocr/'))"), 'reader files are not loaded before "Read text"')
    read_photo(pg)
    txt = pg.input_value('#labelText').lower()
    ok(pg.inner_text('#ocrStatus').startswith('Done in'), 'status "Done in … s" (%s)' % pg.inner_text('#ocrStatus'))
    ok(txt.startswith('ingredients:') and all(w in txt for w in ('sugar', 'wheat flour', 'palm oil', 'soya lecithin', 'tartrazine', 'milk')), 'text read from the box, starts at "Ingredients:"')
    ok('crunchy' not in txt and 'nutrition' not in txt, 'text outside the box is not read')
    pg.wait_for_selector('#result:not([hidden]) #answer')   # v2.13: "Check" reads and checks in one step
    ok('Tartrazine' in pg.text_content('#result') or 'E102' in pg.text_content('#result'), 'one step: the answer shows right after reading (tartrazine found)')
    pg.click('#cardLabel') if pg.is_visible('#cardLabel') else None
    ctx.close()

    ctx, pg = new_page(b, base, 'bg-BG')
    pg.click('#cardLabel')
    pg.set_input_files('#photoPick', photo)
    ok(pg.inner_text('#ocrRead') == 'Провери' and pg.is_hidden('#textFold') and pg.is_hidden('#oneNote') and pg.input_value('#ocrLang') == 'auto' and pg.inner_text('#ocrLang option[value=auto]') == 'Авто', 'BG: button text + label language "Авто" by default (v2.8)')
    ok(pg.eval_on_selector_all('#ocrLang option', 'o => o.map(x => x.textContent)')[1:] == ['EN', 'DE', 'BG', 'HU', 'CZ', 'SK', 'SL'], 'v2.8: menu has EN DE BG HU CZ SK SL')
    pg.select_option('#ocrLang', 'deu')
    pg.reload(); pg.evaluate('LC.dbReady'); pg.click('#cardLabel'); pg.set_input_files('#photoPick', photo)
    ok(pg.input_value('#ocrLang') == 'deu', 'label language choice is remembered (DE)')
    ok(no_side_scroll(pg), 'BG 390 px: no sideways scroll with the photo box')
    pg.screenshot(path=os.path.join(SHOTS, 'v25-label-bg.png'), full_page=True)
    ctx.close()

    print('v2.6: wrong label language -> the reader reads again with the other alphabet')
    BG_LINES = ['Съставки: захар, пшенично брашно, растителна', 'мазнина (палмова), сухо мляко, емулгатор: соев', 'лецитин, консервант: калиев сорбат,', 'оцветител: тартразин, подсладител: аспартам.']
    img = Image.new('RGB', (1200, 1600), (70, 30, 110)); dr = ImageDraw.Draw(img)     # dark label, light letters
    for i, line in enumerate(BG_LINES): dr.text((60, 740 + i * 62), line, fill=(240, 235, 245), font=font(44))
    photo_bg = os.path.join(SHOTS, 'v26-test-label-bg.jpg'); img.rotate(-2, fillcolor=(70, 30, 110)).save(photo_bg, quality=88)
    COUNT = "(() => { const W = window.Worker; window.__reads = 0; window.Worker = function (u, o) { const w = new W(u, o); w.addEventListener('message', e => { if (!e.data.step && !e.data.layout) window.__reads++; }); return w; }; })();"
    pressed = lambda pg: pg.input_value('#ocrLang')
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='bg-BG', service_workers='block'); ctx.add_init_script(COUNT)
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e))); pg.goto(base); pg.evaluate('LC.dbReady'); pg.click('#cardLabel')
    read_photo(pg, lang=None)                     # BG app, Auto -> BG reader first on an English label
    st, txt = pg.inner_text('#ocrStatus'), pg.input_value('#labelText').lower()
    ok(st.startswith('Готово') and 'Прочетено с EN' in st and 'palm oil' in txt and 'tartrazine' in txt, 'Auto, BG app, English label: BG -> Latin -> EN from the heading (%s)' % st)
    ok(pressed(pg) == 'auto' and pg.evaluate('window.__reads') == 3, 'menu stays on Auto; 3 reads (BG, DE, EN)')
    read_photo(pg, lang=None)
    ok(pg.evaluate('window.__reads') == 4 and 'Прочетено с EN' in pg.inner_text('#ocrStatus'), 'next English label: 1 read with EN (Auto remembers it)')
    ctx.close()
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB', service_workers='block'); ctx.add_init_script(COUNT)
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e))); pg.goto(base); pg.evaluate('LC.dbReady'); pg.click('#cardLabel')
    read_photo(pg, lang='eng', file=photo_bg)
    st, txt = pg.inner_text('#ocrStatus'), pg.input_value('#labelText').lower()
    ok('Read with BG' in st and 'тартразин' in txt and pressed(pg) == 'eng', 'EN chosen, dark Bulgarian label: read again with BG, the menu keeps EN (%s)' % st)
    ctx.close()
    # Other language not on the phone and no internet: keep the first text, orange line instead of "Done"
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='bg-BG', service_workers='block'); ctx.add_init_script(COUNT)
    ctx.route('**/ocr/lang/eng.traineddata.gz', lambda r: r.abort())
    ctx.route('**/ocr/lang/deu.traineddata.gz', lambda r: r.abort())
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e))); pg.goto(base); pg.evaluate('LC.dbReady'); pg.click('#cardLabel')
    read_photo(pg, lang=None)
    ok(pg.inner_text('#ocrStatus').startswith('Намерен е малко текст') and pg.input_value('#labelText') != '' and pressed(pg) == 'auto',
       'Latin readers not available: first text kept, orange "little text" line')
    ctx.close()

    print('v2.6: Back button, version in the top bar, BG words')
    TINT = "s => { const b = document.querySelector(s); const c = getComputedStyle(b); return [c.backgroundColor, c.color, b.getBoundingClientRect().height]; }"
    for loc, dark, width in (('en-GB', False, 390), ('bg-BG', True, 320), ('de-AT', False, 360), ('bg-BG', False, 360)):
        ctx, pg = new_page(b, base, loc, dark=dark, width=width); tag = '%s %s %d px' % (loc, 'dark' if dark else 'light', width)
        top = pg.evaluate("() => { const h = document.querySelector('.topbar h1').getBoundingClientRect(), s = document.getElementById('langSwitch').getBoundingClientRect(); return [h.height, h.right <= s.left]; }")
        ok(pg.inner_text('.topbar .ver') == 'v2.51' and top[0] < 32 and top[1] and no_side_scroll(pg), '%s: "v2.20.3" next to the title, one line, left of EN | BG' % tag)
        pg.click('#cardLabel')
        bg, fg, h = pg.evaluate(TINT, '#labelPanel .panel-back')
        ok(bg not in ('rgba(0, 0, 0, 0)', 'transparent') and h >= 44, '%s: Back on "Read a label" is a tinted pill (%s, %d px high)' % (tag, bg, h))
        if loc == 'bg-BG':
            pg.fill('#labelText', 'Съставки: овесени ядки, мед, сол, канела'); pg.check('input[name=kind][value=food]'); pg.click('#checkLabel')
            pg.wait_for_selector('#result:not([hidden]) #answer')
            ok(word(pg) == 'Без предупреждения' and card_fits(pg), '%s: green word "Без предупреждения" (v2.8), not cut' % tag)
            open_details(pg); pg.click('#groups .grp.g-green .grp-head'); pg.click('#groups .row-btn, #groups .gchip')
            bg2 = pg.evaluate(TINT, '#detailBack')[0]
            ok(pg.is_visible('#detail') and bg2 not in ('rgba(0, 0, 0, 0)', 'transparent'), '%s: Back on the ingredient detail is a tinted pill' % tag)
            pg.click('#detailBack'); pg.click('.tabbar button[data-go=scan]')
            type_code(pg, '3800123456781'); pg.wait_for_selector('#pickBox:not([hidden])')
            ok(pg.eval_on_selector_all('#pickBox li button', 'n => n.map(x => x.textContent)')[0] == 'Избери' and no_side_scroll(pg), '%s: "checked before" button says "Избери"' % tag)
            pg.screenshot(path=os.path.join(SHOTS, 'v26-pick-bg.png'))
        else:
            pg.click('.tabbar button[data-go=scan]'); pg.click('#topSearch')
            ok(pg.evaluate(TINT, '#searchPanel .panel-back')[0] not in ('rgba(0, 0, 0, 0)', 'transparent'), '%s: Back on "Find one ingredient" is a tinted pill' % tag)
        pg.screenshot(path=os.path.join(SHOTS, 'v26-%s-%s-%d.png' % (loc, 'dark' if dark else 'light', width)))
        ctx.close()

    print('v2.7: My list, simpler (option A)')
    for loc, dark, width in (('bg-BG', True, 390), ('en-GB', False, 320)):
        ctx, pg = new_page(b, base, loc, dark=dark, width=width); tag = '%s %s %d px' % (loc, 'dark' if dark else 'light', width)
        pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(150)
        h = pg.evaluate("document.getElementById('tab-list').getBoundingClientRect().height")
        ok(h < 2700 and no_side_scroll(pg), '%s: Profile is short (%d px, was about 4500; v2.41 added the profile chips, about 900 px) and has no sideways scroll' % (tag, h))
        ok(pg.locator('#fragSwitch').count() == 0 and pg.locator('#profCos .pchip[data-p=frag]').count() == 1, '%s: fragrance is a Profile chip (v2.41), no separate switch' % tag)
        ok(all(not pg.eval_on_selector(f, 'd => d.open') for f in ('#foodAlgBox', '#cosAlgBox', '#rulesFold', '#ghCard', '#setCard')), '%s: allergens, "What the app checks", Backup and Settings start closed' % tag)
        ok('ODbL' in pg.text_content('#rulesFold') and pg.text_content('#ghCard summary').strip() != '' and pg.locator('#setCard #rulesFold').count() == 1, '%s: credit line (ODbL) is still in "What the app checks" (v2.46: inside Settings); Backup has a title' % tag)
        pg.click('#profCos .pchip[data-p=frag]'); pg.click('#profCos .pchip[data-p=frag]')
        ok(pg.eval_on_selector('#profCos .pchip[data-p=frag]', 'b => b.getAttribute("aria-pressed")') == 'false' and pg.evaluate("!LC.state.avoidFragrance"), '%s: second tap switches fragrance off again' % tag)
        open_card(pg, 'setCard'); pg.click('#rulesFold summary')
        ok(pg.is_visible('#rulesBox .levels'), '%s: Settings -> tapping "What the app checks" opens it' % tag)
        pg.evaluate("document.querySelector('#rulesFold').open = false; document.getElementById('setCard').open = false; scrollTo(0, 0)")
        pg.screenshot(path=os.path.join(SHOTS, 'v27-mylist-%s-%s-%d.png' % (loc, 'dark' if dark else 'light', width)), full_page=True)
        ctx.close()

    print('v2.7: UI check fixes')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True, width=390)
    read_label(pg, SHOWER, 'cosmetic', 'Shower gel')
    open_details(pg)
    ok(pg.evaluate("[...document.querySelectorAll('.grp-head .desc')].every(e => e.scrollWidth <= e.clientWidth + 1)"), 'BG 390 px: group header meanings are not cut')
    ok(pg.evaluate("[...document.querySelectorAll('.row-btn .why')].some(e => e.getBoundingClientRect().height > 30)"), 'reason under an ingredient can use 2 lines')
    pg.click('.tabbar button[data-go=scan]')
    hs = pg.evaluate("[...document.querySelectorAll('.cchip, #recentAll')].map(e => Math.round(e.getBoundingClientRect().height))")
    ok(hs and min(hs) >= 40, '"Checking" chips and "All" are at least 40 px high (%s)' % hs)
    pg.click('#topSearch'); pg.fill('#searchInput', 'e 250'); pg.wait_for_timeout(400)
    ok(pg.locator('#searchList li').count() == 1 and 'E250' in pg.inner_text('#searchList'), 'search "e 250": only E250, no cosmetic with "-250"')
    ctx.close()

    print('v2.8: name after the check, quick answer, Instead, nutrition, household, type guess, backup note')
    DISH = 'Inhaltsstoffe: 5-15% anionische Tenside, <5% nichtionische Tenside, Duftstoffe, Benzisothiazolinone, Methylisothiazolinone, Limonene, Linalool'
    ctx, pg = new_page(b, base, 'bg-BG', dark=True, width=390)
    read_label(pg, 'Съставки: овесени ядки 100%, сол, канела', 'food')
    ok(pg.inner_text('#nameBtn') == '+ Добави име' and word(pg) == 'Без предупреждения', 'green answer, product without a name')
    ok(pg.inner_text('#chkLine span') == 'Проверено:' and pg.inner_text('#chkLine b') == '✓ ЕС' and pg.get_attribute('#chkLine', 'aria-label') == 'Нищо от твоя списък, алергените ти и предупрежденията на ЕС.',
       'v2.13: green answer says what was checked in one line of chips ("Проверено: ✓ ЕС"), never "safe"')
    rename(pg, 'Овесени ядки')
    ok(pg.inner_text('#nameBtn') == 'Овесени ядки' and pg.evaluate('LC.state.history[0].name') == 'Овесени ядки', 'pencil: name saved on the result and in History')
    ok(pg.locator('#labelName').count() == 0, 'no name field on "Read a label" any more')
    pg.screenshot(path=os.path.join(SHOTS, 'v28-green-bg.png'))
    reload_ready(pg)
    pg.click('#recentList li:first-child .open'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == 'Овесени ядки', 'name stays after a reload')
    pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '9001234567890'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Провери' and 'Натриев нитрит' in pg.inner_text('#dtop .qy'), 'orange answer names the ingredient')
    ok(pg.inner_text('#answer .qalt') .startswith('Вместо това:') and 'Овесени ядки' in pg.inner_text('#answer .qalt'), '"Вместо това" shows the saved green food product')
    pg.screenshot(path=os.path.join(SHOTS, 'v28-orange-bg.png'))
    open_details(pg)
    ok(pg.inner_text('.nutline') == 'На 100 г: мазнини 24 г (наситени 9,5 г) · белтъчини 13 г', 'fat + protein line from Open Food Facts (%s)' % pg.inner_text('.nutline'))
    rename(pg, 'Моят колбас')
    pg.evaluate("LC.lookup('9001234567890', true)"); pg.wait_for_timeout(500); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == 'Моят колбас', 'your name wins over the Open Food Facts name after a new lookup')
    pg.click('#answer .altbtn'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == 'Овесени ядки', 'tap on the "Вместо това" name opens that product')
    show_details(pg); pg.click('#details .strip button'); pg.wait_for_timeout(200)   # v2.34: the strip is at the top of Details
    ok(pg.is_visible('#details') and pg.locator('#groups li.flash').count() == 1, 'strip block opens "Подробности" and jumps to the ingredient')
    # type guess
    pg.click('.tabbar button[data-go=scan]'); pg.click('#cardLabel')
    pg.fill('#labelText', SHOWER); pg.wait_for_timeout(700)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'cosmetic' and 'козметика' in pg.inner_text('#kindNote'), 'type guess: cosmetic (%s)' % pg.inner_text('#kindNote'))
    pg.fill('#labelText', DISH); pg.wait_for_timeout(700)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'household', 'type guess: household (dish soap)')
    pg.fill('#labelText', WAFER); pg.wait_for_timeout(700)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'food', 'type guess: food (wafer)')
    pg.fill('#labelText', 'Sonstige Bestandteile: Dodecylpoly(oxyethylen)-2-hydrogensulfat, Natriumsalz; Macrogolglycerolcocoate; Natriumhydroxid; Ponceau 4R; Salzsäure 10 %; Kaliumsorbat; gereinigtes Wasser. Zur Anwendung auf der Haut.'); pg.wait_for_timeout(700)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'cosmetic' and 'skin product' in pg.inner_text('#kindNote') or 'козметика' in pg.inner_text('#kindNote') or 'кожа' in pg.inner_text('#kindNote'), 'v2.19.1: a garbled skin-product label (Ketozolin) is typed Cosmetic, not Food (%s)' % pg.inner_text('#kindNote'))
    pg.fill('#labelText', 'Zutaten: Weizenmehl, Zucker, Palmfett, Salz, Backtriebmittel Natriumhydrogencarbonat, Säuerungsmittel Zitronensäure, Aroma'); pg.wait_for_timeout(700)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'food', 'v2.19.1: an ordinary food label with salt and citric acid stays Food')
    pg.check('input[name=kind][value=cosmetic]'); pg.fill('#labelText', WAFER + ', сол'); pg.wait_for_timeout(700)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'cosmetic' and pg.is_hidden('#kindNote'), 'after you pick a type, the app does not change it')
    ok(no_side_scroll(pg), 'label screen with 3 types: no sideways scroll')
    # household result
    pg.evaluate("localStorage.setItem('lc.avoidFragrance', 'true')"); reload_ready(pg)
    pg.click('#cardLabel'); pg.fill('#labelText', DISH); pg.wait_for_timeout(700); pg.click('#checkLabel'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Избягвай' and 'Duftstoffe' in pg.inner_text('#dtop .qy') and 'аромат' in pg.inner_text('#dtop .qr'), 'household: Duftstoffe is fragrance -> red with "I avoid fragrance"')
    ok(pg.is_hidden('.usebar'), 'household: no "stays on skin" question')
    open_details(pg); pg.click('#groups .grp.g-green .grp-head')
    ok('Анионни ПАВ' in pg.inner_text('#groups') and 'Битова химия' in pg.inner_text('.det-head'), 'household: detergent words get plain names, type shown in Details')
    ok('Правило на ЕС за козметика' in pg.inner_text('#groups li:has-text("Methylisothiazolinone")'), 'household: MI reason marked as an EU cosmetics rule')
    pg.screenshot(path=os.path.join(SHOTS, 'v28-household-bg.png'), full_page=True)
    pg.evaluate("localStorage.setItem('lc.avoidFragrance', 'false')"); reload_ready(pg)
    read_label(pg, 'Inhaltsstoffe: 5-15% anionische Tenside, Aqua, Butylphenyl Methylpropional', 'household')
    ok(word(pg) == 'Провери' and pg.inner_text('#dtop .qr') == 'Причина: не е разрешено в козметика в ЕС. За битова химия правилата са други.', 'household: an EU cosmetics ban is orange "not in cosmetics", not red')
    ctx.close()

    print('v2.9: German compound words and "may contain traces"')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True, width=390)
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({ food: ['soybeans', 'gluten'], cos: [] }))"); reload_ready(pg)
    read_label(pg, 'Zutaten: Zucker, Kakaobutter. Kann Spuren von Soja enthalten.', 'food')
    ok(word(pg) == 'Провери' and pg.inner_text('#dtop .qy') == 'Може да съдържа следи: Соя' and pg.locator('#dtop .qr').count() == 0,
       'v2.47: ticked soy only in "Kann Spuren von Soja": orange Check (not red), "Може да съдържа следи: Соя" (%s)' % pg.inner_text('#dtop .qy'))
    ok(pg.inner_text('#oneLine') == 'Може да съдържа 1 твой алерген' and pg.locator('#qMay li').count() == 1 and 'Соя' in pg.inner_text('#qMay') and pg.locator('#qMay .dot[data-m=p]').count() == 1,
       'v2.47: one line under the word, one "May contain" row with the person mark (%s / %s)' % (pg.inner_text('#oneLine'), pg.inner_text('#qMay')))
    open_details(pg)
    ok(pg.locator('.allergen-line').count() == 0 and pg.locator('#groups li:has-text("Soja")').count() == 0 and pg.inner_text('#mayAll').lower() == 'може да съдържа (следи): соя',
       'v2.47 Details: the traces sentence is no ingredient row; one line "Може да съдържа (следи): соя" instead of the allergen line (%s)' % pg.inner_text('#mayAll'))
    pg.screenshot(path=os.path.join(SHOTS, 'v29-traces-bg.png'))
    pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Zutaten: Hartweizengrieß, Wasser', 'food')
    ok(word(pg) == 'Избягвай' and pg.inner_text('#dtop .qy') == 'Съдържа: Глутен' and pg.inner_text('#dtop .qr') == 'Причина: твой алерген', 'Hartweizengrieß with gluten ticked: red "Съдържа: Глутен"')
    # v2.47: fixes from the 25 photo reads (user 28 Nov)
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({ food: ['milk', 'peanuts'], cos: [] })); localStorage.setItem('lc.avoid', JSON.stringify([{ id: 'a1', text: 'msg, e621', preset: 'msg' }]))"); reload_ready(pg)
    an = lambda kind, text: pg.evaluate("""([kind, text]) => { const a = LC.analyze({ code: 'label-x', kind, source: 'label', name: 'x', ingredientsText: text, texts: [text] });
        return { v: a.verdict, rows: a.rows.map(r => [r.label || r.text || '', r.group]), may: a.traces ? a.traces.mine.map(x => x.id).sort() : null }; }""", [kind, text])
    r = an('food', 'Състав: тиквено семе 98%, трапезна сол 2%. Може да съдържа следи от мляко, фъстъци, соя и сусам.')
    ok(r['v'] == 'check' and r['may'] == ['milk', 'peanuts'] and len(r['rows']) == 2, 'v2.47: "may contain" milk + peanuts (ticked) = Check, not Avoid; the traces sentence is no ingredient row (%s)' % r)
    r = an('food', 'Zutaten: Zucker, Magermilchpulver, Kakaobutter, Vollmilchpulver')
    ok(r['v'] == 'avoid' and [g for t, g in r['rows'] if 'milch' in t.lower()] == ['red', 'red'], 'v2.47: milk ticked: both Magermilchpulver and Vollmilchpulver are red (%s)' % r['rows'])
    r = an('food', 'Състав: овкусители (\u0415621), сол')
    ok(r['v'] == 'avoid' and ['Овкусители', 'red'] in r['rows'], 'v2.47: Cyrillic "Е621" hits "MSG / E621" on your list (%s)' % r['rows'])
    ctx.close()

    print('v2.8: backup note, app shortcuts, text cut at a 2nd heading, 320 px')
    ctx, pg = new_page(b, base, 'bg-BG', dark=False, width=320)
    ok(pg.is_hidden('#bkNote'), 'no backup note while nothing is saved')
    read_label(pg, 'Съставки: овесени ядки 100%, сол, канела', 'food', 'Овесени ядки')
    ok(card_fits(pg) and no_side_scroll(pg), '320 px: "Без предупреждения" fits in the card')
    pg.click('.tabbar button[data-go=scan]')
    ok(pg.is_visible('#bkNote') and pg.inner_text('#bkTitle') == 'Още нямаш резервно копие.', 'backup note on the start screen (no backup yet)')
    pg.click('#bkLater')
    ok(pg.is_hidden('#bkNote') and pg.evaluate("+localStorage.getItem('lc.backupLater') > 0"), '"По-късно" hides it for 7 days')
    pg.evaluate("localStorage.removeItem('lc.backupLater'); LC.renderStart()")
    with pg.expect_download() as dl: pg.click('#bkSave')
    ok(dl.value.suggested_filename.startswith('label-check-backup-') and pg.is_hidden('#bkNote') and pg.text_content('#bkLast').startswith('Последно копие:'), '"Запази копие" saves the backup file and the note goes away')
    backup = json.load(open(dl.value.path(), encoding='utf-8'))
    ok(any(v == 'Овесени ядки' for v in backup.get('names', {}).values()), 'your product names are in the backup')
    root = base.replace('index.html', '')
    pg.goto(root + '?go=label'); pg.evaluate('LC.dbReady'); pg.wait_for_timeout(200)
    ok(pg.is_visible('#labelPanel') and '?go' not in pg.url, 'long-press menu "Read a label" (?go=label) opens the label screen')
    pg.goto(root + '?go=search'); pg.evaluate('LC.dbReady'); pg.wait_for_timeout(200)
    ok(pg.is_visible('#searchPanel'), 'long-press menu "Find one ingredient" (?go=search)')
    cut = pg.evaluate("[LC.cleanOcr('Zutaten: Zucker, Weizenmehl, Palmöl, Haselnüsse 8%. Ingredients: sugar, wheat flour, palm oil'), LC.cleanOcr('Zutaten Teig: Mehl, Butter, Zucker. Zutaten Füllung: Äpfel, Zimt'), LC.cleanOcr('Összetevők: búzaliszt, cukor, só. Složení: pšeničná mouka, cukr')]")
    ok(cut == ['Ingredients: sugar, wheat flour, palm oil', 'Zutaten Teig: Mehl, Butter, Zucker. Zutaten Füllung: Äpfel, Zimt', 'Összetevők: búzaliszt, cukor, só.'], 'text stops at a heading in another language (v2.24: English wins over German), same-language headings stay (%s)' % cut)
    man = json.load(open(os.path.join(ROOT, 'manifest.json'), encoding='utf-8'))
    ok(man['share_target']['params']['files'][0]['name'] == 'photo' and [s['url'] for s in man['shortcuts']] == ['./?go=scan', './?go=label', './?go=search'], 'manifest: share target + 3 shortcuts')
    ctx.close()

    print('v2.10: the box finds the ingredient list by itself; only the list is kept; name from the photo')
    img = Image.new('RGB', (1200, 1700), (252, 252, 250)); dr = ImageDraw.Draw(img)
    dr.text((150, 120), 'SOFT HAND CREAM', fill=(30, 60, 140), font=font(84, True))
    for i, line in enumerate(['Die Handcreme mit Panthenol unterstützt das', 'Gleichgewicht der Hautflora und fördert den Erhalt.']):
        dr.text((70, 420 + i * 52), line, fill=(40, 40, 40), font=font(38))
    dr.line((60, 560, 1140, 560), fill=(30, 60, 140), width=4)
    LIST = ['INGREDIENTS/SASTOJCI/СЪСТАВКИ: AQUA · GLYCERIN ·', 'PANTHENOL · CETYL ALCOHOL · GLYCERYL STEARATE ·', 'DICAPRYLYL ETHER · ISO-', 'PROPYL MYRISTATE · ALLANTOIN · CITRIC ACID ·', 'SODIUM HYDROXIDE.']
    for i, line in enumerate(LIST): dr.text((70, 590 + i * 56), line, fill=(25, 25, 25), font=font(40))
    dr.line((60, 890, 1140, 890), fill=(30, 60, 140), width=4)
    for i, line in enumerate(['(PL) Krem do rąk z pantenolem. (IT) Crema mani al', 'pantenolo per pelli sensibili. Senza profumi.', '(HU) Ultra szenzitív kézkrém panthenollal.']):
        dr.text((70, 930 + i * 52), line, fill=(40, 40, 40), font=font(38))
    photo_hc = os.path.join(SHOTS, 'v210-test-handcream.jpg'); img.rotate(-1.5, fillcolor=(252, 252, 250)).save(photo_hc, quality=90)
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='bg-BG', service_workers='block', color_scheme='dark')
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e))); pg.goto(base); pg.evaluate('LC.dbReady')
    pg.click('#cardLabel'); pg.set_input_files('#photoPick', photo_hc); pg.wait_for_selector('#ocrArea:not([hidden])')
    pg.wait_for_function("() => { const s = document.getElementById('ocrStatus'); return !s.hidden && !s.classList.contains('busy'); }", timeout=90000)
    box = pg.evaluate("(() => { const b = document.getElementById('cropBox').style; return [parseFloat(b.top), parseFloat(b.height)]; })()")
    ok(pg.inner_text('#ocrStatus') == 'Рамката е върху съставките. Премести я, ако трябва.' and 30 < box[0] < 36 and box[1] < 25,
       'box moved onto the ingredient list by itself (top %.0f %%, height %.0f %%)' % tuple(box))
    pg.evaluate("document.getElementById('cropWrap').scrollIntoView({block:'center'})"); pg.screenshot(path=os.path.join(SHOTS, 'v210-autobox-bg.png'))
    pg.click('#ocrRead')
    pg.wait_for_function("() => { const s = document.getElementById('ocrStatus'); return !s.hidden && !s.classList.contains('busy'); }", timeout=90000)
    txt = pg.input_value('#labelText')
    rows = pg.evaluate("t => LCDB.checkCosmetic(t, 'en').map(r => r.found)", txt)
    ok(txt.startswith('AQUA') and 'SODIUM HYDROXIDE' in txt and 'Handcreme' not in txt and 'Krem' not in txt and 'INGREDIENTS' not in txt,
       'only the list is kept: starts with AQUA, ends with SODIUM HYDROXIDE, no German / Polish text, joined heading removed (%s)' % txt[:80])
    ok(sum(rows) >= 9 and len(rows) <= 11, 'dots read as - : » are separators again: %d of %d names known (ISO-PROPYL joined)' % (sum(rows), len(rows)))
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'cosmetic', 'type guess: cosmetic')
    pg.wait_for_selector('#result:not([hidden]) #answer')   # v2.13: one step
    ok(pg.inner_text('#nameBtn span') == 'Soft Hand Cream' and pg.inner_text('#nameBtn .fromphoto') == 'от снимката', 'name from the photo: "Soft Hand Cream", tag "от снимката" (%s)' % pg.inner_text('.qn'))
    pg.screenshot(path=os.path.join(SHOTS, 'v210-name-from-photo-bg.png'))
    rename(pg, 'Ръчен крем')
    ok(pg.inner_text('#nameBtn') == 'Ръчен крем' and pg.locator('#nameBtn .fromphoto').count() == 0, 'pencil: you can still change the name; the tag goes away')
    pg.click('.tabbar button[data-go=scan]'); pg.click('#cardLabel'); pg.fill('#labelText', 'Zutaten: Zucker, Salz, Hafer'); pg.check('input[name=kind][value=food]'); pg.click('#checkLabel')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#nameBtn') == '+ Добави име', 'pasted text without photo: "+ Добави име" button instead of grey "Продукт без име"')
    ctx.close()

    print('v2.11: how many names are known, "Incomplete result", fix suggestions for misread names')
    ctx, pg = new_page(b, base, 'en-GB', width=320)
    pg.click('#cardLabel'); pg.fill('#labelText', 'Aqua, Glycern, Phenoxyetanol, Cetyl Alcohol, Parfum')
    pg.wait_for_selector('#fixBox:not([hidden])', timeout=5000)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'cosmetic', 'typing: names one letter off count for the type guess (cosmetic)')
    ok(pg.inner_text('#fixBox .fixhead') == '2 names look misread:' and pg.locator('#fixBox li').count() == 2 and pg.inner_text('#fixBox li b') == 'Glycerin',
       'fix box: "2 names look misread", Glycern -> Glycerin (same letter style)')
    pg.locator('#fixBox .fixok').first.click()
    ok('Glycerin,' in pg.input_value('#labelText') and pg.locator('#fixBox li').count() == 1 and pg.locator('#fixAll').count() == 0 and '1 name fixed' in pg.inner_text('#toast'),
       'tap the tick: the name changes in the text, 1 suggestion left, toast "1 name fixed"')
    pg.locator('#fixBox .fixok').first.click()
    ok(pg.input_value('#labelText') == 'Aqua, Glycerin, Phenoxyethanol, Cetyl Alcohol, Parfum' and pg.is_hidden('#fixBox'), 'all fixed: box goes away, nothing else in the text changed')
    pg.check('input[name=kind][value=food]')
    pg.fill('#labelText', 'Zucker, Glycern'); pg.wait_for_timeout(900)
    ok(pg.is_hidden('#fixBox'), 'food: no fix suggestions')
    ctx.close()
    ctx, pg = new_page(b, base, 'en-GB', width=320)
    MISREAD = 'AQUA, GLYCERN, Phenoxyetanol, Bienenwachs, Wsxq lorem, CETYL ALCOHOL, PARFUM'
    # v2.13: GLYCERN and Phenoxyetanol are corrected by the app (one clear close name, no warning); still 2 no data
    read_label(pg, MISREAD, 'cosmetic')
    ok(word(pg) == 'No warnings' and card_fits(pg) and no_side_scroll(pg), 'v2.13: 2 misread names corrected by the app: 5 of 7 known = "No warnings", fits at 320 px')
    ok(pg.inner_text('#knownLine .qkn') == '5 of 7 ingredients recognised' and pg.inner_text('#knownLine .qks') == ' · 2 not in our data · 2 corrected by the app'
       and pg.inner_text('#unkBtn') == 'See' and pg.get_attribute('#unkBtn', 'aria-label') == 'See 2 unknown',
       'known line in one line: "5 of 7 … · 2 not in our data · 2 corrected by the app · See · Fix the text" (%s)' % pg.inner_text('#knownLine'))
    pg.screenshot(path=os.path.join(SHOTS, 'v213-auto-en.png'))
    see_unknown(pg); pg.wait_for_timeout(400)
    ok(pg.get_attribute('#detBtn', 'aria-expanded') == 'true' and pg.is_visible('#groups .grp.g-nodata .chiplist') and pg.locator('#groups li.flash .gchip.nf').count() == 1,
       '"See": Details open at the first unknown name (grey "No data" group)')
    if pg.locator('#groups .grp.g-green .grp-head[aria-expanded=false]').count(): pg.click('#groups .grp.g-green .grp-head')
    pg.locator('#groups .grp.g-green .gchip', has_text='Glycerin').click(); pg.wait_for_selector('#detail:not([hidden])')
    ok('Corrected by the app' in pg.inner_text('#detail .d-tags') and pg.inner_text('#autoCard p') == 'The label was read as GLYCERN. The app counts it as Glycerin.',
       'detail of GLYCERN: tag "Corrected by the app", "The label was read as GLYCERN. The app counts it as Glycerin."')
    pg.click('#detailBack')
    pg.wait_for_selector('#detail', state='hidden')
    code = pg.evaluate('LC.state.current.p.code')
    pg.evaluate('window.scrollTo(0, 0)'); show_details(pg); pg.click('#fixTextBtn'); pg.wait_for_selector('#fixBox:not([hidden])')
    ok(pg.is_visible('#labelPanel') and pg.is_visible('#textPart') and pg.input_value('#labelText') == MISREAD and pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'cosmetic',
       '"Fix the text": the form opens with the saved text and type')
    pg.click('#fixAll')
    ok(pg.input_value('#labelText') == 'AQUA, GLYCERIN, Phenoxyethanol, Bienenwachs, Wsxq lorem, CETYL ALCOHOL, PARFUM', '"Fix all (2)": both names fixed in the text (%s)' % pg.input_value('#labelText'))
    pg.click('#checkLabel'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'No warnings' and pg.inner_text('#knownLine .qkn') == '5 of 7 ingredients recognised' and pg.inner_text('#knownLine .qks') == ' · 2 not in our data' and pg.evaluate('LC.state.current.p.code') == code,
       'after the fix: 5 of 7 known with "2 not in our data" (nothing left to correct); the same product is updated')
    pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
    ok(pg.locator('#historyList li').count() == 1 and pg.locator('#historyList li .dot.g-green').count() == 1, 'History: one entry (same product), green dot')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')   # 2nd tap on Scan goes back to the start
    read_label(pg, 'Zucker, Wsxq lorem, Bnmz ipsum, Plkr dolor', 'food')
    ok(word(pg) == 'No warnings' and pg.locator('.qk').count() == 0, 'food: never "Incomplete result", no known line')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Aqua, Sodium Laureth Sulfate, Glycern, 5-15% anionic surfactants, Parfum', 'household')
    ok(pg.inner_text('#knownLine .qks') == ' · 1 corrected by the app', 'household: the detergent words are known, Glycern is corrected by the app (%s)' % pg.inner_text('#knownLine'))
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Aqua, Wsxq lorem, Bnmz ipsum, Bienenwachs, Cetyl Alcohol, Parfum, Plkr dolor', 'cosmetic')
    ok(word(pg) == 'Incomplete result' and pg.evaluate('LC.state.current.a.verdict') == 'partial' and card_fits(pg) and no_side_scroll(pg),
       'only 3 of 7 names known (no close names): grey "Incomplete result" instead of green, fits at 320 px')
    ctx.close()

    print('v2.12/v2.13: "No data" (grey), legend with counts, corrected by the app, check the label, teach the app')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    TEACH = 'AQUA, GLYCERN, CETEARYL ALCOHOL, Bienenwachs, PANTHENOL, PHENOXYETANOL, PARFUM'
    read_label(pg, TEACH, 'cosmetic')
    ok(pg.locator('.strip .g-nodata').count() == 1 and pg.locator('.strip .g-green').count() == 5 and pg.locator('.strip .g-info').count() == 1 and pg.locator('.strip .nf').count() == 0,
       'strip: Bienenwachs grey (no data); GLYCERN and PHENOXYETANOL corrected by the app (green / info)')
    ok(pg.text_content('#legend') == '1 инфо1 няма данни5 нищо открито' and card_fits(pg) and no_side_scroll(pg),
       'v2.13 legend with a count for every colour shown: "1 инфо · 1 няма данни · 5 нищо открито" (%s)' % pg.text_content('#legend'))
    ok(pg.inner_text('#knownLine .qkn') == '6 от 7 съставки разпознати' and pg.inner_text('#knownLine .qks') == ' · 1 липсва в данните ни · 2 поправени от приложението',
       'known line in one line: "6 от 7 … · 1 липсва в данните ни · 2 поправени от приложението" (%s)' % pg.inner_text('#knownLine'))
    pg.screenshot(path=os.path.join(SHOTS, 'v213-card-bg.png'))
    see_unknown(pg); pg.wait_for_timeout(400)
    ok(pg.evaluate("[...document.querySelectorAll('#groups .grp')].map(g => g.classList[1] + ':' + g.querySelector('.num').textContent).join(' ')") == 'g-info:1 g-nodata:1 g-green:5',
       'Details: grey group "Няма данни" (1) above the green group (5)')
    ok(pg.inner_text('#groups .grp.g-nodata .ttl') == 'Няма данни' and pg.inner_text('#groups .grp.g-nodata .grpnote') == 'Приложението не знае нищо за тези имена – нито добро, нито лошо.'
       and pg.locator('#groups li.flash .gchip.nf').count() == 1, '"Виж" opens the grey group at the unknown name; meaning line')
    pg.screenshot(path=os.path.join(SHOTS, 'v212-groups-bg.png'))
    pg.click('#groups .grp.g-green .grp-head')
    ok(pg.inner_text('#groups .grp.g-green .grpnote') == 'Познати съставки. Не са в списъците на ЕС, които приложението проверява.', 'green group: "Познати съставки. …" (cosmetics)')
    # (d) no close name: grey badge, "Какво знае приложението: Нищо", teach with the picker
    pg.locator('#groups .grp.g-nodata .gchip').first.click(); pg.wait_for_selector('#detail:not([hidden])')
    ok(pg.inner_text('#detail .badge') == 'Няма данни' and pg.inner_text('#nothingLine').startswith('Нищо. Това име не е в данните ни'),
       'detail of Bienenwachs: grey badge "Няма данни" (not green) + "Нищо. …"')
    ok(pg.inner_text('#teachCard p') == 'Приложението не познава това име. Кажи му коя съставка е.' and pg.inner_text('#teachOther') == 'Избери съставката…' and pg.locator('#teachYes').count() == 0,
       'no guess: "Приложението не познава това име…" + "Избери съставката…"')
    pg.screenshot(path=os.path.join(SHOTS, 'v212-teach-card-bg.png'))
    pg.click('#teachOther'); pg.wait_for_selector('#searchPanel:not([hidden])'); pg.wait_for_timeout(300)
    rows = pg.evaluate("[...document.querySelectorAll('#searchList li')].map(l => l.innerText)")
    ok(pg.inner_text('#searchPanel h2') == 'Какво е „Bienenwachs“?' and pg.input_value('#searchInput') == 'Bienenwachs' and rows and rows[0].startswith('Beeswax')
       and not any('Добавка' in r for r in rows), 'picker: "Какво е „Bienenwachs“?", name typed in, Beeswax found through E901, no food rows (%s)' % rows[:3])
    pg.screenshot(path=os.path.join(SHOTS, 'v212-picker-bg.png'))
    pg.locator('#searchList li button').first.click(); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(300)
    ok(word(pg) == 'Без предупреждения' and pg.inner_text('#knownLine .qkn') == '7 от 7 съставки разпознати' and '1 научена от теб' in pg.inner_text('#knownLine')
       and pg.evaluate('history.state.view') == 'result' and pg.is_hidden('#searchPanel'), 'pick Beeswax: back on the result, 7 of 7 known, "1 научена от теб"')
    ok(pg.inner_text('#toast') == 'Научено: Bienenwachs = Beeswax' and pg.evaluate("JSON.parse(localStorage.getItem('lc.taught')).bienenwachs.to") == 'BEESWAX',
       'saved on the phone (Bienenwachs = BEESWAX), toast "Научено: …"')
    # taught name: tag + card with undo
    if pg.get_attribute('#detBtn', 'aria-expanded') != 'true': pg.click('#detBtn')
    if pg.locator('#groups .grp.g-green .grp-head[aria-expanded=false]').count(): pg.click('#groups .grp.g-green .grp-head')
    pg.locator('#groups .grp.g-green .gchip', has_text='Beeswax').click(); pg.wait_for_selector('#detail:not([hidden])')
    ok('Научено от теб' in pg.inner_text('#detail .d-tags') and pg.inner_text('#taughtCard p') == 'На етикета пише Bienenwachs. Ти научи приложението, че това е Beeswax.',
       'detail of a taught name: tag "Научено от теб", "На етикета пише Bienenwachs…"')
    pg.click('#undoTeach'); pg.wait_for_selector('#detail', state='hidden'); pg.wait_for_timeout(200)
    ok(pg.inner_text('#toast') == 'Премахнато: Bienenwachs' and pg.locator('.strip .g-nodata').count() == 1, '"Отмени": Bienenwachs is unknown (grey) again')
    # (a) corrected by the app: "Не е това" keeps it unknown and remembers that
    if pg.get_attribute('#detBtn', 'aria-expanded') != 'true': pg.click('#detBtn')
    if pg.locator('#groups .grp.g-green .grp-head[aria-expanded=false]').count(): pg.click('#groups .grp.g-green .grp-head')
    pg.locator('#groups .grp.g-green .gchip', has_text='Glycerin').click(); pg.wait_for_selector('#detail:not([hidden])')
    ok('Поправено от приложението' in pg.inner_text('#detail .d-tags') and pg.inner_text('#autoCard p') == 'Прочетено е GLYCERN. Приложението го брои като Glycerin.',
       'detail of GLYCERN: tag "Поправено от приложението", "Прочетено е GLYCERN. Приложението го брои като Glycerin."')
    pg.screenshot(path=os.path.join(SHOTS, 'v213-auto-detail-bg.png'))
    pg.click('#notThis'); pg.wait_for_selector('#detail', state='hidden'); pg.wait_for_timeout(200)
    ok(pg.inner_text('#toast') == 'Добре: GLYCERN остава непознато.' and pg.locator('.strip .g-nodata').count() == 2
       and pg.evaluate("JSON.parse(localStorage.getItem('lc.taught')).glycern.no") == 'GLYCERIN', '"Не е това": GLYCERN stays unknown (grey), remembered on the phone')
    if pg.get_attribute('#detBtn', 'aria-expanded') != 'true': pg.click('#detBtn')
    if pg.locator('#groups .grp.g-nodata .grp-head[aria-expanded=false]').count(): pg.click('#groups .grp.g-nodata .grp-head')
    pg.locator('#groups .grp.g-nodata .gchip', has_text='GLYCERN').click(); pg.wait_for_selector('#detail:not([hidden])')
    ok(pg.locator('#teachYes').count() == 0 and pg.inner_text('#teachOther') == 'Избери съставката…', 'after "Не е това": no "Да, това е Glycerin" again, only "Избери съставката…"')
    pg.click('#detailBack'); pg.wait_for_selector('#detail', state='hidden')
    # (b) the closest name has a warning: orange "check the label", you decide
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Aqua, Glycerin, BUTYLPHENYL METHYLPROPI0NAL, Parfum', 'cosmetic')
    ok(word(pg) == 'Провери' and pg.inner_text('#dtop .qy') == 'Butylphenyl Methylpropional?' and 'погледни етикета' in pg.inner_text('#dtop .qr'),
       '(b) close name with an EU warning (Lilial): orange "Провери", "Butylphenyl Methylpropional?", "погледни етикета" – never decided alone')
    pg.click('#detBtn')
    if pg.locator('#groups .grp.g-orange .grp-head[aria-expanded=false]').count(): pg.click('#groups .grp.g-orange .grp-head')
    pg.locator('#groups .grp.g-orange .row-btn').first.click(); pg.wait_for_selector('#detail:not([hidden])')
    ok(pg.inner_text('#detail .badge') == 'Провери етикета' and 'Прочетено е „BUTYLPHENYL METHYLPROPI0NAL“' in pg.inner_text('#askCard') and pg.inner_text('#askYes') == 'Да, това е Butylphenyl Methylpropional'
       and pg.inner_text('#askNo') == 'Не, друго е' and 'Ако е Butylphenyl Methylpropional:' in pg.inner_text('#askCard'), 'detail: "Провери етикета", what was read, "Да, това е …" / "Не, друго е", the EU reason if it is')
    pg.screenshot(path=os.path.join(SHOTS, 'v213-ask-bg.png'))
    pg.click('#askYes'); pg.wait_for_selector('#detail', state='hidden'); pg.wait_for_timeout(200)
    ok(word(pg) == 'Избягвай' and 'Butylphenyl Methylpropional' in pg.inner_text('#dtop .qy'), '"Да, това е": taught, now red "Избягвай" (banned in the EU)')
    # (c) several close names: you choose
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Aqua, Glycerin, Laureth-B, Parfum', 'cosmetic')
    pg.click('#detBtn')
    if pg.locator('#groups .grp.g-nodata .grp-head[aria-expanded=false]').count(): pg.click('#groups .grp.g-nodata .grp-head')
    pg.locator('#groups .grp.g-nodata .gchip').first.click(); pg.wait_for_selector('#detail:not([hidden])')
    ok('Коя от тези е?' in pg.inner_text('#teachCard') and pg.inner_text('#teachChoice0') == 'Laureth-1' and pg.locator('#teachCard [id^=teachChoice]').count() == 3,
       '(c) Laureth-B: "Коя от тези е?" with Laureth-1 / -2 / -3')
    pg.click('#teachChoice1'); pg.wait_for_selector('#detail', state='hidden'); pg.wait_for_timeout(200)
    ok(pg.evaluate("JSON.parse(localStorage.getItem('lc.taught'))['laureth b'].to") == 'LAURETH-2' and pg.locator('.strip .g-nodata').count() == 0, 'choosing Laureth-2: taught, nothing grey left')
    # the fix box does not offer a name you answered
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.click('#cardLabel'); pg.fill('#labelText', 'Aqua, Glycern, Phenoxyetanol, Parfum'); pg.check('input[name=kind][value=cosmetic]'); pg.wait_for_timeout(900)
    ok(pg.locator('#fixBox li').count() == 1 and pg.inner_text('#fixBox li b') == 'Phenoxyethanol', 'fix box: Glycern ("Не е това") is not offered again, only Phenoxyetanol')
    # Food: legend, no grey, no "corrected"
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Zucker, Wsxq lorem, Bnmz ipsum, Plkr dolor', 'food')
    ok(pg.locator('.strip .g-nodata').count() == 0 and pg.text_content('#legend') == '4 нищо открито' and card_fits(pg), 'food: no grey blocks; legend "4 нищо открито"')
    # My list: taught names (incl. "не поправяй"), delete; backup
    with pg.expect_download() as dl:
        pg.click('.tabbar button[data-go=list]'); open_card(pg, 'ghCard'); pg.click('#exportBtn')
    bk = json.load(open(dl.value.path(), encoding='utf-8'))
    ok(bk.get('taught', {}).get('glycern', {}).get('no') == 'GLYCERIN' and bk.get('vibrate') is True, 'backup file includes the taught names and the vibration setting')
    pg.click('#taughtBox summary'); pg.wait_for_timeout(200)
    names = pg.evaluate("[...document.querySelectorAll('#taughtList .taughtrow')].map(r => r.querySelector('s').textContent + '>' + r.querySelector('b').textContent)")
    ok(pg.inner_text('#taughtCount') == '(3)' and 'GLYCERN>не поправяй' in names and 'BUTYLPHENYL METHYLPROPI0NAL>Butylphenyl Methylpropional' in names,
       'My list: "Научени имена" (3), GLYCERN → "не поправяй" (%s)' % names)
    pg.evaluate("document.getElementById('taughtBox').scrollIntoView({block: 'center'})"); pg.screenshot(path=os.path.join(SHOTS, 'v212-mylist-bg.png'))
    for k in range(3): pg.locator('#taughtList .taughtrow .x').first.click(); pg.wait_for_timeout(150)
    ok(pg.inner_text('#taughtCount') == '(0)' and 'Още няма' in pg.inner_text('#taughtList') and pg.evaluate("localStorage.getItem('lc.taught')") == '{}', '✕ deletes them; empty text')
    open_card(pg, 'setCard')
    ok(pg.is_visible('#vibSwitch') or pg.is_visible('#vibRow'), 'v2.13: "Вибрация при резултат" switch in My list (card Settings)')
    ok(no_side_scroll(pg), 'My list: no sideways scroll')
    for tab in ['list', 'history']:   # bug found 21 Oct: 🔍 on My list / History showed nothing
        pg.click('.tabbar button[data-go=%s]' % tab); pg.wait_for_timeout(200); pg.click('#topSearch'); pg.wait_for_timeout(300)
        ok(pg.is_visible('#searchInput') and pg.get_attribute('.tabbar button[data-go=scan]', 'aria-current') == 'page' and pg.input_value('#searchInput') == '',
           '🔍 on %s: switches to Scan and shows the Find screen (empty box)' % tab)
        pg.go_back(); pg.wait_for_timeout(300)
    ctx.close()
    # v2.13: History mini strip, vibration patterns, "Checked:" chips with your settings, one step after a photo
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.evaluate("window.__buzz = []; navigator.vibrate = p => { window.__buzz.push(p); return true; }; 0")
    pg.evaluate("localStorage.setItem('lc.avoid', JSON.stringify([{id:'a1', text:'palm oil, palmöl'}])); localStorage.setItem('lc.allergens', JSON.stringify({food:['milk'], cos:[]}))")
    reload_ready(pg); pg.evaluate("window.__buzz = []; navigator.vibrate = p => { window.__buzz.push(p); return true; }; 0")
    read_label(pg, 'Съставки: овесени ядки, сол, канела', 'food')
    ok(pg.evaluate("[...document.querySelectorAll('#chkLine b')].map(b => b.textContent).join('|')") == '✓ ЕС|✓ Твоят списък · 1|✓ Алергени · 1',
       '"Проверено:" chips show what was checked: ЕС, your list (1), allergens (1)')
    ok(pg.evaluate('window.__buzz') == [[70]], 'vibration: 1 short buzz on a new "Без предупреждения" (%s)' % pg.evaluate('window.__buzz'))
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Zutaten: Zucker, Palmöl, Natriumnitrit', 'food')
    ok(pg.evaluate('window.__buzz')[-1] == [70, 90, 70, 90, 70], 'vibration: 3 buzzes on "Избягвай"')
    pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
    ok(pg.locator('#historyList li').nth(0).locator('.dot.g-red').count() == 1 and 'Днес · 1 червена' in pg.inner_text('#historyList li >> nth=0'),
       'v2.34 History B: red dot and "Днес · 1 червена" (the mini strip is gone) (%s)' % pg.inner_text('#historyList li >> nth=0'))
    n = len(pg.evaluate('window.__buzz')); pg.locator('#historyList li .open').first.click(); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(len(pg.evaluate('window.__buzz')) == n, 'opening a saved product from History: no vibration')
    pg.screenshot(path=os.path.join(SHOTS, 'v213-history-bg.png'))
    pg.click('.tabbar button[data-go=list]'); open_card(pg, 'setCard'); pg.click('#vibSwitch')
    ok(pg.evaluate("localStorage.getItem('lc.vibrate')") == 'false', 'vibration switch off is saved')
    # safety: a photo read without the list heading is never green
    v = pg.evaluate("[LC.analyze({kind:'food', ingredientsText:'Zucker, Salz, Hafer, Wasser', read:{photo:true, list:false}}).verdict, LC.analyze({kind:'food', ingredientsText:'Zucker, Salz, Hafer, Wasser', read:{photo:true, list:true}}).verdict, LC.analyze({kind:'food', ingredientsText:'Zucker, Salz, Hafer, Wasser'}).verdict]")
    ok(v == ['partial', 'ok', 'ok'], 'v2.13 safety: photo read without a list heading -> "Непълен резултат", with heading or typed text -> "Без предупреждения" (%s)' % v)
    pg.click('.tabbar button[data-go=scan]')
    pg.evaluate("LC.showProduct({code:'t-nolist', kind:'food', source:'label', ingredientsText:'Brennwert 0 kJ, Salz 0,02 g', texts:['Brennwert 0 kJ, Salz 0,02 g'], read:{photo:true, list:false}, tags:[], allergens:[], analysis:[]})")
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Непълен резултат' and pg.inner_text('#dtop .qy') == 'Не намерих заглавието на списъка със съставки на снимката. Прочетеният текст може да не е списъкът.'
       and pg.locator('#fixTextBtn2').count() == 1 and card_fits(pg), 'no list heading on the photo: grey card says so, with "Поправи текста"')
    pg.screenshot(path=os.path.join(SHOTS, 'v213-nolist-bg.png'))
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.click('#cardLabel')
    ok(pg.inner_text('#photoTip') == 'отблизо, само съставките' and pg.is_visible('#photoTip') and pg.is_visible('#textFold') and not pg.eval_on_selector('#textFold', 'd => d.open'),
       'Read a label: close-up tip inside the Снимай card (v2.36); the text part is a folded row (paste)')
    ctx.close()
    # EN and DE, light, 320 px
    for loc, lang, nd, pick in [('en-GB', 'en', 'No data', 'Choose the ingredient…'), ('de-DE', 'de', 'Keine Daten', 'Zutat auswählen…')]:
        ctx, pg = new_page(b, base, loc, width=320)
        read_label(pg, 'Aqua, Glycern, Bienenwachs, Cetearyl Alcohol, Parfum', 'cosmetic')
        ok(card_fits(pg) and no_side_scroll(pg) and pg.locator('.strip .g-nodata').count() == 1, '%s 320 px light: card fits, 1 grey block (Glycern corrected)' % lang.upper())
        see_unknown(pg); pg.wait_for_timeout(300)
        ok(pg.inner_text('#groups .grp.g-nodata .ttl') == nd, '%s: grey group "%s"' % (lang.upper(), nd))
        pg.locator('#groups li.flash .gchip').click(); pg.wait_for_selector('#detail:not([hidden])')
        ok(pg.inner_text('#detail .badge') == nd and pg.inner_text('#teachOther') == pick and pg.evaluate("document.getElementById('detail').scrollWidth <= window.innerWidth"),
           '%s: detail badge "%s", "%s", no sideways scroll' % (lang.upper(), nd, pick))
        pg.screenshot(path=os.path.join(SHOTS, 'v212-teach-%s-320.png' % lang))
        ctx.close()

    print('v2.14 / v2.34: answer = word + count line + chips + red/orange list; "Покажи всички" / Снимай пак; Следващ продукт')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.evaluate("localStorage.setItem('lc.avoid', JSON.stringify([{id:'a1', text:'methylisothiazolinone'}])); 0"); reload_ready(pg)
    read_label(pg, 'AQUA, GLYCERIN, PANTHENOL, CETYL ALCOHOL, ALLANTOIN, CITRIC ACID', 'cosmetic', 'Крем')
    ok(word(pg) == 'Без предупреждения' and pg.inner_text('#oneLine') == 'Проверени са 6 съставки' and pg.locator('#answer .qr, #answer #chkLine, #answer #knownLine, #answer #legend, #answer .strip').count() == 0
       and pg.inner_text('#qChips') == '6 нищо открито' and pg.locator('#qList').count() == 0, 'v2.34 green: word, "Проверени са 6 съставки", one chip; no strip, no list on the answer')
    ok(pg.inner_text('#detBtn') == 'Покажи всички 6 съставки' and pg.inner_text('#againBtn') == 'Снимай пак' and pg.inner_text('#nextBtn') == 'Следващ продукт'
       and 'btn-primary' in pg.get_attribute('#nextBtn', 'class') and 'btn-ghost' in pg.get_attribute('#againBtn', 'class')
       and pg.evaluate("getComputedStyle(document.getElementById('qBar')).position") == 'sticky', 'v2.34: "Покажи всички 6 съставки"; bottom bar: blue "Следващ продукт" + "Снимай пак"')
    ok(pg.locator('#details .strip button').count() == 6, 'v2.34: the colour strip is at the top of Details')
    ok(pg.is_hidden('#details') and pg.evaluate("[...document.querySelectorAll('#chkLine b')].length") == 2, 'the "Проверено" chips are in Подробности (closed)')
    pg.click('#detBtn'); pg.wait_for_timeout(300)
    ok(pg.is_visible('#dtop #chkLine') and pg.is_visible('#dtop #legend') and pg.get_attribute('#detBtn', 'aria-expanded') == 'true', 'ⓘ Подробности opens the info: Проверено chips + legend at the top')
    pg.screenshot(path=os.path.join(SHOTS, 'v214-green-details-bg.png'))
    pg.click('#detBtn')
    ok(pg.is_hidden('#details'), 'a second tap closes it')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, SHOWER, 'cosmetic', 'Душ гел')
    ok(word(pg) == 'Избягвай' and pg.inner_text('#oneLine') == '2 червени съставки' and card_fits(pg) and no_side_scroll(pg),
       'v2.34 red: count line "2 червени съставки" (%s)' % pg.inner_text('#oneLine'))
    ok(pg.locator('#qList .dot.g-red').count() == 2 and 'Methylisothiazolinone' in pg.inner_text('#qList') and 'Butylphenyl Methylpropional' in pg.inner_text('#qList'),
       'v2.34 red: the red names are in the list under the chips')
    ok(pg.inner_text('#dtop .qr') == 'Причина: в твоя списък, забранено в ЕС', 'the reason is in Подробности')
    pg.screenshot(path=os.path.join(SHOTS, 'v214-red-bg.png'))
    pg.click('#againBtn'); pg.wait_for_selector('#labelPanel:not([hidden])')
    ok(pg.is_visible('#photoInput') or pg.is_visible('.filebtn'), '"Снимай пак" opens Read a label')
    pg.go_back(); pg.wait_for_selector('#result:not([hidden]) #answer')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({food:['soybeans', 'gluten'], cos:[]})); 0"); reload_ready(pg)
    read_label(pg, 'Zutaten: Hartweizengrieß, Zucker. Kann Spuren von Soja enthalten.', 'food')
    ok(word(pg) == 'Избягвай' and 'Соя' in pg.inner_text('#qMay') and 'Соя' not in pg.inner_text('#qList') and 'Hartweizengrieß' in pg.inner_text('#qList'), 'red with traces: v2.47: the real ingredient is red, the trace has its own "May contain" row (%s / %s)' % (pg.inner_text('#oneLine'), pg.inner_text('#qMay')))
    pg.click('.tabbar button[data-go=scan]')
    pg.evaluate("LC.showProduct({code:'t-nolist2', kind:'food', source:'label', ingredientsText:'Brennwert 0 kJ, Salz 0,02 g', texts:['Brennwert 0 kJ, Salz 0,02 g'], read:{photo:true, list:false}, tags:[], allergens:[], analysis:[]})")
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Непълен резултат' and pg.inner_text('#oneLine') == 'Снимай отблизо само списъка.' and pg.locator('#answer .strip').count() == 0
       and 'btn-primary' in pg.get_attribute('#againBtn', 'class') and 'btn-ghost' in pg.get_attribute('#nextBtn', 'class'),
       'grey (no list on the photo): "Снимай отблизо само списъка.", no strip, "Снимай пак" is the blue button')
    pg.screenshot(path=os.path.join(SHOTS, 'v214-grey-bg.png'))
    ctx.close()
    ctx, pg = new_page(b, base, 'en-GB', width=320)
    type_code(pg, '9001234567890'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.inner_text('#againBtn') == 'Photo the label' and pg.inner_text('#nextBtn') == 'Next product' and card_fits(pg) and no_side_scroll(pg),
       'EN 320 px, barcode product: "Photo the label" / "Next product", fits')
    ctx.close()

    print('v2.8: Auto reads a German label with DE (BG app)')
    DE_LINES = ['Zutaten: Zucker, Weizenmehl, Palmöl, Glukosesirup,', 'Emulgator: Sojalecithin, Farbstoff: Tartrazin,', 'Salz, Aroma. Kann Spuren von Milch und', 'Haselnüssen enthalten.']
    img = Image.new('RGB', (1200, 1600), (250, 248, 240)); dr = ImageDraw.Draw(img)
    for i, line in enumerate(DE_LINES): dr.text((70, 740 + i * 62), line, fill=(25, 25, 25), font=font(46))
    photo_de = os.path.join(SHOTS, 'v28-test-label-de.jpg'); img.rotate(-2, fillcolor=(250, 248, 240)).save(photo_de, quality=90)
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='bg-BG', service_workers='block'); ctx.add_init_script(COUNT)
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e))); pg.goto(base); pg.evaluate('LC.dbReady'); pg.click('#cardLabel')
    read_photo(pg, lang=None, file=photo_de)
    st, txt = pg.inner_text('#ocrStatus'), pg.input_value('#labelText').lower()
    ok('Прочетено с DE' in st and 'palmöl' in txt and pg.evaluate('window.__reads') == 2, 'Auto: German label read with DE (BG first, then DE; "Zutaten" agrees) (%s)' % st)
    ok(pg.eval_on_selector('input[name=kind]:checked', 'i => i.value') == 'food', 'type guess after reading: food')
    ctx.close()

    # With the service worker: reader files stay on the phone after the first use -> works offline.
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB')
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('navigator.serviceWorker.ready'); reload_ready(pg)
    ok(pg.evaluate('!!navigator.serviceWorker.controller'), 'service worker controls the page')
    pg.click('#cardLabel'); read_photo(pg)
    cached = pg.evaluate("async () => (await (await caches.open('label-check-v69')).keys()).map(r => r.url.split('/').pop())")
    ok(all(f in cached for f in ('ocr-worker-2.js', 'tesseract-core-simd-lstm.js', 'tesseract-core-simd-lstm.wasm', 'eng.traineddata.gz')) and 'deu.traineddata.gz' not in cached,
       'after first use: worker, program and only the used language are on the phone')
    ctx.set_offline(True)
    reload_ready(pg); pg.click('#cardLabel'); read_photo(pg)
    ok(pg.inner_text('#ocrStatus').startswith('Done in') and 'palm oil' in pg.input_value('#labelText').lower(), 'offline: Read text still works')
    ctx.set_offline(False)
    print('v2.8: label reader without internet (My list)')
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(300); open_card(pg, 'packCard')   # v2.46: the label reader is in "Without internet"
    ok(pg.inner_text('#offState').startswith('On this phone: EN (1 of 7)') and 'Download all languages' in pg.inner_text('#offGet'), 'My list: "On this phone: EN (1 of 7)" + download button (%s / %s)' % (pg.inner_text('#offState'), pg.inner_text('#offGet')))
    pg.click('#offGet')
    pg.wait_for_function("() => document.getElementById('offState').textContent.startsWith('All 7')", timeout=60000)
    ok(pg.is_hidden('#offGet'), 'after the download: "All 7 label languages are on this phone", no button')
    ctx.set_offline(True)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')   # 2nd tap on Scan closes the open label screen
    pg.click('#cardLabel'); read_photo(pg, lang='hun')
    ok(pg.inner_text('#ocrStatus').startswith('Done in'), 'offline: the HU reader works after the download')
    ctx.set_offline(False)
    print('v2.8: photo shared to the app, "new version" line')
    pg.goto(base); pg.evaluate('LC.dbReady')
    sent = pg.evaluate('''async () => { const img = await (await fetch('icon-192.png')).blob(); const f = new FormData(); f.append('photo', new File([img], 'p.png', { type: 'image/png' }));
      const r = await fetch('share-target', { method: 'POST', body: f, redirect: 'manual' }); return [r.type, (await caches.keys()).includes('lc-share')]; }''')
    ok(sent[0] == 'opaqueredirect' and sent[1], 'share target: the service worker keeps the photo and answers with a redirect (%s)' % sent)
    pg.goto(base.replace('index.html', '') + '?shared=1'); pg.wait_for_selector('#ocrArea:not([hidden])', timeout=20000)
    ok(pg.is_visible('#labelPanel') and pg.is_visible('#ocrArea') and not pg.evaluate("caches.has('lc-share')"), 'shared photo opens "Read a label" with the photo (and is then removed)')
    ok(pg.is_hidden('#updBar'), 'no "new version" line before an update')
    ctx.close()
    # ---------- v2.15 ----------
    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#cardLabel')
    ok(pg.locator('#photoStart .scard').count() == 3 and pg.is_visible('#photoTip') and pg.is_visible('#textFold') and pg.is_hidden('#checkBar') and pg.is_hidden('#againRow'),
       'v2.15/v2.36: Read a label before a photo: three cards (Photo, Gallery, Type), short tip, folded "Type or paste" row')
    pg.set_input_files('#photoPick', photo); pg.wait_for_selector('#ocrArea:not([hidden])')
    ok(pg.is_hidden('#photoStart') and pg.is_hidden('#textFold') and pg.is_visible('#againRow') and pg.is_visible('#checkBar'), 'v2.15: after the photo the top part folds away; "Another photo" and the Check bar show')
    pg.evaluate('window.scrollTo(0, 0)'); pg.wait_for_timeout(200)
    bb = pg.locator('#checkBar').bounding_box()
    ok(bb and bb['y'] + bb['height'] <= 844 - 60 and bb['y'] > 300, 'v2.15: the Check bar is in view above the tab bar without scrolling (y=%s)' % (bb and round(bb['y'] + bb['height'])))
    ok(no_side_scroll(pg), 'v2.15: no sideways scroll with the Check bar')
    ctx.close()

    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#codeLink')
    ok(pg.is_visible('#manualForm') and pg.is_visible('#codeClose'), 'v2.15: barcode number box has a close button')
    pg.click('#codeClose')
    ok(pg.is_hidden('#manualForm') and pg.is_visible('#codeLink') and pg.evaluate('history.state && history.state.view') != 'code', 'v2.15: the close button closes the box and the link is back')
    pg.click('#codeLink'); pg.go_back(); pg.wait_for_timeout(300)
    ok(pg.is_hidden('#manualForm') and pg.is_visible('#codeLink') and pg.is_visible('#cardLabel'), 'v2.15: phone Back closes the barcode box (stays in the app)')
    ctx.close()

    ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, SHOWER, 'cosmetic', 'Shower gel')
    ok('14 read' in pg.inner_text('#endsLine') and pg.inner_text('#endsLine').startswith('#1 ') and 'Methylpropional' in pg.inner_text('#endsLine'), 'v2.15: under the strip: first name, "14 read", last name (%s)' % pg.inner_text('#endsLine').replace('\n', ' | '))
    ok(pg.locator('#typeChip').count() == 0 and pg.inner_text('#answer .qkind') == 'Cosmetic', 'v2.34: you chose the type, so no type line; the type is in the top line')
    menu_pick(pg, '#moreMenu .seg:has-text("Food")')
    ok(pg.evaluate('LC.state.current.p.kind') == 'food' and pg.inner_text('#answer .qkind') == 'Food' and pg.evaluate('LC.state.current.p.kindSet') is True,
       'v2.34: the ⋯ menu changes the type and checks the product again as that type')
    # v2.34: the type line only when the app guessed the type and is not sure
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.click('#cardLabel'); pg.evaluate("() => { const f = document.getElementById('textFold'); f.hidden = false; f.open = true; }")
    pg.fill('#labelText', 'Ingredients: Aqua, Glycerin, Sugar, Salt, Citric Acid, Xqzvbt Lomrha'); pg.wait_for_timeout(800)
    pg.click('#checkLabel'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.is_visible('#typeChip') and 'tap if wrong' in pg.inner_text('#typeChip'), 'v2.34: a guessed, unsure type shows the type line "… ▾ tap if wrong"')
    pg.click('#typeChip'); pg.click('#typeRow .seg:has-text("Cosmetic")'); pg.wait_for_selector('#answer .qkind')
    ok(pg.evaluate('LC.state.current.p.kind') == 'cosmetic' and pg.locator('#typeChip').count() == 0, 'v2.34: after choosing, the type line goes away')
    # F1: a photo read with too few names or a cut end is never "No warnings"
    v = pg.evaluate("""() => ({
      few: LC.analyze({ kind: 'cosmetic', ingredientsText: 'Ingredients: Aqua', read: { photo: true, list: true } }).verdict,
      cut: LC.analyze({ kind: 'cosmetic', ingredientsText: 'Ingredients: Aqua, Glycerin, Alcohol, Menthol, Limonene,', read: { photo: true, list: true } }).verdict,
      full: LC.analyze({ kind: 'cosmetic', ingredientsText: 'Ingredients: Aqua, Glycerin, Alcohol, Menthol, Limonene', read: { photo: true, list: true } }).verdict,
      blur: LC.analyze({ kind: 'food', ingredientsText: 'Bestandteile: Vlpoly, lumsalz, Dinatriumsalz, Natriumchlorid, Wasser', read: { photo: true, list: true, conf: 58 } }).verdict,
      sure: LC.analyze({ kind: 'food', ingredientsText: 'Bestandteile: Vlpoly, lumsalz, Dinatriumsalz, Natriumchlorid, Wasser', read: { photo: true, list: true, conf: 73 } }).verdict,
      typed: LC.analyze({ kind: 'cosmetic', ingredientsText: 'Ingredients: Aqua' }).verdict })""")
    ok(v['few'] == 'partial' and v['cut'] == 'partial' and v['full'] != 'partial' and v['typed'] != 'partial' and v['blur'] == 'partial' and v['sure'] == 'ok', 'v2.16.1: read confidence under 66 is grey, 73 is not; v2.15: photo read with 1 name or a cut end is grey, a full list is not, typed text is not (%s)' % v)
    ctx.close()

    # v2.16: two photos of a round bottle: the second read is joined to the first
    ctx, pg = new_page(b, base, 'en-GB')
    pg.evaluate('LC.dbReady')
    j = pg.evaluate("""() => [LC.joinParts('Ingredients: Aqua, Glycerin, Alcohol, Menthol', 'Alcohol, Menthol, Limonene, Aroma'),
      LC.joinParts('Ingredients: Aqua, Glycerin, Sodium Lauroyl Sarco-', 'sinate, Limonene'), LC.joinParts('Aqua, Glycerin', 'Limonene, Aroma'), LC.joinParts('', 'Aqua')]""")
    ok(j == ['Ingredients: Aqua, Glycerin, Alcohol, Menthol, Limonene, Aroma', 'Ingredients: Aqua, Glycerin, Sodium Lauroyl Sarcosinate, Limonene', 'Aqua, Glycerin, Limonene, Aroma', 'Aqua'],
       'v2.16: two photos are joined (overlap removed, split word mended) (%s)' % j)
    pg.click('#cardLabel'); pg.set_input_files('#photoPick', photo); pg.wait_for_selector('#ocrArea:not([hidden])')
    pl = pg.evaluate("() => { const r = id => document.getElementById(id).getBoundingClientRect(); return { vh: innerHeight, check: r('checkBar').bottom, again: r('againRow').bottom, img: r('cropImg').bottom, title: getComputedStyle(document.getElementById('labelTitle')).display, nav: document.querySelector('nav') ? document.querySelector('nav').getBoundingClientRect().top : 0 } }")
    pl2 = pg.evaluate("() => { const s = document.getElementById('ocrStatus'); s.hidden = false; s.textContent = 'Looking for the ingredient list… · photo 5 of 8'; const r = id => document.getElementById(id).getBoundingClientRect(); const o = { status: r('ocrStatus').bottom, checkTop: r('checkBar').top, doc: document.documentElement.scrollHeight - innerHeight }; s.hidden = true; return o }")
    ok(pl2['status'] <= pl2['checkTop'] + 1, 'v2.18.2: while reading ("photo 5 of 8") the status line is above the Check bar, no scrolling needed (%s)' % pl2)
    ok(pl['title'] == 'none' and pl['again'] <= pl['vh'] and pl['check'] <= pl['vh'] and pl['img'] < pl['check'], 'v2.18: the photo screen (picture, box, Another photo, Check) fits one screen (%s)' % pl)
    gk = pg.evaluate("(tx) => LC.guessKind(tx)", "Glycerin, Pantuene Cetyl Alcohol, Glyceryl Stearate, Dicaprylyl Ether, Propyl Myristate, Allantoin, Caprylyl Glycol, Caprylhydroxamic Acid, Citric Acid, Panthenol, Sodium Hydroxide, Aqua, Parfum")
    ok(gk and gk['kind'] == 'cosmetic', 'v2.20.3: a cream list with Glycerin / Citric Acid (also food) is typed Cosmetic by its cosmetic-only names (%s)' % gk)
    gw = pg.evaluate("(tx) => LC.guessKind(tx)", "Wasser, Zucker, Salz, Glycerin, Zitronensäure, Aroma, Sonnenblumenöl, Weizenmehl")
    ok(gw and gw['kind'] == 'food', 'v2.21: plain German food words (Wasser, Zucker, Weizenmehl ...) are typed Food by the names file (%s)' % gw)
    gb = pg.evaluate("(tx) => LC.guessKind(tx)", "Декстрати, Мента, Манитол, Лимонена киселина, Захар, Вода")
    ok(gb and gb['kind'] == 'food', 'v2.21: Bulgarian food / sweet names are typed Food (%s)' % gb)
    gf = pg.evaluate("(tx) => LC.guessKind(tx)", "Zucker, Weizenmehl, Palmfett, Kakaopulver, Emulgator Sojalecithin, Salz, Backtriebmittel Natriumcarbonate, Aroma, Magermilchpulver")
    ok(gf and gf['kind'] == 'food', 'v2.20.3: a food list stays Food (%s)' % gf)
    ok(pg.is_visible('#secondPhoto') and 'round bottle' in pg.inner_text('#secondPhoto'), 'v2.16: "Add 2nd photo (round bottle)" next to "Another photo"')
    pg.evaluate("LC.showProduct({code:'label-x', kind:'food', source:'label', name:'x', ingredientsText:'Zutaten: Aqua', read:{photo:true, list:true}, texts:['Zutaten: Aqua'], tags:[], allergens:[], analysis:[], fetchedAt:Date.now()})")
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.is_visible('#secondBtn') and 'Incomplete' in word(pg), 'v2.16: a grey photo result offers "Add 2nd photo" (%s)' % word(pg))
    ctx.close()

    # ---------- v2.21.1: reader fixes (glued names, wrong big fix, sentence lines) ----------
    ctx, pg = new_page(b, base, 'en-GB')
    rr = pg.evaluate("(t) => LC.repairNames(t)", "GLYCER PROPYL MYRISTATE; ALLA SODIUM CETEARYL SULFF MIC ACID; CITRIC ACID; ALLANTOIN; HELIANTHUS ANI tYL SULFATE; CAPRYLYL GLYCOL; C ACID; SODIUM HYDROXIDE.; GLYCERIN; PANTHENOL; DICAPRYLYL ETHER; I$0- IANTHUS ANNUUS HYBRID Oil YL GLYCOL; ISO 1ELIANTHUS ANNUUS HYBRID OIL RYLYL GLYCOL; tzt das ,Gleichgewicht der er intakten Hautbarriere")
    ok('ISOPROPYL MYRISTATE' in rr and 'SODIUM CETEARYL SULFATE' in rr and 'HELIANTHUS ANNUUS HYBRID OIL' in rr, 'v2.21.1: names glued with noise ("PROPYL MYRISTATE", "SODIUM CETEARYL SULFF", cut "IANTHUS ANNUUS ...") are found inside the block (%s)' % rr)
    ok('tzt' not in rr.lower() and 'gleichgewicht' not in rr.lower(), 'v2.21.1: a sentence line of the label is no ingredient')
    ok(rr.upper().count('CAPRYLYL GLYCOL') == 1 and 'YL GLYCOL' not in rr.replace('CAPRYLYL GLYCOL', ''), 'v2.21.1: a cut piece of a name that is already in the list ("YL GLYCOL") is dropped, the name stays once')
    mc = "Ingredients: Sugar, wheat flour, palm oil, salt, flavouring. May contain traces of milk and hazelnuts."
    ok(pg.evaluate("(t) => LC.repairNames(t)", mc) == mc, 'v2.21.1: "May contain traces of ..." is never dropped as a sentence')
    ok(pg.evaluate("(t) => LC.repairNames(t)", "Emulgator: Lecithin, GLYCER PROPYL MYRISTATE, Aqua") == "Emulgator: Lecithin, GLYCER, ISOPROPYL MYRISTATE, Aqua", 'v2.21.1: a name with a colon at the start is not taken as a heading (no doubled word)')
    gn = pg.evaluate("(l) => l.map(x => LC.garbledName(x))", ["XPAHMTENIHA VH®OPMALLUR M CbCTAB B EAMHMUNA N03A", "MATHE3IMER EUCTTIMUMHAT", "Sugar", "Wheat flour (Wheat, Calcium carbonate)", "E150d", "Vitamin B12", "Soy lecithin (E322)", "H2O2 (hydrogen peroxide)", "NaCl", "Mono- und Diglyceride von Speisefettsäuren"])
    ok(gn[:2] == [True, True] and not any(gn[2:]), 'v2.21.2: nonsense text is "garbled", normal names (E150d, B12, NaCl, H2O2 ...) are not (%s)' % gn)
    gv = pg.evaluate("(t) => { const a = LC.analyze({ kind: 'food', ingredientsText: t, read: { photo: true, list: true, conf: 80 } }); return { v: a.verdict, n: a.counts.nodata, g: a.counts.green } }", "Ingredients: XPAHMTENIHA VH®OPMALLUR N03A, MATHE3IMER EUCTTIMUMHAT 14%, MATHE3MEB BUCTTIMUMHAT NOCTABALL, Sugar, Salt")
    ok(gv['n'] == 3 and gv['g'] == 2 and gv['v'] == 'partial', 'v2.21.2: food: 3 nonsense rows are "No data" (grey), not green; the verdict is "Incomplete" (%s)' % gv)
    gc = pg.evaluate("(t) => { const a = LC.analyze({ kind: 'food', ingredientsText: t, read: { photo: true, list: true, conf: 80 } }); return { v: a.verdict, n: a.counts.nodata } }", "Ingredients: Sugar, Wheat flour, Palm oil, Glucose syrup, Emulsifier: Soya lecithin, Colour: E150d, Vitamin B12, Salt")
    ok(gc['n'] == 0 and gc['v'] == 'ok', 'v2.21.2: a clean food list is not changed by the nonsense rule (%s)' % gc)
    ls = pg.evaluate("(t) => LCDB.labelSegments(t).segs", "Magnesium stearate, 500 MG, 48%, Silicon dioxide, 100 MG), 1,5 g")
    ok(ls == ['Magnesium stearate', 'Silicon dioxide'], 'v2.21.3: pieces that are only an amount (500 MG, 48 percent, 100 MG), 1,5 g) are no ingredients (%s)' % ls)
    ok(pg.evaluate("(l) => l.map(x => LC.isSupplementText(x))", ["2 tablets 500 mg magnesium bisglycinate 14% elemental magnesium 70 mg", "Food supplement. Other ingredients: cellulose", "Хранителна добавка", "Nahrungsergänzungsmittel", "Sugar, Salt, Wheat flour 5%", "Chocolate 30% cocoa, fat 5 g"]) == [True, True, True, True, False, False], 'v2.21.3: a supplement is seen by its doses or its words; a normal food is not')
    hd = pg.evaluate("(l) => l.map(x => LC.cleanOcr(x))", ["Hilfsstoffe: Mikrokristalline Cellulose, Magnesiumstearat", "ДРУГИ СЪСТАВКИ: целулоза, магнезиев стеарат", "Помощни вещества: целулоза, магнезиев стеарат", "Excipients: cellulose, silica", "Some noise here Excipients: cellulose, silica"])
    ok(hd[0].startswith('Hilfsstoffe:') and hd[2].startswith('Помощни вещества:') and hd[3].startswith('Excipients:') and hd[4].startswith('Excipients:') and hd[1].startswith('СЪСТАВКИ:'), 'v2.21.3: more headings start the list: Hilfsstoffe, Помощни вещества, Excipients, Други съставки (%s)' % hd)
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, 'Food supplement. 2 tablets 500 mg magnesium bisglycinate 14% elemental magnesium 70 mg. Other ingredients: microcrystalline cellulose, magnesium stearate, silicon dioxide', 'food')
    open_details(pg)
    ok('compared with the EU upper limits for adults' in pg.inner_text('#suppNote'), 'v2.21.3/v2.48: a supplement result says the amounts are compared with the EU upper limits (%s)' % pg.inner_text('#dtop')[:80])
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, 'Sugar, wheat flour, palm oil, salt', 'food')
    open_details(pg)
    ok(pg.locator('#suppNote').count() == 0, 'v2.21.3: a normal food result has no supplement note')
    ctx.close(); ctx, pg = new_page(b, base, 'bg-BG')
    read_label(pg, 'Хранителна добавка. Други съставки: целулоза, магнезиев стеарат', 'food')
    open_details(pg)
    ok('горните граници за възрастни' in pg.inner_text('#suppNote'), 'v2.21.3: the supplement note is in Bulgarian too')
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    # v2.22: tick-list for names the app cannot match, the capture hint and the closest-name helper
    ok(pg.evaluate("() => LCDB.closest('Glyxerxn', 3)") == ['GLYCERIN'] and pg.evaluate("() => LCDB.closest('Aqua', 3)") == [], 'v2.22: closest() gives the nearest known name, and nothing for a known or very short name')
    read_label(pg, 'Aqua, Glyxerxn, Lanolxxn, Cetyl Alcohol, Panthenol', 'cosmetic')
    pg.wait_for_selector('#readCard', timeout=20000)
    # v2.33: "What the app read" card (option B) replaces the v2.26 tick card
    ok(pg.locator('#readChips .chip').count() == 5 and pg.locator('#readChips .chip.q').count() == 2 and pg.inner_text('#readCard .rd-badge') == '2',
       'v2.33: all 5 names as tiles, 2 orange unclear tiles, badge 2 (%s)' % pg.inner_text('#readCard').replace('\n', ' | ')[:160])
    ok(pg.inner_text('#readCard .rd-top b') == 'What the app read' and pg.inner_text('#readGuess0') == 'Glycerin' and pg.evaluate("() => document.getElementById('readGuess0').classList.contains('btn-primary')"),
       'v2.33: title "What the app read"; the first unclear name is open, its best guess "Glycerin" is the blue button')
    ok(pg.evaluate("() => [...document.querySelectorAll('#readPanel .btn')].every(b => b.getBoundingClientRect().height >= 48) && [...document.querySelectorAll('#readChips button')].every(b => b.getBoundingClientRect().height >= 40)"),
       'v2.33: panel buttons are at least 48 px high, tiles at least 40 px')
    ok(pg.evaluate("() => !!(document.getElementById('readCard').compareDocumentPosition(document.getElementById('againBtn')) & Node.DOCUMENT_POSITION_FOLLOWING) && document.getElementById('answer').nextElementSibling.id === 'detBtn' && document.getElementById('detBtn').nextElementSibling.id === 'readCard'"),
       'v2.33 / v2.34: the card sits under the answer and its "Show all" link, before the bottom buttons')
    pg.click('#readGuess0'); pg.wait_for_timeout(600)
    ok(pg.locator('#readChips .chip.q').count() == 1 and pg.locator('#readChips .chip.fixed').count() == 1 and pg.inner_text('#readGuess0') == 'Lanolin' and 'Glycerin' in pg.inner_text('#readChips .chip.fixed'),
       'v2.33: one tap on the right name teaches it (tile green with a tick); the next unclear name opens (%s)' % pg.inner_text('#readCard').replace('\n', ' | ')[:160])
    pg.click('#readKeep'); pg.wait_for_timeout(600)
    ok(pg.locator('#readChips .chip.q').count() == 0 and pg.locator('#readPanel').count() == 0 and pg.locator('#readChips .chip.none').count() == 1 and pg.inner_text('#readCard .rd-badge') == '✓'
       and 'All unclear names checked' in pg.inner_text('#readCard') and pg.evaluate("LC.state.current.p.readKept.length") == 1,
       'v2.33: "Keep as read": the tile turns grey, no more unclear names, badge ✓, saved on the product only')
    pg.click('#readChips .chip.fixed'); pg.wait_for_timeout(600)
    ok(pg.locator('#readChips .chip.q').count() == 1 and pg.inner_text('#readGuess0') == 'Glycerin', 'v2.33: tapping a fixed tile undoes it (the name is unclear again)')
    ok(pg.evaluate("() => [LCDB.guessCosmetic('Helianthu us sed oil', 2)[0], LCDB.guessCosmetic('Caprylic/Capri erde', 2)[0], LCDB.guessCosmetic('Glycery ate', 2)[0], LCDB.guessCosmetic('Benzyl alchl', 2)[0], LCDB.guessCosmetic('Aqua', 2).length]")
       == ['HELIANTHUS ANNUUS SEED OIL', 'CAPRYLIC/CAPRIC TRIGLYCERIDE', 'GLYCERYL STEARATE', 'BENZYL ALCOHOL', 0], 'v2.33: better guesses for broken names (words cut short or lost), the common name first')
    ctx.close(); ctx, pg = new_page(b, base, 'de-DE')
    read_label(pg, 'Zutaten: Zuker, Kakaomase, Salz, Weizenmeh', 'food')
    pg.wait_for_selector('#readCard', timeout=20000)
    ok(pg.locator('#readChips .chip.q').count() == 2 and pg.inner_text('#readGuess0') == 'Zucker' and pg.locator('#readSearch').count() == 0 and pg.locator('#readChips .chip:not(.q):not(.none)').count() == 2,
       'v2.33: food: 2 misread names are unclear, guess "Zucker" from the food names; "Weizenmeh" (gluten found) is not unclear; no "Search" for food (%s)' % pg.inner_text('#readCard').replace('\n', ' | ')[:160])
    pg.click('#readGuess0'); pg.wait_for_timeout(600)
    ok(pg.evaluate("LC.state.current.p.ingredientsText").startswith('Zutaten: Zucker, Kakaomase') and pg.locator('#readChips .chip.fixed').count() == 1 and pg.inner_text('#readGuess0') == 'Kakaomasse',
       'v2.33: food: the tap changes the text of this product; the tile is green; the next name opens (%s)' % pg.evaluate("LC.state.current.p.ingredientsText"))
    pg.click('#readGuess0'); pg.wait_for_timeout(600)
    ok(pg.evaluate("LC.state.current.p.ingredientsText") == 'Zutaten: Zucker, Kakaomasse, Salz, Weizenmeh' and pg.locator('#readChips .chip.q').count() == 0 and pg.locator('#readChips .chip.fixed').count() == 2,
       'v2.33: food: both names fixed, no unclear name left (%s)' % pg.evaluate("LC.state.current.p.ingredientsText"))
    pg.click('#readChips .chip.fixed >> nth=0'); pg.wait_for_timeout(600)
    ok(pg.evaluate("LC.state.current.p.ingredientsText").startswith('Zutaten: Zuker,') and pg.locator('#readChips .chip.q').count() == 1, 'v2.33: food: tapping a fixed tile puts the read text back')
    ctx.close(); ctx, pg = new_page(b, base, 'bg-BG')
    READ = 'Калиум фосфорикум D6\nСъстав:\nВсяка таблетка съдържа:\nKalium phosphoricum (Калиум\nфосфорикум) D6 250 mg\nПомощни вещества:\nлактоза монохидрат,\nпшенично нишесте и др.\nРегистрационен No.: 20100164\nБез лекарско предписание.\nЗа перорална употреба.'
    main = pg.evaluate("(t) => LC.repairNames(LC.cleanOcr(t))", READ)
    left = pg.evaluate("([t, m]) => LC.leftOut([{ read: t }], m)", [READ, main])
    ok(left == ['Регистрационен No.: 20100164 Без лекарско предписание.', 'За перорална употреба.'], 'v2.33: text after the list end is "left out"; list names, headings and the product name are not (%s)' % left)
    r = pg.evaluate("(t) => { const c = LC.cleanOcr(t); return c; }", 'Състав: лактоза, пшенично нишесте и др Регистрационен номер 123')
    ok(r == 'Състав: лактоза, пшенично нишесте', 'v2.33: "и др" without the dot still ends the list when a new sentence follows (%s)' % r)
    read_label(pg, main, 'food')
    pg.wait_for_selector('#readCard', timeout=20000)
    pg.evaluate("(l) => { const p = LC.state.current.p; p.readLeft = l; LC.showProduct(p); }", left); pg.wait_for_timeout(500)
    ok(pg.locator('#readLeft .chip.left').count() == 2 and 'пропуснати: 2' in pg.inner_text('#readCard .rd-legend') and 'Какво прочете приложението' in pg.inner_text('#readCard'),
       'v2.33: left-out text as grey dashed tiles with +, in Bulgarian (%s)' % pg.inner_text('#readCard').replace('\n', ' | ')[:200])
    pg.click('#readLeft .chip.left >> nth=1'); pg.wait_for_timeout(600)
    ok(pg.evaluate("LC.state.current.p.ingredientsText").endswith(', За перорална употреба.') and pg.locator('#readLeft .chip.added').count() == 1, 'v2.33: + adds the text to the list; the tile turns green')
    pg.click('#readLeft .chip.added'); pg.wait_for_timeout(600)
    ok('перорална' not in pg.evaluate("LC.state.current.p.ingredientsText") and pg.locator('#readLeft .chip.added').count() == 0, 'v2.33: tapping it again takes it out')
    ctx.close()
    for dark, width in ((True, 390), (False, 320)):
        ctx, pg = new_page(b, base, 'de-DE', dark=dark, width=width)
        read_label(pg, 'Aqua, Glyxerxn, Lanolxxn, Cetyl Alcohol, Panthenol, Caprylic/Capri erde, Helianthu us sed oil', 'cosmetic')
        pg.wait_for_selector('#readCard', timeout=20000)
        ok(no_side_scroll(pg) and pg.inner_text('#readCard .rd-top b') == 'Was die App gelesen hat' and pg.evaluate("() => { const c = document.getElementById('readCard').getBoundingClientRect(); return c.right <= innerWidth + 0.5; }"),
           'v2.33: %s, %d px wide, German: the card fits, no side scroll' % ('dark' if dark else 'light', width))
        pg.screenshot(path=os.path.join(SHOTS, 'v233-readcard-%s-%d.png' % ('dark' if dark else 'light', width)), full_page=True)
        ctx.close()
    ctx, pg = new_page(b, base, 'en-GB')
    ok(pg.evaluate("() => LC.getRep ? 1 : 0") == 1, 'v2.22: report helper still exported')
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    good = "Aqua, Glycerin, Panthenol, Cetyl Alcohol, Glyceryl Stearate, Dicaprylyl Ether, Isopropyl Myristate, Allantoin, Helianthus Annuus Hybrid Oil, Sodium Cetearyl Sulfate, Caprylyl Glycol, Caprylhydroxamic Acid, Citric Acid, Sodium Hydroxide"
    ok(pg.evaluate("(t) => LC.repairNames(t)", good) == good, 'v2.21.1: a clean list is not changed')
    fl = "Zucker, Weizenmehl, Palmfett, Kakaopulver, Salz, Magermilchpulver, Emulgator Sojalecithin, Aroma"
    ok(pg.evaluate("(t) => LC.repairNames(t)", fl) == fl, 'v2.21.1: a food list is not changed')
    read_label(pg, 'Aqua, Glycerin, Cetyl Alcohol, Glyceryl Stearate, Panthenol, Allantoin, Citric Acid, Caprylhydrxmc Acid', 'cosmetic')
    ok(word(pg) == 'Check', 'v2.21.1: a name that needs a big fix (3 letters off) is a question (orange "Check"), not a green correction (%s)' % word(pg))
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, 'Aqua, Glycerin, Cetyl Alcohol, Glyceryl Stearate, Panthenol, Allantoin, Citric Acid, Caprylhydroxamc Acid', 'cosmetic')
    ok(word(pg) == 'No warnings', 'v2.21.1: a small fix (1 letter off) is still done by the app (%s)' % word(pg))
    ctx.close()

    # ---------- v2.17: in-app camera, sweep, "Your photos" ----------
    bcam = force_tess(p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']))
    cctx = bcam.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB', permissions=['camera'])
    pg = cctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('LC.dbReady')
    pg.click('#cardLabel'); pg.click('#takePhoto'); pg.wait_for_selector('#camVideo', state='visible'); pg.wait_for_timeout(1200)
    ok(pg.is_visible('#photoCam') and pg.is_visible('#shutter') and pg.is_visible('#modePhoto') and pg.is_visible('#modeSweep') and pg.is_hidden('#checkBar'), 'v2.17: "Take photo" opens the in-app camera (Photo / Sweep, big button, "Your photos", no Check bar before a photo)')
    pg.click('#shutter'); pg.wait_for_timeout(700); pg.click('#shutter'); pg.wait_for_timeout(700)
    ok(pg.locator('#thumbs .tn').count() == 2 and '2' in pg.inner_text('#partsHead') and pg.is_visible('#checkBar'), 'v2.17: two photos are kept and shown (small pictures 1, 2) and the Check bar appears')
    pg.click('#thumbs .tn >> nth=0 >> .tx')
    ok(pg.locator('#thumbs .tn').count() == 1, 'v2.17: the ✕ on a small picture removes that photo')
    ok(pg.evaluate("[...document.querySelectorAll('#thumbs .tn img')].every(i => i.complete && i.naturalWidth > 0)"), 'v2.17.1: the small pictures really show (real images, the page security rule blocks inline styles)')
    d = pg.evaluate("LC.dedupeNames('Aqua, Glycerin, Dodecylpoly(oxyethylen)-2-hydrogensulfat, Natriumsalz; Dodecylpoly(oxyethylen)-2-hydrogensul, Natrium salz; Glycerin')")
    cn = pg.evaluate("(fr) => LC.consensusNames(fr, { split: t => LCDB.splitIngredients(t), known: LC.nameKnown, dice: LC.bigramDice, ident: LC.nameIdent })", ["Sonstige Bestandteile: Dodecylpoly(oxyethylen)-2-hydrogensulfat, Natriumsalz; Dodecylpoly(oxyethylen)-2-hydrogensulfosuccinat, Dinatriumsalz; Poly(oxyethylen)-120-methyl(D-glucopyranosid)dioleat; Macrogolglycerolcocoate (Ph.Eur.) [7 EO-Einheiten]; Natriumhydroxid; Natriumchlorid; Ponceau 4R (E124); Salzsäure 10 % (in geringen Mengen zur pH-Wert-Einstellung); Kaliumsorbat; Natriumsulfat; Phenoxyethanol; Zitronensäure; gereinigtes Wasser. Zur Anwendung auf der Haut.", "Bestandteile: Do secy Ipolyloxyethylen)-2- hydroger Na “ıumsalz; Dodecylpolyloxyethyleni 3-h drogensulfosuccinat; Dinatriums Po! ‘oxyethylen)-120-methyl(D-glucopyranosid)dioleat; Macrogolglycerolcocoate Ph.Eur.) [7 EO-Einheiten]; Natriumhydroxid; Natriumchlorid; Ponce:. RIEI24); Kaliumsorbat; Natriumsulfat; Phenoxyethanol; Zitronensäure; gereinigtes Wasser", "Atrium ethylen)-1 20-methyl(D-gluc- h i .) En Macrogolglycerolce Oat: O-Einheiten]; © fatriumsulfat; Phenoxyetha“ säure; Gereinigtes Wasser aliumsorbat. BEI24); K:; Parkungsbeilage beachten", "Tridodecylammoniumpolypeptid (MMG 2000); Moniumpolypeptid (MMG 2000); Phenoxyethar: gereinigtes Wasser; Phenoxyetha: Kaliumsorbat"])
    need = ['Natriumchlorid', 'Kaliumsorbat', 'Ponceau 4R (E124)', 'Natriumsulfat', 'Phenoxyethanol', 'Natriumhydroxid', 'Zitronensäure']
    ok(all(x in cn for x in need) and not any('©' in x or '“' in x for x in cn) and 12 <= len(cn) <= 19 and sum(1 for z in cn if z.lower().startswith('phenoxyeth')) == 1 and not any(z.startswith('Moniumpolypeptid') for z in cn) and any('hydrogensulfat' in x for x in cn) and any('hydrogensulfosuccinat' in x for x in cn), 'v2.20: three garbled frames give clean names, none of the real names lost, Ponceau (E124) kept (%d names: %s)' % (len(cn), cn[:4]))
    ok(d.count('Dodecylpoly') == 1 and d.count('Glycerin') == 1 and 'Aqua' in d, 'v2.17.1: near-identical names from several pictures count once (%s)' % d)
    pg.click('#modeSweep'); pg.click('#shutter'); pg.wait_for_timeout(4200)
    ok('Move slowly' in pg.inner_text('#camHint'), 'v2.17: sweep: "Move slowly over the list · N pictures"')
    pg.click('#shutter'); pg.wait_for_timeout(1200)
    ok(pg.locator('#thumbs .tn').count() >= 1 and pg.evaluate("!document.getElementById('shutter').classList.contains('stop')"), 'v2.17: sweep adds a sharp picture and stops (%d photos)' % pg.locator('#thumbs .tn').count())
    # v2.27: standing still in front of one place = ONE photo (before: one every 1.6 s)
    import io, tempfile
    from PIL import Image
    import numpy as np
    tmpd = tempfile.mkdtemp(); still = os.path.join(tmpd, 'still.mjpeg')
    base_im = Image.new('RGB', (640, 360), (40, 40, 40))
    from PIL import ImageDraw
    dr = ImageDraw.Draw(base_im)
    for k in range(14): dr.text((20 + (k % 2) * 300, 20 + k * 22), 'Zutaten: Wasser, Zucker, Fruktose %d' % k, fill=(235, 235, 235))
    buf = b''
    for i in range(30):
        fr = Image.fromarray(np.clip(np.asarray(base_im).astype(float) + np.random.randn(360, 640, 3) * 3, 0, 255).astype('uint8')); bb = io.BytesIO(); fr.save(bb, 'JPEG', quality=85); buf += bb.getvalue()
    open(still, 'wb').write(buf)
    bst = force_tess(p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--use-file-for-fake-video-capture=' + still]))
    sctx = bst.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB', permissions=['camera']); sp = sctx.new_page(); sp.on('pageerror', lambda e: errors.append(str(e)))
    sp.goto(base); sp.evaluate('LC.dbReady'); sp.click('#cardLabel'); sp.click('#takePhoto'); sp.wait_for_selector('#camVideo', state='visible'); sp.wait_for_timeout(800)
    sp.click('#modeSweep'); sp.click('#shutter'); sp.wait_for_timeout(6000); sp.click('#shutter'); sp.wait_for_timeout(1500)
    ok(sp.locator('#thumbs .tn').count() == 1, 'v2.27: sweep: holding the phone on one place for 6 s gives 1 photo, not 4 (%d)' % sp.locator('#thumbs .tn').count())
    bst.close()
    ok(no_side_scroll(pg), 'v2.17: camera screen: no sideways scroll')
    lay = pg.evaluate("""() => { const r = id => document.getElementById(id).getBoundingClientRect(), cv = r('camView'), cb = r('checkBar');
      return { guide: !!document.querySelector('.camguide'), inView: ['shutter','camClose','camModes'].every(i => { const b = r(i); return b.top >= cv.top - 1 && b.bottom <= cv.bottom + 1; }),
        bottom: Math.max(cb.bottom, r('partsSum').bottom), vh: innerHeight, scrollable: document.documentElement.scrollHeight - innerHeight, title: getComputedStyle(document.getElementById('labelTitle')).display } }""")
    ok(not lay['guide'] and lay['inView'] and lay['title'] == 'none', 'v2.18: no white frame; shutter, ✕ and Photo/Sweep sit on the camera view; title hidden (%s)' % lay)
    ok(lay['bottom'] <= lay['vh'], 'v2.18: the whole camera menu (view, photos, Check bar) is on one screen at 390x844 (bottom %d of %d)' % (lay['bottom'], lay['vh']))
    pg.click('#camView', position={'x': 150, 'y': 150}); pg.wait_for_timeout(300)
    ok(pg.evaluate("document.getElementById('camVideo').srcObject != null"), 'v2.18: tapping the camera view does not break it (focus is best effort)')
    pg.go_back(); pg.wait_for_timeout(400)
    ok(pg.is_hidden('#photoCam') and pg.is_visible('#photoStart') and pg.is_visible('#labelPanel') and pg.evaluate("!document.getElementById('camVideo').srcObject"), 'v2.17: phone Back closes the camera and switches it off')
    pg.click('#takePhoto'); pg.wait_for_selector('#camVideo', state='visible'); pg.click('#camClose'); pg.wait_for_timeout(400)
    ok(pg.is_hidden('#photoCam') and pg.is_visible('#photoStart'), 'v2.17: "Close camera" goes back to the two photo cards')
    pg.set_input_files('#photoPick', [photo, photo]); pg.wait_for_timeout(500)
    ok(pg.locator('#thumbs .tn').count() == 2 and pg.is_hidden('#camVideo') and pg.is_visible('#checkBar'), 'v2.17: two photos chosen from the phone go to "Your photos" (no live view)')
    pg.click('#ocrRead'); pg.wait_for_function("document.getElementById('labelPanel').classList.contains('reading')", timeout=60000)
    rd = pg.evaluate("() => { const r = id => document.getElementById(id).getBoundingClientRect(); return { thumbs: document.querySelectorAll('#thumbs .tn').length, now: document.querySelectorAll('#thumbs .tn.now').length, cam: !document.getElementById('photoCam').hidden, x: document.querySelectorAll('#thumbs .tx').length && getComputedStyle(document.querySelector('#thumbs .tx')).display, checkBottom: r('checkBar').bottom, chk: getComputedStyle(document.getElementById('checkBar')).display, vh: innerHeight, again: getComputedStyle(document.getElementById('againRow')).display, bar: !document.getElementById('readBar').hidden, crop: getComputedStyle(document.getElementById('cropWrap')).display } }""")
    ok(rd['thumbs'] == 2 and rd['now'] == 1 and rd['cam'] and rd['x'] == 'none' and rd['again'] == 'none' and rd['chk'] == 'none' and rd['checkBottom'] <= rd['vh'] and rd['bar'] and rd['crop'] == 'none', 'v2.19: progress bar shows, the big picture is hidden, no jumping; v2.18.3: while several photos are read, the small pictures stay on the same screen (the one being read is marked, no ✕) (%s)' % rd)
    pg.wait_for_selector('#result:not([hidden]) #answer', timeout=120000)
    ok(pg.is_hidden('#photoCam') and not pg.evaluate("document.getElementById('labelPanel').classList.contains('reading')"), 'v2.18.3: after reading the small pictures are gone and the result shows')
    pg.wait_for_selector('#result:not([hidden]) #moreBtn', timeout=20000)
    rp = pg.evaluate("async () => { const d = await LC.buildReport(true); const n = await LC.buildReport(false); return { v: d.version, kind: d.kind, verdict: !!d.verdict, frames: d.frames.length, f0: Object.keys(d.frames[0] || {}).sort().join(','), photos: (d.photos || []).length, noPhotos: !('photos' in n), text: d.text.length, rows: d.rows.length, bytes: JSON.stringify(d).length } }")
    ok(rp['v'].startswith('v2.') and rp['frames'] == 2 and rp['photos'] == 2 and rp['noPhotos'] and rp['text'] > 20 and rp['rows'] >= 1 and 'conf' in rp['f0'] and 'read' in rp['f0'], 'v2.21: the report has version, type, verdict, text of both photos (frames), the photos (and none when switched off) (%s)' % rp)
    pg.click('#moreBtn'); pg.wait_for_selector('#moreMenu')
    ok(pg.is_visible('#repPhotos') and pg.is_visible('#mSecond'), 'v2.21 / v2.34: in the ⋯ menu: "Send to Claude" with the "include photos" switch, and "Add 2nd photo"')
    with pg.expect_download(timeout=15000) as dl:
        pg.click('#repBtn')
    ok(dl.value.suggested_filename.startswith('label-check-for-claude-') and dl.value.suggested_filename.endswith('.txt'), 'v2.22: "Send to Claude" makes one .txt file (%s)' % dl.value.suggested_filename)
    cctx.close(); bcam.close()


    # ---- v2.23: the new reader (PaddleOCR) ----
    print('v2.23: PaddleOCR reader')
    bp = p.chromium.launch()
    ctx, pg = new_page(bp, base, 'en-GB')
    ok(pg.evaluate("localStorage.getItem('lc.ocrEngine')") is None, 'v2.23: the new reader is the default (nothing saved)')
    pg.click('#cardLabel'); pg.set_input_files('#photoPick', photo); pg.wait_for_selector('#ocrArea:not([hidden])')
    ok(pg.eval_on_selector_all('#ocrEngine option', 'o => o.map(x => x.value)') == ['paddle', 'tess'] and pg.input_value('#ocrEngine') == 'paddle', 'v2.23: Settings choice "Reader": New (Paddle) / Old (Tesseract)')
    ctx.close()
    ctx, pg = new_page(bp, base, 'en-GB')
    pg.click('#cardLabel')
    read_photo(pg)
    txt = pg.input_value('#labelText').lower()
    ok(txt.startswith('ingredients:') and all(w in txt for w in ('sugar', 'wheat flour', 'palm oil', 'lecithin', 'tartrazine', 'milk')), 'v2.23: Paddle reads the box and starts at "Ingredients:" (%s)' % txt[:80])
    ok('crunchy' not in txt and 'nutrition' not in txt, 'v2.23: Paddle: text outside the box is not read')
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok('Tartrazine' in pg.text_content('#result') or 'E102' in pg.text_content('#result'), 'v2.23: Paddle: the answer shows (tartrazine found)')
    res = pg.evaluate("performance.getEntriesByType('resource').map(e => e.name)")
    ok(any('/ocr-paddle/paddle-worker-4.js' in x for x in res) and not any('/ocr/' in x for x in res), 'v2.23: the Paddle worker was used, no Tesseract file was loaded')
    ok(pg.evaluate("LC.getRep().frames[0].engine") == 'paddle', 'v2.23: the report says which reader was used')
    ctx.close()
    ctx, pg = new_page(bp, base, 'bg-BG')
    seen = []                                                    # the worker's own requests (not in the page's resource list)
    ctx.route('**/ocr-paddle/**', lambda r: (seen.append(r.request.url), r.continue_()))
    pg.click('#cardLabel')
    read_photo(pg, lang='auto', file=photo_bg, box=(0.02, 0.44, 0.98, 0.62))
    txt = pg.input_value('#labelText').lower()
    ok('съставки' in txt and 'захар' in txt and 'лецитин' in txt, 'v2.23: Paddle reads a Cyrillic label by itself (no wrong-alphabet read) (%s)' % txt[:80])
    res = seen
    ok(any(x.endswith('/ocr-paddle/rec-eslav-5.onnx') for x in res) and any(x.endswith('/ocr-paddle/dict-eslav-5.txt') for x in res) and not any(x.endswith('/rec-eslav.onnx') for x in res),
       'v2.33: the Cyrillic reader is the new one (rec-eslav-5.onnx + dict-eslav-5.txt)')
    ctx.close()
    # v2.33: a Bulgarian label with Latin names in it (like the tablets): no word mixes the two alphabets, "mg" stays "mg"
    tab = Image.new('RGB', (1300, 560), (246, 247, 250)); dr = ImageDraw.Draw(tab)
    for i, line in enumerate(['Състав:', 'Всяка таблетка съдържа:', 'Kalium phosphoricum (Калиум', 'фосфорикум) D6 250 mg', 'Помощни вещества:', 'лактоза монохидрат,', 'пшенично нишесте и др.']):
        dr.text((50, 30 + i * 72), line, fill=(30, 40, 70), font=font(48))
    photo_tab = os.path.join(SHOTS, 'v233-tablets-bg.jpg'); tab.rotate(-2, expand=True, fillcolor=(246, 247, 250)).save(photo_tab, quality=90)
    ctx, pg = new_page(bp, base, 'bg-BG')
    pg.click('#cardLabel')
    read_photo(pg, lang='auto', file=photo_tab, box=(0.01, 0.01, 0.99, 0.99))
    txt = pg.input_value('#labelText')
    import re as _re
    mixed = [w for w in _re.findall(r'[^\W\d_]+', txt) if _re.search('[а-яА-Я]', w) and _re.search('[a-zA-Z]', w)]
    ok(not mixed and 'Kalium phosphoricum' in txt and 'Калиум' in txt and '250 mg' in txt and 'пшенично нишесте' in txt,
       'v2.33: Bulgarian label with Latin names: read without mixed words, "250 mg" kept (mixed: %s) (%s)' % (mixed, txt[:120]))
    ctx.close()
    # ---- v2.31: curved and tilted lines are straightened before reading ----
    print('v2.31: curved lines')
    import numpy as np, base64
    flat = Image.new('RGB', (1400, 520), (250, 248, 240)); dr = ImageDraw.Draw(flat)
    CURVE = ['Ingredients: Sugar, wheat flour, palm oil, glucose', 'syrup, emulsifier: soya lecithin, colour:', 'tartrazine, salt, flavouring. May contain', 'traces of milk and hazelnuts.']
    for i, line in enumerate(CURVE): dr.text((60, 60 + i * 100), line, fill=(25, 25, 25), font=font(50))
    a = np.asarray(flat); H, W = a.shape[:2]
    shift = (70 * ((np.arange(W) - W / 2) / (W / 2)) ** 2).astype(int)      # like a round bottle: the line ends bend
    bent = np.full((H + 100, W, 3), (250, 248, 240), np.uint8)
    for x in range(W): bent[80 - shift[x]:80 - shift[x] + H, x] = a[:, x]
    curved = os.path.join(SHOTS, 'v231-curved-label.jpg')
    Image.fromarray(bent).rotate(-4, expand=True, fillcolor=(250, 248, 240)).save(curved, quality=90)
    WORDS = ['sugar', 'wheat flour', 'palm oil', 'glucose', 'soya lecithin', 'emulsifier', 'tartrazine', 'flavouring', 'milk', 'hazelnuts']
    ctx, pg = new_page(bp, base, 'en-GB')
    pg.click('#cardLabel')
    read_photo(pg, file=curved, box=(0.01, 0.01, 0.99, 0.99))
    txt = pg.input_value('#labelText').lower()
    ok(sum(w in txt for w in WORDS) == len(WORDS), 'v2.31: a curved, tilted label: all 10 names read (%d) (%s)' % (sum(w in txt for w in WORDS), txt[:90]))
    b64 = base64.b64encode(open(curved, 'rb').read()).decode()
    r = pg.evaluate("""async ([b64]) => { const w = new Worker('ocr-paddle/paddle-worker-4.js'), out = {};
      for (const straight of [false, true]) {
        const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        const m = await new Promise(res => { w.onmessage = e => { if (!e.data.step) res(e.data); }; w.postMessage({ id: straight ? 2 : 1, image: bin, lang: 'eng', straight }, [bin.buffer]); });
        out[straight ? 'on' : 'off'] = { text: (m.text || '').toLowerCase(), straight: m.straight };
      }
      w.terminate(); return out; }""", [b64])
    on, off = sum(w in r['on']['text'] for w in WORDS), sum(w in r['off']['text'] for w in WORDS)
    ok(on == len(WORDS) and off <= 6 and r['on']['straight'] >= 4 and r['off']['straight'] == 0,
       'v2.31: the same label without straightening reads only %d of 10 names; with it %d (%d lines straightened)' % (off, on, r['on']['straight']))
    ctx.close()
    ctx, pg = new_page(bp, base, 'en-GB')
    ctx.route('**/ocr-paddle/**', lambda r: r.abort())
    pg.click('#cardLabel')
    read_photo(pg)
    txt = pg.input_value('#labelText').lower()
    ok('tartrazine' in txt and pg.evaluate("LC.getRep().frames[0].engine") == 'tess', 'v2.23: Paddle files missing (offline, first use): the old reader takes over (%s)' % txt[:60])
    ctx.close()
    bp.close()


    # ---- v2.24: several languages on the pack: English list first, then Cyrillic, then the first one ----
    print('v2.24: list language priority')
    ctx, pg = new_page(b, base, 'en-GB')
    def tsv(paras):
        rows = ['level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext']
        y = 10
        for bi, text in enumerate(paras):
            for wi, w in enumerate(text.split()):
                rows.append('\t'.join(['5', '1', str(bi + 1), '1', '1', str(wi + 1), str(10 + wi * 60), str(y), '55', '20', '90', w]))
            y += 80
        return '\n'.join(rows)
    def pick(paras):
        return pg.evaluate("(tsv) => LC.listPieces(LC.tsvPieces(tsv)).map(p => p.text).join(' | ')", tsv(paras))
    DE = 'Zutaten: Zucker, Weizenmehl, Salz, Palmfett, Kakaopulver.'; EN = 'Ingredients: sugar, wheat flour, salt, palm fat, cocoa powder.'; BG = 'Съставки: захар, пшенично брашно, сол, палмова мазнина, какао.'
    r = pick([DE, EN]); ok(r.startswith('Ingredients:') and 'Zutaten' not in r, 'v2.24: German first, English second: the English list is taken (%s)' % r[:40])
    r = pick([DE, BG]); ok(r.startswith('Съставки:') and 'Zutaten' not in r, 'v2.24: German and Bulgarian, no English: the Cyrillic list is taken')
    r = pick([BG, EN]); ok(r.startswith('Ingredients:'), 'v2.24: Bulgarian and English: English wins')
    r = pick([DE, 'Ingredients: sugar.']); ok(r.startswith('Zutaten:'), 'v2.24: an English list with fewer than 3 names does not win (%s)' % r[:40])
    r = pick([DE]); ok(r.startswith('Zutaten:'), 'v2.24: one list only: as before')
    r = pick([DE, 'Zutaten: Wasser, Zucker, Aroma.']); ok(r.startswith('Zutaten: Zucker'), 'v2.24: two lists in the same language: the first one, as before')
    c = pg.evaluate("(t) => LC.cleanOcr(t)", 'Zutaten: Zucker, Weizenmehl, Salz, Palmfett, Kakaopulver. Ingredients: sugar, wheat flour, salt, palm fat, cocoa powder. Sastojci: secer, brasno, sol, mast.')
    ok(c.startswith('Ingredients:') and 'Zucker' not in c and 'secer' not in c, 'v2.24: text with several languages: only the English list is kept (%s)' % c[:60])
    c = pg.evaluate("(t) => LC.cleanOcr(t)", 'Zutaten: Zucker, Weizenmehl, Salz, Palmfett, Kakaopulver. Sastojci: secer, brasno, sol, mast.')
    ok(c.startswith('Zutaten:') and 'secer' not in c, 'v2.24: no English or Cyrillic: the first list, as before')
    ctx.close()


    # ---- v2.25: known names inside running text (a toilet block label), contact lines, tick-list for household ----
    print('v2.25: names in running text')
    ctx, pg = new_page(b, base, 'en-GB')
    WC = "TOFFANGABEN: 30 % und darüber: anionische Tenside - unter 5 %: nichtionische Tenside - Duftstoffe - allergene : Menthol. Denkmit WC-Duftstein körbchenfrei Zitrus Traum Gefahr. SODIUM C14-16 OLEFIN SULFONATE, SODIUM C10-13 ALKYL BENZENESULFONATE. Enthält MENTHA ARVENSIS LEAF OIL. Kann allergische Reaktionen hervorrufen. Verursacht Hautreizungen. Verursacht schwere Augenschäden. Ist ärztlicher Rat erforderlich, Verpackung oder Kennzeichnungsetikett bereithalten. Darf nicht in die Hände von Kindern gelangen. Nach Gebrauch Hände gründlich waschen. BEI VERSCHLUCKEN: Sofort GIFTINFORMATIONSZENTRUM/ Arzt anrufen. BEI BERÜHRUNG MIT DER HAUT: Mit viel Wasser und Seife waschen. BEl KONTAKT MIT DEN AUGEN: Einige Minuten lang behutsam mit Wasser spülen. Eventuell vorhandene Kontaktlinsen nach Möglichkeit entfernen. Weiter spülen. UFI: 8MAM-5EET-N10D-XGHV dm-drogerie markt GmbH + Co. KG, Am dm-Platz 1, DE-76227 Karlsruhe, Tel. 0800 3658633, www.dm.de/denkmit, servicecenter@dm.de Vertrieb in Österreich: dm drogerie markt, Günter-Bauer-Straße 1, AT-5071 Wals, Tel. 0800 3658633, www.dm.at, kundenservice@dm.at K S LEERE VERPACKUNG? SCANNEN & TRENNEN www.cleanright.eu Duftsteine können variieren."
    rp = pg.evaluate("(t) => LC.repairNames(LC.cleanOcr(t))", WC)
    ok(rp == 'anionische tenside, nichtionische tenside, Duftstoffe, MENTHOL, SODIUM C14-16 OLEFIN SULFONATE, SODIUM C10-13 ALKYL BENZENESULFONATE, MENTHA ARVENSIS LEAF OIL', 'v2.25: the label of a toilet block: 4 names + 3 detergent-rule words kept, sentences and address dropped (%s)' % rp[:70])
    an = pg.evaluate("(t) => { const a = LC.analyze({ kind: 'household', ingredientsText: t }); return [a.known, a.unknown, a.verdict]; }", rp)
    ok(an[0] == 7 and an[1] == 0, 'v2.25: all 7 pieces are recognised (%s)' % an)
    ok(pg.evaluate("(t) => LC.repairNames(t)", 'Aqua, Glycerin, Tel. 0800 3658633, www.dm.at, Am dm-Platz 1, Parfum') == 'Aqua, Glycerin, Am dm-Platz 1, Parfum' or pg.evaluate("(t) => LC.repairNames(t)", 'Aqua, Glycerin, Tel. 0800 3658633, www.dm.at, Parfum') == 'Aqua, Glycerin, Parfum', 'v2.25: phone and web lines are no ingredients')
    tr = pg.evaluate("(t) => LC.repairNames(t)", 'Aqua, Glycerin, Kann Spuren von Sodium Laureth Sulfate enthalten und weiteren Stoffen aus der Produktion')
    ok('Kann Spuren' in tr, 'v2.25: a "may contain / traces" line keeps its words (%s)' % tr)
    ok(pg.evaluate("(t) => LC.repairNames(t)", 'AQUA, GLYCERIN, ISOPROPYL MYRISTATE ALLANTOIN HELIANTHUS ANNUUS HYBRID OIL, CITRIC ACID') == 'AQUA, GLYCERIN, ISOPROPYL MYRISTATE, ALLANTOIN, HELIANTHUS ANNUUS HYBRID OIL, CITRIC ACID', 'v2.25: a glued list keeps its short names (Allantoin) - only running text is cut down to the long names')
    ok(pg.evaluate("(t) => LC.repairNames(t)", 'Aqua, Glycerin, Panthenol, Parfum') == 'Aqua, Glycerin, Panthenol, Parfum', 'v2.25: a clean list is not changed')
    ctx.close()

    # ---- v2.28: share / import products, bigger store ----
    print('v2.28: share products')
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    pg.evaluate("""() => { const s = LC.state.products; s['4005808123456'] = { code: '4005808123456', kind: 'food', source: 'label', name: 'Test Riegel', brand: 'X', image: 'http://x/y.jpg', ingredientsText: 'Zucker, Wasser, Salz', texts: ['Zucker, Wasser, Salz'], tags: [], allergens: [], analysis: [], fetchedAt: 1 };
      s['label-99'] = { code: 'label-99', kind: 'food', source: 'label', name: 'No barcode', ingredientsText: 'Mehl', texts: ['Mehl'], fetchedAt: 2 };
      s['5000000000017'] = { code: '5000000000017', kind: 'food', source: 'off', name: 'From the list', ingredientsText: 'Milch', texts: ['Milch'], fetchedAt: 3 };
      localStorage.setItem('lc.products', JSON.stringify(s)); }""")
    pg.click('.tabbar button[data-go=list]'); open_card(pg, 'ghCard')
    with pg.expect_download() as dl:
        pg.click('#shareProdBtn')
    shared = os.path.join(SHOTS, 'shared-products.json'); dl.value.save_as(shared)
    sh = json.load(open(shared, encoding='utf-8'))
    ok(sh.get('kind') == 'products' and [x['code'] for x in sh['products']] == ['4005808123456'] and 'image' not in sh['products'][0] and 'avoid' not in sh, 'v2.28: the products file has only the read product with a barcode: no photo, no settings, no online-list products (%s)' % [x.get('code') for x in sh.get('products', [])])
    ctx.close(); ctx, pg = new_page(b, base, 'en-GB')
    ok(pg.evaluate("Object.keys(LC.state.products).length") == 0, 'v2.28: fresh phone has no products')
    pg.click('.tabbar button[data-go=list]'); open_card(pg, 'ghCard')
    pg.set_input_files('#prodInput', shared); pg.wait_for_timeout(600)
    got = pg.evaluate("LC.state.products['4005808123456']")
    ok(got and got['ingredientsText'] == 'Zucker, Wasser, Salz' and got['source'] == 'label' and got['name'] == 'Test Riegel', 'v2.28: import adds the product (%s)' % (got or {}).get('name'))
    pg.evaluate("LC.state.products['4005808123456'].ingredientsText = 'Mine'")
    pg.set_input_files('#prodInput', shared); pg.wait_for_timeout(600)
    ok(pg.evaluate("LC.state.products['4005808123456'].ingredientsText") == 'Mine' and 'skipped' in pg.inner_text('#toast'), 'v2.28: importing again does not overwrite your own copy ("skipped")')
    bad = os.path.join(SHOTS, 'bad.json'); open(bad, 'w').write('{"app":"label-check","kind":"backup"}')
    pg.set_input_files('#prodInput', bad); pg.wait_for_timeout(500)
    ok('not a Label Check products file' in pg.inner_text('#toast'), 'v2.28: a wrong file is refused')
    # the phone storage is full before the limit: the app makes room instead of losing the new product
    pg.evaluate("""() => { for (let i = 0; i < 30; i++) LC.state.products['4000000000' + (100 + i)] = { code: '4000000000' + (100 + i), kind: 'food', source: 'off', ingredientsText: 'y'.repeat(2000), texts: [], fetchedAt: i };
      localStorage.setItem('lc.products', JSON.stringify(LC.state.products));
      for (const size of [100000, 1000, 10]) { const fill = 'x'.repeat(size); let n = 0; try { for (;;) { localStorage.setItem('lc.fill' + size + '_' + n, fill); n++; } } catch (e) { /* full */ } } }""")
    fp = os.path.join(SHOTS, 'one.json'); open(fp, 'w').write(json.dumps({'app': 'label-check', 'kind': 'products', 'version': 1, 'products': [{'code': '4005808777777', 'kind': 'food', 'name': 'Newcomer', 'ingredientsText': 'Zucker, Salz ' + 'abc ' * 200}]}))
    pg.set_input_files('#prodInput', fp); pg.wait_for_timeout(800)
    r = pg.evaluate("() => ({ mem: !!LC.state.products['4005808777777'], stored: (localStorage.getItem('lc.products') || '').includes('4005808777777'), n: Object.keys(LC.state.products).length })")
    ok(r['mem'] and r['stored'] and r['n'] < 31, 'v2.28: storage full: the oldest online-list products make room, the new product is saved (%s)' % r)
    ctx.close()
    # ---- v2.29: "Instead" from the same category (your saved products first, then the database) ----
    print('v2.29: Instead from the same category')
    ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, 'Zutaten: Haferflocken 100 %, Salz, Zimt', 'food'); rename(pg, 'Haferflocken')
    del ALT_SEARCHES[:]
    pg.click('.tabbar button[data-go=scan]'); type_code(pg, '9001234500008'); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(700)
    alts = pg.eval_on_selector_all('#answer .qalt:not([hidden]) .altbtn', 'n => n.map(x => x.textContent)')
    ok(word(pg) == 'Check' and alts == [] and len(ALT_SEARCHES) == 1 and ALT_SEARCHES[0]['cat'] == 'en:snacks|en:sweet-snacks|en:chocolates',
       'v2.30: a chocolate bar, the database has no other one, you saved only oats -> no "Instead" line (not the oats) (%s, %d searches)' % (alts, len(ALT_SEARCHES)))
    del ALT_SEARCHES[:]
    pg.click('.tabbar button[data-go=scan]'); type_code(pg, '9001234500001'); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_selector('#qalt:not([hidden])')
    alts = pg.eval_on_selector_all('#answer .altbtn', 'n => n.map(x => x.textContent)')
    ok(word(pg) == 'Check' and alts == ['Example Bio Geflügelwurst', 'Example Putenwurst natur'],
       'v2.29: a salami with nitrite -> two sausages from the database with "No warnings" under YOUR rules, shown with the brand; not the product itself, not the one with E250, not the one without a list, no double name, not the oats (%s)' % alts)
    ok(card_fits(pg) and no_side_scroll(pg), 'v2.29: the card still fits at 390 px with two database names')
    ok([s['cat'] for s in ALT_SEARCHES] == ['en:prepared-meats|en:sausages|en:salami'] and ALT_SEARCHES[0]['countries'] == 'austria|germany|bulgaria' and ALT_SEARCHES[0]['sort'] == 'unique_scans_n' and ALT_SEARCHES[0]['host'] == 'world.openfoodfacts.org',
       'v2.29: ONE search for the three deepest categories; Austria, Germany or Bulgaria; most scanned first; the ham in the answer is not offered (%s)' % ALT_SEARCHES)
    ok(pg.evaluate("LC.state.products['9001234500003'] === undefined"), 'v2.29: a suggestion is not saved until you open it')
    open_details(pg); pg.click('.tabbar button[data-go=history]'); pg.click('.tabbar button[data-go=scan]')
    pg.evaluate("LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])')
    ok(len(ALT_SEARCHES) == 1, 'v2.29: showing the product again asks nothing new (%d searches)' % len(ALT_SEARCHES))
    # Open Food Facts refuses a part of the searches (503): the app tries again, twice at most
    del ALT_SEARCHES[:]; ALT_FAIL['n'] = 2
    pg.evaluate("LC.altCache.clear(); LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])', timeout=6000)
    alts = pg.eval_on_selector_all('#answer .altbtn', 'n => n.map(x => x.textContent)')
    ok(len(ALT_SEARCHES) == 3 and alts == ['Example Bio Geflügelwurst', 'Example Putenwurst natur'], 'v2.29: two refused searches (503), the third answer is used (%d searches, %s)' % (len(ALT_SEARCHES), alts))
    del ALT_SEARCHES[:]; ALT_FAIL['n'] = 5
    pg.evaluate("LC.altCache.clear(); LC.altTimes.length = 0; LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_timeout(4600)
    alts = pg.eval_on_selector_all('#answer .qalt:not([hidden]) .altbtn', 'n => n.map(x => x.textContent)')
    ok(len(ALT_SEARCHES) == 3 and alts == [], 'v2.30: three refused searches: it stops, no line (not the oats) (%d searches, %s)' % (len(ALT_SEARCHES), alts))
    pg.evaluate("LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_timeout(600)
    ok(len(ALT_SEARCHES) == 3, 'v2.29: after a refused search it does not ask again for a minute (%d searches)' % len(ALT_SEARCHES))
    # never more than 6 searches a minute
    del ALT_SEARCHES[:]; ALT_FAIL['n'] = 0
    pg.evaluate("LC.altCache.clear(); LC.altTimes.length = 0; for (let i = 0; i < 6; i++) LC.altTimes.push(Date.now()); LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_timeout(700)
    ok(len(ALT_SEARCHES) == 0, 'v2.29: 6 searches in the last minute: no new search (%d)' % len(ALT_SEARCHES))
    pg.evaluate("LC.altCache.clear(); LC.altTimes.length = 0; LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])'); pg.wait_for_timeout(300)
    del ALT_SEARCHES[:]
    pg.click('#answer .altbtn'); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(400)
    ok(pg.inner_text('#nameBtn') == 'Bio Geflügelwurst' and word(pg) == 'No warnings' and pg.evaluate("LC.state.products['9001234500003'].cats.join()") == 'en:meats,en:prepared-meats,en:sausages',
       'v2.29: a tap opens the suggested product with its own check; its categories are saved (%s)' % pg.inner_text('#nameBtn'))
    # your saved product of the same category comes first
    pg.evaluate("LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])'); pg.wait_for_timeout(300)
    alts = pg.eval_on_selector_all('#answer .altbtn', 'n => n.map(x => x.textContent)')
    ok(alts == ['Bio Geflügelwurst', 'Example Putenwurst natur'] and pg.evaluate("LC.sameCatSaved(LC.state.products['9001234500001']).map(q => q.name).join()") == 'Bio Geflügelwurst',
       'v2.29: your saved sausage is first, the database fills the second place (%s)' % alts)
    pg.click('.tabbar button[data-go=scan]'); type_code(pg, '9001234500007'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'No warnings' and pg.locator('#answer .qalt').count() == 0, 'v2.29: no "Instead" on a product without warnings')
    pg.evaluate("LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])'); pg.wait_for_timeout(300)
    ok(pg.evaluate("LC.sameCatSaved(LC.state.products['9001234500001']).map(q => q.name).join()") == 'Bio Geflügelwurst'
       and pg.evaluate("LC.catScore(LC.state.products['9001234500001'], LC.state.products['9001234500003'])") == 0.6 and pg.evaluate("LC.catScore(LC.state.products['9001234500001'], LC.state.products['9001234500007'])") == 0.3,
       'v2.30: your saved sausage counts as the same shelf for a salami (0.6), your saved ham (0.3) and the oats do not (%s)' % pg.evaluate("LC.sameCatSaved(LC.state.products['9001234500001']).map(q => q.name).join()"))
    r = pg.evaluate("""(() => { const P = (name, cats) => ({ code: 'x', name, cats }); const coke0 = P('Coke zero', ['en:carbonated-drinks', 'en:flavoured-soft-drinks', 'en:diet-beverages', 'en:sodas', 'en:colas', 'en:diet-sodas', 'en:diet-cola-soft-drink', 'en:sweetened-beverages']);
      return [LC.catScore(coke0, P('Cola', ['en:beverages', 'en:carbonated-drinks', 'en:sodas', 'en:colas', 'en:sweetened-beverages'])), LC.catScore(coke0, P('Eistee', ['en:beverages', 'en:iced-teas', 'en:sweetened-beverages'])), LC.catScore(coke0, P('x', [])), LC.catScore(P('y', []), coke0)]; })()""")
    ok(r == [0.5, 0.22, 0, 0], 'v2.30: a broad category at the end of the list ("sweetened beverages") is not enough: another cola 0.5, an iced tea 0.22 (%s)' % r)
    pg.evaluate("LC.altCache.clear()")
    ALT_PRODUCTS['9001234500005']['product_name'] = 'Bio Geflügelwurst 2 x 150 g'
    pg.evaluate("LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])'); pg.wait_for_timeout(400)
    alts = pg.eval_on_selector_all('#answer .altbtn', 'n => n.map(x => x.textContent)')
    ok(alts == ['Bio Geflügelwurst', 'Example Putenwurst natur'], 'v2.30: the same name in another pack size ("... 2 x 150 g") is not offered a second time (%s)' % alts)
    ALT_PRODUCTS['9001234500005']['product_name'] = 'Bio Geflügelwurst'
    # your own rule decides: mustard on your list removes the sausage with mustard
    pg.evaluate("localStorage.setItem('lc.avoid', JSON.stringify([{id:'a1', text:'senf'}])); localStorage.setItem('lc.history', JSON.stringify(LC.state.history.filter(h => h.code === '9001234500001'))); 0"); reload_ready(pg)
    pg.evaluate("LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#qalt:not([hidden])'); pg.wait_for_timeout(300)
    mustard_free = pg.evaluate("(async () => (await LC.suggestAlternatives(LC.state.products['9001234500001'], [])).map(q => q.code + ' ' + q.name))()")
    ok(mustard_free == ['9001234500005 Bio Geflügelwurst', '9001234500006 Putenwurst natur'], 'v2.29: "senf" on your list: the sausage with mustard is not suggested, the one without mustard is (%s)' % mustard_free)
    # offline: nothing is asked, your saved products only
    del ALT_SEARCHES[:]
    ctx.set_offline(True)
    pg.evaluate("LC.altCache.clear(); LC.showProduct(LC.state.products['9001234500001'])"); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(400)
    ok(len(ALT_SEARCHES) == 0 and pg.locator('#answer .qalt:not([hidden]) .altbtn').count() == 0, 'v2.29: offline: no search, no line when you have no saved product of this type (%d searches)' % len(ALT_SEARCHES))
    ctx.set_offline(False)
    # an old saved product (before v2.29, no categories) is asked again once when you scan it
    pg.evaluate("(() => { const p = LC.state.products['9001234500001']; delete p.cats; p.name = 'old name'; localStorage.setItem('lc.products', JSON.stringify(LC.state.products)); })()"); reload_ready(pg)
    type_code(pg, '9001234500001'); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(400)
    ok(pg.evaluate("Array.isArray(LC.state.products['9001234500001'].cats) && LC.state.products['9001234500001'].name") == 'Salami scharf', 'v2.29: a product saved before v2.29 gets its categories at the next scan')
    ctx.close()
    # ---- v2.32: tablets (25 Nov report): the list is cut at "и др.", sub-headings split it, an allergen line is never dropped ----
    print('v2.32: tablets list')
    ctx, pg = new_page(b, base, 'en-GB')
    READ = 'Състав:\nВсяка таблетка съдържа:\nKalium phosphoricum (Kaлиym\nфосфорикум) D6 250 mg\nПомощни вещества:\nлактоза монохидрат,\nпшенично нишесте и др.\nРегистрационен №о.: 20100164\n\nБез лекарско предписание.\nЗа перорална употреба.\nПрочетете листовката преди\nупотреба\n\nДа се сьхранява на място'
    r = pg.evaluate("(t) => { const c = LC.repairNames(LC.cleanOcr(t)); return { c, segs: LCDB.labelSegments(c).segs, al: LCDB.checkFood(c).allergens.map(a => a.id) }; }", READ)
    ok(r['segs'] == ['Kalium phosphoricum (Kaлиym фосфорикум) D6 250 mg', 'лактоза монохидрат', 'пшенично нишесте'] and sorted(r['al']) == ['gluten', 'milk'],
       'v2.32: the tablets read as 3 names (active substance, lactose, wheat starch); milk AND gluten found; "Регистрационен…" not in the list (%s)' % r)
    r = pg.evaluate("(t) => LC.repairNames(LC.cleanOcr(t))", 'Zutaten: Wasser, Zucker. Hergestellt aus Weizenmehl und Gerste aus der Region, Salz')
    ok('Weizenmehl und Gerste' in r, 'v2.32: a sentence that names an allergen (Weizenmehl, Gerste) is kept, not dropped as running text (%s)' % r)
    r = pg.evaluate("(t) => LC.cleanOcr(t)", 'Zutaten: Weizenmehl, Zucker, Gewürze (Pfeffer, Senf etc.), Salz')
    ok(r == 'Zutaten: Weizenmehl, Zucker, Gewürze (Pfeffer, Senf etc.), Salz', 'v2.32: "etc." inside brackets does not end the list (%s)' % r)
    r = pg.evaluate("(t) => LC.cleanOcr(t)", 'Ingredients: Each tablet contains: Vitamin C 80 mg. Other ingredients: maltodextrin, magnesium stearate, etc. Store in a dry place.')
    ok(r == 'Ingredients: Vitamin C 80 mg., maltodextrin, magnesium stearate', 'v2.32: English: "Each tablet contains:" goes, "Other ingredients:" becomes a comma, "etc." ends the list (%s)' % r)
    # ---- v2.33: a word with Latin AND Cyrillic letters is a reader mistake; "тд" after a number is "mg" ----
    print('v2.33: mixed letters')
    MIX = {'Kaлиym': 'Калиум', 'Eucalyрtus': 'Eucalyptus', 'мaсло': 'масло', 'агeнти': 'агенти', 'тg': 'mg', 'Mentha': 'Mentha', 'захар': 'захар', 'Е330': 'Е330', 'Glycerin': 'Glycerin', 'sрецифичен': 'sрецифичен'}
    r = pg.evaluate("(ws) => ws.map(w => LC.fixMixed(w))", list(MIX))
    ok(r == list(MIX.values()), 'v2.33: mixed words take one alphabet; one-alphabet words and unclear ones stay (%s)' % r)
    r = pg.evaluate("(t) => LC.cleanOcr(t)", 'Съставки: имуноподдържащ комплекс - 90/180 тд, ментово масло - 0,65/1,3 тg, Glycerin 5 мг')
    ok('90/180 mg' in r and '1,3 mg' in r and '5 мг' in r, 'v2.33: "180 тд" / "1,3 тg" become "mg"; the Bulgarian "мг" stays (%s)' % r)
    ctx.close()
    # A real update: serve a copy of the app, change its sw.js (as a push does), ask the browser to check.
    import shutil, tempfile
    tmp = tempfile.mkdtemp()
    for f in ('index.html', 'style.css', 'i18n.js', 'db.js', 'app.js', 'manifest.json', 'sw.js', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png'): shutil.copy(os.path.join(ROOT, f), tmp)
    shutil.copytree(os.path.join(ROOT, 'data'), os.path.join(tmp, 'data'))
    class Quiet2(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
        def end_headers(self): self.send_header('Cache-Control', 'no-store'); super().end_headers()
    srv2 = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet2, directory=tmp))
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    base2 = 'http://127.0.0.1:%d/' % srv2.server_address[1]
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB')
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base2); pg.evaluate('navigator.serviceWorker.ready'); pg.reload(); pg.evaluate('LC.dbReady')
    ok(pg.evaluate('!!navigator.serviceWorker.controller') and pg.is_hidden('#updBar'), 'copy of the app: controlled, no update line yet')
    # v2.14.1: other apps on the same website (Pocket Docs, Sun Launcher) keep their offline copies after an update
    pg.evaluate("Promise.all(['pocketdocs-v7', 'sunlauncher-v1'].map(n => caches.open(n).then(c => c.put('/x', new Response('x')))))")
    swp = os.path.join(tmp, 'sw.js'); new_sw = open(swp, encoding='utf-8').read().replace("label-check-v69'", "label-check-test-update'")
    open(swp, 'w', encoding='utf-8').write(new_sw)
    pg.evaluate('navigator.serviceWorker.getRegistration().then(r => r.update())')
    pg.wait_for_selector('#updBar:not([hidden])', timeout=30000)
    ok(pg.is_visible('#updBar') and pg.inner_text('#updReload') == 'Reload', 'after a new version took over: "A new version is ready. Reload"')
    for i in range(50):   # the new worker takes over first; the old cache goes a moment later (after its reader files are copied)
        keys = pg.evaluate('caches.keys()')
        if 'label-check-v69' not in keys: break
        pg.wait_for_timeout(300)
    ok('pocketdocs-v7' in keys and 'sunlauncher-v1' in keys and 'label-check-v69' not in keys and 'label-check-test-update' in keys,
       'v2.14.1: the update deletes only the old Label Check cache; Pocket Docs / Sun Launcher caches stay (%s)' % keys)
    ctx.close(); srv2.shutdown(); shutil.rmtree(tmp, ignore_errors=True)

    # ---- v2.34: new look (start B, result B, history B, ⋯ menu, calmer colours) ----
    print('v2.34: new look')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    ok(pg.evaluate("getComputedStyle(document.body).backgroundColor") == 'rgb(15, 17, 21)', 'calmer dark background #0F1115')
    ok(pg.inner_text('.startq') == 'Какво искаш да провериш?' and 'Баркод' in pg.inner_text('#cardScan') and 'Без баркод' in pg.inner_text('#cardLabel'), 'start B: question + tiles Баркод / Съставки')
    read_label(pg, 'Zutaten: Haferflocken, Wasser, Salz', 'food', 'Овесена напитка')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, SHOWER, 'cosmetic', 'Душ гел')
    ok(pg.inner_text('#answer .qkind') == 'Козметика' and pg.is_visible('#moreBtn') and pg.locator('#favBtn').count() == 0, 'top line: name · type + ⋯ (heart in the menu)')
    chips = pg.evaluate("[...document.querySelectorAll('#qChips .qchip')].map(c => c.dataset.g + ':' + c.textContent)")
    ok(chips == ['red:1 избягвай', 'orange:1 провери', 'info:5 инфо', 'green:7 нищо открито'], 'count chips in colour order (%s)' % chips)
    dot = pg.evaluate("(() => { const d = document.querySelector('#qList .dot'); const s = getComputedStyle(d); return [d.getBoundingClientRect().width, s.boxShadow.includes('rgba') || s.boxShadow.includes('color')]; })()")
    ok(dot[0] >= 14 and dot[1], 'user 25 Nov: the dots before the names are bigger, with a ring (%s)' % dot)
    pg.click('#qChips .qchip[data-g=info]'); pg.wait_for_timeout(300)
    ok(pg.is_visible('#details') and pg.get_attribute('#groups .grp.g-info .grp-head', 'aria-expanded') == 'true', 'a tap on a chip opens Details at that colour')
    toggle = pg.get_attribute('#detBtn', 'aria-expanded')
    pg.click('#detBtn'); pg.evaluate('window.scrollTo(0, 0)')
    ok(toggle == 'true' and pg.is_hidden('#details'), '"Покажи всички" closes Details again')
    pg.click('#qList .qrow >> nth=0'); pg.wait_for_selector('#detail:not([hidden])')
    ok('Butylphenyl' in pg.inner_text('#detail') or 'Methylisothiazolinone' in pg.inner_text('#detail'), 'a tap on a red / orange name opens that ingredient')
    pg.go_back(); pg.wait_for_selector('#detail', state='hidden')
    pg.click('#moreBtn'); pg.wait_for_selector('#moreMenu')
    items = pg.evaluate("[...document.querySelectorAll('#moreMenu .mitem')].map(b => b.id)")
    ok(items == ['mName', 'favBtn', 'mShare', 'mFront', 'mDetails', 'repBtn'] and pg.locator('#moreMenu .seg').count() == 3, '⋯ menu: rename, ♥, share, product photo (v2.44), details, type, Send to Claude (%s)' % items)
    pg.go_back(); pg.wait_for_timeout(300)
    ok(pg.locator('#moreMenu').count() == 0 and pg.is_visible('#result') and pg.inner_text('#nameBtn') == 'Душ гел', 'phone Back closes the menu and stays on the result')
    pg.click('#moreBtn'); pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    ok(pg.locator('#moreMenu').count() == 0 and not (pg.evaluate('history.state') or {}).get('menu'), 'Escape closes the menu (and its Back step)')
    menu_pick(pg, '#favBtn')
    ok('Душ гел' in pg.evaluate("JSON.stringify(LC.state.favs.map(c => LC.state.products[c] && LC.state.products[c].name))"), '♥ in the menu adds the favourite')
    menu_pick(pg, '#mName'); pg.wait_for_selector('#nameInput')
    pg.fill('#nameInput', 'Душ гел 2'); pg.press('#nameInput', 'Enter'); pg.wait_for_selector('#nameBtn')
    ok(pg.inner_text('#nameBtn') == 'Душ гел 2', '"Промени името" in the menu renames')
    bar = pg.evaluate("(() => { const r = document.getElementById('qBar').getBoundingClientRect(); const t = document.querySelector('.tabbar').getBoundingClientRect(); return [Math.round(r.bottom), Math.round(t.top)]; })()")
    ok(bar[0] <= bar[1] and bar[1] - bar[0] < 30, 'the two buttons sit just above the tab bar (%s)' % bar)
    pg.screenshot(path=os.path.join(SHOTS, 'v234-red-bg.png'))
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    ok(pg.locator('#recentList li.srow').count() == 2 and pg.inner_text('#recentList li.srow >> nth=0 >> .vv') == 'Избягвай' and 'Днес' in pg.inner_text('#recentList'), 'start: last scans with day and result on the right')
    ok(pg.evaluate("document.getElementById('recent').compareDocumentPosition(document.getElementById('checking')) & 4") > 0, '"Проверява" sits under the last scans')
    dc = pg.evaluate("[...document.querySelectorAll('#recentList .vv .dot')].map(d => getComputedStyle(d).backgroundColor)")
    ok(dc[0] == 'rgb(255, 107, 107)' and dc[1] == 'rgb(95, 211, 154)', 'start rows: the dot has the result colour (red / green), not grey (%s)' % dc)
    pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
    cnt = pg.evaluate("[...document.querySelectorAll('#histCount .hc')].map(c => c.dataset.v + ':' + c.querySelector('b').textContent)")
    ok(cnt == ['avoid:1', 'check:0', 'ok:1'], 'history counters (%s)' % cnt)
    pg.click('#histCount .hc[data-v=avoid]')
    ok(pg.locator('#historyList li').count() == 1 and 'Душ гел' in pg.inner_text('#historyList') and pg.get_attribute('#histCount .hc[data-v=avoid]', 'aria-pressed') == 'true', 'a tap on a counter shows only that result')
    pg.click('#histCount .hc[data-v=avoid]')
    pg.fill('#histSearch', 'овес'); pg.wait_for_timeout(200)
    ok(pg.locator('#historyList li').count() == 1 and 'Овесена' in pg.inner_text('#historyList'), 'search finds by name')
    pg.fill('#histSearch', 'zzz'); pg.wait_for_timeout(200)
    ok(pg.locator('#historyList li').count() == 0 and pg.inner_text('#historyEmpty') == 'Няма съвпадение.', 'search with no match says so')
    pg.fill('#histSearch', '')
    pg.click('#histFilter button[data-f=favs]')
    ok(pg.is_visible('#favList') and 'Душ гел' in pg.inner_text('#favList') and pg.is_hidden('#histCount'), '♥ shows the favourites')
    pg.screenshot(path=os.path.join(SHOTS, 'v234-history-bg.png'))
    ctx.close()
    # ---- v2.35: Type the ingredients, honest grey, merge keeps "may contain" and short names, sulphites ----
    print('v2.35: type the ingredients')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({food:['gluten'], cos:[]})); 0"); reload_ready(pg)
    pg.click('#cardLabel')
    ok(pg.is_visible('#typeBtn') and pg.inner_text('#typeBtn strong') == 'Напиши' and pg.get_attribute('#typeBtn', 'aria-label') == 'Напиши съставките', 'Read a label: card "Напиши" (screen reader: "Напиши съставките")')
    pg.click('#typeBtn'); pg.wait_for_selector('#typePanel:not([hidden])')
    ok(pg.inner_text('#typeWord') == 'Добави съставки' and pg.is_visible('#typeEmpty'), 'empty list: "Добави съставки" + help line')
    pg.fill('#typeInput', 'пше'); pg.wait_for_timeout(150)
    sug = pg.evaluate("[...document.querySelectorAll('#typeSug .tsrow')].map(b => [b.querySelector('.nm').textContent, b.querySelector('.dot').className])")
    ok(sug[0][0] == 'Пшеница' and 'g-red' in sug[0][1] and sug[-1][0] == 'Добави „пше“ както е написано', 'typing "пше": Пшеница first with a red dot (your allergen gluten), last row "add as typed" (%s)' % sug[:2])
    pg.press('#typeInput', 'Enter')
    ok(pg.locator('#typeList li').count() == 1 and pg.inner_text('#typeWord') == 'Избягвай' and pg.input_value('#typeInput') == '', 'Enter adds the first name; the live result says "Избягвай" at once; the field is empty again')
    pg.fill('#typeInput', 'e22'); pg.wait_for_timeout(150)
    ok(pg.inner_text('#typeSug .tsrow >> nth=3').startswith('E223 · Натриев метабисулфит') and 'сулфити' in pg.inner_text('#typeSug .tsrow >> nth=3'), 'typing "e22": E223 shows as the allergen sulphites')
    pg.click('#typeSug .tsrow >> nth=3')
    pg.fill('#typeInput', 'захар, сол,'); pg.wait_for_timeout(150)
    ok(pg.locator('#typeList li').count() == 4, 'a comma adds several names at once (захар, сол)')
    for w in ('xqzv', 'plorbex', 'trundal'):
        pg.fill('#typeInput', w); pg.press('#typeInput', 'Enter')
    rows = pg.evaluate("[...document.querySelectorAll('#typeList li')].map(l => [l.querySelector('strong').textContent, l.querySelector('.dot').className, (l.querySelector('small') || {}).textContent || ''])")
    ok(rows[4][0] == 'Xqzv' and 'g-nodata' in rows[4][1] and rows[4][2] == 'Няма данни', 'an unknown typed name is grey "Няма данни" (%s)' % rows[4])
    pg.click('#typeList li:nth-child(1) .tx')
    ok(pg.locator('#typeList li').count() == 6 and pg.inner_text('#typeWord') == 'Непълен резултат', 'without the red name: 3 of 6 names unknown -> "Непълен резултат", never "Без предупреждения" (%s)' % pg.inner_text('#typeWord'))
    pg.screenshot(path=os.path.join(SHOTS, 'v235-type-bg.png'), full_page=True)
    kb_close(pg); pg.click('#typeSave'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Непълен резултат' and pg.inner_text('#oneLine') == '3 от 6 съставки разпознати' and pg.locator('#readCard').count() == 0 and pg.inner_text('#againBtn') == 'Промени списъка',
       'saved: grey result "3 of 6", no "What the app read" card, button "Промени списъка" (%s | %s)' % (word(pg), pg.inner_text('#oneLine')))
    ok(pg.evaluate("LC.state.current.p.read.typed") is True and pg.evaluate("LC.state.current.a.rows.some(r => (r.allergens || []).some(a => a.id === 'sulphur-dioxide-and-sulphites'))"), 'the product is saved as typed; E223 counts as the allergen sulphites')
    pg.click('#againBtn'); pg.wait_for_selector('#typePanel:not([hidden])')
    ok(pg.locator('#typeList li').count() == 6, '"Промени списъка" opens the typed list again')
    pg.go_back(); pg.wait_for_selector('#result:not([hidden]) #answer')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.click('#cardLabel'); pg.click('#typeBtn'); pg.wait_for_selector('#typePanel:not([hidden])')
    pg.fill('#typeInput', 'xq'); pg.wait_for_timeout(150)
    ok(pg.inner_text('#typeSug .tsrow >> nth=0').startswith('Xqzv') and 'вече използвано' in pg.inner_text('#typeSug .tsrow >> nth=0'), 'your own names come first ("вече използвано")')
    # barcode not found -> type the ingredients, linked to the barcode
    pg.go_back(); pg.go_back(); pg.wait_for_timeout(300)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '4001234567891'); pg.wait_for_selector('#labelPanel:not([hidden])')
    pg.click('#typeBtn'); pg.wait_for_selector('#typePanel:not([hidden])')
    ok('4001234567891' in pg.inner_text('#typeLead'), 'barcode not found: "Напиши съставките" knows the barcode (%s)' % pg.inner_text('#typeLead'))
    pg.fill('#typeInput', 'сол'); pg.press('#typeInput', 'Enter'); pg.fill('#typeInput', 'захар'); pg.press('#typeInput', 'Enter')
    kb_close(pg); pg.click('#typeSave'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.evaluate("LC.state.current.p.code") == '4001234567891' and word(pg) == 'Без предупреждения', 'saved under the barcode; known names -> "Без предупреждения"')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '4001234567891'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.evaluate("LC.state.current.p.read && LC.state.current.p.read.typed") is True, 'the next scan of that barcode opens the typed product at once')
    ok(no_side_scroll(pg), 'no sideways scroll')
    # merge of several photos (crackers report): short names, the "may contain" line and allergens stay; label text after it goes
    ctxm = "{ split: tx => LCDB.splitIngredients(tx), known: LC.nameKnown, dice: LC.bigramDice, ident: LC.nameIdent, allergen: x => LCDB.checkFood(x).allergens.length > 0, trace: x => /може да съдържа|may contain/i.test(x) }"
    names = pg.evaluate("(r) => LC.consensusNames(r, " + ctxm + ")", ['Съставки: Пшенично брашно, палмово масло, сол, суроватка на прах (от Мляко), СиРеНЕ на прах 0,1%, оцветител (паприка екстракт). МОЖЕ ДА СЪДЪРЖА ЯЙЦА, СОЯ. mestu./ Te ruhet ne vend t',
                                                                    'Съставки: Пшенично брашно, палмово масло, сол, суроватка на прах (от Мляко), оцветител (паприка екстракт). МОЖЕ ДА СЪДЪРЖА ЯЙЦА, сОЯ.'])
    ok(all(n in names for n in ('сол', 'СиРеНЕ на прах 0,1%', 'оцветител (паприка екстракт)', 'МОЖЕ ДА СЪДЪРЖА ЯЙЦА', 'СОЯ')) and not any('mestu' in n for n in names), 'merge keeps "сол", "СиРеНЕ на прах", the colour before ". ", the "may contain" line and "СОЯ"; drops the text after it (%s)' % names)
    names = pg.evaluate("(r) => LC.consensusNames(r, " + ctxm + ")", ['Ingredients: rice, olive oil, rosemary extract]. Packaged in a protective atmosphere: nitrogen. Store in a dry and cool place', 'Ingredients: rice, olive oil, salt'])
    ok('rice' in names and 'rosemary extract' in names and not any('Store' in n or 'Packaged' in n for n in names), 'label sentences after a ". " are still dropped; v2.51: no stray "]" at the end (%s)' % names)
    ctx.close()

    # ---- v2.36: typing mode (user 26 Nov: "while typing the screen becomes very small") ----
    print('v2.36: typing mode')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({food:['gluten'], cos:[]})); 0"); reload_ready(pg)
    pg.click('#cardLabel'); pg.click('#typeBtn'); pg.wait_for_selector('#typePanel:not([hidden])')
    ok(pg.is_visible('#typePanel h2') and pg.is_visible('#typeKind') and pg.is_visible('#typeSave') and pg.is_visible('.tabbar'), 'just opened: title, Food/Cosmetics/Household, Save and the tab bar show')
    for w in ('захар', 'сол'): pg.fill('#typeInput', w); pg.press('#typeInput', 'Enter')
    pg.set_viewport_size({'width': 390, 'height': 420})   # the keyboard takes the lower half
    pg.fill('#typeInput', 'пше'); pg.wait_for_timeout(300)
    hidden = pg.evaluate("['#typePanel > h2', '#typeLead', '#typeKind', '#typeBar', '.topbar', '.tabbar', '#typePanel > .panel-back'].filter(q => { const e = document.querySelector(q); return e && e.offsetParent !== null; })")
    ok(pg.evaluate("document.body.classList.contains('kbtype')") and hidden == [], 'keyboard open: the app bar, title, help text, type buttons, Save and the tab bar fold away (still shown: %s)' % hidden)
    seen = pg.evaluate("[...document.querySelectorAll('#typeSug .tsrow')].filter(b => { const r = b.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }).length")
    circ = pg.evaluate("(() => { const r = document.querySelector('#typeLive .ring, #typeLive svg, #typeLive').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })()")
    ok(seen >= 3 and circ and pg.is_visible('#typeWord'), '390 x 420 px (keyboard open): the result circle and at least 3 suggestions are visible (%d)' % seen)
    pg.click('#typeSug .tsrow >> nth=0'); pg.wait_for_timeout(300)
    ok(pg.evaluate("document.activeElement.id") == 'typeInput' and pg.evaluate("document.body.classList.contains('kbtype')") and pg.locator('#typeList li').count() == 3, 'a tap on a suggestion adds it and keeps the keyboard open (no jump)')
    pg.press('#typeInput', 'Enter'); pg.wait_for_timeout(350)
    ok(pg.evaluate("document.activeElement.id") != 'typeInput' and not pg.evaluate("document.body.classList.contains('kbtype')") and pg.is_visible('#typeSave') and pg.is_visible('#typePanel h2'), 'Enter on an empty field closes the keyboard; title and Save come back')
    pg.focus('#typeInput'); pg.wait_for_timeout(100)
    ok(pg.evaluate("document.body.classList.contains('kbtype')"), 'tap in the field again: typing mode again')
    pg.go_back(); pg.wait_for_timeout(300)
    ok(not pg.evaluate("document.body.classList.contains('kbtype')") and pg.is_visible('.tabbar') and pg.is_visible('.topbar'), 'Back from the type screen: the app bar and the tab bar are back')
    pg.set_viewport_size({'width': 390, 'height': 844})
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()

    print('v2.36: fewer things per screen (Read a label, My list)')
    for lang, w in (('bg-BG', 390), ('de-AT', 320), ('en-GB', 320)):
        ctx, pg = new_page(b, base, lang, dark=(lang == 'bg-BG'), width=w)
        pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({food:['gluten','milk'], cos:['limonene']})); localStorage.setItem('lc.avoid', JSON.stringify([{id:'a1', text:'palm oil, palmöl'}, {id:'a2', text:'sugar'}, {id:'a3', text:'salt'}, {id:'a4', text:'honey'}])); 0"); reload_ready(pg)
        pg.click('#cardLabel'); pg.wait_for_selector('#labelPanel:not([hidden])')
        tops = pg.evaluate("[...document.querySelectorAll('#photoStart .scard')].map(c => { const r = c.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height), c.scrollWidth <= c.clientWidth + 1]; })")
        ok(len(tops) == 3 and len(set((t[0], t[1]) for t in tops)) == 1 and all(t[2] for t in tops) and pg.is_hidden('#labelLead'), '%s %d px: Read a label = 3 cards in one row, same size, text fits; no general line (%s)' % (lang, w, tops))
        pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(300)
        cards = pg.evaluate("[...document.querySelectorAll('#tab-list > details.lcard')].filter(d => !d.hidden).map(d => [d.id, d.open])")
        ok(cards == [['avoidCard', False], ['ghCard', False], ['packCard', False], ['setCard', False]], '%s: v2.46: Profile = 4 cards (My list and allergens, Backup, Without internet, Settings), all closed; "Taught names" hidden while empty (%s)' % (lang, cards))
        subs = [pg.inner_text(q) for q in ('#avoidSub', '#algSub', '#setSub')]
        ok(subs[0].endswith('+1') and subs[0].count(',') == 2 and ('+ 1' in subs[1]) and '·' in subs[2], '%s: the closed cards say what is inside (%s)' % (lang, subs))
        ok(no_side_scroll(pg) and pg.evaluate("document.documentElement.scrollHeight") < 2500, '%s %d px: no sideways scroll; the page is short (%d px; v2.41: + profile chips)' % (lang, w, pg.evaluate("document.documentElement.scrollHeight")))
        if lang == 'bg-BG':
            ok(subs[1].startswith('Глутен, Мляко') and subs[2].startswith('Езикът на телефона · Като телефона'), 'BG: "Глутен, Мляко …" and "Езикът на телефона · Като телефона"')
            open_card(pg, 'setCard'); pg.select_option('#themeSelect', 'light'); pg.wait_for_timeout(100)
            ok('Светли' in pg.inner_text('#setSub') or 'Светл' in pg.inner_text('#setSub'), 'changing Colours updates the line under "Настройки" (%s)' % pg.inner_text('#setSub'))
            pg.select_option('#themeSelect', 'dark')
            pg.click('#avoidCard > summary'); pg.wait_for_timeout(100)
            ok(pg.eval_on_selector('#avoidCard', 'd => d.open') and pg.is_visible('#avoidInput') and pg.is_visible('#foodAlgBox'), 'a tap on the title opens "My list and allergens": your words and the allergen lists')
            pg.click('#avoidCard > summary'); pg.wait_for_timeout(100)
            ok(not pg.eval_on_selector('#avoidCard', 'd => d.open') and pg.is_hidden('#avoidInput'), 'a second tap closes it')
            pg.screenshot(path=os.path.join(SHOTS, 'v236-mylist-bg.png'), full_page=True)
        ctx.close()

    # ---- v2.37: offline product pack + 3 small things ----
    print('v2.37: offline product pack')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    files = pack_files(); hits = []; pack_route(ctx, files, hits)
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({food:['gluten'], cos:[]})); 0"); reload_ready(pg)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(300)
    ok(pg.inner_text('#packSub') == 'Не е изтеглено' and not pg.eval_on_selector('#packCard', 'd => d.open'), 'My list: card "Продукти без интернет" closed, "Не е изтеглено"')
    ok(hits == [], 'nothing is downloaded before you open the card')
    open_card(pg, 'packCard'); pg.wait_for_function("() => document.getElementById('packState-main').textContent.includes('MB')")
    ok(pg.inner_text('#packState-main').startswith('Не е на телефона · 0,1 MB') and not pg.is_checked('#packSw-main') and pg.is_hidden('#packAuto'),
       'open: "Не е на телефона · size", switch off, no "updates by itself" line yet (%s)' % pg.inner_text('#packState-main'))
    pg.set_viewport_size({'width': 375, 'height': 844}); pg.wait_for_timeout(150)
    xs = pg.evaluate("[...document.querySelectorAll('#packRows .packset')].map(r => { const sw = r.querySelector('.switch').getBoundingClientRect(), g = r.querySelector('.grow').getBoundingClientRect(), b = r.getBoundingClientRect(); return [Math.round(b.right - sw.right), Math.round(sw.left - g.right), r.dataset.part]; })")
    ok(len(xs) == 6 and len(set(x[0] for x in xs)) == 1 and all(x[1] >= 0 for x in xs), 'v2.44: 375 px: 6 country rows, every switch on the right, beside its text ([right gap, gap to text] %s)' % xs)
    pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(150)
    pg.click('#packSw-main'); pg.wait_for_function("() => document.getElementById('packState-main').textContent.includes('продукта')", timeout=15000)
    ok(pg.inner_text('#packState-main').startswith('5 продукта · 3.12.2026') or pg.inner_text('#packState-main').startswith('5 продукта · 3 дек'), 'switch on: downloads at once: "5 продукта · date" (%s)' % pg.inner_text('#packState-main'))
    ok(pg.is_checked('#packSw-main') and pg.inner_text('#packSub').startswith('5 продукта') and pg.is_visible('#packAuto') and 'Обновява се само' in pg.inner_text('#packAuto'),
       'switch stays on; the card line says 5 products; "Обновява се само, всяка седмица" shows')
    ctx.set_offline(True)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '3800000000017'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(word(pg) == 'Избягвай' and pg.evaluate("LC.state.current.p.pack") == '2026-12-03' and pg.evaluate("LC.state.current.p.source") == 'off',
       'offline: a pack product is found at once; gluten (your allergen) -> "Избягвай" (%s)' % word(pg))
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '123456789012'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.evaluate("LC.state.current.p.name") == 'UPC product', 'a 12-digit UPC finds the 13-digit pack entry with the 0 in front')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '9008700000000'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.evaluate("LC.state.current.p.kind") == 'cosmetic' and 'Limonene' in pg.evaluate("LC.state.current.p.ingredientsText"), 'a cosmetic from the pack is checked as cosmetic')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '3800000000024'); pg.wait_for_timeout(800)
    ok(pg.evaluate("LC.state.current && LC.state.current.p.name") == 'Само име' or 'Само име' in pg.inner_text('body'), 'offline, name only in the pack: the product name shows (not "not found")')
    ctx.set_offline(False)
    # online: the pack answers first, then the online data replaces it quietly (here the online text is longer: mustard)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '9001234500003'); pg.wait_for_selector('#result:not([hidden]) #answer')
    pg.wait_for_function("() => LC.state.current && LC.state.current.p.ingredientsText.includes('Senf')", timeout=8000)
    ok(not pg.evaluate("LC.state.current.p.pack") and 'Обновено от интернет' in pg.inner_text('#status'), 'online: the pack answer is replaced by the newer online text; note "Обновено от интернет."')
    # a newer pack on GitHub
    files2 = pack_files('2027-01-03'); files.clear(); files.update(files2)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200)
    pg.evaluate("document.getElementById('packCard').open = false"); open_card(pg, 'packCard')
    pg.evaluate("LC.packInfo && LC.packInfo(true)"); pg.wait_for_timeout(300); pg.evaluate("LC.renderPack && LC.renderPack()"); pg.wait_for_timeout(300)
    ok('нова версия' in pg.inner_text('#packState-main'), 'a newer pack on GitHub: "нова версия" (%s)' % pg.inner_text('#packState-main'))
    hits.clear(); pg.evaluate("LC.packAuto()"); pg.wait_for_timeout(500)
    ok(hits == [], 'v2.44: checked less than a week ago: the app does not look again (%s)' % hits)
    pg.evaluate("localStorage.setItem('lc.packCheck', String(Date.now() - 8 * 864e5)); LC.packAuto()")
    pg.wait_for_function("() => document.getElementById('packState-main').textContent.includes('2027') || document.getElementById('packState-main').textContent.includes('3.01')", timeout=15000)
    ok('нова версия' not in pg.inner_text('#packState-main') and 'pack-main.ndjson.gz' in hits and 'pack-de.ndjson.gz' not in hits,
       'v2.44: after a week the new version downloads by itself, only the switched-on part (%s, %s)' % (pg.inner_text('#packState-main'), hits))
    pg.click('#packSw-de'); pg.wait_for_function("() => document.getElementById('packState-de').textContent.includes('продукт')", timeout=15000)
    ok(pg.inner_text('#packSub').endswith('+ Германия'), 'Germany switched on: the card line says "+ Германия"')
    pg.screenshot(path=os.path.join(SHOTS, 'v237-pack-bg.png'), full_page=True)
    pg.click('#packSw-main'); pg.wait_for_timeout(400)
    ok(pg.is_checked('#packSw-main') and pg.inner_text('#packState-main').startswith('5 продукта'), 'v2.44: switch off -> the app asks first; "Cancel" keeps the pack')
    pg.once('dialog', lambda d: d.accept()); pg.click('#packSw-main'); pg.wait_for_timeout(500)
    ok(not pg.is_checked('#packSw-main') and pg.inner_text('#packState-main').startswith('Не е на телефона') and pg.inner_text('#packSub') == '+ Германия',
       'switch off + OK removes the main pack; Germany stays (%s)' % pg.inner_text('#packSub'))
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()

    print('v2.37: chips, start on the camera, unknown barcode -> type first')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.evaluate("localStorage.setItem('lc.typedNames', JSON.stringify({'xqzv': {n: 'xqzv', c: 3, t: 1}, 'once': {n: 'once', c: 1, t: 2}})); 0"); reload_ready(pg)
    pg.click('#cardLabel'); pg.click('#typeBtn'); pg.wait_for_selector('#typePanel:not([hidden])')
    chips = pg.eval_on_selector_all('#typeChipRow .tchip', 'b => b.map(x => x.textContent)')
    ok(pg.is_visible('#typeChips') and len(chips) == 8 and chips[0] == 'Xqzv' and chips[1] == 'Сол' and 'Once' not in chips, 'empty field: 8 chips, your name used 3 times first, then common names (%s)' % chips)
    pg.click('#typeChipRow .tchip >> nth=1'); pg.wait_for_timeout(150)
    chips2 = pg.eval_on_selector_all('#typeChipRow .tchip', 'b => b.map(x => x.textContent)')
    ok(pg.locator('#typeList li').count() == 1 and 'Сол' not in chips2 and len(chips2) == 8, 'a tap adds "Сол"; it leaves the chips, the next common name comes in (%s)' % chips2)
    pg.fill('#typeInput', 'пш'); pg.wait_for_timeout(150)
    ok(pg.is_hidden('#typeChips') and pg.is_visible('#typeSug'), 'while you type: suggestions, no chips')
    pg.fill('#typeInput', ''); pg.dispatch_event('#typeInput', 'input'); pg.wait_for_timeout(150)
    ok(pg.is_visible('#typeChips'), 'field empty again: chips again')
    kb_close(pg); pg.click('#typeKind .seg[data-k=cosmetic]'); pg.wait_for_timeout(150)
    ok(pg.inner_text('#typeChipRow .tchip >> nth=1') == 'Aqua', 'Cosmetic: INCI names as chips (Aqua …)')
    pg.go_back(); pg.go_back(); pg.wait_for_timeout(300)
    # unknown barcode -> "Напиши" is the first, big card
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '4001234567808'); pg.wait_for_selector('#labelPanel:not([hidden])')
    xs = pg.evaluate("['#typeBtn', '#takePhoto'].map(q => Math.round(document.querySelector(q).getBoundingClientRect().left))")
    bg = pg.evaluate("getComputedStyle(document.getElementById('typeBtn')).backgroundColor") == pg.evaluate("getComputedStyle(document.querySelector('.tabbar button[aria-current=page]')).color")
    ok(pg.evaluate("document.getElementById('photoStart').classList.contains('typefirst')") and xs[0] < xs[1], 'barcode not found: "Напиши" is the first card (%s)' % xs)
    pg.go_back(); pg.wait_for_timeout(200)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.click('#cardLabel'); pg.wait_for_selector('#labelPanel:not([hidden])')
    ok(not pg.evaluate("document.getElementById('photoStart').classList.contains('typefirst')"), '"Прочети етикет" from the start: Снимай stays first')
    # setting: open on the barcode camera
    pg.click('.tabbar button[data-go=list]'); open_card(pg, 'setCard')
    ok(pg.is_visible('#camStartSwitch') and pg.inner_text('#camStartRow label') == 'Отваряй направо камерата за баркод', 'Settings: switch "Отваряй направо камерата за баркод"')
    pg.click('#camStartSwitch'); pg.wait_for_timeout(100)
    ok(pg.evaluate("localStorage.getItem('lc.camStart')") == 'true', 'the switch is saved')
    pg.evaluate("document.getElementById('exportBtn')")
    pg.goto(base); pg.evaluate('LC.dbReady'); pg.wait_for_timeout(600)
    ok(pg.is_visible('#manualForm') or pg.is_visible('#scanner video') or pg.evaluate("!!document.querySelector('.toast:not([hidden])')"), 'app start with the switch on: the barcode camera opens (no camera here: the code box opens)')
    ctx.close()

    # ---- v2.38: Луканка report (27 Nov): the list ends at the nutrition table / label text; tap a name = not an ingredient; "All correct" ----
    print('v2.38: list end, not an ingredient, all correct')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    LUK = ("Съставки: свинско месо, говеждо месо, трапезна сол, подправки (кимион, черен пипер), захар, консервант: калиев нитрат; антиоксидант: натриев аскорбат; "
           "стартерни култури. Мазнини: 30,7 g, от които наситени мастни киселини: 13,3 д, Въглехидрати: 2,0 д, от които захари: 0,8 д, Влакнини: 0,8 д, Белтьци: 24,5 д, "
           "Сол: 3,70 г. Неотворен, при съхранение от 0°С до +8°С, най-добър до:/ Партида: Произведено от „КФМ“ ООД бул.„Св. Димитър Солунски“№1, 2700 Благоевград, България. Нетно 400ge количество: ИЗХВЪРЛЯЙ ПРАВИЛНО")
    cut = pg.evaluate('t => LC.repairNames(LC.cleanOcr(t))', LUK)
    ok(cut.endswith('натриев аскорбат; стартерни култури.') and 'Мазнини' not in cut and 'Благоевград' not in cut, 'Луканка: the list ends after "стартерни култури"; nutrition table and label text are out (%s)' % cut[-60:])
    cases = [("Zutaten: Schweinefleisch, Speck, Salz, Gewürze, Dextrose. Nährwerte pro 100 g: Energie 1500 kJ / 360 kcal, Fett 30 g, Salz 4,2 g", 'Zutaten: Schweinefleisch, Speck, Salz, Gewürze, Dextrose.'),
             ("Ingredients: wheat flour, sugar, salt 1.2%, yeast. Store in a cool dry place. Best before: see top", 'Ingredients: wheat flour, sugar, salt 1.2%, yeast.'),
             ("Съставки: свинско месо, сол, захар. Произведено от Х ООД. Може да съдържа следи от соя.", 'Съставки: свинско месо, сол, захар. Може да съдържа следи от соя.'),
             ("Zutaten: Wasser, Zucker (12 g pro 100 ml), Zitronensaft, Salz. Nährwerte: Energie 80 kJ", 'Zutaten: Wasser, Zucker (12 g pro 100 ml), Zitronensaft, Salz.'),
             ("Ingredients: oats, salt, sugar, fat 30 g, protein 10 g, salt 1 g", 'Ingredients: oats, salt, sugar.'),
             ("Съставки: краве мляко, сол (2%), култури.", 'Съставки: краве мляко, сол (2%), култури.')]
    got = [pg.evaluate('t => LC.repairNames(LC.cleanOcr(t))', c) for c, _ in cases]
    ok(got == [w for _, w in cases], 'list end: DE nutrition table, EN storage line, BG producer (the "may contain" line stays), an amount inside ( ) stays, a short list without a table is unchanged (%s)' % [g for g, (_, w) in zip(got, cases) if g != w])
    read_label(pg, 'Съставки: свинско месо, трапезна сол, захар, Изхвърляй правилно. Може да съдържа следи от соя.', 'food')
    pg.wait_for_selector('#readCard', timeout=20000)
    ok(pg.is_visible('#readCard .rd-hint') and pg.inner_text('#readCard .rd-hint') == 'Тапни име, което не е съставка.' and pg.is_visible('#readOkBtn') and pg.inner_text('#readOkBtn') == '✓ Всичко е вярно',
       'the card says "Тапни име, което не е съставка." and has "✓ Всичко е вярно"')
    pg.click('#readChips .chip:has-text("Изхвърляй правилно")'); pg.wait_for_timeout(500)
    txt = pg.evaluate("LC.state.current.p.ingredientsText")
    ok('Изхвърляй' not in txt and 'захар. Може да съдържа' in txt and pg.locator('#readChips .chip:has-text("Изхвърляй")').count() == 0 and pg.locator('#readLeft .chip.left:has-text("Изхвърляй правилно")').count() == 1,
       'a tap takes the name out of the list; it waits under "left out" with + (%s)' % txt)
    pg.click('#readLeft .chip.left:has-text("Изхвърляй правилно")'); pg.wait_for_timeout(500)
    txt = pg.evaluate("LC.state.current.p.ingredientsText")
    ok(txt.index('Изхвърляй правилно') < txt.index('Може да съдържа') and pg.locator('#readChips .chip:has-text("Изхвърляй")').count() == 1, '+ brings it back, before the "may contain" sentence (not as a trace) (%s)' % txt)
    pg.click('#readChips .chip:has-text("Изхвърляй правилно")'); pg.wait_for_timeout(400)
    pg.click('#readOkBtn'); pg.wait_for_timeout(500)
    ok(pg.evaluate("!!LC.state.current.p.readOk") and pg.locator('#readChips').count() == 0 and 'Проверено от теб' in pg.inner_text('#readCard') and pg.is_visible('#readShow'),
       '"Всичко е вярно": saved on the product; the card is one line "Проверено от теб" + "Покажи"')
    pg.click('#readShow'); pg.wait_for_timeout(400)
    ok(pg.locator('#readChips .chip').count() == 3, '"Покажи" opens the card again (3 names; v2.47: the "may contain" line is no name)')
    pg.reload(); pg.evaluate('LC.dbReady'); pg.wait_for_timeout(300)
    ok(pg.evaluate("Object.values(LC.state.products).some(p => p.readOk && (p.readDropped || []).includes('Изхвърляй правилно'))"), 'kept after a reload (saved with the product)')
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()

    # ---- v2.39: "Приемам" on an orange name, only in this product (user 27 Nov: "2 only on this product") ----
    print('v2.39: accept an orange name in this product')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    LUKT = "Съставки: свинско месо, говеждо месо, трапезна сол, подправки (кимион, черен пипер), захар, консервант: калиев нитрат; антиоксидант: натриев аскорбат; стартерни култури."
    read_label(pg, LUKT, 'food', 'Луканка')
    ok(word(pg) == 'Провери' and pg.locator('#qList .qaccbtn').count() == 1 and pg.inner_text('#qList .qaccbtn') == 'Приемам', 'orange E252: "Провери" with one "Приемам" button')
    code1 = pg.evaluate("LC.state.current.p.code")
    pg.click('#qList .qaccbtn'); pg.wait_for_timeout(500)
    ok(word(pg) == 'Без предупреждения' and pg.evaluate("LC.state.current.p.accepted") == ['e252'] and 'Приемаш го в този продукт' in pg.inner_text('#qAcc') and pg.locator('#qList').count() == 0,
       'after "Приемам": no orange left; the line "Приемаш го в този продукт" with "Върни"; saved as e252 on this product')
    ok('Приемаш в този продукт: Консервант: калиев нитрат.' in pg.evaluate("LC.state.current.a.summary"), 'the shared text says what you accepted')
    ok(pg.evaluate("LC.state.history.find(h => h.code === '%s').verdict" % code1) == 'ok', 'History shows the new verdict')
    # another product with E252: orange again (only this product)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Съставки: свинско месо, сол, консервант: калиев нитрат, захар.', 'food')
    ok(word(pg) == 'Провери', 'another product with E252 is still "Провери"')
    pg.evaluate("LC.showProduct(LC.state.products['%s'])" % code1); pg.wait_for_timeout(600)
    ok(word(pg) == 'Без предупреждения' and pg.is_visible('#qAcc .qaccbtn.undo'), 'the first product keeps your "Приемам"')
    pg.click('#qAcc .qaccbtn.undo'); pg.wait_for_timeout(500)
    ok(word(pg) == 'Провери' and not pg.evaluate("LC.state.current.p.accepted") and pg.locator('#qAcc').count() == 0, '"Върни": orange again')
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()
    ctx, pg = new_page(b, base, 'de-AT', width=320)
    read_label(pg, 'Zutaten: Schweinefleisch, Salz, Konservierungsstoff: Kaliumnitrat, Zucker.', 'food')
    ok(pg.inner_text('#qList .qaccbtn') == 'Für mich OK' and no_side_scroll(pg) and pg.evaluate("(() => { const b = document.querySelector('#qList .qaccbtn').getBoundingClientRect(); return b.right <= innerWidth && b.height >= 40; })()"),
       'DE 320 px: "Für mich OK" fits, at least 40 px high')
    ctx.close()

    # ---- v2.40: "To check" -> one file to Claude -> import the answer ----
    print('v2.40: To check, one file to Claude, import the answer')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    ok(pg.is_hidden('#toCheckRow'), 'start: no "За проверка" row while nothing waits')
    seed = {}
    for i, (nm, tx) in enumerate([('Крекери', 'Съставки: пшенично брашно, сирене, сол'), ('', 'Съставки: захар, какаово масло'), ('Чипс', 'Съставки: картофи, сол')]):
        seed['label-t%d' % i] = {'code': 'label-t%d' % i, 'kind': 'food', 'source': 'label', 'name': nm, 'ingredientsText': tx, 'texts': [tx], 'tags': [], 'allergens': [], 'analysis': [],
                                 'read': {'photo': True, 'list': True}, 'fetchedAt': 1795700000000 + i}
    seed['label-t2']['readOk'] = 1795700000000                       # marked "Всичко е вярно": not to check
    seed['label-typed'] = dict(seed['label-t0'], code='label-typed', read={'typed': True})   # typed: not to check
    pg.evaluate("s => { localStorage.setItem('lc.products', JSON.stringify(s)); }", seed); reload_ready(pg)
    ok(pg.is_visible('#toCheckRow') and pg.inner_text('#toCheckSub') == '2 прочетени етикета чакат', 'start: "За проверка от Claude · 2 прочетени етикета чакат" (checked and typed products are not in it)')
    pg.click('#toCheckRow'); pg.wait_for_selector('#checkPanel:not([hidden])'); pg.wait_for_timeout(300)
    ok(pg.locator('#chkList li').count() == 2 and pg.inner_text('#chkCount') == '(2)' and 'Без име' in pg.inner_text('#chkList') and pg.inner_text('#chkSend') == 'Изпрати 2 на Claude',
       'the screen lists 2 products ("Без име" for no name), button "Изпрати 2 на Claude"')
    pg.evaluate("""() => new Promise(res => { const rq = indexedDB.open('lc-photos', 1); rq.onupgradeneeded = () => rq.result.createObjectStore('p');
      rq.onsuccess = () => { const tx = rq.result.transaction('p', 'readwrite'); tx.objectStore('p').put({ at: 1, list: ['data:image/jpeg;base64,AAAA', 'data:image/jpeg;base64,BBBB'] }, 'label-t0'); tx.oncomplete = res; }; })""")
    pg.go_back(); pg.wait_for_timeout(200); pg.click('#toCheckRow'); pg.wait_for_timeout(400)
    ok('2 снимки' in pg.inner_text('#chkList li:has-text("Крекери")'), 'a product with saved photos says "2 снимки"')
    with pg.expect_download() as dl: pg.click('#chkSend')
    import tempfile as _tf
    fp = os.path.join(_tf.mkdtemp(), 'f.txt'); dl.value.save_as(fp); body = open(fp, encoding='utf-8').read()
    data = json.loads(body.rstrip().split('\n')[-1])                 # the note (with the answer format) first, the data on the last line
    ok(body.startswith('NOTE FOR CLAUDE: This file comes from the Label Check app: 2 products to check') and '"labelCheckAnswer":1' in body and data['batch'] == 2
       and sorted(x['code'] for x in data['products']) == ['label-t0', 'label-t1'] and next(x for x in data['products'] if x['code'] == 'label-t0')['photos'] == ['data:image/jpeg;base64,AAAA', 'data:image/jpeg;base64,BBBB'],
       'one file: the note for Claude (with the answer format), 2 products, the saved photos inside (%s)' % dl.value.suggested_filename)
    pg.wait_for_timeout(300)
    ok(pg.locator('#chkList .tag.sent').count() == 2 and pg.evaluate("document.querySelector('#chkSteps li[data-s=\"2\"]').classList.contains('done')"), 'after sending: both say "изпратено", step 2 is done')
    pg.go_back(); pg.wait_for_timeout(300)
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
    ok(pg.is_hidden('#toCheckRow'), 'v2.47: after "Send", the "За проверка" row leaves the start screen')
    pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
    ok(pg.is_visible('#histCheckRow') and pg.inner_text('#histCheckSub') == '2 изпратени · внеси отговора тук' and no_side_scroll(pg)
       and pg.evaluate("document.getElementById('histCheckSub').scrollWidth <= document.getElementById('histCheckSub').clientWidth + 1"),
       'v2.47: History keeps the row: "2 изпратени · внеси отговора тук", not cut (%s)' % pg.inner_text('#histCheckSub'))
    pg.click('#histCheckRow'); pg.wait_for_selector('#checkPanel:not([hidden])'); pg.wait_for_timeout(300)
    ok(pg.locator('#chkList li').count() == 2, 'v2.47: the History row opens the same list (send again, import the answer)')
    ans = {'labelCheckAnswer': 1, 'products': [
        {'code': 'label-t0', 'name': 'Крекери със сирене', 'kind': 'food', 'ingredients': 'Съставки: пшенично брашно, сирене (мляко), сол', 'en': 'wheat flour, cheese (milk), salt', 'note': 'milk was missing'},
        {'code': 'label-t1', 'name': '', 'kind': 'food', 'ingredients': None, 'note': 'no photo'},
        {'code': 'label-gone', 'ingredients': 'x'}]}
    pg.click('#chkPasteFold > summary'); pg.fill('#chkPaste', 'Here it is:\n```json\n' + json.dumps(ans, ensure_ascii=False) + '\n```'); pg.click('#chkPasteBtn'); pg.wait_for_timeout(500)
    p0 = pg.evaluate("LC.state.products['label-t0']")
    ok(p0['ingredientsText'] == 'Съставки: пшенично брашно, сирене (мляко), сол' and p0['name'] == 'Крекери' and p0['texts'][1] == 'EN: wheat flour, cheese (milk), salt' and p0.get('claude') and 'sent' not in p0,
       'import: the correct list replaces the read text (+ EN line); your name stays; the product is "checked by Claude"')
    ok(pg.locator('#chkList li').count() == 1 and 'Claude: no photo' in pg.inner_text('#chkList') and pg.inner_text('#chkList .tag') == 'чака' and pg.inner_text('#chkLast').startswith('Последен отговор:'),
       'a product Claude could not read waits again, with Claude\'s note; "Последен отговор: …"')
    ok(pg.evaluate("new Promise(res => { const rq = indexedDB.open('lc-photos', 1); rq.onsuccess = () => { const g = rq.result.transaction('p').objectStore('p').get('label-t0'); g.onsuccess = () => res(!g.result); }; })"), 'the photos of an answered product are deleted')
    ok(not pg.eval_on_selector('#chkPasteFold', 'd => d.open') and pg.input_value('#chkPaste') == '', 'after a good import the paste box is empty and folded')
    pg.click('#chkPasteFold > summary'); pg.fill('#chkPaste', 'hello'); pg.click('#chkPasteBtn'); pg.wait_for_timeout(300)
    ok('Това не е отговор за Label Check' in pg.inner_text('#toast'), 'other text: "Това не е отговор за Label Check …"')
    pg.evaluate("LC.showProduct(LC.state.products['label-t0'])"); pg.wait_for_timeout(500)
    ok('Проверено от Claude' in pg.inner_text('#readCard'), 'the product: the read card is one line "Проверено от Claude"')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.wait_for_timeout(300)
    ok(pg.inner_text('#toCheckSub') == '1 прочетен етикет чака', 'start: "1 прочетен етикет чака"')
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()
    ctx, pg = new_page(b, base, 'de-AT', width=320)
    pg.evaluate("s => { localStorage.setItem('lc.products', JSON.stringify(s)); }", {'label-t0': seed['label-t0']}); reload_ready(pg)
    pg.click('#toCheckRow'); pg.wait_for_timeout(300)
    ok(pg.inner_text('#chkSend') == '1 an Claude senden' and no_side_scroll(pg) and pg.evaluate("document.getElementById('chkSend').getBoundingClientRect().height") <= 80, 'DE 320 px: "1 an Claude senden" fits')
    ans1 = {'labelCheckAnswer': 1, 'products': [{'code': 'label-t0', 'name': '', 'kind': 'food', 'ingredients': 'Zutaten: Weizenmehl, Käse (Milch), Salz', 'note': ''}]}
    pg.go_back(); pg.wait_for_timeout(200); pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200)
    pg.set_input_files('#importInput', files=[{'name': 'label-check-answer.json', 'mimeType': 'application/json', 'buffer': json.dumps(ans1, ensure_ascii=False).encode('utf-8')}]); pg.wait_for_timeout(600)
    p0 = pg.evaluate("LC.state.products['label-t0']")
    ok(p0.get('claude') and p0['ingredientsText'] == 'Zutaten: Weizenmehl, Käse (Milch), Salz', 'v2.47: "Import backup" also takes Claude\'s answer file')
    ctx.close()

    # ---- v2.48: supplement doses vs. EU upper limits (user 28 Nov: orange above, blue "close" from 80 %) ----
    print('v2.48: supplement doses')
    SUPP = 'Zutaten: Magnesiumcitrat, Zinkgluconat, Pyridoxinhydrochlorid. Nahrungsergänzungsmittel. Pro Tagesdosis (2 Kapseln): Magnesium 400 mg (107 %*), Zink 22 mg (220 %*), Vitamin B6 1,4 mg (100 %*).'
    for lang, w in (('en-GB', 390), ('de-AT', 320), ('bg-BG', 390)):
        ctx, pg = new_page(b, base, lang, dark=lang != 'de-AT', width=w)
        read_label(pg, SUPP, 'food')
        ql = pg.inner_text('#qList')
        ok(word(pg) == {'en-GB': 'Check', 'de-AT': 'Prüfen', 'bg-BG': 'Провери'}[lang] and pg.locator('#qList .dot.g-orange[data-m="!"]').count() == 1 and pg.locator('#qList .dot.g-info[data-m=i]').count() == 1,
           '%s: Magnesium 400 mg = orange !, Zinc 22 mg (88 %%) = blue i, verdict Check (%s)' % (lang, ql.replace('\n', ' | ')))
        ok(no_side_scroll(pg) and card_fits(pg), '%s %d px: the dose rows fit' % (lang, w))
        if lang == 'en-GB':
            ok('Above the EU limit · 400 mg a day (limit 250 mg)' in ql and 'Close to the EU limit · 22 mg a day (limit 25 mg)' in ql and pg.locator('#qList .qaccbtn').count() == 1,
               'EN: "Above the EU limit · 400 mg a day (limit 250 mg)", "Close to the EU limit · 22 mg a day (limit 25 mg)"; "OK for me" only on the orange row')
            open_details(pg)
            ok(pg.inner_text('#dtop .qr') == 'Reason: the daily dose is above the EU upper limit for adults (EFSA).' and pg.inner_text('#doseAll') == 'Daily dose vs. EU upper limit (adults): Magnesium 400 mg (160 %), Zinc 22 mg (88 %), Vitamin B6 1.4 mg (12 %)',
               'Details: the reason, and all doses with %% of the limit, biggest first (%s)' % pg.inner_text('#doseAll'))
            pg.click('#detBtn'); pg.wait_for_timeout(200)
            pg.click('#qList .qaccbtn'); pg.wait_for_timeout(400)
            ok(word(pg) == 'No warnings' or pg.locator('#qList .dot.g-orange').count() == 0, '"OK for me" on Magnesium: no orange left (%s)' % word(pg))
        ctx.close()
    ctx, pg = new_page(b, base, 'en-GB', width=390)
    read_label(pg, 'Ingredients: oats, sugar, salt. Nutrition per 100 g: magnesium 300 mg, iron 14 mg', 'food')
    ok(pg.locator('#qList .dot.g-orange').count() == 0 and pg.locator('#doseAll').count() == 0, 'a food with a "per 100 g" table: no dose rows')
    ctx.close()

    # ---- v2.49: Back (user 28 Nov: "Back closes the app" / "no back button on the product, keep what I did") ----
    print('v2.49: Back on the result')
    for lang, w in (('en-GB', 390), ('bg-BG', 320)):
        ctx, pg = new_page(b, base, lang, dark=True, width=w)
        read_label(pg, 'Ingredients: sunflower seeds 97%, salt 3%, packed in a protective atmosphere.', 'food', 'Sunflower seeds')
        ok(pg.is_visible('#resBack') and pg.inner_text('#resBack').strip() == {'en-GB': 'Back', 'bg-BG': 'Назад'}[lang] and no_side_scroll(pg) and card_fits(pg),
           '%s %d px: the result has the "‹ Back" button of the other screens (%s)' % (lang, w, pg.inner_text('#resBack')))
        if lang != 'en-GB': ctx.close(); continue
        pg.click('#readChips .chip:has-text("packed in a protective atmosphere")'); pg.wait_for_timeout(400)
        pg.click('#resBack'); pg.wait_for_timeout(400)
        ok(pg.is_visible('#cardLabel') and pg.is_hidden('#result') and pg.is_hidden('#labelPanel'), '"‹ Back" after "Read a label" = the start screen (not the label screen)')
        pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
        pg.click('#historyList li:has-text("Sunflower seeds") .open'); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(300)
        p0 = pg.evaluate("LC.state.current.p")
        ok(p0['name'] == 'Sunflower seeds' and 'protective' not in p0['ingredientsText'] and pg.locator('#readChips .chip').count() == 2,
           'what you did on the result is kept after Back: the name, the name you took out (%s)' % p0['ingredientsText'])
        pg.click('#resBack'); pg.wait_for_timeout(400)
        ok(pg.is_visible('#historyList') and pg.is_hidden('#result'), 'opened from History: "‹ Back" returns to History')
        pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
        read_label(pg, 'Ingredients: oats, salt.', 'food')
        pg.go_back(); pg.wait_for_timeout(400)
        ok(pg.is_visible('#cardLabel') and pg.is_hidden('#result') and pg.is_hidden('#labelPanel'), 'the phone\'s Back after "Read a label" = the start screen too (one step)')
        pg.click('#cardLabel'); pg.wait_for_timeout(200); pg.click('#labelPanel .panel-back'); pg.wait_for_timeout(300)
        ok(pg.is_visible('#cardLabel') and pg.is_hidden('#labelPanel'), '"‹ Back" on Read a label still goes to the start screen')
        ctx.close()
    apk = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apk', 'MainActivity.java'), encoding='utf-8').read()
    ok('getOnBackPressedDispatcher().addCallback' in apk and 'canGoBack()' in apk and 'goBack()' in apk, 'the Android app sends the Back key to the page (MainActivity: canGoBack -> goBack)')

    # ---- v2.50: medicine fillers with a known effect (EMA list; user 28 Nov: "both" = red for your allergens + blue i for the rest) ----
    print('v2.50: medicine fillers (EMA)')
    CREAM = 'Wirkstoff: Dexpanthenol 50 mg/g. Sonstige Bestandteile: Arachidis oleum raffinatum, Cetylstearylalkohol (Ph.Eur.), Wollwachs, Propylenglycol, gereinigtes Wasser.'
    for lang, w in (('en-GB', 390), ('de-AT', 320), ('bg-BG', 390)):
        ctx, pg = new_page(b, base, lang, dark=lang != 'de-AT', width=w)
        pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({ food: ['peanuts', 'milk'], cos: [] }))"); reload_ready(pg)
        read_label(pg, CREAM, 'cosmetic')
        ql = pg.inner_text('#qList')
        ok(word(pg) == {'en-GB': 'Avoid', 'de-AT': 'Meiden', 'bg-BG': 'Избягвай'}[lang] and pg.locator('#qList .dot.g-red[data-m=p]').count() == 1 and 'Arachidis oleum raffinatum' in ql
           and pg.locator('#qList .dot.g-info[data-m=i]').count() == 3 and no_side_scroll(pg) and card_fits(pg),
           '%s %d px: peanut oil (Latin) in a medicine = red with the person mark at its place; 3 more EU fillers as blue i (%s)' % (lang, w, ql.replace('\n', ' | ')[:160]))
        if lang == 'en-GB':
            ok('Your allergen · Peanuts · Filler in a medicine' in ql and 'Medicine filler (EU list) · May cause local skin reactions (e.g. contact dermatitis).' in ql,
               'EN rows: "Your allergen · Peanuts · Filler in a medicine"; "Medicine filler (EU list) · May cause local skin reactions (e.g. contact dermatitis)."')
            ok(pg.locator('#readChips .chip').count() == 6 and 'Wirkstoff' not in pg.inner_text('#readChips'), '"Wirkstoff:" / "Sonstige Bestandteile:" are no part of a name (6 names)')
            open_details(pg)
            ma = pg.inner_text('#medAll')
            ok(ma.startswith('Medicine – fillers with a known effect (EU list):') and pg.locator('#medAll li').count() == 4 and 'Arachis oil (peanut oil): If you are allergic to peanut or soya, do not use this medicinal product.' in ma,
               'Details: all 4 fillers with the EU warning')
        if lang == 'de-AT':
            ok('Hilfsstoff (EU-Liste)' in ql, 'DE: "Hilfsstoff (EU-Liste)"')
        ctx.close()
    ctx, pg = new_page(b, base, 'bg-BG', width=390)
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({ food: ['peanuts'], cos: [] }))"); reload_ready(pg)
    read_label(pg, 'Kalium phosphoricum D6 250 mg; помощни вещества: лактоза монохидрат', 'food')
    ok('Лактоза' in pg.inner_text('#qList') and pg.locator('#qList .dot.g-info[data-m=i]').count() == 1, 'tablets with lactose (milk not ticked): a blue i row "Лактоза"')
    open_details(pg)
    ok('Лактоза: Ако Вашият лекар Ви е казал, че имате непоносимост към някои захари' in pg.inner_text('#medAll'), 'Details (BG): the EU warning for lactose')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Ingredients: Aqua, Glycerin, Methylparaben, Parfum.', 'cosmetic')
    ok(pg.locator('#medAll').count() == 0 and pg.locator('#qList .dot.g-info[data-m=i]').count() == 0, 'a cosmetic (no medicine words): no filler rows')
    ctx.close()

    # ---- v2.51: "may contain" for barcode products, supplement forms, photo-read fixes (user OK 28 Nov) ----
    print('v2.51: barcode traces, supplement forms, photo merge')
    ctxm_v251 = "{ split: tx => LCDB.splitIngredients(tx), known: LC.nameKnown, dice: LC.bigramDice, ident: LC.nameIdent, allergen: x => LCDB.checkFood(x).allergens.length > 0, trace: x => /може да съдържа|may contain/i.test(x) }"
    import time as _t
    WAF = {'4006040000017': {'code': '4006040000017', 'kind': 'food', 'source': 'off', 'name': 'Hazelnut wafers', 'brand': 'Example', 'image': '',
           'ingredientsText': 'Weizenmehl, Zucker, Palmfett, Haselnüsse 12%, fettarmer Kakao, Emulgator: Lecithine, Salz. Kann Spuren von Milch enthalten.',
           'texts': ['Weizenmehl, Zucker, Palmfett, Haselnüsse 12%, fettarmer Kakao, Emulgator: Lecithine, Salz. Kann Spuren von Milch enthalten.'],
           'tags': [], 'allergens': ['en:gluten', 'en:nuts'], 'traces': ['en:milk', 'en:peanuts', 'en:soybeans', 'en:nuts'], 'analysis': [], 'cats': [], 'fetchedAt': int(_t.time() * 1000)}}
    for lang, w in (('en-GB', 390), ('bg-BG', 320)):
        ctx, pg = new_page(b, base, lang, dark=True, width=w)
        pg.evaluate("s => { localStorage.setItem('lc.products', JSON.stringify(s)); localStorage.setItem('lc.allergens', JSON.stringify({ food: ['milk', 'peanuts'], cos: [] })); }", WAF); reload_ready(pg)
        pg.evaluate("LC.showProduct(LC.state.products['4006040000017'])"); pg.wait_for_selector('#result:not([hidden]) #answer'); pg.wait_for_timeout(300)
        qm = pg.inner_text('#qMay')
        ok(word(pg) == {'en-GB': 'Check', 'bg-BG': 'Провери'}[lang] and pg.locator('#qMay li').count() == 2 and no_side_scroll(pg),
           '%s %d px: a barcode product with "may contain milk, peanuts, soy" (database) = Check, one row each for milk and peanuts; milk is not counted twice (%s)' % (lang, w, qm.replace('\n', ' | ')))
        if lang == 'en-GB':
            open_details(pg)
            ma = pg.inner_text('#mayAll').lower()
            ok('soy' in ma and 'peanut' in ma and 'nuts' not in ma.replace('peanuts', ''), 'Details: all traces from the database (soy too); nuts are an ingredient, not a trace (%s)' % ma)
        ctx.close()
    ctx, pg = new_page(b, base, 'en-GB', width=390)
    read_label(pg, 'Nahrungsergänzungsmittel. Zutaten: Magnesiumorotat, Magnesiumcitrat, Zinkgluconat, Magnesiumstearat. Pro Tagesdosis (2 Kapseln): Magnesium 150 mg, Zink 5 mg.', 'food')
    ql = pg.inner_text('#qList')
    ok('Magnesiumorotat' in ql and 'Not on the EU list for supplements · Directive 2002/46/EC, Annex II' in ql and pg.locator('#qList .dot.g-info[data-m=i]').count() == 1 and 'citrat' not in ql.lower() and 'stearat' not in ql.lower(),
       'a supplement with magnesium orotate: one blue i row; citrate, gluconate and the filler magnesium stearate give nothing (%s)' % ql.replace('\n', ' | '))
    fr = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'chips-frames.json'), encoding='utf-8'))
    names = pg.evaluate("(fr) => LC.consensusNames(LC.oneListLang(fr.map(f => ({ text: f.clean }))).map(x => x.text), " + ctxm_v251 + ")", fr)
    low = [n.lower() for n in names]
    ok(not any(re.search('[\u0400-\u04FF]', n) for n in names) and all(x in low for x in ('citric acid', 'tomato powder', 'sea salt', 'flavouring blend 6%', 'sugar'))
       and not any(x in low for x in ('itric acid', 'mato powder', 'olive ol', 'atric acid', 'osphae')),
       'Protein Chips report (7 photos, BG + EN): only the English list is joined; edge pieces are gone; the "[ ]" list gives its own names (%d names)' % len(names))
    ctx.close()

    # ---- v2.41: Profile tab (user 27 Nov: allergens and things to avoid, "like seed oils, gluten", easy to open) ----
    print('v2.41: Profile tab')
    for lang, w, dark in (('bg-BG', 390, True), ('de-AT', 320, False), ('en-GB', 320, False)):
        ctx, pg = new_page(b, base, lang, dark=dark, width=w)
        pg.evaluate("localStorage.setItem('lc.avoid', JSON.stringify([{id:'a1', text:'palm oil, palmöl, палмово масло'}])); 0"); reload_ready(pg)
        tabname = {'bg-BG': 'Профил', 'de-AT': 'Profil', 'en-GB': 'Profile'}[lang]
        ok(pg.inner_text('.tabbar button[data-go=list]').strip() == tabname, '%s: the tab is called "%s"' % (lang, tabname))
        pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(300)
        ok(pg.inner_text('#tab-list > h2') == tabname and pg.locator('#profAlg .pchip:not(.more)').count() == 8 and pg.is_visible('#profAlgMore')
           and pg.locator('#profFood .pchip[data-p]').count() == 6 and pg.locator('#profCos .pchip[data-p]').count() == 5 and pg.locator('#profDiet .pchip').count() == 1,
           '%s: chips on top: 8 allergens + "more", 6 food groups + own word, 5 cosmetics, vegan' % lang)
        ok(pg.eval_on_selector('#profFood .pchip[data-p=palm]', 'b => b.getAttribute("aria-pressed")') == 'true', '%s: an old "palm oil" list entry shows as the ticked "palm oil" chip' % lang)
        ok(no_side_scroll(pg) and pg.evaluate("[...document.querySelectorAll('#profile .pchip')].every(b => b.getBoundingClientRect().height >= 40 && b.getBoundingClientRect().right <= innerWidth)"), '%s %d px: chips fit, at least 40 px high' % (lang, w))
        if lang == 'bg-BG':
            pg.click('#profFood .pchip[data-p=seed]'); pg.wait_for_timeout(200)
            it = pg.evaluate("LC.state.avoid.find(i => i.preset === 'seed')")
            ok(it and it['text'].startswith('семенни масла, sunflower oil') and 'слънчогледово масло' in it['text'] and 'семенни масла' in pg.text_content('#avoidList').lower(), 'Семенни масла: one tap adds one list entry with all the oil names (EN/DE/BG/RO)')
            ctx2 = None
            pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
            read_label(pg, 'Съставки: пшенично брашно, слънчогледово масло, сол', 'food')
            ok(word(pg) == 'Избягвай' and 'Твоят списък: Семенни масла' in pg.inner_text('#qList'), 'a product with sunflower oil is now "Избягвай" ("Твоят списък: Семенни масла")')
            pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200)
            pg.click('#profFood .pchip[data-p=seed]'); pg.wait_for_timeout(200)
            ok(not pg.evaluate("LC.state.avoid.some(i => i.preset === 'seed')") and pg.eval_on_selector('#profFood .pchip[data-p=seed]', 'b => b.getAttribute("aria-pressed")') == 'false', 'a second tap removes it')
            pg.click('#profAlg .pchip[data-p=gluten]'); pg.wait_for_timeout(200)
            ok(pg.evaluate("LC.state.allergens.food.includes('gluten')") and pg.inner_text('#algSub').startswith('Глутен'), 'allergen chip "Глутен" ticks gluten (the Allergens card says it too)')
            pg.click('#profAlgMore'); pg.wait_for_timeout(150)
            ok(pg.locator('#profAlg .pchip:not(.more)').count() == 14 and pg.locator('#profAlgMore').count() == 0, '"+ още 6": all 14 EU allergens')
            pg.click('#profDiet .pchip[data-p=vegan]'); pg.wait_for_timeout(150)
            ok(pg.evaluate("LC.state.vegan") and pg.locator('#veganSwitch').count() == 0, 'Веган chip switches vegan on; v2.46: no second vegan switch')
            pg.click('#profOwn'); pg.wait_for_timeout(500)
            ok(pg.evaluate("document.activeElement.id") == 'avoidInput' and pg.eval_on_selector('#avoidCard', 'd => d.open'), '"+ моя дума" opens your list and puts the cursor in the field')
            pg.screenshot(path=os.path.join(SHOTS, 'v241-profile-bg.png'), full_page=True)
        ctx.close()

    # ---- v2.43: marks in the dots, blue info, "already checked", "add the barcode", own products kept ----
    print('v2.43: marks, blue info, already checked, add the barcode')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    marks = pg.evaluate("""[['red', {why: 'b'}], ['red', {why: 'mine', mine: {}}], ['red', {why: 'allergen'}], ['orange', {level: 'c'}], ['orange', {level: 'u'}],
      ['info', {level: 'r'}], ['info', {accepted: true}], ['nodata', {}], ['green', {}]].map(([g, r]) => LC.markOf(Object.assign({group: g}, r), g))""")
    ok(marks == ['✕', 'p', 'p', '!', '?', 'i', '✓', '–', ''], 'marks: ✕ not allowed, person = your profile, ! concern, ? under review, i info, ✓ accepted, – no data, none for green (%s)' % marks)
    read_label(pg, 'Съставки: свинско месо, сол, захар, консервант: калиев нитрат, соя', 'food', 'Луканка')
    ok(pg.get_attribute('#qList .dot', 'data-m') == '!' and pg.evaluate("getComputedStyle(document.querySelector('#qList .dot'), '::before').content") == '"!"', 'E252 (concern): orange dot with "!"')
    blue = pg.evaluate("(() => { const d = document.createElement('i'); d.className = 'dot g-info'; document.body.append(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c; })()")
    ok(blue == 'rgb(77, 163, 255)', 'info is clear blue in dark mode (%s)' % blue)
    ok(pg.is_visible('#linkBtn') and pg.inner_text('#linkBtn') == 'Добави баркода', 'a label product without a barcode: "Добави баркода"')
    old = pg.evaluate("LC.state.current.p.code")
    pg.click('#readOkBtn'); pg.wait_for_timeout(300)
    pg.click('#linkBtn'); pg.wait_for_timeout(400)
    ok('Сканирай баркода на „Луканка“' in pg.inner_text('#status'), 'the scanner opens with "Сканирай баркода на „Луканка“ …"')
    pg.evaluate("LC.lookup('4056489693802')"); pg.wait_for_timeout(700)
    ok(pg.evaluate("LC.state.current.p.code") == '4056489693802' and pg.evaluate("!LC.state.products['%s'] && !!LC.state.products['4056489693802'].readOk" % old)
       and pg.evaluate("LC.state.history[0].code") == '4056489693802' and pg.evaluate("LC.state.names['4056489693802']") == 'Луканка',
       'the product (with your ✓ and name) is now saved under the barcode; history follows')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.evaluate("LC.lookup('4056489693802')"); pg.wait_for_timeout(700)
    ok(pg.is_visible('#knownBox') and pg.inner_text('#knownBox strong').startswith('Вече проверен от теб · ') and pg.locator('#linkBtn').count() == 0, 'scanning the barcode again: "Вече проверен от теб · <date> ✓", no "Добави баркода"')
    # the same label photographed again
    pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
    read_label(pg, 'Съставки: свинско месо, сол, захар, консервант калиев нитрат, соя', 'food')
    newc = pg.evaluate("LC.state.current.p.code")
    pg.evaluate("LC.showTwin(LC.state.current.p)"); pg.wait_for_timeout(200)
    ok(pg.is_visible('#twinBox') and pg.inner_text('#twinBox strong') == 'Вече проверен: Луканка', 'a new read of the same list: "Вече проверен: Луканка"')
    pg.click('#twinOpen'); pg.wait_for_timeout(500)
    ok(pg.evaluate("LC.state.current.p.code") == '4056489693802' and pg.evaluate("!LC.state.products['%s']" % newc) and pg.evaluate("!LC.state.history.some(h => h.code === '%s')" % newc),
       '"Отвори": your saved product opens; the copy goes')
    pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
    read_label(pg, 'Съставки: вода, захар, лимонена киселина', 'food')
    pg.evaluate("LC.showTwin(LC.state.current.p)"); pg.wait_for_timeout(200)
    ok(pg.locator('#twinBox').count() == 0, 'a different list: no "Вече проверен"')
    n = pg.evaluate("""(() => { const P = LC.state.products; for (let i = 0; i < 1005; i++) P['40000000' + String(i).padStart(5, '0')] = { code: '40000000' + String(i).padStart(5, '0'), source: 'off', kind: 'food', name: 'x', ingredientsText: 'a', fetchedAt: i };
      LC.saveProduct({ code: '4099999999999', source: 'off', kind: 'food', name: 'y', ingredientsText: 'b', fetchedAt: 9e12 });
      return [Object.keys(P).length, !!P['4056489693802'], Object.values(P).filter(q => LC.isOwn(q)).length]; })()""")
    ok(n[0] <= 1000 and n[1] and n[2] >= 2, 'over 1,000 products: copies from the internet go, your own products stay (%s)' % n)
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()

    # ---- v2.44: product photo, more countries (switches, updates by themselves), automatic GitHub backup ----
    print('v2.44: pack database version 2 keeps the packs of version 1; more countries')
    import gzip as _gz, base64 as _b64, urllib.parse as _up
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, locale='bg-BG', color_scheme='dark', service_workers='block')
    ctx.route('https://world.openfoodfacts.org/**', fake_api); ctx.route('https://world.openbeautyfacts.org/**', fake_api)
    files = pack_files(); hits = []; pack_route(ctx, files, hits)
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base.replace('index.html', 'manifest.json'))
    pg.evaluate("""() => new Promise((res, rej) => { const rq = indexedDB.open('lc-pack', 1);
      rq.onupgradeneeded = () => { const db = rq.result; ['main', 'de', 'meta'].forEach(n => db.createObjectStore(n)); };
      rq.onsuccess = () => { const db = rq.result, tx = db.transaction(['main', 'meta'], 'readwrite');
        tx.objectStore('main').put(['f', 'Стар пакет', 'X', 'вода, сол'], '3800000000099');
        tx.objectStore('meta').put({ main: { date: '2026-11-26', n: 1, bytes: 10 } }, 'parts');
        tx.oncomplete = () => { db.close(); res(); }; tx.onerror = () => rej(tx.error); }; rq.onerror = () => rej(rq.error); })""")
    pg.goto(base); pg.evaluate('LC.dbReady'); ctx.set_offline(True)
    type_code(pg, '3800000000099'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.evaluate("LC.state.current.p.name") == 'Стар пакет', 'the pack downloaded before v2.44 still works after the update (database version 2)')
    ctx.set_offline(False)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200); open_card(pg, 'packCard')
    pg.wait_for_function("() => document.getElementById('packState-main').textContent.includes('3.12') || document.getElementById('packState-main').textContent.includes('3 дек')", timeout=15000)
    ok(pg.is_checked('#packSw-main') and not pg.is_checked('#packSw-de') and not pg.is_checked('#packSw-hu') and 'pack-main.ndjson.gz' in hits,
       'old user: the pack on the phone counts as switched on and updates by itself to the new version; Germany stays off')
    names = pg.eval_on_selector_all('#packRows .packset label > span:first-child', 'e => e.map(x => x.textContent)')
    ok(names == ['Австрия · България · Румъния · Словакия', 'Германия', 'Унгария', 'Чехия', 'Хърватия', 'Италия'], '6 rows: main, Germany, Hungary, Czechia, Croatia, Italy (%s)' % names)
    pg.click('#packSw-hu'); pg.wait_for_timeout(600)
    ok(pg.is_checked('#packSw-hu') and 'скоро' in pg.inner_text('#packState-hu'), 'Hungary on before GitHub has it: the switch stays on, "Изтегля се скоро" (%s)' % pg.inner_text('#packState-hu'))
    body = json.dumps({'v': 1, 'part': 'hu', 'date': '2026-12-03', 'n': 1}) + '\n' + json.dumps(['5990000000013', 'f', 'Pick szalámi', 'Pick', 'sertéshús, só, paprika'], ensure_ascii=False) + '\n'
    files['pack-hu.ndjson.gz'] = _gz.compress(body.encode('utf-8'))
    info = json.loads(files['pack-info.json']); info['parts']['hu'] = {'file': 'pack-hu.ndjson.gz', 'bytes': len(files['pack-hu.ndjson.gz']), 'n': 1, 'ni': 1}
    files['pack-info.json'] = json.dumps(info).encode()
    pg.evaluate("LC.packAuto()")
    pg.wait_for_function("() => document.getElementById('packState-hu').textContent.includes('продукт')", timeout=15000)
    ok(pg.inner_text('#packSub').endswith('+ Унгария'), 'as soon as GitHub has Hungary, it downloads by itself (no button); the card line says "+ Унгария" (%s)' % pg.inner_text('#packSub'))
    ctx.set_offline(True)
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    type_code(pg, '5990000000013'); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.evaluate("LC.state.current.p.name") == 'Pick szalámi', 'offline: a Hungarian product is found in the Hungary pack')
    ctx.set_offline(False)
    ok(no_side_scroll(pg), 'no sideways scroll')
    ctx.close()

    print('v2.44: product photo')
    JPG = {'name': 'front.jpg', 'mimeType': 'image/jpeg', 'buffer': _b64.b64decode('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCAAeACgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDnqKKK8U/QQooooAKKKKACiiigAooooAKKKKAP/9k=')}
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    read_label(pg, 'Съставки: свинско месо, сол, черен пипер', 'food', 'Луканка Тест')
    code = pg.evaluate("LC.state.current.p.code")
    ok(pg.is_visible('#frontBtn') and 'add' in pg.get_attribute('#frontBtn', 'class') and pg.inner_text('#frontBtn') == 'Снимка', 'no photo yet: a dashed "Снимка" tile next to the name')
    with pg.expect_file_chooser() as fc: pg.click('#frontBtn')
    fc.value.set_files(JPG); pg.wait_for_function("() => document.querySelector('#frontBtn img')", timeout=8000)
    ok('add' not in pg.get_attribute('#frontBtn', 'class') and pg.evaluate("!!LC.state.products['%s'].front && !!LC.frontOf('%s')" % (code, code)), 'the photo shows next to the name and is saved')
    ok(pg.evaluate("LC.isOwn(LC.state.products['%s'])" % code), 'a product with your photo is your own product (never removed by the limit)')
    pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
    ok(pg.locator('#historyList .hrow .thumb img').count() == 1, 'History shows the photo')
    pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(300)
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
    ok(pg.locator('#recentList .srow .thumb img').count() == 1, '"Последни" shows the photo')
    pg.evaluate("LC.showProduct(LC.state.products['%s'])" % code); pg.wait_for_timeout(300)
    pg.click('#moreBtn'); pg.wait_for_selector('#moreMenu')
    ok(pg.inner_text('#mFront') == 'Нова снимка на продукта' and pg.is_visible('#mFrontRm'), '⋯ menu: "Нова снимка на продукта" and "Махни снимката на продукта"')
    pg.click('#mFrontRm'); pg.wait_for_timeout(500)
    ok('add' in pg.get_attribute('#frontBtn', 'class') and not pg.evaluate("LC.state.products['%s'].front || LC.frontOf('%s')" % (code, code)), '"Махни": back to the dashed tile')
    with pg.expect_file_chooser() as fc: pg.click('#frontBtn')
    fc.value.set_files(JPG); pg.wait_for_function("() => document.querySelector('#frontBtn img')", timeout=8000)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200); open_card(pg, 'ghCard')
    with pg.expect_download() as dl: pg.click('#exportBtn')
    bkfile = os.path.join(SHOTS, 'v244-backup.json'); dl.value.save_as(bkfile)
    data = json.load(open(bkfile, encoding='utf-8'))
    ok(str(data.get('fronts', {}).get(code, '')).startswith('data:image/jpeg') and 'packWant' in data, 'the backup file has the product photo and your countries')
    ctx.close()
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200); open_card(pg, 'ghCard')
    pg.once('dialog', lambda d: d.accept())
    pg.set_input_files('#importInput', bkfile); pg.wait_for_function("(c) => !!LC.frontOf(c)", arg=code, timeout=8000)
    ok(pg.evaluate("!!LC.state.products['%s'].front" % code), 'import on a new phone: the product and its photo come back')
    ctx.close()

    print('v2.44: GitHub backup')
    KEY = 'github_pat_' + 'A1b2' * 10
    GH = {'files': {}, 'puts': [], 'gets': 0, 'key': KEY}
    def gh_route(route):
        rq = route.request
        H = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'authorization, content-type, accept, x-github-api-version', 'Access-Control-Allow-Methods': 'GET, PUT'}
        if rq.method == 'OPTIONS': route.fulfill(status=204, headers=H); return
        if rq.headers.get('authorization') != 'Bearer ' + GH['key']: route.fulfill(status=401, headers=H, content_type='application/json', body='{"message":"Bad credentials"}'); return
        parts = rq.url.split('api.github.com/repos/')[1].split('?')[0].split('/')
        repo, rest = parts[0] + '/' + parts[1], '/'.join(parts[2:])
        if repo not in ('harisonbd/label-check-backup', 'harisonbd/public-one'): route.fulfill(status=404, headers=H, body='{}'); return
        if not rest: route.fulfill(status=200, headers=H, content_type='application/json', body=json.dumps({'full_name': repo, 'private': repo != 'harisonbd/public-one'})); return
        fp = _up.unquote(rest[len('contents/'):])
        if rq.method == 'GET':
            GH['gets'] += 1
            f = GH['files'].get(fp)
            if not f: route.fulfill(status=404, headers=H, body='{"message":"Not Found"}'); return
            if 'raw' in rq.headers.get('accept', ''): route.fulfill(status=200, headers=H, body=f['bytes']); return
            route.fulfill(status=200, headers=H, content_type='application/json', body=json.dumps({'sha': f['sha']})); return
        d = json.loads(rq.post_data)
        f = GH['files'].get(fp)
        if f and d.get('sha') != f['sha']: route.fulfill(status=409, headers=H, body='{}'); return
        GH['files'][fp] = {'bytes': _b64.b64decode(d['content']), 'sha': 'sha%d' % len(GH['puts'])}; GH['puts'].append(fp)
        route.fulfill(status=201, headers=H, content_type='application/json', body='{"content":{}}')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    ctx.route('https://api.github.com/**', gh_route)
    read_label(pg, 'Съставки: свинско месо, сол, черен пипер', 'food', 'Луканка Облак')
    code = pg.evaluate("LC.state.current.p.code")
    with pg.expect_file_chooser() as fc: pg.click('#frontBtn')
    fc.value.set_files(JPG); pg.wait_for_function("() => document.querySelector('#frontBtn img')", timeout=8000)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200)
    ok(pg.inner_text('#ghSub') == 'Автоматичното копие не е настроено' and not pg.eval_on_selector('#ghCard', 'd => d.open'), 'Profile: card "Резервно копие", closed, "Автоматичното копие не е настроено"')
    open_card(pg, 'ghCard')
    hrefs = pg.eval_on_selector_all('#ghSetup .ghsteps a', 'a => a.map(x => x.href)')
    ok(pg.is_visible('#ghSetup') and pg.is_hidden('#ghOn') and hrefs[0].startswith('https://github.com/new') and hrefs[1] == 'https://github.com/settings/personal-access-tokens/new',
       '3 steps with direct links (%s)' % hrefs)
    def connect(repo, key):
        pg.fill('#ghRepo', repo); pg.fill('#ghToken', key); pg.click('#ghConnect'); pg.wait_for_timeout(700)
    connect('harisonbd/label-check-backup', 'abc')
    ok('не е ключ' in pg.inner_text('#ghMsg') and GH['gets'] == 0, 'not a key: a clear message, nothing is sent')
    connect('harisonbd/public-one', KEY)
    ok('публично' in pg.inner_text('#ghMsg') and pg.evaluate("localStorage.getItem('lc.gh')") in (None, 'null') and not GH['puts'], 'a PUBLIC repository is refused; nothing is saved or sent')
    connect('harisonbd/label-check-backup', 'github_pat_' + 'Z9' * 15)
    ok('не работи' in pg.inner_text('#ghMsg') and not GH['puts'], 'a wrong key: "Ключът не работи"')
    connect('https://github.com/harisonbd/label-check-backup', KEY)
    pg.wait_for_function("() => !document.getElementById('ghOn').hidden", timeout=8000); pg.wait_for_timeout(500)
    js = GH['files'].get('label-check-backup.json', {}).get('bytes', b'').decode('utf-8')
    ok(pg.inner_text('#ghOkTitle') == 'Свързано: harisonbd/label-check-backup' and code in js and 'photos/%s.jpg' % code in GH['puts'],
       'connected (a full GitHub address also works): first backup + the product photo are on GitHub (%s)' % GH['puts'])
    ok(KEY not in js and 'github_pat' not in js and pg.input_value('#ghToken') == '', 'the key is never in the backup, and the field is emptied')
    ok('Автоматично в GitHub' in pg.inner_text('#ghSub') and 'продукти: ' in pg.inner_text('#ghOkSub') and 'снимки: 1' in pg.inner_text('#ghOkSub'), 'the card says when and what (%s)' % pg.inner_text('#ghOkSub'))
    n = len(GH['puts'])
    pg.evaluate("LC.ghMaybe()"); pg.wait_for_timeout(500)
    ok(len(GH['puts']) == n, 'by itself: not again on the same day')
    pg.evaluate("(() => { const g = JSON.parse(localStorage.getItem('lc.gh')); g.tried = Date.now() - 25 * 3600e3; localStorage.setItem('lc.gh', JSON.stringify(g)); })()")
    pg.evaluate("LC.ghMaybe()"); pg.wait_for_timeout(700)
    ok(len(GH['puts']) == n, 'by itself after a day, but nothing changed: nothing is sent')
    pg.evaluate("(() => { const g = JSON.parse(localStorage.getItem('lc.gh')); g.tried = Date.now() - 25 * 3600e3; localStorage.setItem('lc.gh', JSON.stringify(g)); })()")
    pg.fill('#avoidInput', 'палмово масло') if pg.is_visible('#avoidInput') else None
    pg.evaluate("LC.state.avoid.push({ id: 'x1', text: 'палмово масло' }); localStorage.setItem('lc.avoid', JSON.stringify(LC.state.avoid)); LC.ghMaybe()"); pg.wait_for_timeout(800)
    ok(GH['puts'][n:] == ['label-check-backup.json'], 'after a day with a change: only the backup file is sent again, not the photo (%s)' % GH['puts'][n:])
    pg.click('#ghNow'); pg.wait_for_timeout(800)
    ok(GH['puts'][-1] == 'label-check-backup.json' and len(GH['puts']) == n + 2, '"Копирай сега" sends at once')
    pg.click('.tabbar button[data-go=scan]'); pg.wait_for_timeout(200)
    ok(pg.is_hidden('#bkNote'), 'with the GitHub backup working there is no "Още нямаш резервно копие" note')
    pg.evaluate("(() => { const g = JSON.parse(localStorage.getItem('lc.gh')); g.ok = Date.now() - 9 * 864e5; g.at = g.ok; localStorage.setItem('lc.gh', JSON.stringify(g)); })()")
    reload_ready(pg); pg.wait_for_timeout(300)
    ok(pg.is_visible('#bkNote') and 'не работи от 9 дни' in pg.inner_text('#bkNote') and pg.inner_text('#bkSave') == 'Отвори', 'not working for 9 days: the start note says so; "Отвори" (%s)' % pg.inner_text('#bkNote'))
    pg.click('#bkSave'); pg.wait_for_timeout(400)
    ok(pg.eval_on_selector('#ghCard', 'd => d.open'), '"Отвори" opens the GitHub card')
    GH['key'] = 'github_pat_' + 'X' * 40
    pg.click('#ghNow'); pg.wait_for_timeout(800)
    ok(pg.is_visible('#ghErr') and 'не работи' in pg.inner_text('#ghErr') and 'Не работи' in pg.inner_text('#ghSub'), 'the key ended: the card says what to do (%s)' % pg.inner_text('#ghErr'))
    GH['key'] = KEY
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'v244-github-bg.png'), full_page=True)
    ctx.close()
    # a new phone (or the APK): connect -> "restore?" -> yes
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    ctx.route('https://api.github.com/**', gh_route)
    n = len(GH['puts'])
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200); open_card(pg, 'ghCard')
    msgs = []
    pg.on('dialog', lambda d: (msgs.append(d.message), d.accept()))
    connect('harisonbd/label-check-backup', KEY); pg.wait_for_function("(c) => !!LC.frontOf(c)", arg=code, timeout=8000)
    ok(msgs and 'копие от' in msgs[0] and pg.evaluate("!!LC.state.products['%s'] && LC.state.avoid.some(a => a.text === 'палмово масло')" % code),
       'a new phone: "В хранилището има копие ... Да го върна?" -> products, list and photo come back (%s)' % msgs[:1])
    ok(len(GH['puts']) == n, 'restoring sends nothing (the backup on GitHub is not overwritten)')
    msgs.clear(); pg.click('#ghOff'); pg.wait_for_timeout(300)
    ok(msgs and pg.is_visible('#ghSetup') and pg.evaluate("localStorage.getItem('lc.gh')") in (None, 'null'), '"Изключи" asks, then deletes the key from the phone')
    ctx.close()
    for lang, w in (('en-GB', 320), ('de-AT', 320)):
        ctx, pg = new_page(b, base, lang, dark=False, width=w)
        pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200)
        open_card(pg, 'packCard'); open_card(pg, 'ghCard'); pg.wait_for_timeout(300)
        ok(no_side_scroll(pg) and pg.is_visible('#ghConnect'), '%s %d px: the country and GitHub cards fit' % (lang, w))
        pg.screenshot(path=os.path.join(SHOTS, 'v244-cards-%s-%d.png' % (lang[:2], w)), full_page=True)
        ctx.close()

    # ---- v2.46: Profile = 4 cards (user OK, picture 23 "A") ----
    print('v2.46: Profile with 4 cards')
    ctx, pg = new_page(b, base, 'en-GB', dark=True)
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200)
    titles = pg.eval_on_selector_all('#tab-list > details.lcard:not([hidden]) > summary .lct strong', 'e => e.map(x => x.textContent)')
    ok(titles == ['My list and allergens', 'Backup', 'Without internet', 'Settings'], '4 cards: %s' % titles)
    ok(pg.locator('#avoidCard #foodAlgBox').count() == 1 and pg.locator('#avoidCard #cosAlgBox').count() == 1, '1: your words and all allergens are in one card')
    ok(all(pg.locator('#ghCard ' + q).count() == 1 for q in ('#ghSetup', '#exportBtn', '#importInput', '#shareProdBtn', '#prodInput')), '2: Backup = GitHub + backup file + share products')
    ok(pg.locator('#packCard #offline').count() == 1 and pg.locator('#setCard #offline').count() == 0, '3: the label reader download is in "Without internet"')
    ok(pg.locator('#setCard #rulesFold').count() == 1 and pg.locator('#veganSwitch').count() == 0, '4: "What the app checks" is in Settings; the second vegan switch is gone')
    pg.click('#profFood .pchip[data-p=seed]'); pg.wait_for_timeout(150)
    open_card(pg, 'avoidCard'); pg.click('#foodAlgBox summary'); pg.click('#foodAlgList label:has-text("Mustard") input'); pg.wait_for_timeout(200)
    sub = pg.inner_text('#avoidCard summary small'); sep = pg.evaluate("getComputedStyle(document.getElementById('algSub'), '::before').content")
    ok('seed oil' in sub.lower() and 'Mustard' in sub and sep == '" · "', 'the card line shows your words · your allergens (%s, %s)' % (sub, sep))
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'v246-profile-en.png'), full_page=True)
    ctx.close()

    # ---- v2.45: inside the Android app (APK): files and texts go to the Android share menu (LCNative) ----
    print('v2.45: Android app bridge')
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, locale='bg-BG', color_scheme='dark', service_workers='block',
                        user_agent='Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36 LabelCheckApp/1')
    ctx.route('https://world.openfoodfacts.org/**', fake_api); ctx.route('https://world.openbeautyfacts.org/**', fake_api)
    # like Android: the bridge is there only from the second page load
    ctx.add_init_script("""window.__loads = (+sessionStorage.getItem('t.loads') || 0) + 1; sessionStorage.setItem('t.loads', window.__loads);
      if (window.__loads > 1) { window.__shared = []; window.LCNative = { shareFile: (n, m, b, t) => { window.__shared.push(['file', n, m, b, t]); return true; }, shareText: t => { window.__shared.push(['text', t]); return true; } }; }""")
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.wait_for_function('window.LC && window.LCNative', timeout=15000); pg.evaluate('LC.dbReady')
    ok(pg.evaluate("window.__loads") == 2 and pg.evaluate("sessionStorage.getItem('lc.nativeReload')") == '1', 'in the app: the page reloads once until LCNative is there (loads: %s)' % pg.evaluate("window.__loads"))
    reload_ready(pg); pg.wait_for_timeout(300)
    ok(pg.evaluate("window.__loads") == 3 and pg.evaluate("!!window.LCNative"), 'no reload loop: the next start opens at once')
    read_label(pg, 'Съставки: вода, захар, сол', 'food', 'Тест апп')
    pg.click('#moreBtn'); pg.wait_for_selector('#moreMenu'); pg.click('#mShare'); pg.wait_for_timeout(400)
    sh = pg.evaluate("window.__shared")
    ok(sh and sh[-1][0] == 'text' and 'Тест апп' in sh[-1][1], '"Сподели" -> the Android share menu with the text')
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(200); open_card(pg, 'ghCard')
    pg.click('#exportBtn'); pg.wait_for_timeout(800)
    sh = pg.evaluate("window.__shared")
    import base64 as _b64b
    f = sh[-1] if sh else None
    ok(f and f[0] == 'file' and f[1].startswith('label-check-backup-') and f[2] == 'application/json' and json.loads(_b64b.b64decode(f[3]).decode('utf-8')).get('app') == 'label-check',
       '"Изнеси копие" -> the backup file goes to the Android share menu (save to Files / Drive)')
    ctx.close()

    for lang, w, dark in (('en-GB', 320, False), ('de-AT', 390, False)):
        ctx, pg = new_page(b, base, lang, dark=dark, width=w)
        read_label(pg, SHOWER, 'cosmetic', 'Shower gel with a long product name')
        ok(card_fits(pg) and no_side_scroll(pg) and pg.is_visible('#qBar') and pg.is_visible('#moreBtn'), '%s %d px light: fits, buttons and ⋯ visible' % (lang, w))
        pg.click('#moreBtn'); pg.wait_for_selector('#moreMenu')
        ok(pg.evaluate("document.querySelector('#moreMenu .mbox').scrollWidth <= window.innerWidth"), '%s %d px: the menu fits' % (lang, w))
        pg.screenshot(path=os.path.join(SHOTS, 'v234-menu-%s-%d.png' % (lang[:2], w)))
        pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
        pg.click('.tabbar button[data-go=history]'); pg.wait_for_timeout(300)
        ok(no_side_scroll(pg), '%s %d px: History fits' % (lang, w))
        ctx.close()
    b.close()
srv.shutdown()

print('\nPage errors:', errors or 'none')
print('ALL PASSED' if not fails and not errors else '%d FAILED' % (len(fails) + len(errors)))
sys.exit(1 if fails or errors else 0)
