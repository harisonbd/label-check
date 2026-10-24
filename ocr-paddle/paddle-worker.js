/* Label Check — PaddleOCR reader (v2.23, runs in a Web Worker).
   Models: PP-OCR (det v3 + rec Latin / rec East-Slavic), Apache-2.0 (see LICENSE-Apache-2.0.txt in ocr/), ONNX files from
   huggingface.co/monkt/paddleocr-onnx. Engine: onnxruntime-web 1.20.1 (MIT), WebAssembly, one thread.
   New file name on purpose when the code changes: phones keep ocr-paddle/ files forever.
   Message in:  { id, image: Uint8Array (PNG/JPEG), lang: 'eng'|'deu'|'bul'|…, layout?: true, maxside?: number }
   Message out: { id, text, conf, tsv, ms, layout, boxes } or { id, error }   (and { id, step } while loading)
   "tsv" has the same columns as the Tesseract reader (level 5 rows), so the app code that finds the list does not change. */
'use strict';
const BASE = self.location.href.replace(/[^/]*$/, '');
const MEAN = [0.485, 0.456, 0.406], STD = [0.229, 0.224, 0.225];
let det = null;
const recs = {};
let ortReady = null;

async function loadOrt() {
  if (ortReady) return ortReady;
  ortReady = (async () => {
    importScripts(BASE + 'ort.wasm.min.js');
    ort.env.wasm.wasmPaths = BASE;
    ort.env.wasm.numThreads = 1;          // GitHub Pages cannot send the headers that threads need
    ort.env.wasm.proxy = false;
  })();
  return ortReady;
}
async function fetchBuf(name) {
  const r = await fetch(BASE + name);
  if (!r.ok) throw new Error('paddle file ' + name + ' ' + r.status);
  return new Uint8Array(await r.arrayBuffer());
}
async function getDet() {
  if (det) return det;
  det = await ort.InferenceSession.create(await fetchBuf('det.onnx'), { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
  return det;
}
async function getRec(kind) {
  if (recs[kind]) return recs[kind];
  const sess = await ort.InferenceSession.create(await fetchBuf('rec-' + kind + '.onnx'), { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
  const dict = new TextDecoder('utf-8').decode(await fetchBuf('dict-' + kind + '.txt')).split('\n');
  if (dict[dict.length - 1] === '') dict.pop();
  recs[kind] = { sess, chars: [''].concat(dict.map(s => s.replace(/\r$/, '')), [' ']) };
  return recs[kind];
}

// ---- detection (DB): probability map -> boxes ----
async function detect(bmp, maxside, pixCap) {
  const w = bmp.width, h = bmp.height;
  let r = Math.min(1, maxside / Math.max(w, h));
  if (r >= 1 && Math.max(w, h) < maxside) r = Math.min(2, maxside / Math.max(w, h));
  if (w * r * h * r > pixCap) r *= Math.sqrt(pixCap / (w * r * h * r));
  const nh = Math.max(32, Math.round(h * r / 32) * 32), nw = Math.max(32, Math.round(w * r / 32) * 32);
  const cv = new OffscreenCanvas(nw, nh), cx = cv.getContext('2d', { willReadFrequently: true });
  cx.imageSmoothingQuality = 'high';
  cx.drawImage(bmp, 0, 0, nw, nh);
  const px = cx.getImageData(0, 0, nw, nh).data, n = nw * nh, x = new Float32Array(3 * n);
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    x[i] = (px[j] / 255 - MEAN[0]) / STD[0]; x[n + i] = (px[j + 1] / 255 - MEAN[1]) / STD[1]; x[2 * n + i] = (px[j + 2] / 255 - MEAN[2]) / STD[2];
  }
  const s = await getDet();
  const out = await s.run({ [s.inputNames[0]]: new ort.Tensor('float32', x, [1, 3, nh, nw]) });
  const p = out[s.outputNames[0]].data;
  // connected components of p > 0.3 (4-neighbour)
  const lab = new Int32Array(n), stack = new Int32Array(n), boxes = [];
  const THR = 0.3, UNCLIP = 1.8, MINSCORE = 0.5;
  let L = 0;
  for (let i0 = 0; i0 < n; i0++) {
    if (lab[i0] || p[i0] <= THR) continue;
    L++; let sp = 0; stack[sp++] = i0; lab[i0] = L;
    let x0 = nw, y0 = nh, x1 = 0, y1 = 0, area = 0, sum = 0;
    while (sp) {
      const i = stack[--sp], yy = (i / nw) | 0, xx = i - yy * nw;
      area++; sum += p[i];
      if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; if (yy < y0) y0 = yy; if (yy > y1) y1 = yy;
      if (xx > 0 && !lab[i - 1] && p[i - 1] > THR) { lab[i - 1] = L; stack[sp++] = i - 1; }
      if (xx < nw - 1 && !lab[i + 1] && p[i + 1] > THR) { lab[i + 1] = L; stack[sp++] = i + 1; }
      if (yy > 0 && !lab[i - nw] && p[i - nw] > THR) { lab[i - nw] = L; stack[sp++] = i - nw; }
      if (yy < nh - 1 && !lab[i + nw] && p[i + nw] > THR) { lab[i + nw] = L; stack[sp++] = i + nw; }
    }
    const bw = x1 - x0 + 1, bh = y1 - y0 + 1;
    if (bw < 4 || bh < 4 || sum / area < MINSCORE) continue;
    const d = area * UNCLIP / (2 * (bw + bh));
    boxes.push({ x0: Math.max(0, x0 - d) * w / nw, y0: Math.max(0, y0 - d) * h / nh, x1: Math.min(nw, x1 + 1 + d) * w / nw, y1: Math.min(nh, y1 + 1 + d) * h / nh });
  }
  return boxes;
}

// ---- recognition (CRNN + CTC) ----
async function readBox(bmp, b, kind) {
  const { sess, chars } = await getRec(kind);
  let sx = Math.floor(b.x0), sy = Math.floor(b.y0), sw = Math.max(1, Math.ceil(b.x1) - sx), sh = Math.max(1, Math.ceil(b.y1) - sy);
  const vertical = sh > sw * 1.5;
  const tw = vertical ? sh : sw, th = vertical ? sw : sh;
  const W = Math.max(8, Math.min(3200, Math.ceil(tw * 48 / th)));
  const cv = new OffscreenCanvas(W, 48), cx = cv.getContext('2d', { willReadFrequently: true });
  cx.imageSmoothingQuality = 'high';
  if (vertical) { cx.translate(0, 48); cx.rotate(-Math.PI / 2); cx.drawImage(bmp, sx, sy, sw, sh, 0, 0, W, 48); }
  else cx.drawImage(bmp, sx, sy, sw, sh, 0, 0, W, 48);
  const px = cx.getImageData(0, 0, W, 48).data, n = W * 48, x = new Float32Array(3 * n);
  for (let i = 0, j = 0; i < n; i++, j += 4) { x[i] = px[j] / 127.5 - 1; x[n + i] = px[j + 1] / 127.5 - 1; x[2 * n + i] = px[j + 2] / 127.5 - 1; }
  const out = await sess.run({ [sess.inputNames[0]]: new ort.Tensor('float32', x, [1, 3, 48, W]) });
  const o = out[sess.outputNames[0]], T = o.dims[1], C = o.dims[2], d = o.data;
  let prev = 0, text = '', csum = 0, cn = 0;
  for (let t = 0; t < T; t++) {
    let bi = 0, bv = -1;
    for (let c = 0; c < C; c++) { const v = d[t * C + c]; if (v > bv) { bv = v; bi = c; } }
    if (bi !== 0 && bi !== prev) { text += chars[bi] || ''; csum += bv; cn++; }
    prev = bi;
  }
  return { text, conf: cn ? csum / cn : 0 };
}

// ---- layout: boxes -> lines (same row, small gap) -> paragraphs (stacked, overlapping) ----
function layout(items) {
  items.sort((a, b) => (a.y0 + a.y1) / 2 - (b.y0 + b.y1) / 2);
  const lines = [];
  for (const it of items) {
    const cy = (it.y0 + it.y1) / 2, h = it.y1 - it.y0;
    let hit = null;
    for (const ln of lines) {
      const lh = ln.y1 - ln.y0, lcy = (ln.y0 + ln.y1) / 2;
      if (Math.abs(lcy - cy) < Math.min(h, lh) * 0.5) {
        const gap = it.x0 > ln.x1 ? it.x0 - ln.x1 : ln.x0 > it.x1 ? ln.x0 - it.x1 : 0;
        if (gap < Math.max(h, lh) * 1.5) { hit = ln; break; }
      }
    }
    if (hit) { hit.parts.push(it); hit.x0 = Math.min(hit.x0, it.x0); hit.x1 = Math.max(hit.x1, it.x1); hit.y0 = Math.min(hit.y0, it.y0); hit.y1 = Math.max(hit.y1, it.y1); }
    else lines.push({ parts: [it], x0: it.x0, x1: it.x1, y0: it.y0, y1: it.y1 });
  }
  for (const ln of lines) { ln.parts.sort((a, b) => a.x0 - b.x0); ln.text = ln.parts.map(p => p.text).join(' ').replace(/\s+/g, ' ').trim(); ln.conf = ln.parts.reduce((s, p) => s + p.conf * (p.text.length || 1), 0) / (ln.parts.reduce((s, p) => s + (p.text.length || 1), 0) || 1); }
  lines.sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
  const pars = [];
  for (const ln of lines) {
    const h = ln.y1 - ln.y0;
    let best = null;
    for (const p of pars) {
      const gap = ln.y0 - p.y1, ov = Math.min(ln.x1, p.x1) - Math.max(ln.x0, p.x0), nar = Math.min(ln.x1 - ln.x0, p.x1 - p.x0);
      if (gap < h * 0.9 && gap > -h * 0.5 && ov > nar * 0.3) { if (!best || p.y1 > best.y1) best = p; }
    }
    if (best) { best.lines.push(ln); best.x0 = Math.min(best.x0, ln.x0); best.x1 = Math.max(best.x1, ln.x1); best.y1 = Math.max(best.y1, ln.y1); best.y0 = Math.min(best.y0, ln.y0); }
    else pars.push({ lines: [ln], x0: ln.x0, x1: ln.x1, y0: ln.y0, y1: ln.y1 });
  }
  pars.sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
  return pars;
}
function toResult(pars) {
  const tsv = ['level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'];
  const texts = []; let cs = 0, cn = 0;
  pars.forEach((p, pi) => {
    texts.push(p.lines.map(l => l.text).join('\n'));
    p.lines.forEach((ln, li) => {
      const words = ln.text.split(' ').filter(Boolean), total = ln.text.length || 1, lw = ln.x1 - ln.x0, lh = Math.round(ln.y1 - ln.y0);
      let pos = 0;
      words.forEach((w, wi) => {
        const x = Math.round(ln.x0 + lw * pos / total), ww = Math.max(1, Math.round(lw * w.length / total));
        pos += w.length + 1;
        tsv.push(['5', 1, pi + 1, 1, li + 1, wi + 1, x, Math.round(ln.y0), ww, lh, Math.round(ln.conf * 100), w].join('\t'));
      });
      cs += ln.conf * ln.text.length; cn += ln.text.length;
    });
  });
  return { text: texts.join('\n\n'), tsv: tsv.join('\n'), conf: cn ? Math.round(cs / cn * 100) : 0 };
}

let queue = Promise.resolve();
self.onmessage = e => { queue = queue.then(() => handle(e)); };
async function handle(e) {
  const { id, image, lang, layout: isLayout, maxside } = e.data;
  try {
    self.postMessage({ id, step: 'load' });
    await loadOrt();
    await getDet(); await getRec('eslav');
    if (!isLayout) self.postMessage({ id, step: 'read' });
    const t0 = performance.now();
    const bmp = await createImageBitmap(new Blob([image]));
    const boxes = await detect(bmp, maxside || (isLayout ? 1280 : 2560), 3.4e6);
    // Which alphabet? The Latin reader cannot read Cyrillic. Read the 8 widest boxes with the East-Slavic reader (it reads both)
    // and count the letters. 30 % or more Cyrillic = a Cyrillic label.
    let cyr = 0, lat = 0;
    for (const b of boxes.slice().sort((a, c) => (c.x1 - c.x0) * (c.y1 - c.y0) - (a.x1 - a.x0) * (a.y1 - a.y0)).slice(0, 8)) {
      const s = (await readBox(bmp, b, 'eslav')).text;
      cyr += (s.match(/[\u0400-\u04FF]/g) || []).length; lat += (s.match(/[A-Za-z\u00C0-\u017F]/g) || []).length;
    }
    const isCyr = cyr + lat > 0 && cyr / (cyr + lat) >= 0.3;
    const kind = isCyr ? 'eslav' : 'latin';
    await getRec(kind);
    const items = [];
    for (const b of boxes) {
      const r = await readBox(bmp, b, kind);
      if (r.text.trim()) items.push({ x0: b.x0, y0: b.y0, x1: b.x1, y1: b.y1, text: r.text, conf: r.conf });
    }
    if (bmp.close) bmp.close();
    const res = toResult(layout(items));
    // Paddle's confidence is 84-95 for good and bad reads alike. Stretch it so the app's old limits (66 = unsure) still mean something.
    const conf = Math.max(0, Math.min(100, Math.round((res.conf - 60) * 2.5)));
    self.postMessage({ id, text: res.text, conf, rawConf: res.conf, tsv: res.tsv, script: isCyr ? 'cyr' : 'lat', layout: !!isLayout, ms: Math.round(performance.now() - t0), boxes: boxes.length });
  } catch (err) {
    self.postMessage({ id, error: String(err && err.message || err), layout: !!isLayout });
  }
}
