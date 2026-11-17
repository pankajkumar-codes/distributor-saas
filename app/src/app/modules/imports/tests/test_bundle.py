"""A bundle zip: the guards, and the sorting of each file by content (bundle plan, PR 1). No database.

Every file here is synthetic (the masked fixtures of each reader); none is a real seller's file."""

import io
import stat
import zipfile

import pytest

from app.modules.imports import bundle, reading
from app.modules.imports.bundle import BundleFile, BundleRefused, Limits, classify, open_bundle
from app.modules.imports.parsing import read_table
from app.modules.imports.readers import SECTIONS, clear_for_tests, readers_for, register_readers

from .fixtures import amazon, flipkart, meesho, own_excel, pdf

LIMITS = Limits(max_files=100, max_total_bytes=100 * 1024 * 1024, max_file_bytes=20 * 1024 * 1024, max_depth=1)


@pytest.fixture(autouse=True)
def readers():
    clear_for_tests()
    register_readers()
    yield
    clear_for_tests()


def zip_of(entries, *, symlink=(), encrypted=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if name in symlink:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, data)
    raw = buf.getvalue()
    for name in encrypted:  # flip the "encrypted" flag in the local and central headers of that entry
        raw = _flag_encrypted(raw, name)
    return raw


def _flag_encrypted(raw: bytes, name: str) -> bytes:
    key = name.encode()
    out = bytearray(raw)
    for sig, flag_at in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (i := out.find(sig, start)) != -1:
            name_at = i + (30 if sig == b"PK\x03\x04" else 46)
            if bytes(out[name_at:name_at + len(key)]) == key:
                out[i + flag_at] |= 1
            start = i + 4
    return bytes(out)


def sort(entries, **kw):
    return classify(open_bundle(zip_of(entries), LIMITS), **kw)


def one(entries, **kw):
    (o,) = sort(entries, **kw)
    return o


# -- the sorting: by content, never by name --------------------------------------------------------------------

REPORTS = {
    "amazon": amazon.b2c_good(),
    "flipkart": flipkart.good(),
    "meesho": meesho.sales_good(),
    "own_invoices_excel": own_excel.good(),
    "own_invoices_pdf": pdf.one_invoice(),
}


def test_one_file_of_every_report_goes_to_its_own_section():
    out = sort([(f"f{i}.bin", data) for i, data in enumerate(REPORTS.values())])
    assert [(o.section, o.state, o.reason) for o in out] == [(s, "used", None) for s in REPORTS]


def test_a_file_is_sorted_by_what_it_holds_not_what_it_is_called():
    # The name says Amazon and the extension says Excel; the content is a Flipkart workbook.
    o = one([("MTR_B2C-July.csv", flipkart.good())])
    assert (o.section, o.state) == ("flipkart", "used")
    # And an Amazon CSV named like an invoice PDF stays Amazon.
    assert one([("invoice.pdf", amazon.b2c_good())]).section == "amazon"
    # The name never rescues a file whose content matches nothing.
    o = one([("MTR_B2C-July.csv", b"a,b\n1,2\n")])
    assert (o.section, o.state, o.reason_code) == (None, "not_used", "no_match")


def test_a_meesho_report_zip_is_opened_once_and_each_workbook_is_sorted_alone():
    inner = amazon.zipped({"tcs_sales.xlsx": meesho.sales_good(), "tcs_sales_return.xlsx": meesho.returns_good()})
    out = sort([("meesho/report.zip", inner), ("amazon/MTR_B2C-July.csv", amazon.b2c_good())])
    assert [(o.name, o.section) for o in out] == [
        ("tcs_sales.xlsx", "meesho"), ("tcs_sales_return.xlsx", "meesho"), ("MTR_B2C-July.csv", "amazon")]
    assert [o.n for o in out] == [1, 2, 3]  # numbered in the flat list, a nested zip's files in place


def test_a_workbook_with_a_report_sheet_and_a_help_sheet_is_one_report():
    assert one([("x.xlsx", flipkart.workbook([flipkart.sale("1")]))]).section == "flipkart"


