#!/usr/bin/env python3
"""Label Check v2 - build the offline ingredient database.

Input  (folder given as 1st argument, default ../_sources): the raw downloads
  lc-cosing-ingredients.json, lc-cosing-substances.json, lc-cosing-range9.json  (EU CosIng)
  lc-edlists.json        (EU endocrine disruptor lists, edlists.org)
  lc-iarc.csv            (IARC list of classifications)
  lc-fad.json            (EU food additives database, Food and Feed Information Portal)
  additives.txt, additives_classes.txt, allergens.txt  (Open Food Facts taxonomies)
Output (folder given as 2nd argument, default ../data):
  db-meta.json, db-cosmetics.json, db-food.json

Levels (most severe first): b = Banned in EU, c = Concern, u = Under review,
r = Restricted, n = No concerns found. Never "safe".
Run:  python3 -I build_db.py <sources folder> <output folder>
"""
import csv, json, os, re, sys, unicodedata
from collections import defaultdict, Counter

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', '_sources')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), '..', 'data')
P = lambda f: os.path.join(SRC, f)
L = lambda v: v if isinstance(v, list) else ([v] if v not in (None, '') else [])
SEV = {'b': 5, 'c': 4, 'u': 3, 'r': 2, 'n': 1}

def worst(*lv):
    return max([x for x in lv if x] or ['n'], key=lambda x: SEV[x])

def cas_list(s):
    return [c.strip() for c in re.split(r'[\/,;\s]+', s or '') if re.match(r'^\d{2,7}-\d{2}-\d$', c.strip())]

def clean(s, n=420):
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'

# ---------------------------------------------------------------- texts (EN / DE / BG)
LEVELS = {
    'b': {'en': 'Banned in EU', 'de': 'In der EU verboten', 'bg': 'Забранено в ЕС', 'color': 'red'},
    'c': {'en': 'Concern', 'de': 'Bedenken', 'bg': 'Има опасения', 'color': 'orange'},
    'u': {'en': 'Under review', 'de': 'Wird geprüft', 'bg': 'В процес на оценка', 'color': 'orange'},
    'r': {'en': 'Restricted', 'de': 'Eingeschränkt', 'bg': 'Ограничено', 'color': 'info'},
    'n': {'en': 'No concerns found', 'de': 'Keine Bedenken gefunden', 'bg': 'Не са открити опасения', 'color': 'green'},
}

