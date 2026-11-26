"""The demo business's ready-made customers and products (local demo only; demo/seed.py adds them).

Everything here is made up so a tester has something to pick on a new invoice without typing it first.
The GSTINs use invented PANs (DEMO...) with a correctly computed check character, so the app accepts
them; they belong to nobody. Names say "(made up)" so nobody mistakes them for a real party.

HSN codes, GST rates and units are picked to give a spread of cases to test, not as tax advice: which
HSN or rate fits a real product is the business's and its CA's call. Every rate is one refdata lists
as a GST rate from RATE_FROM (gst.rate_values; 12% and 28% are no longer on that list).
"""

RATE_FROM = "2026-02-01"  # the start of the current gst.rate_values row, so every rate below is accepted

# Each one tests a different place-of-supply / registration case. Codes are refdata state codes.
CUSTOMERS = [
    {   # B2B, same state as the demo business (WB 19): CGST + SGST
        "name": "Demo Retail Kolkata (made up)",
        "gstin": "19DEMOC1111C1Z7",
        "billing": {"line1": "12 Demo Lane", "city": "Kolkata", "pin": "700012", "state_code": "19"},
        "credit_days": 15,
    },
    {   # B2B, another state (Maharashtra 27): IGST
        "name": "Demo Wholesale Mumbai (made up)",
        "gstin": "27DEMOD2222D1Z1",
        "billing": {"line1": "4 Demo Market", "city": "Mumbai", "pin": "400001", "state_code": "27"},
        "credit_days": 30,
    },
    {   # B2C, unregistered, same state
        "name": "Demo Walk-in Buyer Howrah (made up)",
        "gstin": None,
        "billing": {"line1": "7 Demo Para", "city": "Howrah", "pin": "711101", "state_code": "19"},
    },
    {   # B2C, unregistered, another state (Bihar 10): large or small depending on the invoice value
        "name": "Demo Home Buyer Patna (made up)",
        "gstin": None,
        "billing": {"line1": "21 Demo Nagar", "city": "Patna", "pin": "800001", "state_code": "10"},
    },
    {   # B2B billed in Delhi (07) but delivered in West Bengal: Bill To and Ship To in different states
        "name": "Demo Distributor Delhi, ships to Siliguri (made up)",
        "gstin": "07DEMOE3333E1ZU",
        "billing": {"line1": "9 Demo Chowk", "city": "New Delhi", "pin": "110001", "state_code": "07"},
        "delivery_same_as_billing": False,
        "delivery": {"line1": "3 Demo Godown Road", "city": "Siliguri", "pin": "734001", "state_code": "19"},
        "credit_days": 45,
    },
]


def _taxable(rate):
    return {"tax_category": "taxable", "rate": {"rate": rate, "valid_from": RATE_FROM}}


# sale_rate is per unit, before GST, as a decimal string (never a float). mrp is per unit with GST included and
# required (D-106); each is chosen so MRP / (1 + GST%) gives back the sale rate, so a blank invoice rate shows the same figure.
PRODUCTS = [
    {"code": "DEMO-TSHIRT", "name": "Cotton T-shirt (demo)", "hsn": "6109", "uqc": "PCS", "sale_rate": "499.00", "mrp": "523.95",
     "barcode": "8900000000017", **_taxable("5")},                       # 4-digit HSN, 5%, has a barcode
    {"code": "DEMO-FABRIC", "name": "Cotton fabric by the metre (demo)", "hsn": "520811", "uqc": "MTR",
     "sale_rate": "120.75", "mrp": "126.79", **_taxable("5")},                            # 6-digit HSN, paise in the price
    {"code": "DEMO-CREAM", "name": "Face cream 50 g (demo)", "hsn": "33049910", "uqc": "NOS",
     "sale_rate": "350.00", "mrp": "413.00", **_taxable("18")},                           # 8-digit HSN, 18%
    {"code": "DEMO-HAMPER", "name": "Festive gift hamper (demo, no HSN)", "hsn": None, "uqc": "BOX",
     "sale_rate": "1499.00", "mrp": "1768.82", **_taxable("18")},                          # Missing HSN on purpose
    {"code": "DEMO-SODA", "name": "Aerated soft drink 750 ml (demo)", "hsn": "22021010", "uqc": "BTL",
     "sale_rate": "40.00", "mrp": "56.00", **_taxable("40")},                            # 40%
    {"code": "DEMO-RING", "name": "Gold ring, priced per gram (demo)", "hsn": "7113", "uqc": "GMS",
     "sale_rate": "6500.00", "mrp": "6695.00", **_taxable("3")},                           # 3%, weight unit
    {"code": "DEMO-CONSULT", "name": "Business consulting, per hour (demo service)", "hsn": "998311",
     "uqc": "OTH", "sale_rate": "2500.00", "mrp": "2950.00", **_taxable("18")},           # SAC (service code), 18%
    {"code": "DEMO-RICE", "name": "Loose rice (demo)", "hsn": "1006", "uqc": "KGS", "sale_rate": "62.50", "mrp": "62.50",
     "tax_category": "nil_rated"},                                       # nil-rated, no rate
    {"code": "DEMO-BOOK", "name": "Printed story book (demo)", "hsn": "4901", "uqc": "NOS", "sale_rate": "250.00", "mrp": "250.00",
     "tax_category": "exempt"},                                          # exempt, no rate
    {"code": "DEMO-DIESEL", "name": "Diesel (demo, outside GST)", "hsn": "2710", "uqc": "LTR",
     "sale_rate": "90.50", "mrp": "90.50", "tax_category": "non_gst"},                   # non-GST supply
]