def test_a_file_that_two_reports_claim_is_not_used_and_never_guessed(monkeypatch):
    # Two readers of different sections whose markers both appear in one header row.
    import app.modules.imports.readers as registry

    class Twin:
        id, section, report_type, sheet = "twin_v1", "meesho", "twin", None

        def detect(self, table):
            return any("Seller Gstin".casefold() in c.casefold() for r in table.rows[:5] for c in r)

        def accepts(self, name):
            return False

    registry._registry["twin_v1"] = Twin()
    o = one([("x.csv", amazon.b2c_good())])
    assert (o.section, o.state, o.reason_code) == (None, "not_used", "ambiguous")
    assert o.reason == "This matches more than one report, so we did not guess."


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "not_a_report"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "old_excel"),
        (b"not a table at all", "no_match"),
        (b"PK\x03\x04" + b"\x00" * 30, "not_a_report"),
        (b"\xff\xfe\x00\x00 not utf-8", "not_a_report"),
    ],
)
def test_a_file_that_is_no_report_says_why_in_plain_words(data, code):
    o = one([("f.bin", data or b"x")]) if data else classify([BundleFile(1, "f.bin", b"", 0)])[0]
    assert (o.section, o.state, o.reason_code) == (None, "not_used", code)
    assert o.reason and not o.reason.endswith("_")


def test_an_office_file_that_is_not_a_workbook_is_not_used():
    docx = zip_of([("[Content_Types].xml", "<Types/>"), ("word/document.xml", "<w/>")])
    assert one([("a.docx", docx)]).reason_code == "not_a_report"


def test_a_computer_added_file_is_listed_as_not_a_report():
    out = sort([("__MACOSX/._a.csv", b"junk"), (".DS_Store", b"\x00\x00"), ("Thumbs.db", b"x"), ("~$a.xlsx", b"x")])
    assert [o.reason_code for o in out] == ["system_file"] * 4


def test_a_workbook_with_several_unnamed_sheets_is_not_guessed():
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "One"
    wb.create_sheet("Two")
    buf = io.BytesIO()
    wb.save(buf)
    assert one([("x.xlsx", buf.getvalue())]).reason_code == "no_match"


def test_a_broken_workbook_is_unreadable_not_an_error():
    broken = zip_of([("[Content_Types].xml", "<Types/>"), ("xl/workbook.xml", "not xml")])
    assert one([("x.xlsx", broken)]).reason_code == "unreadable"


# -- the business's own choice ------------------------------------------------------------------------------

def test_a_report_the_business_did_not_choose_is_listed_and_not_selected():
    out = sort([("a.csv", amazon.b2c_good()), ("f.xlsx", flipkart.good())], selected=frozenset({"amazon"}))
    assert [(o.section, o.state, o.reason_code) for o in out] == [
        ("amazon", "used", None), ("flipkart", "not_selected", "not_selected")]
    assert out[1].reason == "This report is not selected for your business."


def test_nothing_selected_means_every_section_is_open():
    assert one([("a.csv", amazon.b2c_good())], selected=None).state == "used"
    assert one([("a.csv", amazon.b2c_good())], selected=frozenset()).state == "not_selected"


# -- the guards: whole-zip refusals ----------------------------------------------------------------------------

def refused(content, limits=LIMITS):
    with pytest.raises(BundleRefused) as e:
        open_bundle(content, limits)
    return e.value


def test_a_file_that_is_not_a_zip_or_has_nothing_in_it_is_refused():
    assert refused(b"this is not a zip").code == "not_a_zip"
    assert refused(zip_of([])).code == "empty_zip"
    assert refused(zip_of([("only/", b"")])).code == "empty_zip"  # a folder alone is no file


@pytest.mark.parametrize("name", ["../x.csv", "a/../../x.csv", "/etc/x.csv", "C:/x.csv", "C:\\x.csv", "a\\..\\x.csv", "a\x01.csv"])
def test_a_name_that_climbs_out_or_starts_at_a_root_is_refused(name):
    assert refused(zip_of([(name, b"x")])).code == "unsafe_name"


