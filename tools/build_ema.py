# v2.50: the EU list of medicine fillers (excipients) with a "known effect" -> data/ema-excipients.json
# Source: Annex to the European Commission guideline "Excipients in the labelling and package leaflet of medicinal products
# for human use" (SANTE-2017-11668), revision 5, 5 Dec 2025, EMA, all-languages XLSX (sheets EN, DE, BG), read 28 Nov 2026.
# Texts are the EMA package-leaflet sentences; sentences with placeholders (x mg, <dosage unit>) are left out.
# Only fillers that matter for products bought in a shop (oral "o" / skin and mouth "t"); amount-only entries (sodium,
# potassium, glycerol, mannitol, xylitol) and injection-only entries (dextrans, heparin, phosphate buffers) are left out.
import json, os

SUGAR = {'en': 'If you have been told by your doctor that you have an intolerance to some sugars, contact your doctor before taking this medicinal product.',
         'de': 'Bitte nehmen Sie dieses Arzneimittel erst nach Rücksprache mit Ihrem Arzt ein, wenn Ihnen bekannt ist, dass Sie unter einer Zuckerunverträglichkeit leiden.',
         'bg': 'Ако Вашият лекар Ви е казал, че имате непоносимост към някои захари, свържете се с него, преди да приемете този лекарствен продукт.'}
SKIN = {'en': 'May cause local skin reactions (e.g. contact dermatitis).', 'de': 'Kann örtlich begrenzte Hautreizungen (z. B. Kontaktdermatitis) hervorrufen.',
        'bg': 'Може да причини локални кожни реакции (например контактен дерматит).'}
ALLERGIC = {'en': 'May cause allergic reactions.', 'de': 'Kann allergische Reaktionen hervorrufen.', 'bg': 'Може да причини алергични реакции.'}
SKIN_EYES = {'en': 'May cause local skin reactions (e.g. contact dermatitis), or irritation to the eyes and mucous membranes.',
             'de': 'Kann örtlich begrenzt Hautreizungen (z. B. Kontaktdermatitis), Reizungen der Augen und der Schleimhäute hervorrufen.',
             'bg': 'Може да причини локални кожни реакции (например контактен дерматит) или дразнене на очите и лигавиците.'}
STOMACH = {'en': 'May cause stomach upset and diarrhea.', 'de': 'Kann Magenbeschwerden und Durchfall hervorrufen.', 'bg': 'Може да причини стомашно неразположение и диария.'}
PEANUT_SOY = {'en': 'If you are allergic to peanut or soya, do not use this medicinal product.',
              'de': 'Es darf nicht eingenommen/angewendet werden, wenn Sie überempfindlich (allergisch) gegenüber Erdnuss oder Soja sind.',
              'bg': 'Ако сте алергични към фъстъци или соя, не използвайте този лекарствен продукт.'}
PKU = {'en': 'Phenylalanine may be harmful if you have phenylketonuria (PKU), a rare genetic disorder in which phenylalanine builds up because the body cannot remove it properly.',
       'de': 'Phenylalanin kann schädlich sein, wenn Sie eine Phenylketonurie haben, eine seltene angeborene Erkrankung, bei der sich Phenylalanin anreichert, weil der Körper es nicht ausreichend abbauen kann.',
       'bg': 'Фенилаланинът може да Ви навреди, ако имате фенилкетонурия, рядко генетично заболяване, при което се натрупва фенилаланин, тъй като организмът не може да го отделя правилно.'}

