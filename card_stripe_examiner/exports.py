"""Spreadsheet export and issuer packet. Files are written only where the examiner chooses."""

from __future__ import annotations

import csv
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from card_stripe_examiner.bin_lookup import BinResult, clean_country, prompt_digits
from card_stripe_examiner.parse import expiration_display, format_pan, list_brand, luhn_label
from card_stripe_examiner.report import (
    LINE,
    ROW,
    Destination,
    _header_painter,
    numbered_canvas,
    _clock,
    _escape,
    _register_fonts,
    _styles,
    mask_pan,
)
from card_stripe_examiner.session import (
    FACE_TYPES,
    PRINTED_NAMES,
    CaseSession,
    card_findings,
    card_label,
    duplicates_for,
    normalize_face,
    normalize_printed,
    printed_summary,
)

CSV_COLUMNS = (
    "Exhibit",
    "Swiped at",
    "Card type",
    "Stripe format",
    "Brand",
    "Account",
    "BIN",
    "Name on stripe",
    "Expiration",
    "Expired",
    "Service code",
    "Luhn",
    "Tracks read",
    "Track read errors",
    "Tracks differ",
    "Printed account",
    "Printed name",
    "Printed expiration",
    "Issuing bank",
    "Bank country",
    "Card kind",
    "Prepaid",
    "Lookup source",
    "Same account or swipe as",
    "Findings",
    "Examiner note",
)