def test_a_name_with_a_non_breaking_space_or_zero_width_mark_is_fine_a_bidi_override_is_not():
    ok = open_bundle(zip_of([("report\u00a0July\u200b.csv", amazon.b2c_good())]), LIMITS)
    assert [f.name for f in ok] == ["report\u00a0July\u200b.csv"]
    assert refused(zip_of([("invoice\u202egnp.csv", b"x")])).code == "unsafe_name"
    assert refused(zip_of([("a\u2066b.csv", b"x")])).code == "unsafe_name"
    assert refused(zip_of([("a\x85b.csv", b"x")])).code == "unsafe_name"  # a C1 control character


def test_folder_entries_cannot_bloat_the_directory_past_a_bound():
    entries = [(f"d{i}/", b"") for i in range(41)] + [("a.csv", b"1")]
    assert refused(zip_of(entries), Limits(10, 10**6, 10**6, 1)).code == "too_many_files"  # 42 entries > 10 * 4
    assert open_bundle(zip_of(entries[:30] + entries[-1:]), Limits(10, 10**6, 10**6, 1))[0].name == "a.csv"


def test_a_link_in_the_zip_is_refused():
    assert refused(zip_of([("a.csv", b"x"), ("b.csv", b"a.csv")], symlink=("b.csv",))).code == "symlink"


def test_a_password_protected_entry_is_refused():
    assert refused(zip_of([("a.csv", b"x")], encrypted=("a.csv",))).code == "encrypted"


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_the_same_name_in_the_same_place_twice_is_refused():
    assert refused(zip_of([("x.csv", b"1"), ("x.csv", b"2")])).code == "duplicate_name"
    assert refused(zip_of([("a/x.csv", b"1"), ("a/X.CSV", b"2")])).code == "duplicate_name"


def test_one_name_in_two_folders_keeps_both_told_apart_by_their_folder():
    files = open_bundle(zip_of([("Jan/report.csv", b"1"), ("Feb/Report.csv", b"2"), ("other.csv", b"3")]), LIMITS)
    assert [f.name for f in files] == ["Jan - report.csv", "Feb - Report.csv", "other.csv"]
    assert [f.n for f in files] == [1, 2, 3]
    # One at the top and one in a folder: the folder one is told apart. Still clashing after that is refused.
    top = open_bundle(zip_of([("report.csv", b"1"), ("Jan/report.csv", b"2")]), LIMITS)
    assert [f.name for f in top] == ["report.csv", "Jan - report.csv"]
    assert refused(zip_of([("a/x/r.csv", b"1"), ("b/x/r.csv", b"2")])).code == "duplicate_name"


def test_the_same_name_in_two_inner_zips_is_told_apart_by_the_zip_names():
    inner1 = zip_of([("r.csv", b"1")])
    inner2 = zip_of([("r.csv", b"2")])
    files = open_bundle(zip_of([("jan.zip", inner1), ("feb.zip", inner2)]), LIMITS)
    assert [f.name for f in files] == ["jan - r.csv", "feb - r.csv"]


def test_folders_are_fine_and_only_the_base_name_is_kept():
    files = open_bundle(zip_of([("Q2 folder/amazon/MTR_B2C-July.csv", amazon.b2c_good()), ("Q2 folder/", b"")]), LIMITS)
    assert [f.name for f in files] == ["MTR_B2C-July.csv"]
    assert "Q2" not in repr(files)  # the path the person zipped is not kept anywhere (only a clash uses a folder name)


def test_too_many_files_is_refused_nested_ones_counted():
    entries = [(f"f{i}.csv", b"a") for i in range(4)]
    assert refused(zip_of(entries), Limits(3, 10**6, 10**6, 1)).code == "too_many_files"
    inner = zip_of([("i1.csv", b"1"), ("i2.csv", b"2"), ("i3.csv", b"3")])
    assert refused(zip_of([("in.zip", inner), ("o.csv", b"o")]), Limits(3, 10**6, 10**6, 1)).code == "too_many_files"


