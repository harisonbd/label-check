"""Label Check v2 – app test in a phone-size browser (390 x 844).
Run from the repo root:  python tools/test_app.py
Needs: pip install playwright && playwright install chromium
Starts a local web server, fakes the Open Food Facts answer, and checks the main screens.
Screenshots go to tools/shots/ (not for GitHub)."""
import json, os, sys, threading, http.server, functools
from playwright.sync_api import sync_playwright

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

def fake_api(route):
    url = route.request.url
    if 'openfoodfacts' in url and '9001234567890' in url:
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': 1, 'product': {
            'product_name': 'Extrawurst', 'brands': 'Example', 'ingredients_text': SAUSAGE,
            'additives_tags': ['en:e250', 'en:e451'], 'allergens_tags': ['en:mustard', 'en:celery', 'en:milk'],
            'nutriscore_grade': 'd', 'nova_group': 4}}))
    else:
        route.fulfill(status=200, content_type='application/json', body='{"status":0}')

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
    pg.fill('#labelName', name)
    pg.click('#checkLabel')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    pg.evaluate('window.scrollTo(0, 0)')

def counts(pg):
    return pg.eval_on_selector_all('.tile b', 'n => n.map(x => +x.textContent)')

def no_side_scroll(pg):
    return pg.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

def tiles_fit(pg):
    # No tile word is cut with "…"
    return pg.evaluate('[...document.querySelectorAll(".tile span")].every(s => s.scrollWidth <= s.clientWidth + 1)')

