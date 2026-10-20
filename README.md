# Label Check

Personal phone web app. Scan food or cosmetics, see a red / orange / green result with reasons.
Later it becomes a part of Jarvis.

## Kickoff summary (agreed 2026-10-12)

- **Done:** Scan food or cosmetics on the Android phone and get a red alert for anything on the avoid list or the starter rules.
- **Deliverable:** Installable web app on GitHub Pages (same setup as Pocket Docs).
- **Data:** Open Food Facts and Open Beauty Facts APIs (free, ODbL, credit shown in the app).
- **Photo reading:** Free share flow to the Claude app. The paid API can replace it later.
- **Data leaving the phone:** Barcodes go to Open Food Facts / Open Beauty Facts. Label photos go to Claude only when shared. Avoid list, rule settings, history and saved products stay on the phone.
- **Cost:** 0 EUR. **Backup:** this repo + "Export backup" in the app.
- **Not in v1:** rule groups beyond the starter set, alternatives, travel translation mode, price log, Jarvis links.

## Files

| File | What it does |
|---|---|
| index.html | The screens: Scan, My list, Rules, History |
| style.css | Colours and layout (light and dark) |
| app.js | Scanning, lookup, rule check, label reading, backup |
| rules.json | Starter rules, each with a source |
| manifest.json | Makes the app installable |
| sw.js | Lets the app open without internet |
| icon-192.png, icon-512.png | App icon |

## Change a rule

Edit `rules.json`. Each rule needs: `id`, `group`, `name`, `applies` (food or cosmetic), `level` (high = red, medium = orange), `reason`, `terms`, `tags`, `source`.
After any change, raise `VERSION` in `sw.js` (for example `label-check-v2`), so the phone loads the new files.

## Parked ideas

Travel mode (translate labels), compare 2 products, better food alternative, EU fragrance allergen group, cosmetics "(nano)" flag, price log, shopping-list check, expiry tracker link, open-jar reminder, AGES recall alerts, paid API reading, add missing products to Open Food Facts.
