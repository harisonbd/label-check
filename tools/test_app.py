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
    ok('EU data from' in pg.inner_text('.data-line'), 'data line shows the EU data date')

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

    print('German, dark, 360 px')
    ctx, pg = new_page(b, base, 'de-AT', dark=True, width=360)
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
srv.shutdown()

print('\nPage errors:', errors or 'none')
print('ALL PASSED' if not fails and not errors else '%d FAILED' % (len(fails) + len(errors)))
sys.exit(1 if fails or errors else 0)
