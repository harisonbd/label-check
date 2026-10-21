Label Check - offline label reader files

Program: tesseract.js-core 7.0.0 (Tesseract OCR compiled to WebAssembly)
  https://github.com/naptha/tesseract.js-core  (commit acffef2)
  Files: tesseract-core-simd-lstm.js/.wasm (most phones), tesseract-core-lstm.js/.wasm (old phones without SIMD)
  Licence: Apache License 2.0 (see LICENSE-Apache-2.0.txt). Tesseract OCR: https://github.com/tesseract-ocr/tesseract

Language files: tessdata_fast (eng, deu, bul), gzip-packed, unchanged otherwise
  https://github.com/tesseract-ocr/tessdata_fast  (commit 8741641)
  Added in v2.8: hun, ces, slk, slv (same repository, commit 8741641; eng there is byte-identical)
  Licence: Apache License 2.0

ocr-worker.js: written for Label Check. It loads the program and one language file,
reads the image and sends back the text. No internet is used after the first time.

If you change any file here, rename the folder (e.g. ocr2/) and the paths in app.js and sw.js,
because the service worker keeps these files without checking for updates.
