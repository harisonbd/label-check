# Label Check

Personal phone web app. Scan food or cosmetics, see a red / orange / green result with reasons.
Later it becomes a part of Jarvis.

## Kickoff summary (agreed 2026-10-12)

- **Done:** Scan food or cosmetics on the Android phone and get a red alert for anything on the avoid list or the starter rules.
- **Deliverable:** Installable web app on GitHub Pages (same setup as Pocket Docs).
- **Data:** Open Food Facts and Open Beauty Facts APIs (free, ODbL, credit shown in the app).
- **Photo reading:** Free share flow to the Claude app. The paid API can replace it later.
- **Photo reading (v2.5, 20 Oct 2026):** offline on the phone with Tesseract (folder `ocr/`), no Claude needed. The Claude share flow stays as option 2 for hard labels.
- **Data leaving the phone:** Barcodes go to Open Food Facts / Open Beauty Facts. Label photos go to Claude only when shared. Avoid list, rule settings, history and saved products stay on the phone.
- **Cost:** 0 EUR. **Backup:** this repo + "Export backup" in the app.
- **Not in v1:** rule groups beyond the starter set, alternatives, travel translation mode, price log, Jarvis links.

## Files

| File | What it does |
|---|---|
| index.html | The screens: Scan (quick answer + Details), My list (incl. allergens, settings, offline readers, what the app checks), History (with a ♥ Favourites filter) |
| style.css | Colours and layout: "Clear blue" (light) and "Night" (dark) |
| i18n.js | All screen texts in English, German and Bulgarian |
| db.js | Offline ingredient database lookup (LCDB) |
| data/ | The ingredient database (see data/SOURCES.md) |
| data/products.json | Our own product list: products that Open Food Facts / Open Beauty Facts do not have. Checked first on a scan (offline too); products without a barcode are found with Search. Label data only, no photos. |
| app.js | Scanning, lookup, ingredient check, result screen, detail, favourites, label reading, backup |
| manifest.json | Makes the app installable |
| sw.js | Lets the app and the database open without internet |
| ocr/ | Offline label reader: tesseract.js-core 7.0.0 + language files EN/DE/BG/HU/CS/SK/SL (Apache-2.0, see ocr/README.txt). Loaded only on "Read text" or "Download all languages" |
| icon-192.png, icon-512.png | App icon |
| tools/ | Database download (fetch_sources.py), build (build_db.py), tests (test_db.js, test_app.py), IARC list |
| .github/workflows/update-db.yml | Monthly automatic database update on GitHub |
| .github/workflows/audit.yml | Accuracy check by hand: compares our finds with Open Food Facts tags on real products (tools/audit.js) |

## Change the data or a text

- Database: updates itself every month (see `tools/FETCH.md`). By hand: `python tools/fetch_sources.py _sources`, then `python tools/build_db.py _sources data` and `node tools/test_db.js`.
- Screen text: edit `i18n.js` (same key in `en`, `de` and `bg`).
- App test (needs Python Playwright): `python tools/test_app.py`.
- After any change, raise `VERSION` in `sw.js` (for example `label-check-v8`), so the phone loads the new files.

## Parked ideas

Travel mode (translate labels), compare 2 products, better food alternative, EU fragrance allergen group, cosmetics "(nano)" flag, price log, shopping-list check, expiry tracker link, open-jar reminder, AGES recall alerts, paid API reading, add missing products to Open Food Facts.
