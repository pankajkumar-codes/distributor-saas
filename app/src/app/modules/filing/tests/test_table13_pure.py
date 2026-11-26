"""Table 13 (documents issued) without a database: the series suggested from documents, the checks of a row, and the JSON
(docs/TABLE13_SPEC.md sections 4 and 6, issue #353). The figures are made up; the file layout is the real tool file's."""

import json
from types import SimpleNamespace

import pytest

from app.modules.filing import export_model as em
from app.modules.filing import render_json as rj
from app.modules.filing import snapshots, table13
from app.modules.filing.checks import c08_documents_issued
from app.modules.filing.table13 import DocRow

from .test_render_json_pure import build_of
from .test_gstr1_sections import PART_A as LINES


def docs_of(*numbers, kind="invoice", live=False):
    return [SimpleNamespace(doc_kind=kind, doc_number=n, source_ref=n if live else f"f.xlsx row {i}")
            for i, n in enumerate(numbers, 2)]  # fmt: skip


def row(nature, a, b, total, cancelled=0, source="manual", counted=True):
    return DocRow(nature, a, b, total, cancelled, source, counted)


# -- Suggestions -------------------------------------------------------------------------------------------------


def test_a_series_with_one_number_missing_counts_the_numbers_found_and_says_how_many_are_missing():
    nums = [f"INV/26-27/{n:04d}" for n in (1, 2, 3, 4, 5, 6, 8)]
    (r,) = table13.suggest(docs_of(*nums))
    assert (r.nature, r.from_no, r.to_no, r.total, r.cancelled, r.net_issue) == (1, "INV/26-27/0001", "INV/26-27/0008", 7, 0, 7)
    assert r.missing == 1 and r.source == "uploaded_own" and r.counted


def test_lines_of_one_document_count_once_and_credit_notes_are_their_own_nature():
    out = table13.suggest(docs_of("A-1", "A-1", "A-2") + docs_of("CN-1", kind="credit_note"))
    assert [(r.nature, r.from_no, r.to_no, r.total) for r in out] == [(1, "A-1", "A-2", 2), (5, "CN-1", "CN-1", 1)]


def test_an_invoice_cancelled_in_the_app_counts_in_total_and_cancelled_not_net_issue():  # #456
    from app.modules.filing.build import CancelledDoc

    nums = [f"INV/26-11/{n:06d}" for n in (1, 3)]
    (r,) = table13.suggest(docs_of(*nums, live=True), [CancelledDoc("invoice", "INV/26-11/000002")])
    assert (r.from_no, r.to_no, r.total, r.cancelled, r.net_issue, r.missing) == (
        "INV/26-11/000001", "INV/26-11/000003", 3, 1, 2, 0)
    assert r.source == "own_live"
    # A return holding only a cancelled invoice still lists its series.
    (only,) = table13.suggest([], [CancelledDoc("invoice", "INV/26-11/000004")])
    assert (only.total, only.cancelled, only.net_issue) == (1, 1, 0)


def test_two_prefixes_and_two_digit_widths_are_separate_series():
    out = table13.suggest(docs_of("A-001", "A-002", "B-001", "A-0003"))
    assert [(r.from_no, r.to_no, r.total) for r in out] == [("A-0003", "A-0003", 1), ("A-001", "A-002", 2), ("B-001", "B-001", 1)]


def test_the_range_runs_by_the_number_in_the_text_not_by_the_text():
    (r,) = table13.suggest(docs_of("INV-2", "INV-9", "INV-5"))
    assert (r.from_no, r.to_no, r.total, r.missing) == ("INV-2", "INV-9", 3, 5)  # 2 to 9 is 8 numbers, 3 found


def test_a_series_made_only_of_live_documents_says_so_and_a_debit_note_is_left_out():
    out = table13.suggest(docs_of("INV-1", "INV-2", live=True) + docs_of("DN-1", kind="debit_note"))
    assert [(r.source, r.total) for r in out] == [("own_live", 2)]


def test_nothing_to_suggest_for_no_documents():
    assert table13.suggest([]) == []


# -- The checks of a row -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows",
    [
        [row(13, "A-1", "A-2", 2)],
        [row(1, "", "A-2", 2)],
        [row(1, "A-1", "A" * 17, 2)],
        [row(1, "A#1", "A#2", 2)],
        [row(1, "A-1", "A-2", 2, 3)],
        [row(1, "A-1", "A-2", -1)],
        [row(1, "A-2", "A-1", 1)],
        [row(1, "A-1", "B-2", 2)],
        [row(1, "A-01", "A-100", 2)],
        [row(1, "A-1", "A-2", 3)],
        [row(1, "A-1", "A-5", 5), row(1, "A-5", "A-9", 5)],
        [row(1, "A-1", "A-5", 5), row(5, "A-3", "A-9", 5)],
    ],
)
def test_a_row_that_breaks_a_check_is_refused_with_a_reason(rows):
    with pytest.raises(table13.RowInvalid) as e:
        table13.validate(rows)
    assert str(e.value)


def test_good_rows_pass_and_a_number_may_follow_in_another_series():
    table13.validate([row(1, "A-1", "A-5", 5, 1), row(1, "A-6", "A-9", 4), row(1, "B-1", "B-1", 1), row(5, "CN/1", "CN/2", 2)])
    table13.validate([row(6, "RV-1", "RV-1", 1)])