# {ref} = annex entry number, {g} = IARC group
REASONS = {
    'ann.II.b': {'en': 'Banned in EU cosmetics (Annex II, entry {ref}).',
                 'de': 'In EU-Kosmetik verboten (Anhang II, Eintrag {ref}).',
                 'bg': 'Забранено в козметиката в ЕС (Приложение II, позиция {ref}).'},
    'ann.II.r': {'en': 'Banned in the EU in some forms or uses (Annex II, entry {ref}).',
                 'de': 'In der EU in bestimmten Formen oder Verwendungen verboten (Anhang II, Eintrag {ref}).',
                 'bg': 'Забранено в ЕС в някои форми или употреби (Приложение II, позиция {ref}).'},
    'ann.II.adv': {'en': 'Note: the EU bans some forms of this, e.g. by origin (Annex II, entry {ref}).',
                   'de': 'Hinweis: Die EU verbietet manche Formen davon, z. B. nach Herkunft (Anhang II, Eintrag {ref}).',
                   'bg': 'Бележка: ЕС забранява някои форми, напр. според произхода (Приложение II, позиция {ref}).'},
    'ann.nano': {'en': 'Banned in EU cosmetics in nano form (Annex II, entry {ref}).',
                 'de': 'In EU-Kosmetik in Nanoform verboten (Anhang II, Eintrag {ref}).',
                 'bg': 'Забранено в козметиката в ЕС в нано форма (Приложение II, позиция {ref}).'},
    'ann.III': {'en': 'Allowed in EU cosmetics only with limits (Annex III, entry {ref}).',
                'de': 'In EU-Kosmetik nur mit Einschränkungen erlaubt (Anhang III, Eintrag {ref}).',
                'bg': 'Разрешено в козметиката в ЕС само с ограничения (Приложение III, позиция {ref}).'},
    'ann.IV': {'en': 'Colour allowed in EU cosmetics only as listed, with conditions (Annex IV, entry {ref}).',
               'de': 'Farbstoff, in EU-Kosmetik nur wie gelistet und mit Bedingungen erlaubt (Anhang IV, Eintrag {ref}).',
               'bg': 'Оцветител, разрешен в козметиката в ЕС само както е посочено и с условия (Приложение IV, позиция {ref}).'},
    'ann.V': {'en': 'Preservative allowed in EU cosmetics only up to a limit (Annex V, entry {ref}).',
              'de': 'Konservierungsmittel, in EU-Kosmetik nur bis zu einer Höchstmenge erlaubt (Anhang V, Eintrag {ref}).',
              'bg': 'Консервант, разрешен в козметиката в ЕС само до определено количество (Приложение V, позиция {ref}).'},
    'ann.VI': {'en': 'UV filter allowed in EU cosmetics only up to a limit (Annex VI, entry {ref}).',
               'de': 'UV-Filter, in EU-Kosmetik nur bis zu einer Höchstmenge erlaubt (Anhang VI, Eintrag {ref}).',
               'bg': 'UV филтър, разрешен в козметиката в ЕС само до определено количество (Приложение VI, позиция {ref}).'},
    'allergen': {'en': 'Fragrance allergen. EU law requires it on the label above 0.001% in leave-on and 0.01% in rinse-off products.',
                 'de': 'Duftstoff-Allergen. Muss laut EU ab 0,001 % (bleibt auf der Haut) bzw. 0,01 % (wird abgespült) auf dem Etikett stehen.',
                 'bg': 'Ароматен алерген. Според ЕС трябва да е на етикета над 0,001 % (остава върху кожата) или 0,01 % (отмива се).'},
    'ed.I.h': {'en': 'Identified at EU level as an endocrine disruptor (it can disturb hormones).',
               'de': 'Auf EU-Ebene als endokriner Disruptor eingestuft (kann Hormone stören).',
               'bg': 'Определено на ниво ЕС като ендокринен разрушител (може да нарушава хормоните).'},
    'ed.I.e': {'en': 'Identified at EU level as an endocrine disruptor for the environment (wildlife).',
               'de': 'Auf EU-Ebene als endokriner Disruptor für die Umwelt (Tiere) eingestuft.',
               'bg': 'Определено на ниво ЕС като ендокринен разрушител за околната среда (животни).'},
    'ed.II.h': {'en': 'The EU is checking if it disturbs hormones (endocrine disruptor).',
                'de': 'Die EU prüft, ob es Hormone stört (endokriner Disruptor).',
                'bg': 'ЕС проверява дали нарушава хормоните (ендокринен разрушител).'},
    'ed.II.e': {'en': 'The EU is checking if it disturbs hormones in the environment (wildlife).',
                'de': 'Die EU prüft, ob es Hormone in der Umwelt (Tiere) stört.',
                'bg': 'ЕС проверява дали нарушава хормоните в околната среда (животни).'},
    'ed.III.h': {'en': 'A national authority in the EU found that it disturbs hormones. The EU has not decided yet.',
                 'de': 'Eine nationale Behörde in der EU stuft es als hormonell wirksam ein. Die EU hat noch nicht entschieden.',
                 'bg': 'Национален орган в ЕС е установил, че нарушава хормоните. ЕС още не е решил.'},
    'ed.III.e': {'en': 'A national authority in the EU found that it disturbs hormones in the environment. The EU has not decided yet.',
                 'de': 'Eine nationale Behörde in der EU stuft es für die Umwelt als hormonell wirksam ein. Die EU hat noch nicht entschieden.',
                 'bg': 'Национален орган в ЕС е установил, че нарушава хормоните в околната среда. ЕС още не е решил.'},
    'iarc.1': {'en': 'IARC (WHO cancer agency): causes cancer in humans (Group 1).',
               'de': 'IARC (Krebsagentur der WHO): krebserregend für Menschen (Gruppe 1).',
               'bg': 'IARC (агенцията за рак на СЗО): причинява рак при хората (група 1).'},
    'iarc.2A': {'en': 'IARC (WHO cancer agency): probably causes cancer in humans (Group 2A).',
                'de': 'IARC (Krebsagentur der WHO): wahrscheinlich krebserregend (Gruppe 2A).',
                'bg': 'IARC (агенцията за рак на СЗО): вероятно причинява рак (група 2А).'},
    'iarc.2B': {'en': 'IARC (WHO cancer agency): possibly causes cancer in humans (Group 2B).',
                'de': 'IARC (Krebsagentur der WHO): möglicherweise krebserregend (Gruppe 2B).',
                'bg': 'IARC (агенцията за рак на СЗО): възможно е да причинява рак (група 2B).'},
    'iarc.note': {'en': 'IARC rates how strong the evidence is that something can cause cancer, not how big the risk is at normal use.',
                  'de': 'IARC bewertet, wie stark die Belege sind, dass etwas Krebs auslösen kann – nicht, wie groß das Risiko bei normaler Verwendung ist.',
                  'bg': 'IARC оценява колко силни са доказателствата, че нещо може да причини рак, а не колко голям е рискът при нормална употреба.'},
    'efsa.high': {'en': 'EFSA ({y}): people who eat a lot of it, often children, may take in more than the acceptable daily intake. A newer opinion may exist.',
                  'de': 'EFSA ({y}): Wer viel davon isst, oft Kinder, kann mehr als die duldbare tägliche Aufnahmemenge aufnehmen. Es kann eine neuere Bewertung geben.',
                  'bg': 'EFSA ({y}): хора, които ядат много от него, често деца, може да приемат повече от допустимия дневен прием. Може да има по-нова оценка.'},
    'food.noteu': {'en': 'Not on the EU list of allowed food additives. It can still appear in imported food.',
                   'de': 'Nicht auf der EU-Liste der zugelassenen Lebensmittelzusatzstoffe. Kann in importierten Lebensmitteln vorkommen.',
                   'bg': 'Не е в списъка на ЕС с разрешени хранителни добавки. Може да се срещне във вносни храни.'},
    'food.eu': {'en': 'Allowed as a food additive in the EU, only in listed foods and amounts.',
                'de': 'In der EU als Lebensmittelzusatzstoff zugelassen, nur in genannten Lebensmitteln und Mengen.',
                'bg': 'Разрешена хранителна добавка в ЕС, само в посочени храни и количества.'},
    'food.allergen': {'en': 'One of the 14 allergens that EU law requires to be highlighted on food labels.',
                      'de': 'Eines der 14 Allergene, die laut EU auf Lebensmitteln hervorgehoben werden müssen.',
                      'bg': 'Един от 14-те алергена, които според ЕС трябва да са отбелязани на етикета на храните.'},
}

