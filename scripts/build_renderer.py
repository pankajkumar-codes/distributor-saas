"""Builds build/renderer.zip, the PDF renderer Lambda (TD-9; TD-1(b) amendment, D-042),
from the locks in renderer/ only, so the same commit gives the same zip.

    python3.12 scripts/build_renderer.py                 # arm64, for Lambda
    python3.12 scripts/build_renderer.py --arch x86_64   # build/renderer-x86_64.zip, for
                                                         # the smoke render in CI only

What goes in (renderer/README.md has the why of each step):
- the wheels in renderer/requirements.txt, every one hash-checked;
- lib/: the shared objects WeasyPrint dlopens (ROOTS) and everything they need, from the
  conda-forge packages in renderer/natives.lock (sha256-checked), unmodified, plus each
  package's licence files under licenses/native/ and a table in licenses/NATIVE.txt;
- fonts/: the static Noto fonts in renderer/fonts.lock (sha256-checked), OFL.txt and
  fonts.conf;
- the renderer package, which preloads lib/ before importing WeasyPrint;
- bytecode for everything, hash-based and unchecked: the package is read-only on Lambda,
  so without it every cold start compiles WeasyPrint again.

The zip is deterministic: sorted entries, fixed timestamps and modes. It needs Python
3.12 (the bytecode must match the runtime), readelf, and zstandard or the zstd command.
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "renderer"
CACHE = ROOT / "build" / ".cache" / "renderer"

# The libraries WeasyPrint 70 opens by name (weasyprint/text/ffi.py).
ROOTS = ["libgobject-2.0.so.0", "libpango-1.0.so.0", "libpangoft2-1.0.so.0", "libharfbuzz.so.0",
         "libharfbuzz-subset.so.0", "libharfbuzz-vector.so.0", "libfontconfig.so.1"]
# Wheels built for glibc 2.34 or older: AL2023, under the python3.12 runtime, has 2.34.
# Provided by the Lambda base image (glibc); never bundled.
GLIBC_LIBS = {"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "libresolv.so.2", "librt.so.1"}
ARCHES = {
    "aarch64": {"wheel": [f"manylinux_2_{v}_aarch64" for v in (34, 28, 17)], "conda": "linux-aarch64", "elf": 183,
                "base": GLIBC_LIBS | {"ld-linux-aarch64.so.1"}, "zip": "renderer.zip"},
    "x86_64": {"wheel": [f"manylinux_2_{v}_x86_64" for v in (34, 28, 17)], "conda": "linux-64", "elf": 62,
               "base": GLIBC_LIBS | {"ld-linux-x86-64.so.2"}, "zip": "renderer-x86_64.zip"},
}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def needed(path: Path) -> list[str]:
    out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True, check=True).stdout
    return [line.split("[", 1)[1].split("]", 1)[0] for line in out.splitlines() if "(NEEDED)" in line]


def closure(libdir: Path, base: set[str]) -> list[str]:
    """ROOTS and every NEEDED soname they reach, except the base image's. Fails on a
    soname that is neither in libdir nor in base."""
    seen, todo = set(), list(ROOTS)
    while todo:
        name = todo.pop()
        if name in seen or name in base:
            continue
        if not (libdir / name).exists():
            sys.exit(f"{name} is needed but is neither bundled nor in the base image")
        seen.add(name)
        todo += needed(libdir / name)
    return sorted(seen)


def fetch(url: str, sha256: str) -> bytes:
    cached = CACHE / sha256
    if cached.exists() and hashlib.sha256(cached.read_bytes()).hexdigest() == sha256:
        return cached.read_bytes()
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - fixed https URLs from the locks
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        sys.exit(f"sha256 mismatch for {url}: lock says {sha256}, got {got}")
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def unzstd(data: bytes) -> bytes:
    try:
        import zstandard
    except ImportError:
        return subprocess.run(["zstd", "-dc"], input=data, capture_output=True, check=True).stdout
    return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()


def extract_conda(data: bytes, dest: Path) -> None:
    """A .conda file is a zip of info-*.tar.zst and pkg-*.tar.zst; both go into dest."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            if member.endswith(".tar.zst"):
                with tarfile.open(fileobj=io.BytesIO(unzstd(z.read(member)))) as t:
                    t.extractall(dest, filter="data")


