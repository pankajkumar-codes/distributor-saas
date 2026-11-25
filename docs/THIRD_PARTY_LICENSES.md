# Third-party licences (web fonts)

| Package | Version | Licence |
|---|---|---|
| `@fontsource-variable/geist` (Geist) | 5.3.0 | SIL Open Font License 1.1 (`OFL-1.1` in the package metadata) |
| `@fontsource-variable/geist-mono` (Geist Mono) | 5.3.0 | SIL Open Font License 1.1 (`OFL-1.1` in the package metadata) |

Both are bundled by Vite from npm (and copied into the landing page by `landing/build.mjs`) and served from the app's own origin. Fraunces and Hanken Grotesk were removed with mocks v16 (D-105). The OFL allows bundling and redistribution with the application; the fonts are not sold on their own. Each package ships its own licence file in `node_modules`.

# Programs used by tests only (not shipped)

| Program | Licence | Use |
|---|---|---|
| Tesseract OCR (`tesseract-ocr`) | Apache-2.0 | Run as a separate program by the scan-reader tests on a developer machine and in CI. |
| poppler-utils (`pdftoppm`) | GPL-2.0-or-later | Run as a separate program (not linked) to turn pages into pictures for the same tests. |

Neither is in the application package or the Lambda zips. If a scan reader is ever deployed (D-078), this list and the deployment checklist change first.
