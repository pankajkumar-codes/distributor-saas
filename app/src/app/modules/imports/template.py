"""The own-invoice Excel template the seller downloads (R1-M5 slice 2; BRD GF-14).

Built in code from the reader's own column list (`readers.own_excel.COLUMNS`), so the headers can never drift
from what the reader expects: a test reads the generated workbook back through the reader. It holds no sample
values, no real names or numbers: an `Invoices` sheet with the header row, and a `How to fill` sheet that the
reader does not read. The plain-words list of what is not supported yet is here, next to the columns.
"""

import io

import openpyxl
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from .readers.own_excel import COLUMNS, DOC_TYPES, SHEET

HELP_SHEET = "How to fill"
FILE_NAME = "own-invoices-template.xlsx"
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HOW_TO = (
    "Fill one row for each line of each invoice, credit note or debit note. A document with three lines takes "
    "three rows that repeat its number, date and the other document details.",
    "Use your own GSTIN in the Seller GSTIN column on every row. A file with another GSTIN is not accepted.",
    "Type the buyer's GSTIN only when the buyer is GST-registered. Do not add columns for names, addresses or "
    "phone numbers: they are not read and not kept.",
    "Type the GST rate as a plain number, for example 18. Type tax amounts as printed on the document and leave a "
    "tax column blank when it was not charged.",
    "Do not rename or reorder the header row's titles on the Invoices sheet. Do not use formulas.",
    "A row we cannot place, for example a missing HSN or place of supply, is shown to you as held, with the reason. "
    "Nothing is filed from this sheet: it only fills your preview.",
)
NOT_SUPPORTED = (
    "Not supported yet. Do not enter any of these as ordinary rows; we need your CA's answer first:",
    "Exports, with or without payment of tax",
    "Supplies to a Special Economic Zone (SEZ)",
    "Supplies on which the buyer pays tax (reverse charge)",
    "Advances received before the supply",
    "Nil-rated, exempt or non-GST supplies, and any marking of them",
    "Sales made through an e-commerce operator, and the operator's GSTIN",
)


def build() -> bytes:
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = SHEET
    sheet.append([c.header for c in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, column in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = max(14, len(column.header) + 4)
    sheet.freeze_panes = "A2"
    doc_type = next(i for i, c in enumerate(COLUMNS, start=1) if c.header == "Document type")
    choices = DataValidation(type="list", formula1='"' + ",".join(DOC_TYPES.values()) + '"', allow_blank=False)
    sheet.add_data_validation(choices)
    letter = openpyxl.utils.get_column_letter(doc_type)
    choices.add(f"{letter}2:{letter}5000")

    guide = wb.create_sheet(HELP_SHEET)
    guide.column_dimensions["A"].width = 28
    guide.column_dimensions["B"].width = 90
    guide.append(["How to fill the Invoices sheet"])
    guide["A1"].font = Font(bold=True)
    for line in HOW_TO:
        guide.append([line])
    guide.append([])
    guide.append(["Column", "What to type"])
    guide.cell(row=guide.max_row, column=1).font = Font(bold=True)
    guide.cell(row=guide.max_row, column=2).font = Font(bold=True)
    for column in COLUMNS:
        guide.append([column.header, column.help])
    guide.append([])
    for index, line in enumerate(NOT_SUPPORTED):
        guide.append([line])
        if index == 0:
            guide.cell(row=guide.max_row, column=1).font = Font(bold=True)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
