"""Documents issued, Table 13 of GSTR-1 (issue #353, docs/TABLE13_SPEC.md), under /api/v1/b/{business_id}.

GET shows the rows for a return: the series derived from its documents with the person's earlier edits laid over them, and
whether a confirmation stands for the return as it is now. PUT confirms the rows as the next version (insert-only; the same
confirmation again returns the same version). `returns.prepare` is needed for both. The instance id comes from the path and is
checked by RLS and by the lookup, so another business's return is the same 404 as an unknown one.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW

from . import table13
from .api import _instance_or_404
from .build import build_return

router = APIRouter(prefix="/b/{business_id}", tags=["filing"])
PREPARE = [Depends(require(Permission.RETURNS_PREPARE))]
Source = Literal["own_live", "uploaded_own", "marketplace", "manual"]
Count = Annotated[int, Field(ge=0, le=99_999_999)]
Number = Annotated[str, Field(min_length=1, max_length=table13.MAX_LEN)]


class DocRowOut(BaseModel):
    nature: int
    nature_label: str
    from_no: str
    to_no: str
    total_issued: int  # every number issued in the range, cancelled ones included
    cancelled: int
    net_issue: int
    source: Source
    counted: bool
    manual: bool  # from and to may be edited only on a manual row
    missing: int  # numbers inside the range that no document of ours has: enter them as cancelled or confirm a smaller total
    needs_ca_check: bool  # a marketplace series: whether it counts in the seller's Table 13 is a CA question


class Table13Out(BaseModel):
    instance_id: str
    applies: bool  # only a GSTR-1 carries Table 13
    required: bool  # Tables 4 to 10 hold data, so the portal will not generate the summary without it
    confirmed: bool  # a confirmation stands for the return as it is now
    stale: bool  # confirmed once, but the documents in the period have changed since: confirm again
    version: int | None
    confirmed_at: datetime | None
    fingerprint: str
    rows: list[DocRowOut]


class DocRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nature: Annotated[int, Field(ge=min(table13.NATURES), le=max(table13.NATURES))]
    from_no: Number
    to_no: Number
    total_issued: Count
    cancelled: Count
    counted: bool = True
    manual: bool = False


class Table13In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: Annotated[list[DocRowIn], Field(max_length=500)]


def _out(uow: BusinessUoW, inst, build, rows, last) -> Table13Out:
    standing = last is not None and last.fingerprint == build.fingerprint
    return Table13Out(
        instance_id=str(inst.id), applies=inst.form == "GSTR1", required=inst.form == "GSTR1" and table13.has_data(build),
        confirmed=standing, stale=last is not None and not standing, version=None if last is None else last.version,
        confirmed_at=None if last is None else last.at, fingerprint=build.fingerprint,
        rows=[DocRowOut(nature=r.nature, nature_label=table13.NATURES[r.nature], from_no=r.from_no, to_no=r.to_no,
                        total_issued=r.total, cancelled=r.cancelled, net_issue=r.net_issue, source=r.source, counted=r.counted,
                        manual=r.source == "manual", missing=r.missing, needs_ca_check=r.source == "marketplace")
              for r in rows],
    )  # fmt: skip


@router.get("/returns/{instance_id}/table13", dependencies=PREPARE)
def get_table13(instance_id: str, uow: BusinessUoW) -> Table13Out:
    inst = _instance_or_404(uow, instance_id)
    build = build_return(uow.tx, inst)
    last = table13.latest(uow.tx, inst.id)
    rows = table13.working_rows(table13.suggest(build.lines), last) if inst.form == "GSTR1" else []
    return _out(uow, inst, build, rows, last)


@router.put("/returns/{instance_id}/table13", dependencies=PREPARE)
def put_table13(instance_id: str, body: Table13In, uow: BusinessUoW) -> Table13Out:
    inst = _instance_or_404(uow, instance_id)
    build = build_return(uow.tx, inst)
    sent = [(table13.DocRow(r.nature, r.from_no, r.to_no, r.total_issued, r.cancelled, "manual", r.counted), r.manual)
            for r in body.rows]  # fmt: skip
    last, _ = table13.confirm(uow, inst, build, sent)
    return _out(uow, inst, build, table13.working_rows(table13.suggest(build.lines), last), last)
