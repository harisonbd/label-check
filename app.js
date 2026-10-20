/* Label Check — app logic. Plain JavaScript, no libraries.
   Parts: storage, matching, data lookup, camera, label reading, screens. */
'use strict';

(() => {
  // ---------- Settings ----------
  const OFF = 'https://world.openfoodfacts.org';
  const OBF = 'https://world.openbeautyfacts.org';
  const FIELDS = [
    'code', 'product_name', 'product_name_de', 'product_name_en', 'generic_name', 'brands',
    'image_front_small_url', 'image_small_url',
    'ingredients_text', 'ingredients_text_de', 'ingredients_text_en',
    'ingredients_tags', 'additives_tags', 'allergens_tags', 'ingredients_analysis_tags',
    'nutriscore_grade', 'nova_group', 'last_modified_t'
  ].join(',');
  const CACHE_DAYS = 7;
  const MAX_PRODUCTS = 300;
  const MAX_HISTORY = 100;
  const PROMPT =
    'Read the ingredient list on this product label.\n' +
    'Reply with the ingredients only, as plain text, separated by commas, in the language on the label.\n' +
    'If the label is not in English, add one more line that starts with "EN:" and gives the English translation.';

  const QUICK_PICKS = [
    'palm oil, palmöl, palmfett, huile de palme',
    'parfum, fragrance, duftstoffe',
    'aspartame, aspartam, e951',
    'glucose-fructose syrup, glukose-fruktose-sirup, isoglucose',
    'alcohol denat, alkohol denat'
  ];

  // ---------- Storage (stays on this phone) ----------
  const store = {
    get(key, fallback) {
      try {
        const v = localStorage.getItem('lc.' + key);
        return v === null ? fallback : JSON.parse(v);
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem('lc.' + key, JSON.stringify(value)); return true; }
      catch (e) { toast('Could not save on this phone. Storage may be full.'); return false; }
    }
  };

  let RULES = [];
  let GROUPS = {};
  let RULES_VERSION = '';

  const state = {
    avoid: store.get('avoid', []),       // [{id, text}]
    rulesOff: store.get('rulesOff', []), // [ruleId]
    history: store.get('history', []),   // [{code, name, brand, kind, verdict, time}]
    products: store.get('products', {}), // {code: product}
    lastCode: null
  };

  // ---------- Text matching ----------
  // Lower case, remove accents, join E-numbers ("E 250" -> "e250"), keep only letters and digits.
  function norm(s, keepStar) {
    let t = String(s || '').toLowerCase().replace(/ß/g, 'ss')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/\be[\s\-‐-―]*(\d{3,4}[a-z]?)\b/g, 'e$1');
    t = keepStar ? t.replace(/[^a-z0-9*]+/g, ' ') : t.replace(/[^a-z0-9]+/g, ' ');
    return t.trim();
  }

  const reCache = new Map();
  // Whole-word match. A * at the end of a term allows any word ending.
  function termRegex(term) {
    if (reCache.has(term)) return reCache.get(term);
    const t = norm(term, true);
    let re = null;
    if (t.replace(/\*/g, '').trim()) {
      const body = t.split('*')
        .map(p => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&'))
        .join('[a-z0-9]*');
      re = new RegExp('(?:^| )' + body + '(?= |$)');
    }
    reCache.set(term, re);
    return re;
  }

  function toTag(text) {
    const t = norm(text);
    return t ? 'en:' + t.replace(/ /g, '-') : '';
  }

  function stripLabelWord(text) {
    return String(text || '').replace(/^\s*(zutaten|ingredients?|ingr[eé]dients?|inci|ingredienti|ingredientes|composition)\s*:\s*/i, '');
  }

  // Split at commas and semicolons that are not inside brackets.
  function splitIngredients(text) {
    const out = [];
    let depth = 0, cur = '';
    for (const ch of stripLabelWord(text)) {
      if ('([{'.includes(ch)) depth++;
      else if (')]}'.includes(ch)) depth = Math.max(0, depth - 1);
      if ((ch === ',' || ch === ';') && depth === 0) {
        if (cur.trim()) out.push(cur.trim());
        cur = '';
      } else {
        cur += ch;
      }
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  function analyze(product) {
    const texts = (product.texts || []).filter(Boolean);
    const normTexts = texts.map(t => norm(t));
    const mainSegs = splitIngredients(product.ingredientsText).map(s => norm(s));
    const tagSet = new Set([...(product.tags || []), ...(product.allergens || [])].map(t => String(t).toLowerCase()));

    const shown = term => {
      const t = term.replace(/\*+$/, '');
      return /^e\d{3,4}[a-z]?$/i.test(t) ? t.toUpperCase() : t;
    };

    function check(terms, tags) {
      // First the main ingredient list (gives the position), then other texts (e.g. the English line).
      for (const term of terms) {
        const re = termRegex(term);
        if (!re) continue;
        const idx = mainSegs.findIndex(s => re.test(s));
        if (idx >= 0) return { found: shown(term), position: idx + 1 };
      }
      for (const term of terms) {
        const re = termRegex(term);
        if (re && normTexts.some(t => re.test(t))) return { found: shown(term), position: null };
      }
      for (const tag of tags || []) {
        if (tag && tagSet.has(tag)) {
          return { found: tag.replace(/^[a-z]{2}:/, '').replace(/-/g, ' '), position: null };
        }
      }
      return null;
    }

    const findings = [];
    for (const item of state.avoid) {
      const terms = item.text.split(',').map(s => s.trim()).filter(Boolean);
      const hit = check(terms, terms.map(toTag));
      if (hit) {
        findings.push(Object.assign({
          type: 'mine', level: 'high', name: terms[0], reason: 'On your avoid list.'
        }, hit));
      }
    }
    for (const rule of RULES) {
      if (state.rulesOff.includes(rule.id)) continue;
      if (!rule.applies.includes(product.kind)) continue;
      const hit = check(rule.terms, rule.tags);
      if (hit) {
        findings.push(Object.assign({
          type: 'rule', level: rule.level, name: rule.name, reason: rule.reason, source: rule.source
        }, hit));
      }
    }

    const hasIngredients = normTexts.some(t => t.length > 0) || (product.tags || []).length > 0;
    let verdict = 'ok';
    if (findings.some(f => f.level === 'high')) verdict = 'avoid';
    else if (findings.some(f => f.level === 'medium')) verdict = 'check';
    else if (!hasIngredients) verdict = 'unknown';

    const order = { high: 0, medium: 1 };
    const mineFirst = f => (f.type === 'mine' ? 0 : 1);
    findings.sort((a, b) => (order[a.level] - order[b.level]) || (mineFirst(a) - mineFirst(b)));
    return { verdict, findings, count: mainSegs.length };
  }

  // ---------- Data lookup ----------
  async function fetchJson(url, ms) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), ms || 9000);
    try {
      const r = await fetch(url, { signal: ctl.signal });
      if (r.status === 404) return { status: 0 };
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function fromApi(p, kind, base, code) {
    return {
      code,
      kind,
      source: kind === 'food' ? 'off' : 'obf',
      name: p.product_name || p.product_name_de || p.product_name_en || p.generic_name || '',
      brand: String(p.brands || '').split(',')[0].trim(),
      image: p.image_front_small_url || p.image_small_url || '',
      ingredientsText: p.ingredients_text || p.ingredients_text_de || p.ingredients_text_en || '',
      texts: [p.ingredients_text, p.ingredients_text_de, p.ingredients_text_en].filter(Boolean),
      tags: [].concat(p.ingredients_tags || [], p.additives_tags || []),
      allergens: p.allergens_tags || [],
      analysis: p.ingredients_analysis_tags || [],
      nutriscore: /^[a-e]$/.test(p.nutriscore_grade || '') ? p.nutriscore_grade : null,
      nova: p.nova_group || null,
      updated: p.last_modified_t ? p.last_modified_t * 1000 : null,
      fetchedAt: Date.now(),
      url: base + '/product/' + code
    };
  }

  // Asks both databases at the same time. Returns a product, null (not found) or throws (no connection).
  async function fetchProduct(code) {
    const sources = [['food', OFF], ['cosmetic', OBF]];
    const results = await Promise.allSettled(
      sources.map(([, base]) => fetchJson(base + '/api/v2/product/' + code + '.json?fields=' + FIELDS))
    );
    let reached = false;
    for (let i = 0; i < sources.length; i++) {
      const r = results[i];
      if (r.status !== 'fulfilled') continue;
      reached = true;
      const d = r.value;
      if (d && (d.status === 1 || d.status === 'success') && d.product) {
        return fromApi(d.product, sources[i][0], sources[i][1], code);
      }
    }
    if (!reached) throw new Error('offline');
    return null;
  }

  function saveProduct(p) {
    state.products[p.code] = p;
    const codes = Object.keys(state.products);
    if (codes.length > MAX_PRODUCTS) {
      codes
        .sort((a, b) => {
          const pa = state.products[a], pb = state.products[b];
          const la = pa.source === 'label' ? 1 : 0, lb = pb.source === 'label' ? 1 : 0;
          return (la - lb) || (pa.fetchedAt - pb.fetchedAt);
        })
        .slice(0, codes.length - MAX_PRODUCTS)
        .forEach(c => delete state.products[c]);
    }
    store.set('products', state.products);
  }

  function addHistory(p, verdict) {
    state.history = state.history.filter(h => h.code !== p.code);
    state.history.unshift({ code: p.code, name: p.name, brand: p.brand, kind: p.kind, verdict, time: Date.now() });
    state.history = state.history.slice(0, MAX_HISTORY);
    store.set('history', state.history);
    renderHistory();
  }

  async function lookup(raw, forceOnline) {
    const code = String(raw || '').replace(/\D/g, '');
    if (code.length < 8 || code.length > 14) {
      toast('A barcode has 8 to 14 digits.');
      return;
    }
    state.lastCode = code;
    hideAll();
    showStatus('Looking up ' + code + ' …');

    const cached = state.products[code];
    const fresh = cached && !forceOnline &&
      (cached.source === 'label' || Date.now() - cached.fetchedAt < CACHE_DAYS * 864e5);
    if (fresh) { showProduct(cached); return; }

    try {
      const p = await fetchProduct(code);
      if (p) { saveProduct(p); showProduct(p); }
      else if (cached) showProduct(cached, 'Not found online. Showing the saved result.');
      else showNotFound(code);
    } catch (e) {
      if (cached) showProduct(cached, 'No connection. Showing the saved result.');
      else showOffline(code);
    }
  }

  // ---------- Screens ----------
  const $ = id => document.getElementById(id);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return n;
  };

  const VERDICT = {
    avoid: { word: 'Avoid', cls: 'v-avoid' },
    check: { word: 'Check', cls: 'v-check' },
    ok: { word: 'No flags', cls: 'v-ok' },
    unknown: { word: 'No ingredients', cls: 'v-unknown' }
  };

  const ANALYSIS = {
    'en:palm-oil': 'Contains palm oil',
    'en:may-contain-palm-oil': 'May contain palm oil',
    'en:palm-oil-free': 'Palm oil free',
    'en:vegan': 'Vegan',
    'en:non-vegan': 'Not vegan',
    'en:vegetarian': 'Vegetarian',
    'en:non-vegetarian': 'Not vegetarian'
  };

  const NOVA = { 1: 'unprocessed', 2: 'culinary ingredient', 3: 'processed', 4: 'ultra-processed' };

  function fmtDate(ms) {
    try { return new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
    catch (e) { return ''; }
  }

  function hideAll() {
    $('result').hidden = true;
    $('labelPanel').hidden = true;
    $('status').hidden = true;
  }

  function showStatus(text, buttons) {
    const s = $('status');
    s.replaceChildren(el('p', { text, class: 'status-text' }));
    if (buttons && buttons.length) s.append(el('div', { class: 'row' }, buttons));
    s.hidden = false;
  }

  function sub(verdict, findings) {
    if (verdict === 'ok') return 'Nothing from your list or the starter rules.';
    if (verdict === 'unknown') return 'The database has no ingredient list. Read the label to check it.';
    const n = findings.length;
    return n + (n === 1 ? ' finding. See why below.' : ' findings. See why below.');
  }

  function showProduct(p, note) {
    const a = analyze(p);
    const v = VERDICT[a.verdict];
    hideAll();
    if (note) showStatus(note);

    const r = $('result');
    const chips = [];
    chips.push(p.kind === 'food' ? 'Food' : 'Cosmetic');
    if (p.nutriscore) chips.push('Nutri-Score ' + p.nutriscore.toUpperCase());
    if (p.nova && NOVA[p.nova]) chips.push('NOVA ' + p.nova + ' (' + NOVA[p.nova] + ')');
    for (const t of p.analysis || []) if (ANALYSIS[t]) chips.push(ANALYSIS[t]);

    const allergens = (p.allergens || []).map(t => t.replace(/^[a-z]{2}:/, '').replace(/-/g, ' '));

    const findingItems = a.findings.map(f => el('li', { class: 'lv-' + f.level },
      el('span', { class: 'f-name', text: f.name }),
      el('span', { class: 'f-tag', text: f.type === 'mine' ? 'your list' : (f.level === 'high' ? 'red' : 'orange') }),
      el('p', { class: 'f-why', text: f.reason }),
      el('p', { class: 'f-where', text: 'Found as "' + f.found + '"' + (f.position ? ', ingredient ' + f.position + ' of ' + a.count : '') + '.' }),
      f.source ? el('p', { class: 'f-src' }, 'Source: ', el('a', { href: f.source.url, target: '_blank', rel: 'noopener', text: f.source.label })) : null
    ));

    const sourceName = p.source === 'off' ? 'Open Food Facts' : p.source === 'obf' ? 'Open Beauty Facts' : 'your label photo';
    const dataLine = el('p', { class: 'data-line' },
      p.code && !p.code.startsWith('label-') ? 'Barcode ' + p.code + '. ' : null,
      'Data from ' + sourceName + (p.updated ? ', updated ' + fmtDate(p.updated) : (p.source === 'label' ? ', saved ' + fmtDate(p.fetchedAt) : '')) + '. ',
      p.url ? el('a', { href: p.url, target: '_blank', rel: 'noopener', text: 'Open product page' }) : null
    );

    const actions = el('div', { class: 'actions' },
      el('button', { class: 'btn btn-primary', type: 'button', text: 'Scan next', onclick: scanNext }),
      el('button', { class: 'btn btn-ghost', type: 'button', text: a.verdict === 'unknown' ? 'Read label' : 'Read label again', onclick: () => openLabel(p) }),
      p.source === 'label' && p.code && !p.code.startsWith('label-')
        ? el('button', { class: 'btn btn-ghost', type: 'button', text: 'Look up online', onclick: () => lookup(p.code, true) })
        : null
    );

    r.replaceChildren(...[
      el('div', { class: 'verdict ' + v.cls },
        el('span', { class: 'verdict-word', text: v.word }),
        el('span', { class: 'verdict-sub', text: sub(a.verdict, a.findings) })
      ),
      el('div', { class: 'product-head' },
        p.image ? el('img', { src: p.image, alt: '', loading: 'lazy', onerror: e => e.target.remove() }) : null,
        el('div', {},
          el('h2', { text: p.name || 'Unnamed product' }),
          p.brand ? el('p', { text: p.brand }) : null
        )
      ),
      el('ul', { class: 'chips' }, chips.map(c => el('li', { text: c }))),
      allergens.length ? el('p', { class: 'allergens' }, el('strong', { text: 'Allergens: ' }), allergens.join(', ')) : null,
      findingItems.length ? el('ul', { class: 'findings' }, findingItems) : null,
      p.ingredientsText
        ? el('details', {},
            el('summary', { text: 'Ingredients' + (a.count ? ' (' + a.count + ')' : '') }),
            el('p', { class: 'ingredients', text: stripLabelWord(p.ingredientsText) }))
        : null,
      dataLine,
      actions
    ].filter(Boolean));
    r.hidden = false;
    addHistory(p, a.verdict);
    r.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }

  function showNotFound(code) {
    hideAll();
    showStatus('Barcode ' + code + ' is not in Open Food Facts or Open Beauty Facts. Read the label with Claude instead.');
    openLabel({ code });
  }

  function showOffline(code) {
    hideAll();
    showStatus('No connection, and this product is not saved on your phone yet.', [
      el('button', { class: 'btn btn-primary', type: 'button', text: 'Try again', onclick: () => lookup(code) }),
      el('button', { class: 'btn btn-ghost', type: 'button', text: 'Read label', onclick: () => openLabel({ code }) })
    ]);
  }

  function scanNext() {
    hideAll();
    window.scrollTo({ top: 0 });
    startCamera();
  }

  // ---------- Read a label (free share flow) ----------
  let labelFor = null; // product or {code} the label belongs to

  function openLabel(p) {
    labelFor = p && p.code ? p : null;
    $('result').hidden = true;
    const panel = $('labelPanel');
    panel.hidden = false;
    $('labelText').value = '';
    $('labelName').value = (p && p.name) || '';
    const kind = (p && p.kind) || 'food';
    document.querySelectorAll('input[name="kind"]').forEach(i => { i.checked = i.value === kind; });
    $('labelLead').textContent = labelFor && labelFor.code
      ? 'For barcode ' + labelFor.code + '. Free: it uses your normal Claude app.'
      : 'Free: it uses your normal Claude app.';
    panel.scrollIntoView({ behavior: 'auto', block: 'start' });
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) { return false; }
  }

  async function onPhoto(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const copied = await copyText(PROMPT);
    const data = { files: [file], text: PROMPT };
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share(data);
        toast(copied ? 'Question copied. Paste it in Claude.' : 'Pick Claude in the share menu.');
      } catch (err) {
        if (err && err.name !== 'AbortError') toast('Sharing failed. Copy the question and open Claude yourself.');
      }
    } else {
      toast('This browser cannot share photos. Copy the question, open Claude and add the photo there.');
    }
  }

  async function onPaste() {
    try {
      const t = await navigator.clipboard.readText();
      if (t) $('labelText').value = t.trim();
      else toast('The clipboard is empty.');
    } catch (e) {
      toast('Paste is blocked. Long-press in the box and choose Paste.');
    }
  }

  function parseClaudeAnswer(text) {
    const lines = String(text || '').split(/\r?\n/);
    const main = [], extra = [];
    for (const line of lines) {
      const m = line.match(/^\s*EN\s*:\s*(.*)$/i);
      if (m) extra.push(m[1]);
      else if (line.trim()) main.push(line.trim());
    }
    return { main: stripLabelWord(main.join(' ')), extra: extra.join(' ') };
  }

  function onCheckLabel() {
    const raw = $('labelText').value.trim();
    if (!raw) { toast('Paste the ingredient list first.'); $('labelText').focus(); return; }
    const { main, extra } = parseClaudeAnswer(raw);
    const kind = (document.querySelector('input[name="kind"]:checked') || {}).value || 'food';
    const code = labelFor && labelFor.code ? labelFor.code : 'label-' + Date.now();
    const base = labelFor && labelFor.code ? state.products[labelFor.code] : null;
    const p = {
      code,
      kind,
      source: 'label',
      name: $('labelName').value.trim() || (base && base.name) || '',
      brand: (base && base.brand) || '',
      image: (base && base.image) || '',
      ingredientsText: main,
      texts: [main, extra].filter(Boolean),
      tags: [],
      allergens: [],
      analysis: [],
      nutriscore: (base && base.nutriscore) || null,
      nova: (base && base.nova) || null,
      updated: null,
      fetchedAt: Date.now(),
      url: ''
    };
    saveProduct(p);
    showProduct(p);
  }

  // ---------- Camera ----------
  let stream = null, detector = null, scanTimer = null;

  async function startCamera() {
    if (!('BarcodeDetector' in window)) {
      toast('This browser cannot read barcodes from the camera. Type the numbers under the barcode.');
      $('codeInput').focus();
      return;
    }
    try {
      const wanted = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];
      let formats = wanted;
      try {
        const supported = await BarcodeDetector.getSupportedFormats();
        formats = wanted.filter(f => supported.includes(f));
      } catch (e) { /* use the default list */ }
      detector = new BarcodeDetector({ formats: formats.length ? formats : wanted });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    } catch (e) {
      stopCamera();
      toast(e && e.name === 'NotAllowedError'
        ? 'The camera is blocked. Allow it for this site in the browser settings, or type the barcode.'
        : 'The camera did not start. Type the barcode instead.');
      return;
    }
    const v = $('video');
    v.srcObject = stream;
    v.hidden = false;
    $('vfIdle').hidden = true;
    $('scanline').hidden = false;
    $('stopCam').hidden = false;
    try { await v.play(); } catch (e) { /* autoplay is allowed for muted video */ }
    scanLoop();
  }

  async function scanLoop() {
    if (!stream || !detector) return;
    try {
      const v = $('video');
      if (v.readyState >= 2) {
        const codes = await detector.detect(v);
        const hit = codes.find(c => /^\d{8,14}$/.test(c.rawValue));
        if (hit) {
          if (navigator.vibrate) navigator.vibrate(60);
          stopCamera();
          lookup(hit.rawValue);
          return;
        }
      }
    } catch (e) { /* try again on the next frame */ }
    scanTimer = setTimeout(scanLoop, 200);
  }

  function stopCamera() {
    clearTimeout(scanTimer);
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null;
    const v = $('video');
    v.srcObject = null;
    v.hidden = true;
    $('scanline').hidden = true;
    $('stopCam').hidden = true;
    $('vfIdle').hidden = false;
  }

  // ---------- My list ----------
  function renderAvoid() {
    const ul = $('avoidList');
    ul.replaceChildren(...state.avoid.map(item => {
      const parts = item.text.split(',').map(s => s.trim()).filter(Boolean);
      return el('li', {},
        el('span', { class: 'grow' },
          el('strong', { text: parts[0] }),
          parts.length > 1 ? el('span', { class: 'sub', text: 'Also: ' + parts.slice(1).join(', ') }) : null
        ),
        el('button', { class: 'btn btn-ghost', type: 'button', text: 'Remove', 'aria-label': 'Remove ' + parts[0], onclick: () => removeAvoid(item.id) })
      );
    }));
    $('avoidEmpty').hidden = state.avoid.length > 0;

    const have = new Set(state.avoid.map(i => i.text.split(',')[0].trim().toLowerCase()));
    $('picks').replaceChildren(...QUICK_PICKS
      .filter(p => !have.has(p.split(',')[0].trim().toLowerCase()))
      .map(p => el('button', { type: 'button', text: '+ ' + p.split(',')[0], onclick: () => addAvoid(p) })));
  }

  function addAvoid(text) {
    const clean = String(text || '').split(',').map(s => s.trim()).filter(Boolean).join(', ');
    if (!clean) return;
    state.avoid.push({ id: 'a' + Date.now() + Math.random().toString(36).slice(2, 6), text: clean });
    store.set('avoid', state.avoid);
    renderAvoid();
    toast('Added: ' + clean.split(',')[0]);
  }

  function removeAvoid(id) {
    state.avoid = state.avoid.filter(i => i.id !== id);
    store.set('avoid', state.avoid);
    renderAvoid();
  }

  // ---------- Rules ----------
  function renderRules() {
    const box = $('rulesList');
    const groups = {};
    for (const r of RULES) (groups[r.group] = groups[r.group] || []).push(r);
    box.replaceChildren(...Object.keys(groups).map(g => el('div', { class: 'rule-group' },
      el('h3', { text: GROUPS[g] || g }),
      groups[g].map(r => {
        const on = !state.rulesOff.includes(r.id);
        const id = 'rule-' + r.id;
        return el('div', { class: 'rule' },
          el('div', {},
            el('label', { for: id, class: 'r-name' }, r.name),
            el('span', { class: 'r-level ' + r.level, text: r.level === 'high' ? 'red' : 'orange' })
          ),
          el('p', { class: 'r-text', text: r.reason + ' Checks ' + (r.applies.includes('food') ? 'food' : 'cosmetics') + '.' }),
          el('p', { class: 'r-src' }, 'Source: ', el('a', { href: r.source.url, target: '_blank', rel: 'noopener', text: r.source.label })),
          el('span', { class: 'switch' },
            el('input', { type: 'checkbox', id, role: 'switch', checked: on, onchange: e => toggleRule(r.id, e.target.checked) }))
        );
      })
    )));
    $('rulesMeta').textContent = RULES.length
      ? RULES.length + ' rules, version ' + RULES_VERSION + '.'
      : 'Rules did not load. Open the app once with a connection.';
  }

  function toggleRule(id, on) {
    state.rulesOff = state.rulesOff.filter(x => x !== id);
    if (!on) state.rulesOff.push(id);
    store.set('rulesOff', state.rulesOff);
  }

  // ---------- History ----------
  function renderHistory() {
    const ul = $('historyList');
    ul.replaceChildren(...state.history.map(h => el('li', {},
      el('span', { class: 'dot ' + (VERDICT[h.verdict] || VERDICT.unknown).cls, 'aria-hidden': 'true' }),
      el('button', { class: 'open grow', type: 'button', onclick: () => openHistory(h) },
        el('strong', { text: h.name || 'Unnamed product' }),
        el('span', { class: 'sub', text: [h.brand, (VERDICT[h.verdict] || VERDICT.unknown).word, fmtDate(h.time)].filter(Boolean).join(', ') })
      )
    )));
    $('historyEmpty').hidden = state.history.length > 0;
    $('clearHistory').hidden = state.history.length === 0;
  }

  function openHistory(h) {
    go('scan');
    const p = state.products[h.code];
    if (p) showProduct(p);
    else lookup(h.code);
  }

  // ---------- Backup ----------
  function exportBackup() {
    const data = {
      app: 'label-check', version: 1, exportedAt: new Date().toISOString(),
      avoid: state.avoid, rulesOff: state.rulesOff, history: state.history, products: state.products
    };
    const blob = new Blob([JSON.stringify(data, null, 1)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: 'label-check-backup-' + new Date().toISOString().slice(0, 10) + '.json' });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    toast('Backup file saved to your downloads.');
  }

  async function importBackup(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); }
    catch (err) { toast('This file is not a Label Check backup.'); return; }
    if (!data || data.app !== 'label-check') { toast('This file is not a Label Check backup.'); return; }
    if (!confirm('Replace your list, rule settings and history with this backup? Saved products are merged.')) return;
    state.avoid = Array.isArray(data.avoid) ? data.avoid.filter(i => i && typeof i.text === 'string') : [];
    state.rulesOff = Array.isArray(data.rulesOff) ? data.rulesOff.filter(x => typeof x === 'string') : [];
    state.history = Array.isArray(data.history) ? data.history.slice(0, MAX_HISTORY) : [];
    if (data.products && typeof data.products === 'object') Object.assign(state.products, data.products);
    store.set('avoid', state.avoid);
    store.set('rulesOff', state.rulesOff);
    store.set('history', state.history);
    store.set('products', state.products);
    renderAvoid(); renderRules(); renderHistory();
    toast('Backup imported.');
  }

  // ---------- Tabs and toast ----------
  // Each tab change is added to the browser history, so the phone's Back button returns to the previous tab.
  const TABS = ['scan', 'list', 'rules', 'history'];
  let currentTab = 'scan';

  function go(tab, fromBack) {
    if (!TABS.includes(tab)) tab = 'scan';
    if (!fromBack && tab !== currentTab) {
      try { history.pushState({ tab }, '', '#' + tab); } catch (e) { /* ignore */ }
    }
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(s => { s.hidden = s.dataset.tab !== tab; });
    document.querySelectorAll('.tabbar button').forEach(b => {
      if (b.dataset.go === tab) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    if (tab !== 'scan') stopCamera();
    window.scrollTo({ top: 0 });
  }

  let toastTimer = null;
  function toast(text) {
    const t = $('toast');
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3800);
  }

  // ---------- Start ----------
  async function loadRules() {
    try {
      const r = await fetch('rules.json');
      const data = await r.json();
      RULES = Array.isArray(data.rules) ? data.rules : [];
      GROUPS = data.groups || {};
      RULES_VERSION = data.version || '';
    } catch (e) {
      RULES = [];
    }
    renderRules();
  }

  function init() {
    document.querySelectorAll('.tabbar button').forEach(b => b.addEventListener('click', () => go(b.dataset.go)));
    $('startCam').addEventListener('click', startCamera);
    $('stopCam').addEventListener('click', stopCamera);
    $('manualForm').addEventListener('submit', e => {
      e.preventDefault();
      stopCamera();
      lookup($('codeInput').value);
    });
    $('openLabel').addEventListener('click', () => { hideAll(); openLabel(null); });
    $('photoInput').addEventListener('change', onPhoto);
    $('copyPrompt').addEventListener('click', async () => {
      toast((await copyText(PROMPT)) ? 'Question copied. Open Claude and paste it.' : 'Copy failed. Long-press to copy instead.');
    });
    $('pasteBtn').addEventListener('click', onPaste);
    $('checkLabel').addEventListener('click', onCheckLabel);
    $('avoidForm').addEventListener('submit', e => {
      e.preventDefault();
      addAvoid($('avoidInput').value);
      $('avoidInput').value = '';
    });
    $('exportBtn').addEventListener('click', exportBackup);
    $('importInput').addEventListener('change', importBackup);
    $('clearHistory').addEventListener('click', () => {
      if (!confirm('Clear the scan history? Saved products stay.')) return;
      state.history = [];
      store.set('history', state.history);
      renderHistory();
    });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopCamera(); });
    window.addEventListener('popstate', e => go((e.state && e.state.tab) || 'scan', true));
    try { history.replaceState({ tab: 'scan' }, '', location.pathname + location.search); } catch (e) { /* ignore */ }

    renderAvoid();
    renderHistory();
    loadRules();

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js').catch(() => { /* app still works online */ });
    }
  }

  // Small test hook (used only by automated checks).
  window.LC = { norm, termRegex, splitIngredients, analyze, parseClaudeAnswer, state, lookup, rules: () => RULES };

  init();
})();