# Curated rules: reason + source. Kept from v1 where possible.
CURATED = {
    'e171': {'lv': 'b',
             'en': 'Banned as a food additive in the EU since 2022. EFSA could no longer confirm it is acceptable in food. Can still appear in imported food.',
             'de': 'Seit 2022 in der EU als Lebensmittelzusatzstoff verboten. Die EFSA konnte die Unbedenklichkeit in Lebensmitteln nicht mehr bestätigen. Kann in importierten Lebensmitteln vorkommen.',
             'bg': 'Забранен като хранителна добавка в ЕС от 2022 г. EFSA вече не можа да потвърди, че е приемлив в храни. Може да се срещне във вносни храни.',
             'src': {'label': 'Regulation (EU) 2022/63', 'url': 'https://eur-lex.europa.eu/eli/reg/2022/63/oj'}},
    'trans-fat': {'lv': 'c',
                  'en': 'Main source of industrial trans fat. The EU limits industrial trans fat to 2 g per 100 g of fat.',
                  'de': 'Hauptquelle für industrielle Transfette. Die EU begrenzt sie auf 2 g pro 100 g Fett.',
                  'bg': 'Основен източник на индустриални трансмазнини. ЕС ги ограничава до 2 g на 100 g мазнини.',
                  'src': {'label': 'Regulation (EU) 2019/649', 'url': 'https://eur-lex.europa.eu/eli/reg/2019/649/oj'}},
    'southampton': {'lv': 'c',
                    'en': 'EU law requires the warning: may have an adverse effect on activity and attention in children.',
                    'de': 'Laut EU ist der Warnhinweis Pflicht: Kann Aktivität und Aufmerksamkeit bei Kindern beeinträchtigen.',
                    'bg': 'Според ЕС е задължително предупреждението: може да има неблагоприятен ефект върху активността и вниманието при децата.',
                    'src': {'label': 'Regulation (EC) 1333/2008, Annex V', 'url': 'https://eur-lex.europa.eu/eli/reg/2008/1333/oj'}},
    'nitrite': {'lv': 'c',
                'en': 'IARC: probably causes cancer in humans (Group 2A) when it forms nitroso compounds in the body. Common in cured meat as curing salt.',
                'de': 'IARC: wahrscheinlich krebserregend (Gruppe 2A), wenn sich im Körper Nitrosamine bilden. Häufig in Pökelwaren als Nitritpökelsalz.',
                'bg': 'IARC: вероятно причинява рак (група 2А), когато в тялото се образуват нитрозосъединения. Често в колбаси като нитритна сол.',
                'src': {'label': 'IARC Monograph 94 (2010)', 'url': 'https://publications.iarc.who.int/Book-And-Report-Series/Iarc-Monographs-On-The-Identification-Of-Carcinogenic-Hazards-To-Humans/Ingested-Nitrate-And-Nitrite-And-Cyanobacterial-Peptide-Toxins-2010'}},
    'aspartame-label': {'lv': 'r',
                        'en': 'EU law requires the label "contains a source of phenylalanine" (important for people with PKU).',
                        'de': 'Laut EU muss "enthält eine Phenylalaninquelle" auf dem Etikett stehen (wichtig bei PKU).',
                        'bg': 'Според ЕС на етикета трябва да пише „съдържа източник на фенилаланин“ (важно при фенилкетонурия).',
                        'src': {'label': 'Regulation (EU) 1169/2011, Annex III', 'url': 'https://eur-lex.europa.eu/eli/reg/2011/1169/oj'}},
    'polyols': {'lv': 'r',
                'en': 'EU law requires the label "excessive consumption may produce laxative effects" when the food has more than 10% added polyols.',
                'de': 'Laut EU ist der Hinweis "kann bei übermäßigem Verzehr abführend wirken" Pflicht, wenn mehr als 10 % Polyole zugesetzt sind.',
                'bg': 'Според ЕС е задължително „прекомерната консумация може да има слабителен ефект“, ако храната съдържа над 10 % добавени полиоли.',
                'src': {'label': 'Regulation (EU) 1169/2011, Annex III', 'url': 'https://eur-lex.europa.eu/eli/reg/2011/1169/oj'}},
    'd456': {'lv': 'r',
             'en': 'EU (REACH) limits D4, D5 and D6 silicones to below 0.1%: in rinse-off products now, in leave-on products from 6 June 2027.',
             'de': 'Die EU (REACH) begrenzt die Silikone D4, D5 und D6 auf unter 0,1 %: in abwaschbaren Produkten schon jetzt, in Produkten, die auf der Haut bleiben, ab 6. Juni 2027.',
             'bg': 'ЕС (REACH) ограничава силиконите D4, D5 и D6 под 0,1 %: в отмиващи се продукти вече, а в продукти, които остават върху кожата – от 6 юни 2027 г.',
             'src': {'label': 'Regulation (EU) 2024/1328 (REACH Annex XVII, entry 70)', 'url': 'https://eur-lex.europa.eu/eli/reg/2024/1328/oj'}},
    'frel': {'lv': 'c',
             'en': 'Formaldehyde releaser. Formaldehyde causes cancer (IARC Group 1) and skin allergy. The EU requires the warning "releases formaldehyde" above 0.001%.',
             'de': 'Formaldehydabspalter. Formaldehyd ist krebserregend (IARC Gruppe 1) und allergen. Laut EU ist ab 0,001 % der Hinweis "setzt Formaldehyd frei" Pflicht.',
             'bg': 'Отделя формалдехид. Формалдехидът причинява рак (IARC група 1) и кожна алергия. ЕС изисква предупреждение „отделя формалдехид“ над 0,001 %.',
             'src': {'label': 'Regulation (EU) 2022/1181', 'url': 'https://eur-lex.europa.eu/eli/reg/2022/1181/oj'}},
    'mi': {'lv': 'c',
           'en': 'Strong skin allergen. The EU allows it only in rinse-off products, at most 0.0015%, and bans it in leave-on products.',
           'de': 'Starkes Kontaktallergen. Die EU erlaubt es nur in abwaschbaren Produkten bis 0,0015 % und verbietet es in Produkten, die auf der Haut bleiben.',
           'bg': 'Силен кожен алерген. ЕС го разрешава само в отмиващи се продукти, до 0,0015 %, и го забранява в продукти, които остават върху кожата.',
           'src': {'label': 'Regulation (EU) 2016/1198', 'url': 'https://eur-lex.europa.eu/eli/reg/2016/1198/oj'}},
}
CTX = {  # extra context for some IARC matches (exposure route)
    'inhal': {'en': 'The IARC finding is about breathing in fine dust or powder.',
              'de': 'Die IARC-Einstufung betrifft das Einatmen von feinem Staub oder Pulver.',
              'bg': 'Оценката на IARC се отнася за вдишване на фин прах или пудра.'},
    'talc': {'en': 'The IARC finding (2024) is mainly about powder (breathing it in or use in the genital area).',
             'de': 'Die IARC-Einstufung (2024) betrifft vor allem Puder (Einatmen oder Anwendung im Intimbereich).',
             'bg': 'Оценката на IARC (2024) се отнася главно за пудра (вдишване или употреба в интимната зона).'},
}

