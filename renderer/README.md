# renderer: the PDF renderer Lambda

WeasyPrint on the python3.12 arm64 Lambda runtime, from its own zip (TD-9; TD-1(b)
amendment, D-042). The worker writes a render input under `render-input/b/<business>/<render>/input.json`
(`platform_common.render`) and sends only that key to the `render` SQS queue, which
triggers the renderer. The renderer renders the PDF in memory, writes it in one PutObject
to `documents/b/<business>/<render>/document.pdf`. Inputs are never deleted: the
bucket's lifecycle rule expires them, about two days at most (D-042). The first
caller is the draft preview (`app.modules.sales.preview`). `{"task": "selftest"}`,
invoked by hand, renders a fixed sample page and reports pages, bytes, render time and
the embedded fonts.

**Rules (D-042), all in place:**
- Render with `DenyAllFetcher`, which refuses every URL of any scheme, with no base URL.
- `renderer/template.py` escapes every field and refuses anything that isn't a string.
- `renderer/tests` proves a planted URL is never fetched (a local server sees no request) and that a failed render or write leaves no PDF and keeps the input.

**IAM:**
- `s3:GetObject` on `render-input/b/*`.
- `s3:PutObject` on `documents/b/*`.
- No delete and no list.
- `kms:Decrypt` and `kms:GenerateDataKey` only through S3.

**Retries.** A redelivered message renders again to the same document key. An input expires a day after it is written, so a message whose input has expired fails (S3 answers 403 without list rights) and goes to the DLQ. On the last try (`RENDER_MAX_RECEIVES`, set from the queue's `maxReceiveCount`), a failure also writes `failed.json` next to where the PDF would be, holding only `{"error_code": "render_failed"}`, so the app reports the failure instead of waiting. Redriving a DLQ message more than a day old finds nothing, and the user asks for the preview again. At most `render_max_concurrency` (5) renders run at once.

**Tests.** `renderer/tests` need WeasyPrint's native libraries, so they run against an unpacked zip: `RENDERER_TASK=<dir> python -m pytest renderer/tests`. CI does this for the x86_64 build.

```
make renderer-zip                    # build/renderer.zip (arm64) and its checks
make renderer-zip ARCH=x86_64        # build/renderer-x86_64.zip, for a local smoke render
python scripts/check_renderer_zip.py --arch x86_64 --smoke build/renderer-x86_64.zip
```

The build needs Python 3.12, `readelf`, and `zstandard` or the `zstd` command. The
deployed zip is built with **Python 3.12.15 and pip 26.2.2**, pinned in both workflows
(`PYTHON_PIN` and `PIP_PIN` in the build script). Another 3.12 builds a working zip, but
its bytes may differ, and the build says so. CI builds the zip twice and fails if the two
sha256 values differ. It needs
network access to PyPI, conda.anaconda.org and raw.githubusercontent.com. It reads only
the locks below, so the same commit gives the same zip, byte for byte.

## What is in the zip, and why

| Path | From | Why |
|---|---|---|
| WeasyPrint and its Python dependencies | `requirements.txt`, every wheel hash-checked | |
| `lib/` | `natives.lock`: conda-forge packages, sha256-checked | WeasyPrint opens pango, harfbuzz, fontconfig and gobject at run time, and the managed runtime has none of them. conda-forge builds target glibc 2.17, so they run on AL2023 (2.34). Only the seven libraries WeasyPrint opens, plus what they need (19 files), are copied. |
| `renderer/boot.py` | here | Loads every file in `lib/` by absolute path before WeasyPrint is imported. Lambda's `LD_LIBRARY_PATH` finds AL2023's older glib in `/lib64` first, and the bundled pango fails against it. |
| `fonts/` | `fonts.lock`: Google's static Noto Sans, Noto Sans Devanagari and Noto Sans Bengali, Regular and Bold, pinned to a commit | Variable fonts cost about 250 ms per render (WeasyPrint instances them every time). Noto Sans has the rupee sign. Bengali is there for West Bengal businesses (about 200 KB for both weights). |
| `fonts/fonts.conf` | here | Fontconfig sees only these fonts and caches in `/tmp`. |
| `__pycache__/` everywhere | `compileall --invalidation-mode unchecked-hash` | The package is read-only on Lambda, so without bytecode every cold start compiles WeasyPrint again (import 1.3 s instead of 0.45 s locally). |
| `licenses/` | the conda packages, and `licenses/` here for FreeType, whose package ships none | See below. |

## Licences

Native libraries ship **unmodified, as separate shared objects**, loaded at run time.
Each can be replaced by its own build. `licenses/NATIVE.txt` in the zip names each file's
package, version, licence, upstream source and the conda-forge recipe commit, and
`licenses/native/<package>/` holds the licence texts.

| Component | Licence | How we use it |
|---|---|---|
| pango, glib (gobject, gio, gmodule), fribidi, libiconv | LGPL-2.1 (or later; libiconv 2.1 only) | dynamic, unmodified, notice and texts shipped |
| graphite2 | LGPL-2.0-or-later | same |
| harfbuzz, fontconfig, libffi, expat | MIT | notice shipped |
| FreeType | FTL or GPL-2.0, our choice | we use the FreeType License; its credit line is in `NATIVE.txt` |
| pcre2 | BSD-3-Clause | notice shipped |
| libpng, zlib | libpng / zlib licences | notice shipped |
| Noto Sans, Noto Sans Devanagari, Noto Sans Bengali | SIL OFL 1.1 | unmodified, `fonts/OFL.txt` shipped |
| WeasyPrint, pydyf, tinycss2, cssselect2, webencodings, pycparser | BSD | as wheels; licences in their `*.dist-info` |
| fontTools, brotli, tinyhtml5 (MIT), cffi (MIT-0), Pillow (MIT-CMU), zopfli (Apache-2.0) | as listed | same |
| Pyphen | GPL-2.0+ / LGPL-2.1+ / MPL-1.1, our choice: LGPL-2.1+ | unmodified wheel, imported as a library; licence in its `dist-info` |

## Upgrading

`scripts/renderer_lock.py` regenerates `requirements.txt` and `natives.lock` (it needs
py-rattler). Change the pins at its top, run it, then `make renderer-zip` and the smoke
render, and review the size line. `fonts.lock` is edited by hand: a new commit and the
new sha256 values.
