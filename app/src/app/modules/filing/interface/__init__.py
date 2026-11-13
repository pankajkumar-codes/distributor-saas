"""What other modules may use from filing (LLD-5 §12). S6 groundwork: the supply-line
shape sales produces for a finalized document, and the GSTR-1 section builder."""

from ..periods import DocumentRef, PeriodLocked, ReturnInstance, assert_period_open, target_return_instance
from ..gstr1 import Amounts, BadSupplyLine, Gstr1Sections, SupplyLine, build_sections, reconciliation_gap

__all__ = [
    "Amounts",
    "BadSupplyLine",
    "DocumentRef",
    "Gstr1Sections",
    "PeriodLocked",
    "ReturnInstance",
    "SupplyLine",
    "assert_period_open",
    "build_sections",
    "reconciliation_gap",
    "target_return_instance",
]
