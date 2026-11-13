#!/usr/bin/env python3
"""Check a real marketplace report against the platform readers, on your own computer (R1-M4).

    python scripts/check_reader.py path/to/report.zip            # or .csv or .xlsx
    python scripts/check_reader.py path/to/report.xlsx --section flipkart

For each file in it (and each sheet a reader names), prints which reader claims it, which of the reader's
headers were found and which were not, and the row counts: how many rows read, would be staged as new, held
(by reason), skipped as zero value, invalid (by error code), and duplicate or conflicting. It prints header
names and numbers only, never a cell value, a seller GSTIN or an order number. The only file name it shows is
the file's own base name (a Flipkart report's name carries a date range). An unexpected error prints only its
type. With --show-headers it also lists the names of the columns the reader does not use. It writes nothing
(no file, no database, no network) and keeps nothing: run it, read the screen, and report what it says.

A reader's `verified` flag in refdata stays false until someone has run this on a real report and the headers
all matched. Flipping the flag is then a reviewed change to refdata/values/imports.yaml, not an edit here.

Run it with the project's Python (make setup). Exit status: 0 when every file was claimed by exactly one reader,
1 when one was not, 2 when the file could not be read.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app" / "src"), str(ROOT / "libs" / "platform_common")]


def _tables(path: Path, readers):
    from app.modules.imports.parsing import FileRejected, open_zip, read_table, sheet_names

    content = path.read_bytes()
    name = path.name
    files = [(name, content)]
    if name.lower().endswith(".zip"):
        files = open_zip(content, accepts=lambda n: any(r.accepts(n) for r in readers), max_entries=50,
                         max_inflate_bytes=200 * 1024 * 1024)
    for fname, data in files:
        if fname.lower().endswith(".xlsx"):
            wanted = [s for s in sheet_names(data)
                      if any((r.sheet or "").strip().lower() == s.strip().lower() for r in readers)]
            if wanted:
                for s in wanted:
                    yield fname, read_table(data, fname, sheet=s)
                continue
        try:
            yield fname, read_table(data, fname)
        except FileRejected as exc:
            raise FileRejected(f"{fname}: {exc}") from None


def check(path: Path, section: str | None, out, show_headers: bool = False) -> int:
    from app.modules.imports.parsing import FileRejected, RowStatus, parse
    from app.modules.imports.readers import clear_for_tests, readers_for, register_platform_readers
    from app.modules.imports.parsing.profiles import header_key

    clear_for_tests()
    register_platform_readers()
    sections = [section] if section else ["amazon", "flipkart", "meesho"]
    readers = [r for s in sections for r in readers_for(s)]
    status = 0
    try:
        found = list(_tables(path, readers))
    except FileRejected as exc:
        print(f"Could not read the file: {exc}", file=out)
        return 2
    print(f"Files and sheets read: {len(found)}", file=out)
    for index, (fname, table) in enumerate(found, start=1):
        # A sheet's name is printed only when a reader names it ("Sales Report"); Meesho's is a supplier id.
        named = any((r.sheet or "").strip().lower() == (table.sheet or "").strip().lower() for r in readers)
        label = f"[{index}] {Path(fname).name}" + (f" / sheet {table.sheet!r}" if table.sheet and named else "")
        matches = [r for r in readers if (r.sheet is None or (table.sheet or "").strip().lower() == r.sheet.strip().lower())
                   and r.detect(table)]
        print(f"\n{label}: {len(table.rows)} rows read including the header", file=out)
        if len(matches) != 1:
            status = max(status, 1)
            print(f"  Claimed by {len(matches)} readers: " + (", ".join(r.id for r in matches) or "none"), file=out)
            for r in readers:
                _headers(r, table, out, header_key)
            continue
        reader = matches[0]
        print(f"  Reader: {reader.id}  (profile verified flag in the code: {reader.profile().verified})", file=out)
        _headers(reader, table, out, header_key)
        result = parse(table, reader.profile())
        counts: Counter = Counter()
        holds: Counter = Counter()
        errors: Counter = Counter()
        for row in result.rows:
            verdict = reader.classify(row) if row.status == RowStatus.valid else None
            if verdict is not None:
                counts[verdict[0].value] += 1
                if verdict[1]:
                    holds[verdict[1]] += 1
            else:
                counts[row.status.value] += 1
            for e in row.errors:
                errors[e.code] += 1
        print(f"  Data rows: {len(result.rows)} (blank rows skipped: {result.skipped_blank_rows})", file=out)
        print("  Row outcomes: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"), file=out)
        if holds:
            print("  Held by reason: " + ", ".join(f"{k} {v}" for k, v in sorted(holds.items())), file=out)
        if errors:
            print("  Row problems by code: " + ", ".join(f"{k} {v}" for k, v in sorted(errors.items())), file=out)
        gstin = reader.gstin(table)
        print("  Seller GSTIN: " + ("several different ones in one file (the app would refuse it)" if gstin == "MIXED"
                                    else "found" if gstin else "not found"), file=out)
        if result.unmapped_headers:
            print(f"  Columns in the file that the reader does not use: {len(result.unmapped_headers)}", file=out)
            if show_headers:  # header names only, the file's own column titles, never a cell
                for name in result.unmapped_headers:
                    print(f"    not used: {name!r}", file=out)
    return status


def _headers(reader, table, out, header_key):
    found = reader._header(table)
    have = set(found[1]) if found else set()
    if not have:  # no header row matched the reader's markers: look at the first rows for what is there
        for row in table.rows[:10]:
            have |= {header_key(c) for c in row if c.strip()}
    wanted = [(spec.name, spec.headers, spec.required) for spec in reader.profile().fields]
    missing = [(n, hs, req) for n, hs, req in wanted if not any(header_key(h) in have for h in hs)]
    print(f"  {reader.id}: {len(wanted) - len(missing)} of {len(wanted)} headers found", file=out)
    for name, headers, required in missing:
        print(f"    missing{' (required)' if required else ''}: {headers[0]!r} (field {name})", file=out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--section", choices=["amazon", "flipkart", "meesho"])
    parser.add_argument("--show-headers", action="store_true",
                        help="also list the names of the columns the reader does not use (header names only)")
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print("No such file.")
        return 2
    try:
        return check(args.file, args.section, sys.stdout, show_headers=args.show_headers)
    except Exception as exc:  # never let a traceback (which could carry a cell) reach the screen
        print(f"Could not check the file ({type(exc).__name__}).")
        return 2


if __name__ == "__main__":
    sys.exit(main())