# id, route (o = by mouth, t = skin/mouth/topical), names (regex, lower case), allergens, name {en,de,bg}, text {en,de,bg}, text on skin (if other)
E = [
 ('aprotinin', 't', r'aprotinin|апротинин', [], ('Aprotinin', 'Aprotinin', 'Апротинин'),
  {'en': 'May cause hypersensitivity or severe allergic reactions.', 'de': 'Kann Überempfindlichkeitsreaktionen oder schwere Allergien auslösen.', 'bg': 'Може да причини свръхчувствителност или тежки алергични реакции.'}, None),
 ('peanutOil', 'ot', r'arachis oil|peanut oil|erdnussöl|arachidis oleum|arachis hypogaea oil|фъстъчено масло', ['peanuts', 'soybeans'], ('Arachis oil (peanut oil)', 'Erdnussöl', 'Фъстъчено масло'), PEANUT_SOY, None),
 ('aspartame', 'o', r'aspartam(?:e)?|e ?951|аспартам', [], ('Aspartame (E 951)', 'Aspartam (E 951)', 'Аспартам (E 951)'),
  {'en': 'Aspartame is a source of phenylalanine. It may be harmful if you have phenylketonuria (PKU), a rare genetic disorder in which phenylalanine builds up because the body cannot remove it properly.',
   'de': 'Aspartam ist eine Quelle für Phenylalanin. Es kann schädlich sein, wenn Sie eine Phenylketonurie (PKU) haben, eine seltene angeborene Erkrankung, bei der sich Phenylalanin anreichert, weil der Körper es nicht ausreichend abbauen kann.',
   'bg': 'Аспартамът е източник на фенилаланин. Може да Ви навреди ако имате фенилкетонурия, рядко генетично заболяване, при което се натрупва фенилаланин, тъй като организмът не може да го отделя правилно.'}, None),
 ('azo', 'o', r'tartrazin(?:e)?|e ?102|sunset yellow|gelborange s|e ?110|azorubin(?:e)?|carmoisin(?:e)?|e ?122|amaranth|e ?123|ponceau 4r|cochineal red a|e ?124|brillantschwarz bn|brilliant black bn|black pn|e ?151|тартразин|сънсет жълто|азорубин|кармоизин|амарант|понсо 4r',
  [], ('Azo colouring agents', 'Azo-Farbstoffe', 'Азобагрила'), ALLERGIC, None),
 ('peru', 't', r'balsam of peru|peru balsam|perubalsam|myroxylon|перуански балсам', [], ('Balsam of Peru', 'Perubalsam', 'Перуански балсам'),
  {'en': 'May cause skin reactions.', 'de': 'Kann Hautreizungen hervorrufen.', 'bg': 'Може да причини кожни реакции.'}, None),
 ('benzalkonium', 't', r'benzalkonium|бензалкони', [], ('Benzalkonium chloride', 'Benzalkoniumchlorid', 'Бензалкониев хлорид'),
  {'en': 'Benzalkonium chloride may irritate the skin. You should not apply this medicine to the breasts if you are breast-feeding because the baby may take it in with your milk.',
   'de': 'Benzalkoniumchlorid kann Hautreizungen hervorrufen. Wenn Sie stillen, dürfen Sie dieses Arzneimittel nicht auf die Brust auftragen, da ihr Baby es mit der Milch aufnehmen könnte.',
   'bg': 'Бензалкониевият хлорид може да причини дразнене на кожата. Не трябва да прилагате това лекарство върху гърдите ако кърмите, защото бебето може да го поеме с кърмата.'}, None),
 ('benzoate', 'ot', r'benzoic acid|benzoesäure|(?:natrium|kalium|calcium)?(?<!benzyl )benzoat(?:e)?|e ?21[0-3]|бензоена киселина|(?<!бензилов )бензоат', [], ('Benzoic acid and benzoates (E 210-213)', 'Benzoesäure und Benzoate (E 210-213)', 'Бензоена киселина и бензоати (E 210-213)'),
  {'en': 'Benzoic acid/benzoate may increase jaundice (yellowing of the skin and eyes) in newborn babies (up to 4 weeks old).',
   'de': 'Benzoesäure/Benzoat kann Gelbsucht (Gelbfärbung von Haut und Augen) bei Neugeborenen (im Alter bis zu 4 Wochen) verstärken.',
   'bg': 'Бензоената киселина/солта на бензоената киселина може да засили симптомите на жълтеница (пожълтяване на кожата и очите) при новородените (на възраст до 4 седмици).'},
  {'en': 'Benzoic acid/benzoate may cause local irritation.', 'de': 'Benzoesäure/Benzoat kann lokale Reizungen hervorrufen.', 'bg': 'Бензоената киселина/солта на бензоената киселина може да причини локално дразнене.'}),
 ('benzylAlcohol', 'ot', r'benzyl alcohol|benzylalkohol|бензилов алкохол', [], ('Benzyl alcohol', 'Benzylalkohol', 'Бензилов алкохол'),
  {'en': 'Benzyl alcohol may cause allergic reactions.', 'de': 'Benzylalkohol kann allergische Reaktionen hervorrufen.', 'bg': 'Може да причини алергични реакции.'}, None),
 ('bergamot', 't', r'bergamot(?:te)? ?(?:oil|öl)|bergamottöl|bergapten|бергамотово масло', [], ('Bergamot oil (containing bergapten)', 'Bergamottöl (enthält Bergapten)', 'Бергамотово масло (съдържащо бергаптен)'),
  {'en': 'May increase sensitivity to UV light (natural and artificial sunlight).', 'de': 'Kann die Empfindlichkeit gegenüber UV-Licht erhöhen (natürliches und künstliches Sonnenlicht).', 'bg': 'Може да повиши чувствителността към UV светлина (естествена или изкуствена).'}, None),
 ('boric', 'ot', r'boric acid|borsäure|borate?|borax|борна киселина|борат', [], ('Boric acid (and borates)', 'Borsäure und Borate', 'Борна киселина (и борати)'),
  {'en': 'This medicine should not be given to a child younger than 2 years without medical advice, as it contains boron and may impair fertility in the future.',
   'de': 'Dieses Arzneimittel sollte bei einem Kind unter 2 Jahren nicht ohne ärztlichen Rat angewendet werden, da es Bor enthält und später die Fortpflanzungsfähigkeit beeinträchtigen kann.',
   'bg': 'Това лекарство не трябва да се прилага при деца, по-малки от 2 години, без консултация с лекар, тъй като съдържа бор и може да увреди фертилитета в бъдеще.'}, None),
 ('bronopol', 't', r'bronopol|бронопол', [], ('Bronopol', 'Bronopol', 'Бронопол'), SKIN, None),
 ('bha', 't', r'butylhydroxyanisol|butylated hydroxyanisole|e ?320|\bbha\b|бутилхидроксианизол', [], ('Butylated hydroxyanisole (E 320)', 'Butylhydroxyanisol (E 320)', 'Бутилхидроксианизол (E 320)'), SKIN_EYES, None),
 ('bht', 't', r'butylhydroxytoluol|butylated hydroxytoluene|e ?321|\bbht\b|бутилхидрокситолуен', [], ('Butylated hydroxytoluene (E 321)', 'Butylhydroxytoluol (E 321)', 'Бутилхидрокситолуен (E 321)'), SKIN_EYES, None),
 ('cetostearyl', 't', r'cetylstearylalkohol|cetostearyl alcohol|cetearyl alcohol|cetyl alcohol|cetylalkohol|цетостеарилов алкохол|цетилов алкохол', [],
  ('Cetostearyl alcohol (incl. cetyl alcohol)', 'Cetylstearylalkohol (einschließlich Cetylalkohol)', 'Цетостеарилов алкохол (включително цетилов алкохол)'), SKIN, None),
 ('chlorocresol', 't', r'chlorocresol|chlorkresol|хлорокрезол', [], ('Chlorocresol', 'Chlorocresol', 'Хлорокрезол'), ALLERGIC, None),
 ('cyclodextrin', 'ot', r'cyclodextrin|betadex|alfadex|e ?459|циклодекстрин|бетадекс|алфадекс', [], ('Cyclodextrins', 'Cyclodextrine', 'Циклодекстрини'),
  {'en': 'Do not use in children less than 2 years old unless recommended by your doctor.', 'de': 'Wenden Sie dieses Arzneimittel nicht bei Kindern unter 2 Jahren an, es sei denn, Ihr Arzt hat es empfohlen.',
   'bg': 'Да не се прилага при деца на възраст под 2 години, освен ако не е препоръчано от Вашия лекар.'}, None),
 ('dmso', 't', r'dimethyl ?sul(?:ph|f)oxid(?:e)?|диметилсулфоксид', [], ('Dimethyl sulphoxide', 'Dimethylsulfoxid', 'Диметилсулфоксид'),
  {'en': 'May be irritant to the skin.', 'de': 'Kann Hautreizungen hervorrufen.', 'bg': 'Може да причини дразнене на кожата.'}, None),
 ('ethanol', 'ot', r'ethanol|äthanol|ethylalkohol|ethyl alcohol|alcohol (?=96|denat)|alkohol (?=96|denat)|етанол|етилов алкохол', [], ('Ethanol (alcohol)', 'Ethanol (Alkohol)', 'Етанол (алкохол)'),
  None, {'en': 'It may cause burning sensation on damaged skin.', 'de': 'Bei geschädigter Haut kann es ein brennendes Gefühl hervorrufen.', 'bg': 'Той може да предизвика усещане за парене върху увредена кожа.'}),
 ('formaldehyde', 'ot', r'formaldehyd(?:e)?|формалдехид', [], ('Formaldehyde', 'Formaldehyd', 'Формалдехид'), STOMACH,
  {'en': 'May cause local skin reactions (e.g. contact dermatitis).', 'de': 'Kann örtlich begrenzte Hautreizungen (z. B. Kontaktdermatitis) hervorrufen.', 'bg': 'Може да причини локални кожни реакции (например контактен дерматит).'}),
 ('fragrance', 't', r'parfum|perfume|fragrance|duftstoff|parfümöl|аромат|парфюм', [], ('Fragrances containing allergens', 'Allergene enthaltende Duftstoffe', 'Аромати, съдържащи алергени'),
  {'en': 'This medicine contains fragrance with allergens. They may cause allergic reactions.', 'de': 'Dieses Arzneimittel enthält einen Duftstoff mit Allergenen. Sie können allergische Reaktionen hervorrufen.',
   'bg': 'Това лекарство съдържа аромат с алергени. Те може да причинят алергични реакции.'}, None),
 ('fructose', 'o', r'fructose|fruktose|фруктоза', [], ('Fructose', 'Fructose', 'Фруктоза'), SUGAR, None),
 ('galactose', 'o', r'galactose|galaktose|галактоза', [], ('Galactose', 'Galactose', 'Галактоза'), SUGAR, None),
 ('glucose', 'o', r'glucose|glukose|dextrose|traubenzucker|глюкоза|декстроза', [], ('Glucose', 'Glucose', 'Глюкоза'), SUGAR, None),
 ('invertSugar', 'o', r'invert sugar|invertzucker|инвертна захар', [], ('Invert sugar', 'Invertzucker', 'Инвертна захар'), SUGAR, None),
 ('lactitol', 'o', r'lactitol|e ?966|лактитол', [], ('Lactitol (E 966)', 'Lactitol (E 966)', 'Лактитол (E 966)'), SUGAR, None),
 ('lactose', 'o', r'lactose|laktose|lactosum|лактоза|lactose-?monohydrat(?:e)?|laktose-?monohydrat', ['milk'], ('Lactose', 'Lactose', 'Лактоза'), SUGAR, None),
 ('latex', 'ot', r'\blatex\b|naturkautschuk|natural rubber|латекс|естествен каучук', [], ('Latex (natural rubber)', 'Latex (Naturgummi)', 'Латекс (естествен каучук)'),
  {'en': 'The container of this medicinal product contains latex rubber. May cause severe allergic reactions.', 'de': 'Das Behältnis dieses Arzneimittels enthält Latex. Kann schwere Allergien auslösen.',
   'bg': 'Опаковката на този лекарствен продукт съдържа естествен каучук. Може да причини тежки алергични реакции.'}, None),
 ('castorPolyoxyl', 'o', r'macrogolglycerol(?:ricinoleat|hydroxystearat)|macrogol(?:glycerol)? ?(?:ricinoleate|hydroxystearate)|castor oil polyoxyl|polyoxyl \d+ (?:hydrogenated )?castor oil|cremophor|kolliphor el|рициново масло, полиетоксилирано',
  [], ('Castor oil polyoxyl (macrogolglycerol ricinoleate)', 'Macrogolglycerolricinoleat (polyethoxyliertes Rizinusöl)', 'Рициново масло, полиетоксилирано'), STOMACH, None),
 ('maltitol', 'o', r'maltitol|isomalt|e ?965|e ?953|малтитол|изомалт', [], ('Maltitol / isomalt (E 965, E 953)', 'Maltitol / Isomalt (E 965, E 953)', 'Малтитол / изомалт (E 965, E 953)'), SUGAR, None),
 ('mercury', 't', r'thiomersal|thimerosal|phenylmercur|тиомерсал|фенилживач', [], ('Organic mercury compounds (e.g. thiomersal)', 'Organische Quecksilberverbindungen (z. B. Thiomersal)', 'Органични живачни съединения (напр. тиомерсал)'),
  {'en': 'May cause local skin reactions (e.g. contact dermatitis) and discolouration.', 'de': 'Können örtlich begrenzte Hautreizungen (z. B. Kontaktdermatitis) und Verfärbung hervorrufen.',
   'bg': 'Може да причини локални кожни реакции (например контактен дерматит) и промяна в цвета на кожата.'}, None),
 ('parabens', 'ot', r'(?:methyl|ethyl|propyl|butyl|isobutyl|isopropyl|benzyl|метил|етил|пропил|бутил)?парабен|(?:methyl|ethyl|propyl|butyl|isobutyl|isopropyl|benzyl)?parabens?|(?:natrium|kalium|sodium |potassium )?(?:methyl|ethyl|propyl|butyl)?-?4?-?(?:p-)?hydroxybenzoat(?:e)?|e ?21[4-9]|хидроксибензоат', [], ('Parahydroxybenzoates (parabens, E 214-219)', 'Parahydroxybenzoate (Parabene, E 214-219)', 'Парахидроксибензоати (парабени, E 214-219)'),
  {'en': 'May cause allergic reactions (possibly delayed).', 'de': 'Kann allergische Reaktionen, auch Spätreaktionen, hervorrufen.', 'bg': 'Може да причини алергични реакции (вероятно от забавен тип).'}, None),
 ('phenylalanine', 'o', r'phenylalanin(?:e)?|фенилаланин', [], ('Phenylalanine', 'Phenylalanin', 'Фенилаланин'), PKU, None),
 ('polysorbate', 't', r'polysorbat(?:e)?|\btween\b|e ?43[2-6]|полисорбат', [], ('Polysorbates (E 432-436)', 'Polysorbate (E 432-436)', 'Полисорбати (E 432-436)'),
  {'en': 'Polysorbates can cause allergic reactions.', 'de': 'Polysorbate können allergische Reaktionen hervorrufen.', 'bg': 'Полисорбатите могат да причинят алергични реакции.'}, None),
 ('proline', 'ot', r'\bprolin(?:e)?\b|\bпролин\b', [], ('Proline', 'Prolin', 'Пролин'),
  {'en': 'Proline may be harmful for patients with hyperprolinaemia, a rare genetic disorder in which proline builds up in the body.', 'de': 'Prolin kann schädlich sein, wenn Sie eine Hyperprolinämie haben, eine seltene angeborene Erkrankung bei der sich Prolin anreichert.',
   'bg': 'Пролин може да бъде вреден за пациенти с хиперпролинемия, рядко генетично нарушение, при което в организма се натрупва пролин.'}, None),
 ('propyleneGlycol', 'ot', r'propylen(?:e)? ?glycol|propylenglykol|1,2-propandiol|e ?1520|пропиленгликол', [], ('Propylene glycol (E 1520)', 'Propylenglycol (E 1520)', 'Пропиленгликол (E 1520)'),
  {'en': 'If your baby is less than 4 weeks old, talk to your doctor or pharmacist before giving them this medicine, in particular if the baby is given other medicines that contain propylene glycol or alcohol.',
   'de': 'Wenn Ihr Baby weniger als 4 Wochen alt ist, sprechen Sie mit Ihrem Arzt oder Apotheker bevor Sie ihm dieses Arzneimittel geben, insbesondere, wenn Ihr Baby gleichzeitig andere Arzneimittel erhält, die Propylenglycol oder Alkohol enthalten.',
   'bg': 'Ако Вашето бебе е на възраст под 4 седмици, говорете с Вашия лекар или фармацевт преди да му приложите това лекарство, и по-специално ако на бебето се прилагат други лекарства, които съдържат пропиленгликол или етанол.'},
  {'en': 'Propylene glycol may cause skin irritation.', 'de': 'Propylenglycol kann Hautreizungen hervorrufen.', 'bg': 'Пропиленгликолът може да причини дразнене на кожата.'}),
 ('sesameOil', 'ot', r'sesame oil|sesamöl|sesami oleum|sesamum indicum (?:seed )?oil|сусамено масло', ['sesame-seeds'], ('Sesame oil', 'Sesamöl', 'Сусамено масло'),
  {'en': 'May rarely cause severe allergic reactions.', 'de': 'Kann in seltenen Fällen schwere Allergien hervorrufen.', 'bg': 'В редки случаи може да причини тежки алергични реакции.'}, None),
 ('sls', 't', r'sodium lauryl ?sulfate|sodium laurilsulfate|sodium dodecyl ?sulfate|natriumdodecylsulfat|natriumlaurylsulfat|натриев лаурилсулфат', [], ('Sodium laurilsulfate', 'Natriumdodecylsulfat', 'Натриев лаурилсулфат'),
  {'en': 'Sodium laurilsulfate may cause local skin reactions (such as stinging or burning sensation) or increase skin reactions caused by other products when applied on the same area.',
   'de': 'Natriumdodecylsulfat kann lokale Hautreaktionen (wie ein stechendes oder brennendes Gefühl) hervorrufen oder Hautreaktionen verstärken, die durch andere auf dieselbe Hautstelle aufgebrachte Produkte verursacht werden.',
   'bg': 'Натриевият лаурилсулфат може да причини локални кожни реакции (усещане за щипане и парене) или да засили кожните реакции, причинени от други продукти, когато е приложен на същото място.'}, None),
 ('sorbic', 't', r'sorbic acid|sorbinsäure|(?:natrium|kalium|calcium)?sorbat(?:e)?|e ?20[0-3]|сорбинова киселина|(?:калиев |натриев )?сорбат', [], ('Sorbic acid (E 200) and salts', 'Sorbinsäure (E 200) und Sorbate', 'Сорбинова киселина (E 200) и нейните соли'), SKIN, None),
 ('sorbitol', 'o', r'sorbitol|e ?420|сорбитол', [], ('Sorbitol (E 420)', 'Sorbitol (E 420)', 'Сорбитол (E 420)'),
  {'en': 'Sorbitol is a source of fructose. Sorbitol may cause gastrointestinal discomfort and mild laxative effect.',
   'de': 'Sorbitol ist eine Quelle für Fructose. Sorbitol kann Magen-Darm-Beschwerden hervorrufen und kann eine leicht abführende Wirkung haben.',
   'bg': 'Сорбитолът е източник на фруктоза. Сорбитолът може да причини стомашно-чревно неразположение и слабо изразено слабително действие.'}, None),
 ('soyaOil', 'ot', r'soya oil|soybean oil|sojaöl|sojabohnenöl|soiae oleum|glycine soja oil|соево масло', ['soybeans', 'peanuts'], ('Soya oil', 'Sojaöl', 'Соево масло'), PEANUT_SOY, None),
 ('stearyl', 't', r'(?<!ceto)stearyl alcohol|(?<!cetyl)stearylalkohol|стеарилов алкохол', [], ('Stearyl alcohol', 'Stearylalkohol', 'Стеарилов алкохол'), SKIN, None),
 ('sucrose', 'o', r'sucrose|saccharose|sucrosum|захароза', [], ('Sucrose', 'Saccharose', 'Захароза'), SUGAR, None),
 ('sulphites', 'o', r'(?:natrium|kalium|calcium)?(?:meta|hydrogen)?(?:bi|di)?sul(?:ph|f)it(?:e)?|e ?22[0-8]|(?:мета)?бисулфит|сулфит|метабисулфит', ['sulphur-dioxide-and-sulphites'], ('Sulphites (E 220-228)', 'Sulfite (E 220-228)', 'Сулфити (E 220-228)'),
  {'en': 'May rarely cause severe hypersensitivity reactions and bronchospasm.', 'de': 'Kann in seltenen Fällen schwere Überempfindlichkeitsreaktionen und Bronchialkrämpfe (Bronchospasmen) hervorrufen.',
   'bg': 'В редки случаи може да причини тежки реакции на свръхчувствителност и бронхоспазъм.'}, None),
 ('wheatStarch', 'o', r'wheat starch|weizenstärke|tritici amylum|пшенично нишесте', ['gluten'], ('Wheat starch (contains gluten)', 'Weizenstärke (enthält Gluten)', 'Пшенично нишесте (съдържа глутен)'),
  {'en': 'If you have wheat allergy (different from coeliac disease) you should not take this medicine.', 'de': 'Wenn Sie eine Weizenallergie haben (nicht gleichzusetzen mit Zöliakie) dürfen Sie dieses Arzneimittel nicht einnehmen.',
   'bg': 'Ако имате алергия към пшеница (което е различно от цьолиакия), Вие не трябва да приемате това лекарство.'}, None),
 ('lanolin', 't', r'lanolin|wool fat|wollwachs|adeps lanae|ланолин', [], ('Wool fat (lanolin)', 'Wollwachs (Lanolin)', 'Ланолин'), SKIN, None),
]
out = {'source': 'EMA/European Commission, Annex to the guideline "Excipients in the labelling and package leaflet of medicinal products for human use" (SANTE-2017-11668), revision 5, 5 Dec 2025',
       'items': []}
for id_, route, names, al, n, w, wt in E:
    item = {'id': id_, 'r': route, 're': names, 'n': dict(zip(('en', 'de', 'bg'), n))}
    if al: item['al'] = al
    if w: item['w'] = w
    if wt: item['wt'] = wt
    out['items'].append(item)
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'ema-excipients.json')
json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(len(out['items']), 'fillers ->', p, os.path.getsize(p), 'bytes')
