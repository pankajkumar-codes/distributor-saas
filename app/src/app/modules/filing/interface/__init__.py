"""What other modules may use from filing (LLD-5 §12). S6 groundwork: the supply-line
shape sales produces for a finalized document, and the GSTR-1 section builder."""

from ..build import CaFlag, ReturnBuild, build_return
from ..checks import Finding, run_checks
from ..periods import (
    DocumentRef,
    PeriodLocked,
    ReturnInstance,
    assert_period_open,
    ensure_instances,
    instances_between,
    target_return_instance,
)
from ..entitlement import invoicing_allowed, set_invoice_check
from .. import plans
from ..plans import FREE_INVOICES, GST_NOTE, INVOICING, prorated_change
from ..gstr1 import Amounts, BadSupplyLine, Gstr1Sections, SupplyLine, build_sections, reconciliation_gap

def free_for_now() -> bool:
    """True while payments are a placeholder (D-074): nothing is charged and no plan is required."""
    return plans.FREE_FOR_NOW


__all__ = [
    "FREE_INVOICES",
    "GST_NOTE",
    "INVOICING",
    "free_for_now",
    "invoicing_allowed",
    "plans",
    "set_invoice_check",
    "prorated_change",
    "Amounts",
    "BadSupplyLine",
    "CaFlag",
    "DocumentRef",
    "Finding",
    "Gstr1Sections",
    "PeriodLocked",
    "ReturnBuild",
    "ReturnInstance",
    "SupplyLine",
    "assert_period_open",
    "build_return",
    "build_sections",
    "ensure_instances",
    "instances_between",
    "reconciliation_gap",
    "run_checks",
    "target_return_instance",
]
