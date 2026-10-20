# Label Check – ingredient database (v2)

Built 2026-10-20 by `tools/build_db.py`. Works offline. Test: `node tools/test_db.js`.

## Files

| File | Size | What is in it |
|---|---|---|
| db-cosmetics.json | 1.7 MB (330 KB zipped) | 33,602 INCI names from EU CosIng: function, level, flags, links to the sources. 1,417 extra names (US INCI names, WATER→AQUA, Lilial…). |
| db-food.json | 0.16 MB (32 KB zipped) | 541 E-numbers with names in EN/DE/BG, the 14 EU food allergens (EN/DE/BG), 1 food rule (trans fat). |
| db-meta.json | 0.38 MB (63 KB zipped) | Level names and reason texts in EN/DE/BG, 82 function names, EU annex entries (limits, conditions, expert opinion links), ED and IARC entries, sources. |

## Sources (all free)

| Source | Used for | Downloaded |
|---|---|---|
| [EU CosIng](https://ec.europa.eu/growth/tools-databases/cosing/) – all 33,656 ingredients + Annexes II–VI (2,389 entries) | cosmetics: function, banned / restricted, fragrance allergens | 2026-10-20 |
| [EU endocrine disruptor lists I–III](https://edlists.org/the-ed-lists) | concern / under review | 2026-10-20 |
| [IARC list of classifications](https://monographs.iarc.who.int/list-of-classifications/) (Groups 1, 2A, 2B) | concern | 2026-10-20 |
| [EU food additives database](https://ec.europa.eu/food/food-feed-portal/screen/food-additives/search) | which E-numbers are allowed in the EU | 2026-10-20 |
| [Open Food Facts taxonomies](https://github.com/openfoodfacts/openfoodfacts-server/tree/main/taxonomies) (ODbL) | additive and allergen names in EN/DE/BG, EFSA links, vegan flags | 2026-10-20 |
| Regulation (EU) 1169/2011, Annex II | the 14 food allergens | – |

Credit in the app: "Ingredient data: European Commission (CosIng, food additives database), edlists.org, IARC/WHO, Open Food Facts (ODbL)."

## Levels (most severe first) – never "safe"

| Code | Level | Colour | Comes from |
|---|---|---|---|
| b | Banned in EU | red | CosIng Annex II without conditions · E-number not on the EU additive list · E171 · nano-only bans when the label says (nano) |
| c | Concern | orange | EU ED list I (health) · IARC 1 / 2A / 2B · curated: formaldehyde releasers, MI/MCI, Southampton colours, nitrite/nitrate, trans fat |
| u | Under review | orange | EU ED list II or III (health) |
| r | Restricted | info | CosIng Annex III–VI · Annex II with conditions ("except…", "when used in hair dye…") · D4/D5/D6 (REACH) · EU label warnings (aspartame, polyols) |
| n | No concerns found | green | none of the above |

Flags: `f` fragrance · `a` fragrance allergen that must be on the label (Regulation (EU) 2023/1545) · `e` endocrine finding for the environment only (note, no colour change) · `o` old CosIng name · `h` EFSA exposure note (food, note only).

## Decisions (change them in `tools/build_db.py`)

1. **Research papers do not set a level.** Only official lists and reviews. The app shows a "Find studies" link (Europe PMC) on the detail screen.
2. **Environment-only endocrine findings** (e.g. nonoxynols) are a note, not orange.
3. **IARC matches skipped when the route does not apply:** ethanol and acetaldehyde in drinks, ginkgo extract (eaten), attapulgite (fibre length unknown), talc and E153 in food (evidence is about powder/inhalation). TiO2, carbon black, quartz and talc in cosmetics get a short "breathing in powder" note.
4. **Vitamin D3** is on ED list I only as a rat poison → skipped.
5. **EFSA "may exceed the daily intake"** (Open Food Facts data) is a dated note only. Skipped for E200/E202: EFSA raised the sorbate ADI to 11 mg/kg in 2019.
6. **"Please consider…" notes** in CosIng (e.g. tallow from high-risk animal material) are notes, not levels.
7. **Not on the EU additive list ≠ banned.** Only 53 hand-checked E-numbers (old colours, bromates, flour bleaches, antibiotics, BVO…) are "Banned in EU". Others (enzymes, dextrin, gelatine…) are simply not EU additives.
8. **Nano-only bans** (styrene/acrylates copolymer, gold, platinum, Regulation (EU) 2024/858) apply only when the label says "(nano)".
9. **v1 rules kept as curated rules** with their sources: E171, trans fat, Southampton colours, nitrite, MI, formaldehyde releasers. Banned parabens, Lilial, zinc pyrithione and triclosan now come from CosIng/ED data directly.

## Limits

- CosIng texts (annex entries, conditions) are English only. Level names, reasons and functions are EN/DE/BG.
- The app cannot know if a product is leave-on or rinse-off, or the amount. "Restricted" means "allowed with limits", not "too much".
- Food: names are matched as whole words; a few allergen synonyms are broad (e.g. "butter" → milk).
- Update: re-download with `tools/FETCH.md`, then run the build and the test.
