"""Turn records into an Excel (.xlsx) file, using only the standard library.

An .xlsx file is a zip of XML files. This writes the minimum Excel, LibreOffice and
Google Sheets need: one sheet "Log" with a bold, frozen header row, a filter, column
widths, real dates and durations as numbers. Text is stored as-is, so any language works.
"""
import io
import re
import zipfile
from datetime import date
from xml.sax.saxutils import escape

COLUMNS = [("Date", 12), ("Time", 8), ("Duration", 10), ("Project", 18), ("Description", 70)]
EXCEL_EPOCH = date(1899, 12, 30)
ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

# Cell styles: 0 = normal, 1 = bold header, 2 = date shown as yyyy-mm-dd.
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _text(ref, value, style=0):
    value = escape(ILLEGAL_XML.sub("", value))
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t xml:space="preserve">{value}</t></is></c>'


def _number(ref, value, style=0):
    style_attr = f' s="{style}"' if style else ""
    return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'


def records_to_xlsx(records):
    """Return .xlsx bytes with one row per record: Date, Time, Duration, Project, Description."""
    last_row = len(records) + 1
    rows = ['<row r="1">' + "".join(_text(f"{col}1", name, 1)
                                     for col, (name, _) in zip("ABCDE", COLUMNS)) + "</row>"]
    for n, r in enumerate(records, 2):
        serial = (date.fromisoformat(r["date"]) - EXCEL_EPOCH).days
        rows.append(f'<row r="{n}">' + _number(f"A{n}", serial, 2) + _text(f"B{n}", r["time"])
                    + _number(f"C{n}", r["minutes"]) + _text(f"D{n}", r["project"])
                    + _text(f"E{n}", r["description"]) + "</row>")
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                   for i, (_, w) in enumerate(COLUMNS, 1))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0">'
             '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
             '</sheetView></sheetViews>'
             f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData>'
             f'<autoFilter ref="A1:E{last_row}"/></worksheet>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Log" sheetId="1" r:id="rId1"/></sheets>'
                '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
                f"Log!$A$1:$E${last_row}</definedName></definedNames></workbook>")

    parts = [("[Content_Types].xml", CONTENT_TYPES), ("_rels/.rels", ROOT_RELS),
             ("xl/workbook.xml", workbook), ("xl/_rels/workbook.xml.rels", WORKBOOK_RELS),
             ("xl/styles.xml", STYLES), ("xl/worksheets/sheet1.xml", sheet)]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts:
            # Fixed timestamp: the same records always give the same bytes.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()