def _safe_cell(value) -> str:
    """Keep spreadsheet programs from treating a value as a formula."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _account(pan: str | None, mask: bool) -> str:
    if not pan:
        return ""
    return mask_pan(pan) if mask else pan


def _printed(card, name: str, mask: bool) -> str:
    data = normalize_printed(card.printed)
    if data["matches"]:
        return "Matches the stripe"
    label = PRINTED_NAMES[name]
    rows = dict(printed_summary(card, mask_pan if mask else None))
    return rows.get(label, "")


def _bank(card) -> BinResult | None:
    if not card.bin_lookup:
        return None
    return BinResult.from_dict(card.bin_lookup)


def csv_rows(session: CaseSession, mask: bool = False) -> list[list[str]]:
    rows: list[list[str]] = []
    for card in session.cards:
        parsed = card.view()
        bank = _bank(card)
        found = bank is not None and not bank.error
        prepaid = "" if not found or bank.prepaid is None else ("Yes" if bank.prepaid else "No")
        duplicates = "; ".join(duplicates_for(session, card))
        row = [
            card_label(session, card),
            card.swiped_at.replace("T", " "),
            FACE_TYPES[normalize_face(card.face_type)],
            parsed.card_type,
            list_brand(parsed),
            _account(parsed.pan, mask),
            prompt_digits(parsed.pan) or "",
            parsed.name_on_stripe or "",
            parsed.expiration_display or "",
            "" if parsed.expired is None else ("Yes" if parsed.expired else "No"),
            parsed.service_code or "",
            luhn_label(parsed.luhn),
            ", ".join(parsed.tracks_present),
            ", ".join(parsed.tracks_read_error),
            "Yes" if parsed.comparison.tracks_differ else "No",
            _printed(card, "account", mask),
            _printed(card, "name", mask),
            _printed(card, "expiration", mask),
            (bank.bank_name or "") if found else (bank.error if bank else "Not looked up"),
            (clean_country(bank.country) or "") if found else "",
            (bank.card_kind or "") if found else "",
            prepaid,
            bank.source_text() if bank else "",
            duplicates,
            "; ".join(card_findings(card, session)),
            card.note,
        ]
        rows.append([_safe_cell(value) for value in row])
    return rows


def write_csv(session: CaseSession, path: str | Path, mask: bool = False) -> int:
    """One row per card. UTF-8 with a byte-order mark so Excel opens it correctly."""
    rows = csv_rows(session, mask)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return len(rows)


UNIDENTIFIED = "Issuer not identified"


def issuer_groups(session: CaseSession) -> list[tuple[str, BinResult | None, list]]:
    """Cards grouped by issuing bank. Unidentified cards come last."""
    groups: dict[str, tuple[BinResult | None, list]] = {}
    for card in session.cards:
        parsed = card.view()
        if not parsed.pan:
            continue
        bank = _bank(card)
        if bank is not None and not bank.error and bank.bank_name:
            key = bank.bank_name.strip()
        else:
            key = UNIDENTIFIED
            bank = None
        if key not in groups:
            groups[key] = (bank, [])
        groups[key][1].append(card)
    named = sorted((key for key in groups if key != UNIDENTIFIED), key=str.lower)
    ordered = [(key, groups[key][0], groups[key][1]) for key in named]
    if UNIDENTIFIED in groups:
        ordered.append((UNIDENTIFIED, None, groups[UNIDENTIFIED][1]))
    return ordered


def _key_findings(card, session: CaseSession) -> str:
    keep = []
    for item in card_findings(card, session):
        lowered = item.lower()
        if lowered.startswith(("luhn pass", "track 1 and track 2", "track 3 is present", "luhn not applicable")):
            if "differ" not in lowered:
                continue
        keep.append(item)
    return "\n".join(keep) or "—"


def _cards_table(session: CaseSession, cards: list, styles, mask: bool) -> Table:
    header = [
        Paragraph(text, styles["cellBold"])
        for text in ("Exhibit", "Account", "Name on stripe", "Expiration", "Swiped", "Findings")
    ]
    rows = [header]
    for card in cards:
        parsed = card.view()
        account = mask_pan(parsed.pan) if mask else format_pan(parsed.pan)
        rows.append(
            [
                Paragraph(_escape(card_label(session, card)), styles["cell"]),
                Paragraph(_escape(account or "—"), styles["cell"]),
                Paragraph(_escape(parsed.name_on_stripe or "—"), styles["cell"]),
                Paragraph(_escape(expiration_display(parsed.expiration) or "—"), styles["cell"]),
                Paragraph(_escape(_clock(card.swiped_at)), styles["cell"]),
                Paragraph(_escape(_key_findings(card, session)).replace("\n", "<br/>"), styles["cell"]),
            ]
        )
    table = Table(rows, colWidths=[52, 108, 90, 52, 70, 148], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ROW),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
            ]
        )
    )
    return table


def _unidentified_note(cards: list) -> str:
    bins = sorted({prompt_digits(card.view().pan) or "—" for card in cards})
    return "No issuing bank was identified for these cards. BINs: " + ", ".join(bins)


def build_packet(session: CaseSession, mask: bool = False) -> list:
    body, bold, mono = _register_fonts()
    styles = _styles(body, bold, mono)
    groups = issuer_groups(session)
    story: list = [
        Spacer(1, 8),
        Destination("packet", "Issuer packet", 0, closed=False),
        Paragraph("Issuer packet", styles["h1"]),
        Paragraph(
            _escape(
                "  ·  ".join(
                    part
                    for part in (f"Case {session.case_number}", session.examiner, session.unit)
                    if part
                )
            ),
            styles["meta"],
        ),
        Paragraph(
            "Cards in this case grouped by issuing bank, for use with a records request or legal process. "
            "Bank names come from a BIN directory, not from the bank.",
            styles["note"],
        ),
        Paragraph("Banks", styles["section"]),
    ]
    summary = [[Paragraph("Issuing bank", styles["cellBold"]), Paragraph("Cards", styles["cellBold"])]]
    for name, _bank_result, cards in groups:
        summary.append([Paragraph(_escape(name), styles["cell"]), Paragraph(str(len(cards)), styles["cell"])])
    if len(summary) == 1:
        summary.append([Paragraph("No cards with an account number.", styles["cell"]), Paragraph("", styles["cell"])])
    table = Table(summary, colWidths=[420, 90], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ROW),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
            ]
        )
    )
    story.append(table)
    for index, (name, bank, cards) in enumerate(groups, start=1):
        story.extend(
            [
                PageBreak(),
                Destination(f"bank-{index}", name, 1, closed=True),
                Paragraph(_escape(name), styles["h1"]),
                Paragraph(_escape(f"{len(cards)} card{'s' if len(cards) != 1 else ''} in case {session.case_number}"), styles["meta"]),
            ]
        )
        if bank is None:
            story.append(Paragraph(_escape(_unidentified_note(cards)), styles["note"]))
        story.extend(
            [
                Paragraph("Accounts", styles["section"]),
                _cards_table(session, cards, styles, mask),
            ]
        )
    return story


def write_issuer_packet(session: CaseSession, path: str | Path, mask: bool = False) -> int:
    body, _bold, _mono = _register_fonts()
    footer = "Account numbers are masked" if mask else "Sensitive: contains full account numbers"
    document = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=64,
        bottomMargin=46,
        title=f"Issuer packet — {session.case_number}",
        author=session.examiner or "Card Stripe Examiner",
    )
    header = _header_painter(session, "Card Stripe Analysis — Issuer packet")
    document.build(
        build_packet(session, mask),
        onFirstPage=header,
        onLaterPages=header,
        canvasmaker=numbered_canvas(body, footer),
    )
    return len(issuer_groups(session))


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xml(text: str) -> str:
    cleaned = "".join(
        character
        for character in text
        if character in "\t\n\r" or ord(character) >= 0x20
    )
    return (
        cleaned.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_xlsx(session: CaseSession, path: str | Path, mask: bool = False) -> int:
    """Excel workbook with every value stored as text, so long account numbers keep all their digits."""
    import zipfile

    rows = [list(CSV_COLUMNS)] + [
        [value[1:] if value.startswith("'") else value for value in row] for row in csv_rows(session, mask)
    ]
    widths = []
    for column in range(len(CSV_COLUMNS)):
        longest = max(len(line) for row in rows for line in (row[column] or " ").splitlines() or [" "])
        widths.append(min(60, max(10, longest + 2)))
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        style = ' s="1"' if row_index == 1 else ' s="2"'
        cells = "".join(
            f'<c r="{_column_name(column)}{row_index}" t="inlineStr"{style}><is><t xml:space="preserve">{_xml(value)}</t></is></c>'
            for column, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{row_index}">{cells}</row>')
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    last = f"{_column_name(len(CSV_COLUMNS) - 1)}{len(rows)}"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{columns}</cols><sheetData>{''.join(sheet_rows)}</sheetData>"
        f'<autoFilter ref="A1:{last}"/></worksheet>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF4"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyNumberFormat="1"/>'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
    title = _xml(f"Case {session.case_number}")[:31] or "Cards"
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="Cards" sheetId="1" r:id="rId1"/></sheets>'
        '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
        f"Cards!$A$1:${_column_name(len(CSV_COLUMNS) - 1)}${len(rows)}</definedName></definedNames></workbook>"
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            "</Relationships>"
        ),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{title}</dc:title><dc:creator>{_xml(session.examiner or 'Card Stripe Examiner')}</dc:creator>"
            "</cp:coreProperties>"
        ),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": styles,
        "xl/worksheets/sheet1.xml": sheet,
    }
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return len(rows) - 1
