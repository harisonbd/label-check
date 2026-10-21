/* Label Check — offline label reader (runs in a Web Worker). Version 2 (v2.10): also returns word positions (TSV)
   and can run a fast layout read (psm) to find the ingredient list and the product name on the photo.
   New file name on purpose: phones keep ocr/ files forever, so a changed file must get a new name.
   Uses Tesseract (tesseract.js-core v7, Apache-2.0, see ocr/LICENSE-tesseract.txt) directly, without internet:
   the program and the language files are part of the app and are kept on the phone after the first use.
   Message in:  { id, image: Uint8Array (PNG/JPEG), lang: 'eng' | 'deu' | 'bul' | 'hun' | 'ces' | 'slk' | 'slv', psm?: '3' | '11', layout?: true }
   Message out: { id, text, conf, tsv, ms, layout } or { id, error }  (and { id, step } while loading)
   Messages are handled one after the other (a queue), because the reader can do one image at a time. */
'use strict';
const BASE = self.location.href.replace(/[^/]*$/, '');   // .../ocr/
let core = null, api = null, ready = '';
const langsInMemory = new Set();

// WebAssembly SIMD test (same bytes as wasm-feature-detect). Nearly all phones from 2021 on have it.
const hasSimd = () => { try { return WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11])); } catch (e) { return false; } };

async function loadCore() {
  if (core) return;
  const file = hasSimd() ? 'tesseract-core-simd-lstm.js' : 'tesseract-core-lstm.js';
  importScripts(BASE + file);
  core = await self.TesseractCore({ locateFile: f => BASE + f });
}

async function loadLang(lang) {
  if (langsInMemory.has(lang)) return;
  const res = await fetch(BASE + 'lang/' + lang + '.traineddata.gz');
  if (!res.ok) throw new Error('lang ' + lang + ' ' + res.status);
  const plain = res.body.pipeThrough(new DecompressionStream('gzip'));
  core.FS.writeFile('/' + lang + '.traineddata', new Uint8Array(await new Response(plain).arrayBuffer()));
  langsInMemory.add(lang);
}

let queue = Promise.resolve();
self.onmessage = e => { queue = queue.then(() => handle(e)); };

async function handle(e) {
  const { id, image, lang, psm, layout } = e.data;
  try {
    if (ready !== lang) {
      self.postMessage({ id, step: 'load' });
      await loadCore();
      await loadLang(lang);
      if (api) api.End(); else api = new core.TessBaseAPI();
      if (api.Init('/', lang, 1) !== 0) throw new Error('init ' + lang);   // 1 = LSTM reader only
      api.SetVariable('user_defined_dpi', '300');                        // phone photos have no DPI; stops a warning
      ready = lang;
    }
    api.SetVariable('tessedit_pageseg_mode', psm || '3');                // 3 = find the text blocks
    if (!layout) self.postMessage({ id, step: 'read' });
    const t = performance.now();
    core.FS.writeFile('/input', image);
    if (api.SetImageFile(1, 0) === 1) throw new Error('image');
    api.Recognize(null);
    const text = api.GetUTF8Text(), conf = api.MeanTextConf(), tsv = api.GetTSVText(0);
    api.Clear();
    self.postMessage({ id, text, conf, tsv, layout: !!layout, ms: Math.round(performance.now() - t) });
  } catch (err) {
    self.postMessage({ id, error: String(err && err.message || err), layout: !!layout });
  }
}
