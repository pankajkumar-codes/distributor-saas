"""The invoice computation (LLD-4 §3, L4-1). S4-b calls
`compute(load_inputs(tx, draft, lines, today=...))` on every draft save and inside
finalize, and stores exactly what it returns. `compute` is pure; `load_inputs` does the
interface reads.
"""

from .core import compute
from .model import (
    METHOD_VERSION,
    Buyer,
    ComputeInput,
    Computation,
    DraftIn,
    DraftLineIn,
    Issue,
    LineIn,
    LineOut,
    Rules,
    Seller,
    Tax,
)
from .words import inr

__all__ = [
    "METHOD_VERSION",
    "Buyer",
    "ComputeInput",
    "Computation",
    "DraftIn",
    "DraftLineIn",
    "Issue",
    "LineIn",
    "LineOut",
    "Rules",
    "Seller",
    "Tax",
    "compute",
    "inr",
]