def test_the_two_natures_message_names_the_problem():
    with pytest.raises(table13.RowInvalid, match="two kinds"):
        table13.validate([row(1, "A-1", "A-5", 5), row(5, "A-3", "A-9", 5)])


# -- Working rows ------------------------------------------------------------------------------------------------


def test_earlier_edits_lie_over_the_suggestions_and_manual_rows_stay():
    sug = table13.suggest(docs_of("A-1", "A-2", "A-3"))
    last = SimpleNamespace(rows=(row(1, "A-1", "A-3", 3, 1, "uploaded_own", False), row(6, "RV-1", "RV-2", 2)))
    out = table13.working_rows(sug, last)
    assert [(r.nature, r.total, r.cancelled, r.counted, r.source) for r in out] == [
        (1, 3, 1, False, "uploaded_own"), (6, 2, 0, True, "manual")]  # fmt: skip
    # a suggestion that moved (a number added) starts again rather than keeping a stale edit
    moved = table13.suggest(docs_of("A-1", "A-2", "A-3", "A-4"))
    assert table13.working_rows(moved, last)[0].cancelled == 0


# -- The file ----------------------------------------------------------------------------------------------------

REAL_FILE_SHAPE = (
    '{"flag":"N","doc_det":[{"docs":[{"cancel":0,"num":1,"totnum":5,"from":"AB-001","to":"AB-005","net_issue":5},'
    '{"cancel":1,"num":2,"totnum":4,"from":"AB-006","to":"AB-009","net_issue":3}],"doc_num":1},'
    + ",".join(f'{{"docs":[],"doc_num":{n}}}' for n in (2, 3, 4))
    + ',{"docs":[{"cancel":0,"num":1,"totnum":2,"from":"CN-001","to":"CN-002","net_issue":2}],"doc_num":5},'
    + ",".join(f'{{"docs":[],"doc_num":{n}}}' for n in range(6, 13))
    + "]}"
)
ROWS = (row(1, "AB-001", "AB-005", 5), row(1, "AB-006", "AB-009", 4, 1), row(5, "CN-001", "CN-002", 2))


def render(docs, **kw):
    return rj.render_json(em.export_model(build_of(LINES), docs), **kw)


def test_table_13_is_written_like_the_real_file_between_hsn_and_the_end():
    text = render(ROWS).decode()
    assert f'"doc_issue":{REAL_FILE_SHAPE}' in text
    keys = list(json.loads(text))
    assert keys.index("hsn") < keys.index("doc_issue") == len(keys) - 1  # fil_dt is left out unless asked for
    assert '"chksum"' not in text.split('"doc_issue"')[1]


def test_without_confirmed_rows_no_doc_issue_is_written_and_the_options_apply():
    assert "doc_issue" not in json.loads(render(()))
    placeholder = render(ROWS, options=rj.Options(chksum="placeholder")).decode().split('"doc_issue"')[1]
    assert '"chksum":"0000' in placeholder
    flagless = json.loads(render(ROWS, options=rj.Options(flags=False)))["doc_issue"]
    assert "flag" not in flagless and len(flagless["doc_det"]) == 12


def test_net_issue_is_total_minus_cancelled_on_every_row_and_nothing_is_a_float():
    doc = json.loads(render(ROWS))["doc_issue"]
    rows = [d for slot in doc["doc_det"] for d in slot["docs"]]
    assert all(d["net_issue"] == d["totnum"] - d["cancel"] for d in rows)
    assert all(type(v) is int for d in rows for k, v in d.items() if k not in ("from", "to"))


def test_table_13_rows_count_toward_the_line_limit_and_go_once_in_the_last_file():
    model = em.export_model(build_of(LINES), ROWS)
    base = em.rows_in(em.export_model(build_of(LINES)))
    assert em.rows_in(model) == base + 3
    parts = em.split(model, base)  # one row too few for everything in one file
    assert len(parts) > 1
    assert [p.docs for p in parts].count(ROWS) == 1 and parts[-1].docs == ROWS


def test_a_snapshot_reproduces_the_rows_after_the_summaries():
    out = snapshots.rows_of(build_of(LINES).sections, ROWS)
    docs = [r for r in out if r["section"] == "docs"]
    assert [(r["nature"], r["from_no"], r["to_no"], r["total_count"], r["cancelled_count"]) for r in docs] == [
        (1, "AB-001", "AB-005", 5, 0), (1, "AB-006", "AB-009", 4, 1), (5, "CN-001", "CN-002", 2, 0)]  # fmt: skip
    assert out[-3:] == docs and [r["row_no"] for r in out] == list(range(1, len(out) + 1))


# -- C-08 over a build, with the store replaced ------------------------------------------------------------------


def test_c08_needs_data_in_tables_4_to_10_a_gstr1_and_counted_rows_for_this_build(monkeypatch):
    b = build_of(LINES)
    monkeypatch.setattr(table13, "counted_rows", lambda tx, build: ())
    (f,) = c08_documents_issued(None, b)
    assert f.code == "C-08" and f.level == "block" and not f.needs_ca_check and "Table 13" in f.message
    monkeypatch.setattr(table13, "counted_rows", lambda tx, build: ROWS)
    assert c08_documents_issued(None, b) == []
    monkeypatch.setattr(table13, "counted_rows", lambda tx, build: ())
    assert c08_documents_issued(None, build_of([])) == []  # a nil return needs no Table 13
    assert c08_documents_issued(None, SimpleNamespace(instance=SimpleNamespace(form="IFF"), sections=b.sections)) == []
