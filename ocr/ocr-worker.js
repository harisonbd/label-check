/* Label Check — offline label reader (runs in a Web Worker).
   Uses Tesseract (tesseract.js-core v7, Apache-2.0, see ocr/LICENSE-tesseract.txt) directly, without internet:
   the program and the language files are part of the app and are kept on the phone after the first use.
   Message in:  { id, image: Uint8Array (PNG/JPEG), lang: 'eng' | 'deu' | 'bul' }
   Message out: { id, text, conf, ms } or { id, error }  (and { id, step } while loading) */
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

self.onmessage = async e => {
  const { id, image, lang } = e.data;
  try {
    if (ready !== lang) {
      self.postMessage({ id, step: 'load' });
      await loadCore();
      await loadLang(lang);
      if (api) api.End(); else api = new core.TessBaseAPI();
      if (api.Init('/', lang, 1) !== 0) throw new Error('init ' + lang);   // 1 = LSTM reader only
      api.SetVariable('tessedit_pageseg_mode', '3');                     // find the text blocks
      api.SetVariable('user_defined_dpi', '300');                        // phone photos have no DPI; stops a warning
      ready = lang;
    }
    self.postMessage({ id, step: 'read' });
    const t = performance.now();
    core.FS.writeFile('/input', image);
    if (api.SetImageFile(1, 0) === 1) throw new Error('image');
    api.Recognize(null);
    const text = api.GetUTF8Text(), conf = api.MeanTextConf();
    api.Clear();
    self.postMessage({ id, text, conf, ms: Math.round(performance.now() - t) });
  } catch (err) {
    self.postMessage({ id, error: String(err && err.message || err) });
  }
};