def lock_lines(path: Path) -> list[list[str]]:
    return [line.split() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def natives(arch: dict, task: Path, work: Path) -> None:
    prefix = work / "prefix"
    notice = [
        "Native libraries in lib/ (TD-9, D-042)",
        "",
        "Each file is the unmodified shared object from the conda-forge package named below,",
        "copied under its soname and loaded at run time by renderer/boot.py. None is linked",
        "statically into anything else, so each can be replaced by a build of the same",
        "version from its source. Licence texts are under licenses/native/<package>/.",
        "",
        "FreeType is used under the FreeType License (FTL), not the GPL:",
        "Portions of this software are copyright (c) 2026 The FreeType Project",
        "(https://freetype.org). All rights reserved.",
        "",
        "file | package version build | licence | source | conda-forge recipe",
    ]
    owners: dict[str, list[str]] = {}
    for subdir, name, version, build, sha256, url, licence in lock_lines(SRC / "natives.lock"):
        if subdir != arch["conda"]:
            continue
        pkg = work / "pkgs" / name
        extract_conda(fetch(url, sha256), pkg)
        about = json.loads((pkg / "info" / "about.json").read_text())
        recipe = about.get("extra", {})
        lic_src = pkg / "info" / "licenses"
        if not lic_src.is_dir():  # the package ships none; renderer/licenses/ has its texts
            lic_src = SRC / "licenses" / name
        if not lic_src.is_dir() or not any(lic_src.iterdir()):
            sys.exit(f"no licence files for {name}: add them under renderer/licenses/{name}/")
        shutil.copytree(lic_src, task / "licenses" / "native" / name)
        shutil.copytree(pkg, prefix, dirs_exist_ok=True, ignore=shutil.ignore_patterns("info"), symlinks=True)
        for f in (pkg / "lib").glob("*.so*"):
            owners[f.name] = [f"{name} {version} {build}", licence.replace("_", " "), about.get("home") or about.get("dev_url") or "the recipe's source",
                              f"{recipe.get('remote_url', '')} @ {recipe.get('sha', '')}"]
    lib = task / "lib"
    lib.mkdir()
    for soname in closure(prefix / "lib", arch["base"]):
        shutil.copyfile(os.path.realpath(prefix / "lib" / soname), lib / soname)
        if soname not in owners:
            sys.exit(f"{soname} comes from no locked package")
        notice.append(" | ".join([soname, *owners[soname]]))
    (task / "licenses" / "NATIVE.txt").write_text("\n".join(notice) + "\n")


def fonts(task: Path) -> None:
    out = task / "fonts"
    out.mkdir()
    for sha256, url, name in lock_lines(SRC / "fonts.lock"):
        (out / name).write_bytes(fetch(url, sha256))
    shutil.copyfile(SRC / "fonts.conf", out / "fonts.conf")


def write_zip(task: Path, dest: Path) -> None:
    dest.unlink(missing_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(p for p in task.rglob("*") if p.is_file()):
            if path.is_symlink():
                sys.exit(f"symlink in the package: {path}")
            info = zipfile.ZipInfo(path.relative_to(task).as_posix(), FIXED_TIME)
            info.external_attr = (0o100755 if os.access(path, os.X_OK) else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes(), compresslevel=9)


def build(arch_name: str) -> Path:
    if sys.version_info[:2] != (3, 12):
        sys.exit("run this with Python 3.12, the Lambda runtime's version, e.g. PY=python3.12 make renderer-zip")
    arch = ARCHES[arch_name]
    work = ROOT / "build" / f"renderer-{arch_name}"
    task = work / "task"
    shutil.rmtree(work, ignore_errors=True)
    task.mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--require-hashes", "--only-binary=:all:",
         "--implementation", "cp", "--python-version", "3.12",
         *[a for tag in arch["wheel"] for a in ("--platform", tag)], "--no-compile", "-t", str(task), "-r", str(SRC / "requirements.txt")],
        check=True,
    )
    for unused in ("bin", "share"):  # console scripts and man pages from the wheels
        shutil.rmtree(task / unused, ignore_errors=True)
    natives(arch, task, work)
    fonts(task)
    shutil.copytree(SRC / "renderer", task / "renderer", ignore=shutil.ignore_patterns("__pycache__"))
    for cache in list(task.rglob("__pycache__")):
        shutil.rmtree(cache)
    # A fixed hash seed: set literals are stored in bytecode in iteration order.
    subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "-j0", "--invalidation-mode", "unchecked-hash",
         "-s", str(task), "-p", "/var/task", str(task)],
        check=True, env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    dest = ROOT / "build" / arch["zip"]
    write_zip(task, dest)
    unzipped = sum(p.stat().st_size for p in task.rglob("*") if p.is_file())
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    print(f"built {dest.relative_to(ROOT)}: {dest.stat().st_size:,} bytes zipped, {unzipped:,} unzipped, sha256 {digest}")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", choices=sorted(ARCHES), default="aarch64")
    build(parser.parse_args().arch)