def test_a_zip_inside_a_zip_inside_a_zip_is_refused():
    deepest = zip_of([("d.csv", b"d")])
    middle = zip_of([("m.zip", deepest)])
    assert refused(zip_of([("o.zip", middle)])).code == "too_deep"
    ok = open_bundle(zip_of([("o.zip", zip_of([("m.csv", b"m")]))]), LIMITS)
    assert [f.name for f in ok] == ["m.csv"]
    assert refused(zip_of([("o.zip", zip_of([("m.csv", b"m")]))]), Limits(100, 10**6, 10**6, 0)).code == "too_deep"


def test_a_zip_bomb_is_stopped_part_way_not_after_it_is_inflated():
    bomb = zip_of([("zeros.csv", b"\x00" * (8 * 1024 * 1024))])  # a few KB that inflates to 8 MB
    assert len(bomb) < 100_000
    assert refused(bomb, Limits(10, 1024 * 1024, 20 * 1024 * 1024, 1)).code == "too_big"  # the total cap


def test_a_file_that_lies_about_its_size_is_a_bomb_and_refuses_the_zip():
    raw = bytearray(zip_of([("a.csv", b"\x00" * 50_000)]))
    # Make the declared (uncompressed) size small in both headers while the data still inflates to 50,000 bytes.
    for sig, at in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        i = raw.find(sig)
        raw[i + at:i + at + 4] = (10).to_bytes(4, "little")
    assert refused(bytes(raw), Limits(10, 10**6, 1_000, 1)).code in {"too_big", "damaged"}


def test_a_file_over_the_per_file_cap_is_listed_as_too_large_and_not_read():
    big = b"a,b\n" + b"1,2\n" * 5_000
    files = open_bundle(zip_of([("big.csv", big), ("ok.csv", amazon.b2c_good())]), Limits(10, 10**7, 1_000, 1))
    assert files[0].data == b"" and files[0].size == len(big)  # never inflated
    out = classify(files)
    assert [(o.state, o.reason_code) for o in out][0] == ("not_used", "too_large")
    assert out[0].size == len(big)


def test_the_total_is_one_budget_across_levels():
    inner = zip_of([("i.csv", b"\x01" * 600)])
    # 600 inside the nested zip and 600 beside it: 1,200 together is over a 1,000 total even though each is under.
    assert refused(zip_of([("in.zip", inner), ("o.csv", b"\x02" * 600)]), Limits(10, 1_000, 1_000, 1)).code == "too_big"


def test_a_damaged_entry_refuses_the_zip_with_a_plain_reason():
    raw = bytearray(zip_of([("a.csv", b"abcdefgh" * 400)]))
    i = raw.find(b"PK\x03\x04")
    raw[i + 40:i + 60] = b"\xff" * 20  # corrupt the compressed data
    err = refused(bytes(raw))
    assert err.code == "damaged" and str(err) == bundle.REFUSALS["damaged"]


def test_every_reason_and_refusal_is_plain_words():
    for text in (*bundle.REASONS.values(), *bundle.REFUSALS.values()):
        assert text[0].isupper() and text.endswith(".")
        assert not any(w in text for w in ("zipfile", "BadZip", "utf-8", "xlsx_", "reader", "refdata"))


# -- the sorting agrees with the upload path ----------------------------------------------------------------------

def test_the_sheet_rule_is_the_reading_steps_rule():
    for section in SECTIONS:
        for r in readers_for(section):
            for sheet in (None, "Sales Report", "Invoices", "9999", "Other"):
                table = read_table(amazon.b2c_good(), "x.csv")
                table = type(table)(table.filename, table.checksum_sha256, sheet, table.rows)
                assert bundle._sheet_ok(r, table) == reading._sheet_ok(r, table)


def test_the_same_bundle_classifies_the_same_every_time():
    entries = [("a.csv", amazon.b2c_good()), ("f.xlsx", flipkart.good()), ("p.pdf", REPORTS["own_invoices_pdf"])]
    assert sort(entries) == sort(entries)