FUNC_TR = {  # CosIng function -> (DE, BG)
 'SKIN CONDITIONING': ('Hautpflegend', 'Грижа за кожата'), 'HAIR CONDITIONING': ('Haarpflegend', 'Грижа за косата'),
 'SKIN CONDITIONING - EMOLLIENT': ('Hautpflegend – weichmachend', 'Омекотява кожата'), 'ANTIOXIDANT': ('Antioxidans', 'Антиоксидант'),
 'SKIN PROTECTING': ('Hautschützend', 'Защитава кожата'), 'SURFACTANT - CLEANSING': ('Tensid – reinigend', 'ПАВ – почистващо'),
 'SKIN CONDITIONING - MISCELLANEOUS': ('Hautpflegend – sonstige', 'Грижа за кожата – друго'), 'SURFACTANT - EMULSIFYING': ('Tensid – emulgierend', 'ПАВ – емулгатор'),
 'PERFUMING': ('Parfümierend', 'Ароматизиращо'), 'HUMECTANT': ('Feuchthaltemittel', 'Овлажнител'), 'FRAGRANCE': ('Duftstoff', 'Аромат'),
 'VISCOSITY CONTROLLING': ('Viskositätsregelnd', 'Регулира вискозитета'), 'CLEANSING': ('Reinigend', 'Почистващо'),
 'FILM FORMING': ('Filmbildend', 'Филмообразуващо'), 'ANTIMICROBIAL': ('Antimikrobiell', 'Антимикробно'),
 'SKIN CONDITIONING - HUMECTANT': ('Hautpflegend – feuchtigkeitsbindend', 'Задържа влагата в кожата'), 'ANTISTATIC': ('Antistatisch', 'Антистатик'),
 'EMULSION STABILISING': ('Emulsionsstabilisierend', 'Стабилизира емулсията'), 'SOLVENT': ('Lösungsmittel', 'Разтворител'),
 'ASTRINGENT': ('Adstringierend', 'Стягащо'), 'BINDING': ('Bindemittel', 'Свързващо'), 'SURFACTANT - FOAM BOOSTING': ('Tensid – schaumverstärkend', 'ПАВ – усилва пяната'),
 'HAIR DYEING': ('Haarfärbend', 'Боядисва косата'), 'ABRASIVE': ('Abrasiv', 'Абразив'), 'BLEACHING': ('Bleichend', 'Избелващо'),
 'ANTI-SEBUM': ('Talgregulierend', 'Срещу себум'), 'COLORANT': ('Farbstoff', 'Оцветител'), 'NOT REPORTED': ('Nicht angegeben', 'Не е посочено'),
 'TONIC': ('Tonisierend', 'Тонизиращо'), 'ORAL CARE': ('Mundpflege', 'Грижа за устата'), 'HAIR FIXING': ('Haarfestigend', 'Фиксира косата'),
 'DEODORANT': ('Deodorierend', 'Дезодорант'), 'OPACIFYING': ('Trübend', 'Придава непрозрачност'), 'PRESERVATIVE': ('Konservierungsmittel', 'Консервант'),
 'NAIL CONDITIONING': ('Nagelpflegend', 'Грижа за ноктите'), 'SURFACTANT - HYDROTROPE': ('Tensid – Hydrotrop', 'ПАВ – хидротроп'),
 'BUFFERING': ('Puffernd', 'Буфер (pH)'), 'BULKING': ('Füllstoff', 'Пълнител'), 'FOAMING': ('Schäumend', 'Пенообразуващо'),
 'FLAVOURING': ('Aromastoff', 'Вкусов аромат'), 'CHELATING': ('Komplexbildend', 'Хелатиращо'), 'ABSORBENT': ('Absorbierend', 'Абсорбиращо'),
 'UV ABSORBER': ('UV-Absorber', 'UV абсорбер'), 'PLASTICISER': ('Weichmacher', 'Пластификатор'), 'LIGHT STABILIZER': ('Lichtschutzmittel', 'Светлинен стабилизатор'),
 'EXFOLIATING': ('Peelend', 'Ексфолиращо'), 'ANTI-SEBORRHEIC': ('Antiseborrhoisch', 'Против себорея'), 'ANTICAKING': ('Rieselhilfe', 'Против слепване'),
 'SOOTHING': ('Beruhigend', 'Успокояващо'), 'SKIN CONDITIONING - OCCLUSIVE': ('Hautpflegend – okklusiv', 'Образува защитен слой'),
 'HAIR WAVING OR STRAIGHTENING': ('Wellen oder Glätten', 'Къдрене или изправяне на косата'), 'UV FILTER': ('UV-Filter', 'UV филтър'),
 'ANTIPLAQUE': ('Gegen Zahnbelag', 'Против зъбна плака'), 'REDUCING': ('Reduzierend', 'Редуциращо'), 'MOISTURISING': ('Feuchtigkeitsspendend', 'Хидратиращо'),
 'SURFACTANT - SOLUBILIZING': ('Tensid – lösungsvermittelnd', 'ПАВ – солубилизатор'), 'ANTIFOAMING': ('Schaumverhütend', 'Против пяна'),
 'SLIP MODIFIER': ('Gleitmittel', 'Подобрява плъзгането'), 'DISPERSING NON-SURFACTANT': ('Dispergiermittel (kein Tensid)', 'Диспергатор (не ПАВ)'),
 'DEPILATORY': ('Enthaarend', 'Обезкосмяващо'), 'REFRESHING': ('Erfrischend', 'Освежаващо'), 'SURFACE MODIFIER': ('Oberflächenmodifizierend', 'Модифицира повърхността'),
 'DENATURANT': ('Vergällungsmittel', 'Денатурант'), 'SMOOTHING': ('Glättend', 'Изглаждащо'), 'ANTIPERSPIRANT': ('Antitranspirant', 'Антиперспирант'),
 'OXIDISING': ('Oxidierend', 'Окисляващо'), 'SURFACTANT': ('Tensid', 'ПАВ'), 'EYELASH CONDITIONING': ('Wimpernpflegend', 'Грижа за миглите'),
 'ANTICORROSIVE': ('Korrosionsschützend', 'Антикорозионно'), 'pH ADJUSTERS': ('pH-Regulator', 'Регулатор на pH'), 'GEL FORMING': ('Gelbildend', 'Гелообразуващо'),
 'REFATTING': ('Rückfettend', 'Възстановява мазнините'), 'ADHESIVE': ('Haftmittel', 'Лепило'), 'PROPELLANT': ('Treibmittel', 'Пропелант'),
 'KERATOLYTIC': ('Keratolytisch', 'Кератолитично'), 'SURFACTANT - DISPERSING': ('Tensid – dispergierend', 'ПАВ – диспергиращо'),
 'NAIL SCULPTING': ('Nagelmodellage', 'Моделиране на нокти'), 'DETANGLING': ('Entwirrend', 'Разплита косата'), 'TANNING': ('Bräunend', 'Тен'),
 'EPILATING': ('Epilierend', 'Епилиращо'), 'PEARLESCENT': ('Perlglanz', 'Перлен блясък'), 'LYTIC': ('Lytisch', 'Литично'),
}

