# renderer: the PDF renderer Lambda

WeasyPrint on the python3.12 arm64 Lambda runtime, from its own zip (TD-9; TD-1(b)
amendment, D-042). After finalize the worker will send a message to the `render` SQS
queue, which triggers it (S4, BH-6); a message carries a document ID or an S3 key, never
the invoice. Until then its only task is `{"task": "selftest"}`, invoked by hand, which
renders a fixed sample page and reports pages, bytes, render time and the embedded fonts.

**Rules for S4 (D-042):** render with a deny-all `url_fetcher`, so WeasyPrint fetches
nothing from any URL a field could carry, and escape every field put into the HTML, with
a test that a planted URL is never fetched. The renderer's IAM is `kms:GenerateDataKey`
on our key and `s3:PutObject` on `documents/b/*`. How the renderer gets its input and the
logo under that limit is open (docs/OPEN_QUESTIONS.md).

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
| `fonts/` | `fonts.lock`: Google's static Noto Sans and Noto Sans Devanagari, Regular and Bold, pinned to a commit | Variable fonts cost about 250 ms per render (WeasyPrint instances them every time). Noto Sans has the rupee sign. |
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
| Noto Sans, Noto Sans Devanagari | SIL OFL 1.1 | unmodified, `fonts/OFL.txt` shipped |
| WeasyPrint, pydyf, tinycss2, cssselect2, webencodings, pycparser | BSD | as wheels; licences in their `*.dist-info` |
| fontTools, brotli, tinyhtml5 (MIT), cffi (MIT-0), Pillow (MIT-CMU), zopfli (Apache-2.0) | as listed | same |
| Pyphen | GPL-2.0+ / LGPL-2.1+ / MPL-1.1, our choice: LGPL-2.1+ | unmodified wheel, imported as a library; licence in its `dist-info` |

## Upgrading

`scripts/renderer_lock.py` regenerates `requirements.txt` and `natives.lock` (it needs
py-rattler). Change the pins at its top, run it, then `make renderer-zip` and the smoke
render, and review the size line. `fonts.lock` is edited by hand: a new commit and the
new sha256 values.
