"""Label Check v2 – app test in a phone-size browser (390 x 844).
Run from the repo root:  python tools/test_app.py
Needs: pip install playwright && playwright install chromium
Starts a local web server, fakes the Open Food Facts answer, and checks the main screens.
Screenshots go to tools/shots/ (not for GitHub)."""
import json, os, sys, threading, http.server, functools
from playwright.sync_api import sync_playwright, Page

# v2.15: the text part of "Read a label" sits in a fold. Tests that type text open the fold first, as a person would.
def _wrap(name):
    orig = getattr(Page, name)
    def f(self, sel, *a, **k):
        if isinstance(sel, str) and (sel in ('#labelText', '#checkLabel', '#pasteBtn') or sel.startswith('input[name=kind]')) \
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

def fake_api(route):
    url = route.request.url
    if 'openfoodfacts' in url and '9001234567890' in url:
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': 1, 'product': {
            'product_name': 'Extrawurst', 'brands': 'Example', 'ingredients_text': SAUSAGE,
            'additives_tags': ['en:e250', 'en:e451'], 'allergens_tags': ['en:mustard', 'en:celery', 'en:milk'],
            'nutriscore_grade': 'd', 'nova_group': 4, 'nutriments': {'fat_100g': 24, 'saturated-fat_100g': 9.5, 'proteins_100g': 13}}}))
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
    b = p.chromium.launch()

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
    pg.click('#favBtn')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#labelPanel') and pg.is_hidden('#result'), 'Back from a label result shows the label screen')
    pg.go_back(); pg.wait_for_timeout(200)
    ok(pg.is_visible('#scanner') and pg.is_visible('#cardScan') and pg.locator('.startcards .scard').count() == 2, 'Back again shows the start screen with the 2 big buttons (v2.8)')
    ok(pg.evaluate("[...document.querySelectorAll('.startcards .scard')].every(c => getComputedStyle(c).textAlign === 'center' && getComputedStyle(c).alignItems === 'center')"), 'v2.8: text and icon are centred in both big buttons')
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
    ok(not pg.eval_on_selector('#foodAlgBox', 'd => d.open') and not pg.eval_on_selector('#moreFold', 'd => d.open'), 'My list: allergens and "More" start folded')
    pg.click('#foodAlgBox summary')
    pg.click('#foodAlgList label:has-text("Mustard") input')
    pg.click('#moreFold summary')
    pg.click('#veganSwitch')
    pg.click('#picks .frag-chip')
    ok(pg.eval_on_selector('#picks .frag-chip', 'b => b.getAttribute("aria-pressed")') == 'true' and pg.inner_text('#picks .frag-chip').startswith('✓'), 'fragrance chip is pressed after a tap')
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
    pg.click('#histFilter button[data-f=all]')
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
    ok(pg.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()') == '#7AA2FF', 'dark = Graphite (blue accent, no mint)')
    ok(pg.get_attribute('#themeColor', 'content').upper() == '#121417', 'phone bar colour = graphite')
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
        ok(pg.inner_text('.topbar .ver') == 'v2.20.1' and top[0] < 32 and top[1] and no_side_scroll(pg), '%s: "v2.20.1" next to the title, one line, left of EN | BG' % tag)
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
        ok(h < 1700 and no_side_scroll(pg), '%s: My list is short (%d px, was about 4500; v2.12/13 added "Taught names" + vibration) and has no sideways scroll' % (tag, h))
        ok(pg.locator('#fragSwitch').count() == 0 and pg.locator('#picks .frag-chip').count() == 1, '%s: fragrance is the first Quick pick chip, no separate switch' % tag)
        ok(all(not pg.eval_on_selector(f, 'd => d.open') for f in ('#foodAlgBox', '#cosAlgBox', '#rulesFold', '#moreFold')), '%s: allergens, "What the app checks" and "More" start closed' % tag)
        ok('ODbL' in pg.text_content('#rulesFold') and pg.text_content('#moreFold summary').strip() != '', '%s: credit line (ODbL) is still in "What the app checks"; "More" has a title' % tag)
        pg.click('#picks .frag-chip'); pg.click('#picks .frag-chip')
        ok(pg.eval_on_selector('#picks .frag-chip', 'b => b.getAttribute("aria-pressed")') == 'false' and pg.evaluate("!LC.state.avoidFragrance"), '%s: second tap switches fragrance off again' % tag)
        pg.click('#rulesFold summary')
        ok(pg.is_visible('#rulesBox .levels'), '%s: tapping "What the app checks" opens it' % tag)
        pg.evaluate("document.querySelector('#rulesFold').open = false; scrollTo(0, 0)")
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
    pg.click('#answer .strip button'); pg.wait_for_timeout(200)
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
    ok(word(pg) == 'Избягвай' and pg.inner_text('#dtop .qy') == 'Може да съдържа следи: Соя' and 'следи от твой алерген' in pg.inner_text('#dtop .qr'),
       'ticked soy only in "Kann Spuren von Soja": red, "Може да съдържа следи", reason "следи от твой алерген" (%s / %s)' % (pg.inner_text('#dtop .qy'), pg.inner_text('#dtop .qr')))
    open_details(pg)
    ok('(следи)' in pg.inner_text('.allergen-line') and pg.inner_text('#groups li:has-text("Soja") .chip') == 'Може да съдържа', 'Details: allergen line "(следи)", row chip "Може да съдържа"')
    pg.screenshot(path=os.path.join(SHOTS, 'v29-traces-bg.png'))
    pg.click('.tabbar button[data-go=scan]')
    read_label(pg, 'Zutaten: Hartweizengrieß, Wasser', 'food')
    ok(word(pg) == 'Избягвай' and pg.inner_text('#dtop .qy') == 'Съдържа: Глутен' and pg.inner_text('#dtop .qr') == 'Причина: твой алерген', 'Hartweizengrieß with gluten ticked: red "Съдържа: Глутен"')
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
    ok(cut == ['Zutaten: Zucker, Weizenmehl, Palmöl, Haselnüsse 8%.', 'Zutaten Teig: Mehl, Butter, Zucker. Zutaten Füllung: Äpfel, Zimt', 'Összetevők: búzaliszt, cukor, só.'], 'text stops at a heading in another language, same-language headings stay (%s)' % cut)
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
        pg.click('.tabbar button[data-go=list]'); pg.click('#moreFold summary'); pg.click('#exportBtn')
    bk = json.load(open(dl.value.path(), encoding='utf-8'))
    ok(bk.get('taught', {}).get('glycern', {}).get('no') == 'GLYCERIN' and bk.get('vibrate') is True, 'backup file includes the taught names and the vibration setting')
    pg.click('#taughtBox summary'); pg.wait_for_timeout(200)
    names = pg.evaluate("[...document.querySelectorAll('#taughtList .taughtrow')].map(r => r.querySelector('s').textContent + '>' + r.querySelector('b').textContent)")
    ok(pg.inner_text('#taughtCount') == '(3)' and 'GLYCERN>не поправяй' in names and 'BUTYLPHENYL METHYLPROPI0NAL>Butylphenyl Methylpropional' in names,
       'My list: "Научени имена" (3), GLYCERN → "не поправяй" (%s)' % names)
    pg.evaluate("document.getElementById('taughtBox').scrollIntoView({block: 'center'})"); pg.screenshot(path=os.path.join(SHOTS, 'v212-mylist-bg.png'))
    for k in range(3): pg.locator('#taughtList .taughtrow .x').first.click(); pg.wait_for_timeout(150)
    ok(pg.inner_text('#taughtCount') == '(0)' and 'Още няма' in pg.inner_text('#taughtList') and pg.evaluate("localStorage.getItem('lc.taught')") == '{}', '✕ deletes them; empty text')
    ok(pg.is_visible('#vibSwitch') or pg.is_visible('#vibRow'), 'v2.13: "Вибрация при резултат" switch in My list')
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
    ok(pg.locator('#historyList li').nth(0).locator('.mstrip i.g-red').count() >= 1 and pg.locator('#historyList li').nth(1).locator('.mstrip i').count() == 3,
       'History: a mini colour strip under each product (red block for the palm oil product)')
    n = len(pg.evaluate('window.__buzz')); pg.locator('#historyList li .open').first.click(); pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(len(pg.evaluate('window.__buzz')) == n, 'opening a saved product from History: no vibration')
    pg.screenshot(path=os.path.join(SHOTS, 'v213-history-bg.png'))
    pg.click('.tabbar button[data-go=list]'); pg.click('#vibSwitch')
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
    ok(pg.inner_text('#photoTip') == 'Снимай отблизо, само списъка със съставки.' and pg.is_visible('#textFold') and not pg.eval_on_selector('#textFold', 'd => d.open'),
       'Read a label: close-up tip under the photo cards; the text part is a folded row (paste)')
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

    print('v2.14: simpler card – word + one line + strip; ⓘ Подробности / ↻ Снимай пак; Следващ продукт')
    ctx, pg = new_page(b, base, 'bg-BG', dark=True)
    pg.evaluate("localStorage.setItem('lc.avoid', JSON.stringify([{id:'a1', text:'methylisothiazolinone'}])); 0"); reload_ready(pg)
    read_label(pg, 'AQUA, GLYCERIN, PANTHENOL, CETYL ALCOHOL, ALLANTOIN, CITRIC ACID', 'cosmetic', 'Крем')
    ok(word(pg) == 'Без предупреждения' and pg.locator('#oneLine').count() == 0 and pg.locator('#answer .qr, #answer #chkLine, #answer #knownLine, #answer #legend, #answer .strip-ends').count() == 0
       and pg.locator('#answer .strip button').count() == 6, 'green card: only the word and the strip (no line, no chips, no legend)')
    ok(pg.inner_text('#detBtn') == 'Подробности' and pg.inner_text('#againBtn') == 'Снимай пак' and pg.inner_text('#nextBtn') == 'Следващ продукт'
       and 'btn-primary' in pg.get_attribute('#nextBtn', 'class') and 'btn-ghost' in pg.get_attribute('#againBtn', 'class'), 'two doors "Подробности" / "Снимай пак", blue "Следващ продукт"')
    ok(pg.is_hidden('#details') and pg.evaluate("[...document.querySelectorAll('#chkLine b')].length") == 2, 'the "Проверено" chips are in Подробности (closed)')
    pg.click('#detBtn'); pg.wait_for_timeout(300)
    ok(pg.is_visible('#dtop #chkLine') and pg.is_visible('#dtop #legend') and pg.get_attribute('#detBtn', 'aria-expanded') == 'true', 'ⓘ Подробности opens the info: Проверено chips + legend at the top')
    pg.screenshot(path=os.path.join(SHOTS, 'v214-green-details-bg.png'))
    pg.click('#detBtn')
    ok(pg.is_hidden('#details'), 'a second tap closes it')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    read_label(pg, SHOWER, 'cosmetic', 'Душ гел')
    ok(word(pg) == 'Избягвай' and pg.inner_text('#oneLine') == 'Methylisothiazolinone, Butylphenyl Methylpropional' and card_fits(pg) and no_side_scroll(pg),
       'red card: one line with the names only (%s)' % pg.inner_text('#oneLine'))
    ok(pg.inner_text('#dtop .qr') == 'Причина: в твоя списък, забранено в ЕС', 'the reason is in Подробности')
    pg.screenshot(path=os.path.join(SHOTS, 'v214-red-bg.png'))
    pg.click('#againBtn'); pg.wait_for_selector('#labelPanel:not([hidden])')
    ok(pg.is_visible('#photoInput') or pg.is_visible('.filebtn'), '"Снимай пак" opens Read a label')
    pg.go_back(); pg.wait_for_selector('#result:not([hidden]) #answer')
    pg.click('.tabbar button[data-go=scan]')
    if pg.is_hidden('#cardLabel'): pg.click('.tabbar button[data-go=scan]')
    pg.evaluate("localStorage.setItem('lc.allergens', JSON.stringify({food:['soybeans', 'gluten'], cos:[]})); 0"); reload_ready(pg)
    read_label(pg, 'Zutaten: Hartweizengrieß, Zucker. Kann Spuren von Soja enthalten.', 'food')
    ok(word(pg) == 'Избягвай' and pg.inner_text('#oneLine') == 'Глутен, Соя (следи)', 'red with traces: "Глутен, Соя (следи)" in one line (%s)' % pg.inner_text('#oneLine'))
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
    cached = pg.evaluate("async () => (await (await caches.open('label-check-v32')).keys()).map(r => r.url.split('/').pop())")
    ok(all(f in cached for f in ('ocr-worker-2.js', 'tesseract-core-simd-lstm.js', 'tesseract-core-simd-lstm.wasm', 'eng.traineddata.gz')) and 'deu.traineddata.gz' not in cached,
       'after first use: worker, program and only the used language are on the phone')
    ctx.set_offline(True)
    reload_ready(pg); pg.click('#cardLabel'); read_photo(pg)
    ok(pg.inner_text('#ocrStatus').startswith('Done in') and 'palm oil' in pg.input_value('#labelText').lower(), 'offline: Read text still works')
    ctx.set_offline(False)
    print('v2.8: label reader without internet (My list)')
    pg.click('.tabbar button[data-go=list]'); pg.wait_for_timeout(300)
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
    pg.goto(base.replace('index.html', '') + '?shared=1'); pg.evaluate('LC.dbReady'); pg.wait_for_selector('#ocrArea:not([hidden])', timeout=8000)
    ok(pg.is_visible('#labelPanel') and pg.is_visible('#ocrArea') and not pg.evaluate("caches.has('lc-share')"), 'shared photo opens "Read a label" with the photo (and is then removed)')
    ok(pg.is_hidden('#updBar'), 'no "new version" line before an update')
    ctx.close()
    # ---------- v2.15 ----------
    ctx, pg = new_page(b, base, 'en-GB')
    pg.click('#cardLabel')
    ok(pg.locator('#photoStart .scard').count() == 2 and pg.is_visible('#photoTip') and pg.is_visible('#textFold') and pg.is_hidden('#checkBar') and pg.is_hidden('#againRow'),
       'v2.15: Read a label before a photo: two photo cards, short tip, folded "Type or paste" row')
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
    ok('Cosmetic' in pg.inner_text('#typeChip') and 'tap if wrong' in pg.inner_text('#typeChip'), 'v2.15: type chip "Cosmetic ▾ tap if wrong" on the card')
    pg.click('#typeChip'); pg.click('#typeRow .seg:has-text("Food")'); pg.wait_for_selector('#typeChip')
    ok(pg.evaluate('LC.state.current.p.kind') == 'food' and 'Food' in pg.inner_text('#typeChip'), 'v2.15: choosing another type checks the product again as that type')
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
    ok(pg.is_visible('#secondPhoto') and 'round bottle' in pg.inner_text('#secondPhoto'), 'v2.16: "Add 2nd photo (round bottle)" next to "Another photo"')
    pg.evaluate("LC.showProduct({code:'label-x', kind:'food', source:'label', name:'x', ingredientsText:'Zutaten: Aqua', read:{photo:true, list:true}, texts:['Zutaten: Aqua'], tags:[], allergens:[], analysis:[], fetchedAt:Date.now()})")
    pg.wait_for_selector('#result:not([hidden]) #answer')
    ok(pg.is_visible('#secondBtn') and 'Incomplete' in word(pg), 'v2.16: a grey photo result offers "Add 2nd photo" (%s)' % word(pg))
    ctx.close()

    # ---------- v2.17: in-app camera, sweep, "Your photos" ----------
    bcam = p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
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
    ok(all(x in cn for x in need) and not any('©' in x or '“' in x for x in cn) and 12 <= len(cn) <= 19 and sum(1 for z in cn if z.lower().startswith('phenoxyeth')) == 1 and not any(z.startswith('Moniumpolypeptid') for z in cn) and any(x.endswith('hydrogensulfat') for x in cn) and any(x.endswith('hydrogensulfosuccinat') for x in cn), 'v2.20: three garbled frames give clean names, none of the real names lost, Ponceau (E124) kept (%d names: %s)' % (len(cn), cn[:4]))
    ok(d.count('Dodecylpoly') == 1 and d.count('Glycerin') == 1 and 'Aqua' in d, 'v2.17.1: near-identical names from several pictures count once (%s)' % d)
    pg.click('#modeSweep'); pg.click('#shutter'); pg.wait_for_timeout(4200)
    ok('Move slowly' in pg.inner_text('#camHint'), 'v2.17: sweep: "Move slowly over the list · N pictures"')
    pg.click('#shutter'); pg.wait_for_timeout(1200)
    ok(pg.locator('#thumbs .tn').count() >= 3 and pg.evaluate("!document.getElementById('shutter').classList.contains('stop')"), 'v2.17: sweep adds sharp pictures and stops (%d photos)' % pg.locator('#thumbs .tn').count())
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
    rd = pg.evaluate("() => { const r = id => document.getElementById(id).getBoundingClientRect(); return { thumbs: document.querySelectorAll('#thumbs .tn').length, now: document.querySelectorAll('#thumbs .tn.now').length, cam: !document.getElementById('photoCam').hidden, x: document.querySelectorAll('#thumbs .tx').length && getComputedStyle(document.querySelector('#thumbs .tx')).display, checkBottom: r('checkBar').bottom, vh: innerHeight, again: getComputedStyle(document.getElementById('againRow')).display, bar: !document.getElementById('readBar').hidden, crop: getComputedStyle(document.getElementById('cropWrap')).display } }""")
    ok(rd['thumbs'] == 2 and rd['now'] == 1 and rd['cam'] and rd['x'] == 'none' and rd['again'] == 'none' and rd['checkBottom'] <= rd['vh'] and rd['bar'] and rd['crop'] == 'none', 'v2.19: progress bar shows, the big picture is hidden, no jumping; v2.18.3: while several photos are read, the small pictures stay on the same screen (the one being read is marked, no ✕) (%s)' % rd)
    pg.wait_for_selector('#result:not([hidden]) #answer', timeout=120000)
    ok(pg.is_hidden('#photoCam') and not pg.evaluate("document.getElementById('labelPanel').classList.contains('reading')"), 'v2.18.3: after reading the small pictures are gone and the result shows')
    cctx.close(); bcam.close()

    # A real update: serve a copy of the app, change its sw.js (as a push does), ask the browser to check.
    import shutil, tempfile
    tmp = tempfile.mkdtemp()
    for f in ('index.html', 'style.css', 'i18n.js', 'db.js', 'app.js', 'manifest.json', 'sw.js', 'icon-192.png', 'icon-512.png'): shutil.copy(os.path.join(ROOT, f), tmp)
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
    swp = os.path.join(tmp, 'sw.js'); new_sw = open(swp, encoding='utf-8').read().replace("label-check-v32'", "label-check-test-update'")
    open(swp, 'w', encoding='utf-8').write(new_sw)
    pg.evaluate('navigator.serviceWorker.getRegistration().then(r => r.update())')
    pg.wait_for_selector('#updBar:not([hidden])', timeout=30000)
    ok(pg.is_visible('#updBar') and pg.inner_text('#updReload') == 'Reload', 'after a new version took over: "A new version is ready. Reload"')
    for i in range(50):   # the new worker takes over first; the old cache goes a moment later (after its reader files are copied)
        keys = pg.evaluate('caches.keys()')
        if 'label-check-v32' not in keys: break
        pg.wait_for_timeout(300)
    ok('pocketdocs-v7' in keys and 'sunlauncher-v1' in keys and 'label-check-v32' not in keys and 'label-check-test-update' in keys,
       'v2.14.1: the update deletes only the old Label Check cache; Pocket Docs / Sun Launcher caches stay (%s)' % keys)
    ctx.close(); srv2.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
    b.close()
srv.shutdown()

print('\nPage errors:', errors or 'none')
print('ALL PASSED' if not fails and not errors else '%d FAILED' % (len(fails) + len(errors)))
sys.exit(1 if fails or errors else 0)