# ---------------------------------------------------------------- curated lists
COS_CURATED = {   # INCI name -> curated rule id
    'CYCLOTETRASILOXANE': 'd456', 'CYCLOPENTASILOXANE': 'd456', 'CYCLOHEXASILOXANE': 'd456', 'CYCLOMETHICONE': 'd456',
    'DMDM HYDANTOIN': 'frel', 'IMIDAZOLIDINYL UREA': 'frel', 'DIAZOLIDINYL UREA': 'frel', 'QUATERNIUM-15': 'frel',
    'SODIUM HYDROXYMETHYLGLYCINATE': 'frel', '2-BROMO-2-NITROPROPANE-1,3-DIOL': 'frel', 'METHENAMINE': 'frel',
    '5-BROMO-5-NITRO-1,3-DIOXANE': 'frel', 'BENZYLHEMIFORMAL': 'frel',
    'METHYLISOTHIAZOLINONE': 'mi', 'METHYLCHLOROISOTHIAZOLINONE': 'mi',
}
COS_ALIASES = {  # label word -> INCI (only clear synonyms)
    'WATER': 'AQUA', 'EAU': 'AQUA', 'WASSER': 'AQUA', 'FRAGRANCE': 'PARFUM', 'PERFUME': 'PARFUM', 'PARFÜM': 'PARFUM',
    'FLAVOR': 'AROMA', 'FLAVOUR': 'AROMA', 'LILIAL': 'BUTYLPHENYL METHYLPROPIONAL', 'P-BMHCA': 'BUTYLPHENYL METHYLPROPIONAL',
    'PYRITHIONE ZINC': 'ZINC PYRITHIONE', 'ZINKPYRITHION': 'ZINC PYRITHIONE', 'BRONOPOL': '2-BROMO-2-NITROPROPANE-1,3-DIOL',
    'VITAMIN E': 'TOCOPHEROL', 'D5': 'CYCLOPENTASILOXANE', 'D4': 'CYCLOTETRASILOXANE', 'D6': 'CYCLOHEXASILOXANE',
}
FRAG_NAMES = {'PARFUM', 'AROMA', 'FLAVOR', 'PERFUME'}
FRAG_ONLY_FUNCS = {'PERFUMING', 'FRAGRANCE', 'FLAVOURING', 'DEODORANT', 'TONIC', 'DENATURANT', 'MASKING', 'REFRESHING'}
ED_EXCLUDE = {'67-97-0'}  # cholecalciferol (vitamin D3): ED finding is about its use as rodenticide
IARC_EXCLUDE_AGENTS = {   # route does not apply to the product (drinking alcohol, eating an extract) or form unknown
    'Ethanol in alcoholic beverages', 'Acetaldehyde associated with consumption of alcoholic beverages',
    'Ginkgo biloba extract', 'Palygorskite (Attapulgite) (long fibres, > 5 micrometres)'}
IARC_CTX = {'Titanium dioxide': 'inhal', 'Carbon black': 'inhal', 'Silica dust, crystalline, in the form of quartz or cristobalite': 'inhal', 'Talc': 'talc'}

FOOD_NOT_EU = ['e103', 'e105', 'e107', 'e111', 'e121', 'e125', 'e126', 'e128', 'e130', 'e143', 'e152', 'e154', 'e166', 'e182',
               'e201', 'e209', 'e216', 'e217', 'e230', 'e231', 'e232', 'e233', 'e240', 'e241', 'e265', 'e266', 'e323', 'e324',
               'e388', 'e430', 'e443', 'e487', 'e488', 'e489', 'e537', 'e710', 'e713', 'e918', 'e919', 'e922', 'e923', 'e924',
               'e924a', 'e924b', 'e925', 'e926', 'e928', 'e929', 'e930', 'e940', 'e945', 'e946', 'e956']
FOOD_CURATED = {'e171': ['e171'], 'southampton': ['e102', 'e104', 'e110', 'e122', 'e124', 'e129'],
                'nitrite': ['e249', 'e250', 'e251', 'e252'], 'aspartame-label': ['e951', 'e962'],
                'polyols': ['e420', 'e421', 'e953', 'e965', 'e966', 'e967', 'e968']}
FOOD_IARC_EXTRA = {'e962': ('Aspartame', '2B')}       # salt of aspartame-acesulfame
FOOD_CAS_EXCLUDE = {'e152', 'e553b', 'e1510', 'e153'}  # wrong name match, or IARC route not oral
EFSA_HIGH_SKIP = {'e200', 'e202'}  # EFSA 2019 follow-up raised the ADI to 11 mg/kg bw; the 2015 exposure finding is outdated
EU14 = ['gluten', 'crustaceans', 'eggs', 'fish', 'peanuts', 'soybeans', 'milk', 'nuts', 'celery', 'mustard',
        'sesame-seeds', 'sulphur-dioxide-and-sulphites', 'lupin', 'molluscs']
TRANS_FAT_TERMS = {'en': ['partially hydrogenated*', 'partly hydrogenated*'],
                   'de': ['teilweise gehärtet*', 'teilweise hydriert*', 'teilgehärtet*'],
                   'bg': ['частично хидрогенирани', 'частично хидрогенирана', 'частично хидрогениран*'],
                   'hu': ['részben hidrogénezett*', 'részlegesen hidrogénezett*'],
                   'cs': ['částečně hydrogenovan*', 'částečně ztužen*'],
                   'sk': ['čiastočne hydrogenovan*', 'čiastočne stužen*'],
                   'sl': ['delno hidrogeniran*', 'delno hidrogenirane*']}
# Label languages for additive and allergen names (the app screens stay EN / DE / BG).
NAME_LANGS = ('en', 'de', 'bg', 'hu', 'cs', 'sk', 'sl')

# ---------------------------------------------------------------- helpers
def off_blocks(path):
    out = []
    for b in open(path, encoding='utf-8').read().split('\n\n'):
        names, props = {}, {}
        for l in b.split('\n'):
            l = l.rstrip()
            if not l or l.startswith('#') or l.startswith('<'):
                continue
            m = re.match(r'^([a-z_0-9]+):([a-z_]+):\s*(.*)$', l)
            if m:
                props[m.group(1) + ':' + m.group(2)] = m.group(3)
                continue
            m = re.match(r'^([a-z]{2,3}(?:_[a-z]+)?):\s*(.*)$', l)
            if m and m.group(1) not in ('stopwords', 'synonyms'):
                names[m.group(1)] = [s.strip() for s in m.group(2).split(',') if s.strip()]
        if names:
            out.append({'names': names, 'props': props})
    return out

REF_RE = re.compile(r'\b(VI|IV|V|III|II)\s*/\s*(?:I\s*/\s*)?(\d+\s*[a-z]?)\b', re.I)
QUAL_RE = re.compile(r'except|other than|when used|unless|with the exception|\bif\b|in concentration|as a constituent|'
                     r'for use|hair dye|as a substance in|content in|impurit|exceed|in products', re.I)
LABEL_RE = re.compile(r'indicated.{0,80}?in the list of ingredients', re.I | re.S)
NANO_RE = re.compile(r'\(\s*nano\s*\)', re.I)
REVERSE_SKIP = {('CITRIC ACID', 'V/59')}  # entry is about silver citrate, not citric acid

