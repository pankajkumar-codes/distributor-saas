"""Planted for AC-13: tax numbers and dates written into code."""

from datetime import date
from decimal import Decimal

GST_RATE = Decimal("0.18")
B2CL_THRESHOLD = 250000
RATE_CUT = date(2025, 9, 22)
FILING_START = "2017-07-01"
PAISE = Decimal("0.01")  # allowed: the rounding quantum