srv = serve()
base = 'http://127.0.0.1:%d/index.html' % srv.server_address[1]
with sync_playwright() as p:
    b = p.chromium.launch()

    print('English, cosmetic label')
    ctx, pg = new_page(b, base, 'en-GB')
    read_label(pg, SHOWER, 'cosmetic', 'Shower gel')
    ok(pg.inner_text('.verdict-word') == 'Avoid', 'verdict Avoid (Lilial is banned)')
    ok(counts(pg) == [1, 1, 5, 7], 'tiles 1 / 1 / 5 / 7')
    ok(pg.eval_on_selector_all('.tile span', 'n => n.map(x => x.textContent)') == ['Avoid', 'Check', 'Info', 'Clear'], 'tile words Avoid / Check / Info / Clear')
    ok(pg.is_visible('.topcard .tc-head h2') and pg.inner_text('.topcard .tc-head h2') == 'Shower gel', 'product name inside the top card')
    ok(pg.inner_text('#groups li:has-text("Butylphenyl") .chip') == 'Banned', 'row tag "Banned"')
    ok(pg.inner_text('#groups li:has-text("Sodium Benzoate") .why') == 'Preservative · EU limit', 'why line "Preservative · EU limit"')
    pg.click('#groups .grp.g-green .grp-head')
    ok(pg.locator('#groups .chiplist .gchip').count() == 7, 'Clear group shows 7 name chips')
    ok('Fragrance · Fragrance' not in pg.inner_text('#result'), 'no "Fragrance · Fragrance"')
    ok(pg.locator('.strip-ends').count() == 1 and pg.get_attribute('.strip button:nth-child(14)', 'title').startswith('#14'), 'strip stays in label order')
    ok(pg.locator('.strip button').count() == 14, '14 blocks in the strip')
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'en-cosmetic.png'))
    pg.click('.strip button:nth-child(9)')
    ok(pg.locator('#groups li.flash').count() == 1, 'strip block jumps to the ingredient')
    pg.click('#groups li:has-text("Methylisothiazolinone") .row-btn')
    ok(pg.is_visible('#detail') and 'Regulation (EU) 2016/1198' in pg.inner_text('#detailBody'), 'detail shows reason + source')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_hidden('#detail') and pg.is_visible('#result'), 'Back closes the detail')
    pg.click('.tile.g-info')
    ok(pg.eval_on_selector_all('#groups .grp .ttl', 'n => n.map(x => x.textContent)') == ['Info'], 'tile tap shows only that group')
    pg.click('#favBtn')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#labelPanel') and pg.is_hidden('#result'), 'Back from a label result shows the label screen')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#scanner') and pg.is_visible('#cardScan'), 'Back again shows the start screen with the 3 cards')
    ok(pg.locator('#recentList li').count() == 1 and 'Shower gel' in pg.inner_text('#recent'), 'start screen: Recent shows the product')
    ok('EU lists' in pg.inner_text('#checking'), 'start screen: "Checking" row')

    print('Find one ingredient (offline)')
    pg.click('#cardSearch')
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
    reds = pg.eval_on_selector_all('#groups .grp.g-red .row-btn strong', 'n => n.map(x => x.textContent)')
    ok('Methylisothiazolinone' in reds, '"Stays on skin" makes Methylisothiazolinone red (rinse-off only)')
    ok(pg.inner_text('#groups li:has-text("Methylisothiazolinone") .chip') == 'Rinse-off only', 'tag "Rinse-off only"')
    pg.click('.usebar .seg:nth-child(3)')
    ok('Methylisothiazolinone' not in pg.eval_on_selector_all('#groups .grp.g-red .row-btn strong', 'n => n.map(x => x.textContent)'), '"Not sure" makes it orange again')
    ok(pg.locator('#result .data-line, #result .dbage').count() == 0, 'v2.4: no source / data line on the result (EU data is new)')
    ok(pg.locator('#tab-scan #credit').count() == 0 and pg.locator('#tab-list #credit').count() == 1, 'v2.4: credits only in My list -> What the app checks')

    print('Barcode lookup (faked), allergen + fragrance settings')
    pg.click('.tabbar button[data-go=scan]')
    ok(pg.is_visible('#cardScan'), 'tapping "Scan" on a result shows the start screen')
    pg.fill('#codeInput', '9001234567890'); pg.click('#manualForm button[type=submit]')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok(pg.inner_text('.verdict-word') == 'Check', 'sausage: Check (nitrite, trans fat)')
    pg.click('.tabbar button[data-go=list]')
    pg.click('#foodAlgList label:has-text("Mustard") input')
    pg.click('#veganSwitch')
    pg.click('#fragSwitch')
    pg.click('.tabbar button[data-go=history]')
    ok(pg.locator('#historyList .dot.g-red').count() == 3, 'history: all red after mustard, fragrance and vegan')
    pg.click('#historyList li:has-text("Extrawurst") .open')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok('Not vegan' in pg.inner_text('#groups'), 'vegan: Schweinefleisch is "Not vegan"')
    pg.click('.tabbar button[data-go=favs]')
    ok('Shower gel' in pg.inner_text('#favList'), 'favourite listed')
    ctx.close()

    print('Our product list (data/products.json)')
    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#cardSearch')
    pg.fill('#searchInput', 'magne'); pg.wait_for_timeout(400)
    first = pg.inner_text('#searchList li:first-child')
    ok('MLO Magne Amino Armour' in first and 'Our list' in first and 'Avoid' in first, 'search "magne" shows our product first, Avoid')
    pg.click('#searchList li:first-child .row-btn')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok(pg.inner_text('.verdict-word') == 'Avoid', 'MLO: Avoid (E171)')
    ok(counts(pg)[0] == 1 and 'Titanium dioxide' in pg.inner_text('#groups .grp.g-red'), 'red group = titanium dioxide')
    es = pg.evaluate('LC.state.current.a.rows.flatMap(r => (r.additives || []).map(a => a.e))')
    ok('E464' in es and 'E551' in es, 'хипромелоза = E464 and силиконов диоксид = E551 are found')
    pg.screenshot(path=os.path.join(SHOTS, 'en-own-product.png'))
    ok(pg.locator('#result .data-line').count() == 0, 'v2.4: no data line on our product')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#searchPanel'), 'Back from our product shows the search again')
    pg.go_back(); pg.wait_for_timeout(200)
    pg.click('#recentList li:first-child .open')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok(pg.inner_text('.verdict-word') == 'Avoid', 'opens again from Recent (no barcode)')
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
    pg.fill('#codeInput', '4000000000017'); pg.click('#manualForm button[type=submit]')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok(pg.inner_text('.tc-head h2') == 'Test capsules', 'scan finds our product offline')
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
    pg.fill('#codeInput', '9001234567899'); pg.click('#manualForm button[type=submit]')
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
    pg.fill('#codeInput', '3800123456781'); pg.click('#manualForm button[type=submit]')
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
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok(pg.inner_text('.tc-head h2') == 'Magne Amino Armour' and pg.inner_text('.verdict-word') == 'Avoid', '"This one" opens Magne (Avoid)')
    ok('linked' in pg.inner_text('#toast'), 'toast: barcode linked')
    ctx.route('https://world.openfoodfacts.org/**', lambda r: r.abort())
    pg.click('.tabbar button[data-go=scan]')
    pg.fill('#codeInput', '3800123456781'); pg.click('#manualForm button[type=submit]')
    pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok(pg.inner_text('.tc-head h2') == 'Magne Amino Armour' and pg.is_hidden('#pickBox'), 'next scan opens Magne directly (offline too)')
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
    ok(pg.locator('#result .dbage.old').count() == 1 and 'more than 6 months' in pg.inner_text('#result .dbage.old'), 'EU data older than 6 months: warning stays')
    ctx.close()

    print('German, dark, 360 px')
    ctx, pg = new_page(b, base, 'de-AT', dark=True, width=360)
    ok(pg.locator('#langSwitch [aria-pressed=true]').count() == 0, 'German: EN | BG switch shows neither')
    ok(no_side_scroll(pg), 'no sideways scroll with the switch at 360 px')
    ok(pg.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()') == '#7AA2FF', 'dark = Graphite (blue accent, no mint)')
    ok(pg.get_attribute('#themeColor', 'content').upper() == '#121417', 'phone bar colour = graphite')
    pg.screenshot(path=os.path.join(SHOTS, 'de-dark-start.png'))
    read_label(pg, SHOWER, 'cosmetic', 'Duschgel')
    ok(pg.inner_text('.verdict-word') == 'Meiden', 'German verdict')
    ok('Anhang' in pg.inner_text('#groups') or 'Grenzwert' in pg.inner_text('#groups'), 'German row texts')
    ok(tiles_fit(pg), 'German tile words fit at 360 px')
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'de-dark.png'))
    ctx.close()

    print('Bulgarian, food label, 360 px')
    ctx, pg = new_page(b, base, 'bg-BG', width=360)
    read_label(pg, WAFER, 'food', 'Вафла')
    ok(pg.inner_text('.verdict-word') == 'Провери', 'Bulgarian verdict')
    ok(counts(pg) == [0, 3, 3, 5], 'tiles 0 / 3 / 3 / 5')
    ok('Мляко' in pg.inner_text('.allergen-line'), 'milk allergen named Мляко')
    ok(tiles_fit(pg), 'Bulgarian tile words fit at 360 px')
    ok(no_side_scroll(pg), 'no sideways scroll')
    pg.screenshot(path=os.path.join(SHOTS, 'bg-food.png'))
    ctx.close()
    b.close()

    print('v2.4: camera frame (fake camera)')
    bc = p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'])
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
        pg.click('#stopCam')
        ok(pg.is_visible('#cardScan'), '%s: Stop camera shows the start cards again' % loc)
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
    def read_photo(pg, lang='eng', box=(0.03, 0.44, 0.97, 0.62)):
        pg.set_input_files('#photoPick', photo)
        pg.wait_for_selector('#ocrArea:not([hidden])')
        pg.evaluate("document.getElementById('cropWrap').scrollIntoView({block: 'center'})")
        r = pg.locator('#cropInner').bounding_box()
        drag(pg, '#cropBox i[data-h="nw"]', r['x'] + box[0] * r['width'], r['y'] + box[1] * r['height'])
        drag(pg, '#cropBox i[data-h="se"]', r['x'] + box[2] * r['width'], r['y'] + box[3] * r['height'])
        pg.click('#ocrLang button[data-ocr="%s"]' % lang)
        pg.click('#ocrRead')
        pg.wait_for_function("() => { const s = document.getElementById('ocrStatus'); return !s.hidden && !s.classList.contains('busy'); }", timeout=90000)

    b = p.chromium.launch()
    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#cardLabel')
    ok(pg.inner_text('#labelTitle') == 'Read a label' and not pg.is_visible('#ocrArea') and not pg.eval_on_selector('#claudeBox', 'd => d.open'), 'panel: title "Read a label", no photo box yet, Claude part folded')
    ok(pg.evaluate("[...performance.getEntriesByType('resource')].every(e => !e.name.includes('/ocr/'))"), 'reader files are not loaded before "Read text"')
    read_photo(pg)
    txt = pg.input_value('#labelText').lower()
    ok(pg.inner_text('#ocrStatus').startswith('Done in'), 'status "Done in … s" (%s)' % pg.inner_text('#ocrStatus'))
    ok(txt.startswith('ingredients:') and all(w in txt for w in ('sugar', 'wheat flour', 'palm oil', 'soya lecithin', 'tartrazine', 'milk')), 'text read from the box, starts at "Ingredients:"')
    ok('crunchy' not in txt and 'nutrition' not in txt, 'text outside the box is not read')
    pg.click('#checkLabel'); pg.wait_for_selector('#result:not([hidden]) .topcard')
    ok('Tartrazine' in pg.inner_text('#result') or 'E102' in pg.inner_text('#result'), 'Check ingredients works with the read text (tartrazine found)')
    pg.click('#cardLabel') if pg.is_visible('#cardLabel') else None
    ctx.close()

    ctx, pg = new_page(b, base, 'bg-BG')
    pg.click('#cardLabel')
    pg.set_input_files('#photoPick', photo)
    ok(pg.inner_text('#ocrRead') == 'Прочети текста' and pg.eval_on_selector('#ocrLang button[data-ocr="bul"]', 'b => b.getAttribute("aria-pressed")') == 'true', 'BG: button text + label language BG by default')
    pg.click('#ocrLang button[data-ocr="deu"]')
    pg.reload(); pg.evaluate('LC.dbReady'); pg.click('#cardLabel'); pg.set_input_files('#photoPick', photo)
    ok(pg.eval_on_selector('#ocrLang button[data-ocr="deu"]', 'b => b.getAttribute("aria-pressed")') == 'true', 'label language choice is remembered (DE)')
    ok(no_side_scroll(pg), 'BG 390 px: no sideways scroll with the photo box')
    pg.screenshot(path=os.path.join(SHOTS, 'v25-label-bg.png'), full_page=True)
    ctx.close()

    # With the service worker: reader files stay on the phone after the first use -> works offline.
    ctx = b.new_context(viewport={'width': 390, 'height': 844}, locale='en-GB')
    pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base); pg.evaluate('navigator.serviceWorker.ready'); pg.reload(); pg.evaluate('LC.dbReady')
    ok(pg.evaluate('!!navigator.serviceWorker.controller'), 'service worker controls the page')
    pg.click('#cardLabel'); read_photo(pg)
    cached = pg.evaluate("async () => (await (await caches.open('label-check-v8')).keys()).map(r => r.url.split('/').pop())")
    ok(all(f in cached for f in ('ocr-worker.js', 'tesseract-core-simd-lstm.js', 'tesseract-core-simd-lstm.wasm', 'eng.traineddata.gz')) and 'deu.traineddata.gz' not in cached,
       'after first use: worker, program and only the used language are on the phone')
    ctx.set_offline(True)
    pg.reload(); pg.evaluate('LC.dbReady'); pg.click('#cardLabel'); read_photo(pg)
    ok(pg.inner_text('#ocrStatus').startswith('Done in') and 'palm oil' in pg.input_value('#labelText').lower(), 'offline: Read text still works')
    ctx.set_offline(False)
    ctx.close()
    b.close()
srv.shutdown()

print('\nPage errors:', errors or 'none')
print('ALL PASSED' if not fails and not errors else '%d FAILED' % (len(fails) + len(errors)))
sys.exit(1 if fails or errors else 0)