def refs_of(text):
    out = []
    for t in L(text):
        adv = t.strip().lower().startswith('please consider')
        for m in re.finditer(r'entry\s+(\d+[a-z]?)\s+of\s+Annex\s+(VI|IV|V|III|II)\b', t):
            out.append((m.group(2), m.group(1).lower(), True))
        if adv:
            continue
        for an, no in REF_RE.findall(t):
            out.append((an.upper(), re.sub(r'\s+', '', no).lower(), False))
    return out

def fn_label(f):
    if f == 'pH ADJUSTERS':
        return 'pH adjusters'
    t = (f[0] + f[1:].lower()).replace(' - ', ' – ')
    return re.sub(r'\buv\b', 'UV', t, flags=re.I)

# ---------------------------------------------------------------- load sources
a = json.load(open(P('lc-cosing-ingredients.json')))
r9 = json.load(open(P('lc-cosing-range9.json')))
s = json.load(open(P('lc-cosing-substances.json')))
ING = a['items'] + r9['ingredients']
SUB = s['items'] + r9['substances']
assert len(ING) > 30000 and len(SUB) > 2000, 'CosIng download looks incomplete'
EDJ = json.load(open(P('lc-edlists.json')))
IARC_ROWS = list(csv.reader(open(P('lc-iarc.csv'), encoding='utf-8-sig')))
IARC_HEAD, IARC_ROWS = IARC_ROWS[0], IARC_ROWS[1:]
FAD = json.load(open(P('lc-fad.json')))

# annex entries
ANNEX = {}
for x in SUB:
    if x.get('status') != 'Active':
        continue
    ref = x['annexNo'] + '/' + re.sub(r'\s+', '', x['refNo']).lower()
    ANNEX[ref] = x

def annex_level(an, x, adv):
    if adv:
        return 'n', 'ann.II.adv' if an == 'II' else None
    if an == 'II':
        return ('r', 'ann.II.r') if QUAL_RE.search(x['inciName']) else ('b', 'ann.II.b')
    return 'r', 'ann.' + an

# ED aggregation by CAS
ED = {}
for lst, rows in EDJ['lists'].items():
    for row in rows:
        for c in cas_list(row.get('CAS no.')):
            if c in ED_EXCLUDE:
                continue
            d = ED.setdefault(c, {'lists': set(), 'h': False, 'e': False, 'name': row['Name and abbreviation'], 'link': row.get('link', ''), 'st': set(), 'y': ''})
            d['lists'].add(lst); d['h'] |= row.get('Health effects') == 'Yes'; d['e'] |= row.get('Environmental effects') == 'Yes'
            if row.get('Status'): d['st'].add(row['Status'])
            d['y'] = max(d['y'], row.get('Year') or '')

def ed_eval(c):
    d = ED[c]
    best = 'I' if 'I' in d['lists'] else ('III' if 'III' in d['lists'] else 'II')
    if d['h']:
        return ('c' if best == 'I' else 'u'), 'ed.%s.h' % best
    return 'n', 'ed.%s.e' % best   # environment only: note, no level change

# IARC by CAS
IARC = {}       # id -> row
IARC_CAS = {}   # cas -> id
for i, row in enumerate(IARC_ROWS):
    if row[2] not in ('1', '2A', '2B') or row[1] in IARC_EXCLUDE_AGENTS:
        continue
    IARC[i] = row
    for c in cas_list(row[0]):
        IARC_CAS.setdefault(c, i)

used_annex, used_ed, used_iarc, used_cur = set(), set(), set(), set()
stats = Counter()

# ---------------------------------------------------------------- cosmetics
by_sid = {x['substanceId']: x for x in ING}
extra_refs = defaultdict(set)
for ref, x in ANNEX.items():
    for sid in L(x.get('identifiedIngredient')):
        if sid in by_sid and (by_sid[sid]['inciName'], ref) not in REVERSE_SKIP:
            extra_refs[sid].add(ref)

funcs = sorted({f for x in ING for f in L(x.get('functionName'))}, key=lambda f: -sum(1 for _ in [0]))
fcount = Counter(f for x in ING for f in L(x.get('functionName')))
funcs = [f for f, _ in fcount.most_common()]
fidx = {f: i for i, f in enumerate(funcs)}
missing_tr = [f for f in funcs if f not in FUNC_TR]
assert not missing_tr, 'Function names without translation: %s' % missing_tr

cos_items, names_seen = [], set()
for x in sorted(ING, key=lambda x: x['inciName']):
    name = clean(x['inciName'], 300)
    if name in names_seen:
        continue
    names_seen.add(name)
    lv, flags, refs = 'n', set(), []
    rl = [(an, no, adv) for an, no, adv in refs_of(x.get('cosmeticRestriction'))]
    rl += [(r.split('/')[0], r.split('/')[1], False) for r in sorted(extra_refs.get(x['substanceId'], ()))]
    seen = set()
    for an, no, adv in rl:
        ref = an + '/' + no
        if (ref, adv) in seen or ref not in ANNEX:
            continue
        seen.add((ref, adv))
        l, key = annex_level(an, ANNEX[ref], adv)
        if not key:
            continue
        if an == 'II' and not adv and NANO_RE.search(ANNEX[ref]['inciName']):
            refs.append('N:' + ref)          # banned only in nano form: the app applies it when the label says (nano)
            used_annex.add(ref)
            continue
        lv = worst(lv, l)
        refs.append(('?' if adv else '') + ref)
        used_annex.add(ref)
        if an == 'III' and LABEL_RE.search(str(ANNEX[ref].get('other')) + str(ANNEX[ref].get('wordingOfConditions'))):
            flags.add('a')
    # drop an advisory ref when the same entry is also a real link
    refs = [r for r in refs if not (r.startswith('?') and r[1:] in refs)]
    for c in cas_list(x.get('casNo')):
        if c in ED:
            l, key = ed_eval(c)
            lv = worst(lv, l); refs.append('ED:' + c); used_ed.add(c)
            if key.endswith('.e'): flags.add('e')
        if c in IARC_CAS:
            i = IARC_CAS[c]
            lv = worst(lv, 'c'); refs.append('IARC:%d' % i); used_iarc.add(i)
    cur = COS_CURATED.get(x['inciName'])
    if cur:
        lv = worst(lv, CURATED[cur]['lv']); refs.append('CUR:' + cur); used_cur.add(cur)
    fl = L(x.get('functionName'))
    if (x['inciName'] in FRAG_NAMES or 'a' in flags or
            (set(fl) & {'PERFUMING', 'FRAGRANCE'} and set(fl) <= FRAG_ONLY_FUNCS)):
        flags.add('f')
    if not x.get('status'):
        flags.add('o')
    refs = list(dict.fromkeys(refs))
    item = [name, list(dict.fromkeys(fidx[f] for f in fl if f in fidx)), lv, ''.join(sorted(flags)), refs]
    while item and item[-1] in ([], '', 'n') and len(item) > 2:
        item.pop()
    cos_items.append(item)
    stats['cos.' + lv] += 1
    if 'f' in flags: stats['cos.fragrance'] += 1
    if 'a' in flags: stats['cos.allergen'] += 1

