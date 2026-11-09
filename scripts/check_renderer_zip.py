"""Checks a renderer zip from scripts/build_renderer.py (TD-9, D-042); the CI job
`renderer` runs it.

    python scripts/check_renderer_zip.py build/renderer.zip
    python scripts/check_renderer_zip.py --arch x86_64 --smoke build/renderer-x86_64.zip

- size: under the budgets below, which leave room under Lambda's limits (50 MB zipped for
  a direct upload, 250 MB unzipped) and fail early if a dependency bump balloons it;
- every ELF file is built for the target architecture;
- every library in lib/ finds each library it needs in lib/ or in the base image, and the
  seven WeasyPrint loads are there;
- licences: a notice for every file in lib/, licence texts for every package, OFL.txt
  next to the fonts;
- bytecode: every .py has a hash-based .pyc that is never checked against the source;
- --smoke (x86_64 only, since CI has no arm64): unpacks it and renders the self-test page,
  which must embed only the bundled Noto fonts, Bengali and Devanagari included.
"""

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_renderer", ROOT / "scripts" / "build_renderer.py")
build_renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_renderer)

MB = 1024 * 1024
# Measured 2026-11-02 for the arm64 build: 26.7 MiB zipped, 85.4 MiB unzipped.
MAX_ZIPPED = 32 * MB
MAX_UNZIPPED = 110 * MB
FONTS = {"NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSansDevanagari-Regular.ttf",
         "NotoSansDevanagari-Bold.ttf", "NotoSansBengali-Regular.ttf", "NotoSansBengali-Bold.ttf", "OFL.txt",
         "fonts.conf"}


def check(zip_path: Path, arch_name: str, task: Path) -> list[str]:
    arch = build_renderer.ARCHES[arch_name]
    errors = []
    zipped = zip_path.stat().st_size
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        unzipped = sum(i.file_size for i in z.infolist())
        z.extractall(task)
    print(f"{zip_path.name}: {zipped / MB:.1f} MiB zipped (budget {MAX_ZIPPED // MB}), "
          f"{unzipped / MB:.1f} MiB unzipped (budget {MAX_UNZIPPED // MB})")
    if zipped > MAX_ZIPPED:
        errors.append(f"zipped size {zipped:,} is over the budget of {MAX_ZIPPED:,}")
    if unzipped > MAX_UNZIPPED:
        errors.append(f"unzipped size {unzipped:,} is over the budget of {MAX_UNZIPPED:,}")

    for path in sorted(p for p in task.rglob("*") if p.is_file()):
        head = path.open("rb").read(20)
        if head[:4] == b"\x7fELF" and int.from_bytes(head[18:20], "little") != arch["elf"]:
            errors.append(f"{path.relative_to(task)} is not built for {arch_name}")

    lib = task / "lib"
    libs = {p.name for p in lib.iterdir()} if lib.is_dir() else set()
    for root in build_renderer.ROOTS:
        if root not in libs:
            errors.append(f"lib/{root} is missing")
    for name in sorted(libs):
        for dep in build_renderer.needed(lib / name):
            if dep not in libs and dep not in arch["base"]:
                errors.append(f"lib/{name} needs {dep}, which is neither bundled nor in the base image")

    notice = (task / "licenses" / "NATIVE.txt").read_text() if (task / "licenses" / "NATIVE.txt").exists() else ""
    rows = {line.split(" | ")[0]: line.split(" | ")[1].split()[0] for line in notice.splitlines() if " | " in line}
    for name in sorted(libs):
        if name not in rows:
            errors.append(f"licenses/NATIVE.txt has no row for lib/{name}")
    for package in sorted(set(rows.values()) - {"package"}):
        folder = task / "licenses" / "native" / package
        if not folder.is_dir() or not any(folder.iterdir()):
            errors.append(f"no licence texts for {package} under licenses/native/")

    missing_fonts = FONTS - {n.removeprefix("fonts/") for n in names if n.startswith("fonts/")}
    if missing_fonts:
        errors.append(f"fonts/ is missing {sorted(missing_fonts)}")

    for py in sorted(n for n in names if n.endswith(".py")):
        folder, _, stem = py.rpartition("/")
        pyc = f"{folder}/__pycache__/{stem[:-3]}.cpython-312.pyc".lstrip("/")
        if pyc not in names:
            errors.append(f"{py} has no bytecode")
            continue
        flags = int.from_bytes((task / pyc).open("rb").read(8)[4:8], "little")
        if flags != 0b01:  # hash-based, check_source off
            errors.append(f"{pyc} is not unchecked-hash bytecode (flags {flags})")
    return errors


SMOKE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from renderer import handler
print(json.dumps(handler.handler({"task": "selftest"}, None)))
"""


def smoke(task: Path) -> list[str]:
    out = subprocess.run([sys.executable, "-I", "-c", SMOKE, str(task)], capture_output=True, text=True,
                         cwd=task)
    if out.returncode != 0:
        return [f"the self-test failed:\n{out.stderr[-3000:]}"]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    print(f"self-test: {result}")
    errors = []
    if result["pages"] != 1 or result["bytes"] < 1000:
        errors.append(f"unexpected self-test output {result}")
    if not result["fonts"] or any(not f.startswith("Noto-Sans") for f in result["fonts"]):
        errors.append(f"the PDF should embed only the bundled Noto fonts, not {result['fonts']}")
    if "Noto-Sans-Devanagari" not in result["fonts"]:
        errors.append("the Hindi text did not use Noto Sans Devanagari")
    if "Noto-Sans-Bengali" not in result["fonts"]:
        errors.append("the Bengali text did not use Noto Sans Bengali")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip", type=Path)
    parser.add_argument("--arch", choices=sorted(build_renderer.ARCHES), default="aarch64")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke and args.arch != "x86_64":
        parser.error("--smoke needs the x86_64 build; CI cannot run arm64 code")
    with tempfile.TemporaryDirectory() as d:
        task = Path(d)
        errors = check(args.zip, args.arch, task)
        if args.smoke and not errors:
            errors = smoke(task)
    for e in errors:
        print(f"FAIL {e}", file=sys.stderr)
    print("ok" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
