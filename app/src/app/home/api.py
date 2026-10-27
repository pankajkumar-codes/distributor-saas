"""GET /api/v1/b/{business_id}/home (LLD-1 §10): any member, one read-only unit of work.

Each part is computed on its own and is null until its slice fills it (filing S7, hub
S4, insights S6), so the reply never changes shape. The setup checklist's items follow
M3's order; first_product and first_customer stay not done until catalog's
setup_counts exists (LLD-3).
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.business import interface as business
from app.modules.identity import interface as identity
from platform_common.uow import BusinessUoW

router = APIRouter(tags=["home"])

# Item -> the SPA screen that completes it, under /b/{business_id}. settings/filing,
# products, customers and settings/team are the screens later slices add (LLD-3, LLD-5).
HREFS = {
    "business_profile": "/settings/company",
    "filing_frequency": "/settings/filing",
    "marketplaces": "/onboarding/marketplaces",
    "first_product": "/products",
    "first_customer": "/customers",
    "invite_ca_or_teammate": "/settings/team",
}


class ChecklistItem(BaseModel):
    key: str
    done: bool
    href: str


class Checklist(BaseModel):
    done: int
    total: int
    items: list[ChecklistItem]


class HomeOut(BaseModel):
    greeting_name: str | None
    checklist: Checklist
    filing: dict[str, Any] | None  # S7 (LLD-5 return_status_for_home)
    hub: dict[str, Any] | None  # S4
    insights: dict[str, Any] | None  # S6
    attention: list[dict[str, Any]]


@router.get("/b/{business_id}/home")
def home(uow: BusinessUoW) -> HomeOut:
    uow.become_read_only()
    setup = business.setup_state(uow.tx)
    done = {
        "business_profile": setup.profile_complete,
        "filing_frequency": setup.frequency_set,
        "marketplaces": setup.marketplaces_answered,
        "first_product": False,
        "first_customer": False,
        "invite_ca_or_teammate": identity.team_started(uow.tx),
    }
    base = f"/b/{uow.principal.business_id}"
    items = [ChecklistItem(key=k, done=done[k], href=base + href) for k, href in HREFS.items()]
    return HomeOut(
        greeting_name=identity.greeting_name(uow.tx),
        checklist=Checklist(done=sum(i.done for i in items), total=len(items), items=items),
        filing=None,
        hub=None,
        insights=None,
        attention=[],
    )