aliases = {}
canon = {x['inciName'] for x in ING}
for x in ING:
    for us in L(x.get('inciUsaName')):
        u = clean(us, 300).upper()
        if u != x['inciName'] and u not in canon:
            aliases[u] = x['inciName']
for k, v in COS_ALIASES.items():
    if v in canon:
        aliases[k] = v

# ---------------------------------------------------------------- food
fad_e = set()
fad_note = {}
for it in FAD['items']:
    for e in re.findall(r'E\s*\d{3,4}\s*[a-z]?', it.get('eNumber') or '', re.I):
        k = re.sub(r'\s+', '', e).lower()
        fad_e.add(k)
        if it.get('policyItemNoteText'): fad_note[k] = clean(it['policyItemNoteText'], 300)

def e_key(code):
    return re.sub(r'[^a-z0-9]', '', code.lower())

def e_base(k):
    m = re.match(r'(e\d{3,4}[a-z]?)', k)
    return m.group(1) if m else k

# CAS for additives through CosIng names
nm2cas = defaultdict(set)
for x in ING:
    for c in cas_list(x.get('casNo')):
        for n in [x['inciName']] + L(x.get('chemicalName')) + L(x.get('innName')):
            nm2cas[re.sub(r'[^a-z0-9]+', ' ', n.lower()).strip()].add(c)

cls_blocks = off_blocks(P('additives_classes.txt'))
cls_names = {}
for b in cls_blocks:
    en = b['names'].get('en')
    if en:
        cap = lambda t: t[:1].upper() + t[1:]
        cls_names['en:' + re.sub(r'[^a-z0-9]+', '-', en[0].lower()).strip('-')] = {
            'en': cap(en[0]), 'de': cap((b['names'].get('de') or en)[0]), 'bg': cap((b['names'].get('bg') or en)[0])}
cls_list, cls_idx = [], {}

add_blocks = [b for b in off_blocks(P('additives.txt')) if re.match(r'^E\d{3,4}', (b['names'].get('en') or [''])[0], re.I)]
VAR_RE = re.compile(r'^E\s?(\d{3,4})\s?([a-z])?\s?(\(\s?[ivx]+\s?\)|[ivx]+)?$', re.I)
def code_key(code):
    m = VAR_RE.match(code.strip())
    if not m:
        return e_key(code), True
    return 'e' + m.group(1) + (m.group(2) or '').lower(), bool(m.group(3))
# bases first, so variants can be merged into them
add_blocks.sort(key=lambda b: code_key(b['names']['en'][0])[1])
food_items, food_seen = [], {}
for b in add_blocks:
    code = b['names']['en'][0]
    k, is_variant = code_key(code)
    if is_variant:   # sub-variants like E160a(ii), E322(i): merge names into the base
        base = k
        if base in food_seen:
            tgt = food_seen[base]
            for lang in NAME_LANGS:
                tgt['n'].setdefault(lang, [])
                tgt['n'][lang] += [n for n in b['names'].get(lang, [])[1:] if n not in tgt['n'][lang]]
            continue
        k = base
    if k in food_seen:
        continue
    names = {lang: [n for n in b['names'].get(lang, []) if not re.match(r'^E\s?\d', n, re.I) and len(n) >= 2 and '\\' not in n]
             for lang in NAME_LANGS}
    if not names.get('en'):
        other = [n for b2 in add_blocks if e_key(b2['names']['en'][0]) == k + 'a' for n in b2['names']['en'][1:2]]
        names['en'] = ['bromates (' + ', '.join(other) + ')'] if k == 'e924' and other else [code]
    names = {l: v[:12] for l, v in names.items() if v}
    pr = b['props']
    cl = []
    for c in [c.strip() for c in pr.get('additives_classes:en', '').split(',') if c.strip()]:
        if c in cls_names:
            if c not in cls_idx:
                cls_idx[c] = len(cls_list); cls_list.append(cls_names[c])
            cl.append(cls_idx[c])
    lv, flags, refs = 'n', set(), []
    eu = k in fad_e or e_base(k) in fad_e
    if k in FOOD_NOT_EU:
        lv = 'b'; refs.append('FOOD:noteu')
    for rid, keys in FOOD_CURATED.items():
        if k in keys:
            lv = worst(lv, CURATED[rid]['lv']); refs.append('CUR:' + rid); used_cur.add(rid)
    if k not in FOOD_CAS_EXCLUDE:
        cs = set()
        for n in b['names'].get('en', [])[1:]:
            cs |= nm2cas.get(re.sub(r'[^a-z0-9]+', ' ', n.lower()).strip(), set())
        for c in sorted(cs):
            if c in IARC_CAS:
                lv = worst(lv, 'c'); refs.append('IARC:%d' % IARC_CAS[c]); used_iarc.add(IARC_CAS[c])
            if c in ED:
                l, key = ed_eval(c)
                lv = worst(lv, l); refs.append('ED:' + c); used_ed.add(c)
                if key.endswith('.e'): flags.add('e')
    if k in FOOD_IARC_EXTRA:
        agent = FOOD_IARC_EXTRA[k][0]
        for i, row in IARC.items():
            if row[1] == agent:
                lv = worst(lv, 'c'); refs.append('IARC:%d' % i); used_iarc.add(i)
    if pr.get('efsa_evaluation_overexposure_risk:en') == 'en:high' and k not in EFSA_HIGH_SKIP:
        flags.add('h')
    efsa = [pr.get('efsa_evaluation_date:en', '').replace('/', '-'), pr.get('efsa_evaluation_url:en', '')] if pr.get('efsa_evaluation_url:en') else []
    item = {'e': k, 'n': names, 'cl': cl, 'lv': lv, 'fl': ''.join(sorted(flags)), 'refs': list(dict.fromkeys(refs)),
            'eu': 1 if (eu and k not in FOOD_NOT_EU and k != 'e171') else 0}
    if k in fad_note: item['note'] = fad_note[k]
    if efsa: item['efsa'] = efsa
    if pr.get('vegan:en'): item['vg'] = pr['vegan:en']
    if pr.get('vegetarian:en'): item['vt'] = pr['vegetarian:en']
    for f in ('cl', 'fl', 'refs'):
        if not item[f]: del item[f]
    food_items.append(item); food_seen[k] = item
    stats['food.' + lv] += 1

