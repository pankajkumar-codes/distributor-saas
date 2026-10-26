"""Planted for AC-13: filing reads sales' table directly."""

DIRECT = "select number, total from sales.invoices where business_id = :b"
VIEW_IS_FINE = "select number from sales.v_invoices_for_filing where business_id = :b"
FUNCTION_IS_FINE = "select * from sales.invoices_for_period(:b, :p)"