al_blocks = off_blocks(P('allergens.txt'))
allergens = []
for b in al_blocks:
    en = b['names'].get('en') or []
    if not en: continue
    aid = re.sub(r'[^a-z0-9]+', '-', en[0].lower()).strip('-')
    if aid in EU14:
        allergens.append({'id': aid, 'n': {l: b['names'].get(l, [])[:40] for l in NAME_LANGS if b['names'].get(l)}})
assert len(allergens) == 14, 'expected 14 EU allergens, got %d' % len(allergens)

# ---------------------------------------------------------------- meta
annex_out = {}
for ref in sorted(used_annex):
    x = ANNEX[ref]
    o = {'t': clean(x['inciName']), 'd': (x.get('publicationDate') or '')[:10], 'k': annex_level(ref.split('/')[0], x, False)[0]}
    for k_in, k_out in (('productTypeBodyParts', 'pt'), ('maximumConcentration', 'max'), ('otherRestrictions', None),
                        ('wordingOfConditions', 'warn'), ('other', 'cond'), ('relatedRegulations', 'reg'), ('casNo', 'cas')):
        if k_out and x.get(k_in):
            o[k_out] = clean(' | '.join(L(x[k_in])))
    urls = [u for u in L(x.get('sccsOpinionUrls')) if u.startswith('http')]
    if urls: o['sccs'] = urls[:2]
    annex_out[ref] = o

ed_out = {c: {'lv': ed_eval(c)[0], 'k': ed_eval(c)[1], 'l': sorted(ED[c]['lists']), 'h': int(ED[c]['h']), 'e': int(ED[c]['e']), 'n': clean(ED[c]['name'], 120),
              'st': sorted(ED[c]['st']), 'y': ED[c]['y'], 'url': ED[c]['link']} for c in sorted(used_ed)}
iarc_out = {str(i): {'agent': IARC[i][1], 'g': IARC[i][2], 'vol': IARC[i][3], 'y': IARC[i][5], 'cas': IARC[i][0]}
            for i in sorted(used_iarc)}
for i, v in iarc_out.items():
    if v['agent'] in IARC_CTX: v['ctx'] = IARC_CTX[v['agent']]

def fetched(d):
    return (d.get('fetched') or '')[:10]

# Dates of the sources that have no date inside the file (written by tools/fetch_sources.py).
try:
    FETCHED = json.load(open(P('fetched.json')))
except (OSError, ValueError):
    FETCHED = {}

SOURCES = [
    {'id': 'cosing', 'label': 'EU CosIng – cosmetic ingredients and Annexes II–VI (Regulation (EC) 1223/2009)', 'url': 'https://ec.europa.eu/growth/tools-databases/cosing/', 'fetched': fetched(a), 'licence': 'European Commission, reuse with credit'},
    {'id': 'ed', 'label': 'EU endocrine disruptor lists I–III (edlists.org, run by 6 EU national authorities)', 'url': 'https://edlists.org/the-ed-lists', 'fetched': fetched(EDJ)},
    {'id': 'iarc', 'label': 'IARC Monographs – list of classifications (WHO)', 'url': 'https://monographs.iarc.who.int/list-of-classifications/', 'fetched': (FETCHED.get('iarc') or '2026-10-20')[:10]},
    {'id': 'fad', 'label': 'EU food additives database (Food and Feed Information Portal)', 'url': 'https://ec.europa.eu/food/food-feed-portal/screen/food-additives/search', 'fetched': fetched(FAD)},
    {'id': 'off', 'label': 'Open Food Facts taxonomies – additive names (EN/DE/BG), EFSA links, allergens', 'url': 'https://github.com/openfoodfacts/openfoodfacts-server/tree/main/taxonomies', 'fetched': (FETCHED.get('off') or '2026-10-20')[:10], 'licence': 'ODbL'},
    {'id': 'eu14', 'label': 'EU food allergens – Regulation (EU) 1169/2011, Annex II', 'url': 'https://eur-lex.europa.eu/eli/reg/2011/1169/oj'},
]

meta = {
    'version': '2026-10-20',
    'built': __import__('datetime').date.today().isoformat(),
    'note': 'Levels come only from official lists and reviews. Never shown as "safe". Raw texts from CosIng are English.',
    'levelOrder': ['b', 'c', 'u', 'r', 'n'],
    'levels': LEVELS,
    'reasons': REASONS,
    'curated': {k: {kk: vv for kk, vv in v.items()} for k, v in CURATED.items()},
    'context': CTX,
    'functions': [{'en': fn_label(f), 'de': FUNC_TR[f][0], 'bg': FUNC_TR[f][1]} for f in funcs],
    'foodClasses': cls_list,
    'annex': annex_out,
    'ed': ed_out,
    'iarc': iarc_out,
    'sources': SOURCES,
    'studySearch': 'https://europepmc.org/search?query=%22{name}%22',
    'normalize': 'lower case; ß->ss; remove accents (NFD); keep a-z, 0-9 and Cyrillic а-я; everything else -> one space',
}
cos = {'version': meta['version'], 'fields': ['name', 'functionIdx', 'level', 'flags(f=fragrance,a=labelled allergen,e=environment-only ED,o=old name)', 'refs'],
       'items': cos_items, 'aliases': dict(sorted(aliases.items()))}
food = {'version': meta['version'], 'additives': food_items, 'allergens': allergens,
        'rules': [{'id': 'trans-fat', 'lv': 'c', 'terms': TRANS_FAT_TERMS, 'refs': ['CUR:trans-fat']}]}

os.makedirs(OUT, exist_ok=True)
for fn, obj in (('db-meta.json', meta), ('db-cosmetics.json', cos), ('db-food.json', food)):
    with open(os.path.join(OUT, fn), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    print(fn, os.path.getsize(os.path.join(OUT, fn)))
print(dict(sorted(stats.items())))
print('annex', len(annex_out), 'ed', len(ed_out), 'iarc', len(iarc_out), 'aliases', len(aliases), 'foodClasses', len(cls_list), 'curated used', sorted(used_cur))
