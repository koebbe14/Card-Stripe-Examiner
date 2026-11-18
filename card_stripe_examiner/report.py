"""Case PDF report."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from card_stripe_examiner import __version__
from card_stripe_examiner.bin_lookup import BinResult, clean_country
from card_stripe_examiner.glossary import REPORT_TERMS
from card_stripe_examiner.parse import expiration_display, format_pan, last_four, list_brand, luhn_label, stripe_fields
from card_stripe_examiner.session import (
    FACE_TYPES,
    PHOTO_SIDES,
    PRINTED_FIELDS,
    CaseSession,
    card_findings,
    card_label,
    cards_for_report,
    compare_printed_field,
    face_findings,
    has_duplicates,
    normalize_face,
    normalize_printed,
    photo_path,
    printed_differs,
    printed_states,
)

SLATE = HexColor("#1B2838")
INK = HexColor("#1E293B")
MUTED = HexColor("#64748B")
LABEL = HexColor("#475569")
LINE = HexColor("#E2E8F0")
BORDER = HexColor("#CBD5E1")
ROW = HexColor("#E8EEF4")
LINK = HexColor("#1B4F72")
RED = HexColor("#B91C1C")
RED_TINT = HexColor("#FEF2F2")
AMBER = HexColor("#B45309")
AMBER_TINT = HexColor("#FFFBEB")
GREEN = HexColor("#0F766E")
GREEN_TINT = HexColor("#F0FDFA")
GREY_BOX = HexColor("#F8FAFC")
PAGE_WIDTH, PAGE_HEIGHT = letter
CONTENT_WIDTH = PAGE_WIDTH - 80 - 12  # page margins and the frame's own padding

_HEX = {"red": "#B91C1C", "amber": "#B45309", "green": "#0F766E", "muted": "#64748B", "ink": "#1E293B"}


@dataclass
class ReportOptions:
    include_glossary: bool = False
    include_raw: bool = True
    mask_accounts: bool = False
    differs_only: bool = False
    include_photos: bool = True


def _as_options(options: ReportOptions | bool | None) -> ReportOptions:
    if options is None:
        return ReportOptions()
    if isinstance(options, bool):
        return ReportOptions(include_glossary=options)
    return options


class Destination(Flowable):
    """Named destination and optional bookmark. Takes no page space."""

    def __init__(self, key: str, title: str | None = None, level: int = 0, closed: bool = True) -> None:
        super().__init__()
        self.key = key
        self.title = title
        self.level = level
        self.closed = closed

    def wrap(self, _avail_width, _avail_height):
        return (0, 0)

    def draw(self) -> None:
        self.canv.bookmarkPage(self.key)
        if self.title:
            self.canv.addOutlineEntry(self.title, self.key, level=self.level, closed=self.closed)


def _register_fonts() -> tuple[str, str, str]:
    regular = Path(r"C:\Windows\Fonts\segoeui.ttf")
    bold = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    mono = Path(r"C:\Windows\Fonts\consola.ttf")
    if regular.exists() and bold.exists() and mono.exists():
        if "Segoe" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("Segoe", str(regular)))
            pdfmetrics.registerFont(TTFont("Segoe-Bold", str(bold)))
            pdfmetrics.registerFont(TTFont("Consolas", str(mono)))
            # Link the bold face so <b> inside a paragraph uses Segoe UI Bold.
            registerFontFamily("Segoe", normal="Segoe", bold="Segoe-Bold", italic="Segoe", boldItalic="Segoe-Bold")
            registerFontFamily("Consolas", normal="Consolas", bold="Consolas", italic="Consolas", boldItalic="Consolas")
        return "Segoe", "Segoe-Bold", "Consolas"
    return "Helvetica", "Helvetica-Bold", "Courier"


def _styles(body: str, bold: str, mono: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=18, leading=22, textColor=SLATE, spaceAfter=6),
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=14, leading=18, textColor=SLATE, spaceAfter=4),
        "meta": ParagraphStyle("meta", fontName=body, fontSize=9, leading=13, textColor=INK),
        "note": ParagraphStyle("note", fontName=body, fontSize=9, leading=12, textColor=LABEL, spaceBefore=4),
        "section": ParagraphStyle(
            "section", fontName=bold, fontSize=11, leading=14, textColor=SLATE, spaceBefore=10, spaceAfter=4
        ),
        "label": ParagraphStyle("label", fontName=body, fontSize=8.5, leading=11.5, textColor=LABEL),
        "value": ParagraphStyle("value", fontName=body, fontSize=10, leading=13, textColor=INK),
        "valueBold": ParagraphStyle("valueBold", fontName=bold, fontSize=10, leading=13, textColor=INK),
        "mono": ParagraphStyle("mono", fontName=mono, fontSize=10, leading=13, textColor=INK),
        "small": ParagraphStyle("small", fontName=body, fontSize=8, leading=11, textColor=LABEL),
        "cell": ParagraphStyle("cell", fontName=body, fontSize=8.5, leading=11, textColor=INK),
        "cellMono": ParagraphStyle("cellMono", fontName=mono, fontSize=9, leading=12, textColor=INK),
        "cellBold": ParagraphStyle("cellBold", fontName=bold, fontSize=8.5, leading=11, textColor=SLATE),
        "boxTitle": ParagraphStyle("boxTitle", fontName=bold, fontSize=10, leading=13, textColor=SLATE),
        "finding": ParagraphStyle("finding", fontName=body, fontSize=9.5, leading=13, textColor=INK, leftIndent=10),
        "topic": ParagraphStyle("topic", fontName=bold, fontSize=10.5, leading=14, textColor=SLATE, spaceBefore=8),
        "body": ParagraphStyle("body", fontName=body, fontSize=9, leading=13, textColor=INK, alignment=TA_LEFT),
        "raw": ParagraphStyle("raw", fontName=mono, fontSize=8, leading=11, textColor=INK),
        "link": ParagraphStyle("link", fontName=body, fontSize=8, leading=11, textColor=LINK, spaceBefore=2),
    }


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _color(text: str, tone: str, bold: bool = False) -> str:
    inner = _escape(text)
    if bold:
        inner = f"<b>{inner}</b>"
    return f'<font color="{_HEX[tone]}">{inner}</font>'


def _clock(value: str) -> str:
    """One date format throughout: MM/DD/YYYY HH:MM."""
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%m/%d/%Y %H:%M")
    except (TypeError, ValueError):
        return value


def _wrap_raw(text: str, width: int = 84) -> str:
    """Break long raw tracks after a separator (^ = ? ;) where possible instead of mid-number."""
    lines: list[str] = []
    for line in (text or "").splitlines() or [""]:
        while len(line) > width:
            cut = max(line.rfind(mark, 0, width) for mark in "^=?;%+")
            cut = cut + 1 if cut >= width // 2 else width
            lines.append(line[:cut])
            line = line[cut:]
        lines.append(line)
    return "\n".join(lines)


def mask_pan(pan: str | None) -> str:
    digits = re.sub(r"\D", "", pan or "")
    if not digits:
        return "—"
    if len(digits) < 10:
        if len(digits) <= 4:
            return "••••"
        return f"{'•' * (len(digits) - 4)}{digits[-4:]}"
    return f"{digits[:6]}{'•' * (len(digits) - 10)}{digits[-4:]}"


def _ending(pan: str | None) -> str:
    return f"•••• {last_four(pan)}" if pan else "No account number"


def _network(parsed) -> str:
    brand = list_brand(parsed)
    return "Network not recognized" if brand == "Not recognized" else brand


def _link(label: str, dest: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f'<a href="#{dest}" color="#1B4F72">{_escape(label)}</a>', style)


def _account_text(pan: str | None, mask: bool) -> str:
    if not pan:
        return ""
    return mask_pan(pan) if mask else format_pan(pan)


def _field_table(rows: list[tuple[str, str, bool]], styles: dict[str, ParagraphStyle], markup: bool = False) -> Table:
    data = []
    for label, value, mono in rows:
        style = styles["mono"] if mono else styles["value"]
        shown = value if markup else _escape(value).replace("\n", "<br/>")
        data.append([Paragraph(_escape(label), styles["label"]), Paragraph(shown, style)])
    table = Table(data, colWidths=[130, CONTENT_WIDTH - 130])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _section(heading: Paragraph, *content) -> KeepTogether:
    """A heading kept on the same page as what follows it."""
    return KeepTogether([heading, *content])


# ---------- classifying results ----------

_PROBLEM_WORDS = ("differ", "luhn fail", "read error", "not standard", "printed as", "does not carry", "also on", "identical stripe")
_CAUTION_WORDS = ("in the past", "was not read", "not compared", "not recorded")


def _tone(finding: str) -> str:
    lowered = finding.lower()
    if any(word in lowered for word in _PROBLEM_WORDS):
        return "problem"
    if any(word in lowered for word in _CAUTION_WORDS):
        return "caution"
    return "routine"


def _printed_word(card) -> str:
    states = set(printed_states(card).values())
    if "differs" in states:
        return "Differs"
    if states == {"match"}:
        return "Matches"
    if "match" in states:
        return "Partly matches"
    return "Not compared"


def _tracks_word(parsed) -> str:
    comparison = parsed.comparison
    if comparison.tracks_differ:
        return "Differ"
    if "Match" in {comparison.pan, comparison.expiration, comparison.service_code, comparison.track3_account}:
        return "Match"
    return "Not compared"


def _flags(session: CaseSession, card) -> list[str]:
    parsed = card.view()
    words = []
    if parsed.tracks_read_error:
        words.append("Track read error")
    if face_findings(card):
        words.append("Card type mismatch")
    if has_duplicates(session, card):
        words.append("Duplicate account")
    return words


def _key_findings(session: CaseSession, card) -> tuple[list[str], list[str], list[str]]:
    problems, cautions, routine = [], [], []
    for item in card_findings(card, session):
        {"problem": problems, "caution": cautions, "routine": routine}[_tone(item)].append(item)
    if _printed_word(card) == "Not compared":
        cautions.append("Printed card was not compared with the stripe")
    if normalize_face(card.face_type) == "unknown":
        cautions.append("Card type was not recorded")
    return problems, cautions, routine


# ---------- page furniture ----------


def _footer_text(options: ReportOptions) -> str:
    if options.mask_accounts and not options.include_raw:
        return "Account numbers are masked"
    if options.mask_accounts:
        return "Sensitive: full account numbers appear in the raw tracks"
    return "Sensitive: contains full account numbers"


def numbered_canvas(body_font: str, footer: str):
    """A canvas that writes the footer with 'Page X of Y' once the page count is known."""

    class NumberedCanvas(pdf_canvas.Canvas):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._saved_pages: list[dict] = []

        def showPage(self) -> None:  # noqa: N802
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self.saveState()
                self.setFillColor(LABEL)
                self.setFont(body_font, 8)
                self.drawString(40, 24, f"{footer}  ·  Page {self._pageNumber} of {total}")
                self.restoreState()
                super().showPage()
            super().save()

    return NumberedCanvas


def _header_painter(session: CaseSession, title: str):
    body, bold, _mono = _register_fonts()

    def draw_page(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setFillColor(SLATE)
        canvas.rect(0, PAGE_HEIGHT - 46, PAGE_WIDTH, 46, fill=1, stroke=0)
        canvas.setFillColor(white)
        canvas.setFont(bold, 11)
        canvas.drawString(40, PAGE_HEIGHT - 28, title)
        canvas.setFont(body, 9)
        canvas.drawRightString(PAGE_WIDTH - 40, PAGE_HEIGHT - 28, f"Case {session.case_number}")
        canvas.restoreState()

    return draw_page


# ---------- front page ----------


def _case_block(session: CaseSession, cards: list, options: ReportOptions, styles) -> Table:
    generated = datetime.now().isoformat(timespec="minutes")
    count = str(len(cards))
    if options.differs_only:
        count += f" (only cards that differ from the printed card; {len(session.cards)} in the case)"
    rows = [
        ("Case number", session.case_number),
        ("Examiner", session.examiner or "—"),
        ("Unit", session.unit or "—"),
        ("Case opened", _clock(session.started_at)),
        ("Report generated", _clock(generated)),
        ("Cards in this report", count),
    ]
    if session.notes:
        rows.append(("Session notes", session.notes))
    rows.append(("Prepared with", f"Card Stripe Examiner {__version__}"))
    data = [
        [Paragraph(_escape(label), styles["label"]), Paragraph(_escape(value).replace("\n", "<br/>"), styles["value"])]
        for label, value in rows
    ]
    table = Table(data, colWidths=[130, CONTENT_WIDTH - 130])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("BACKGROUND", (0, 0), (0, -1), GREY_BOX),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _summary_block(session: CaseSession, cards: list, styles) -> Table:
    counts = [
        ("Differ from the printed card", sum(1 for card in cards if printed_differs(card)), "red"),
        ("Track 1 and track 2 differ", sum(1 for card in cards if card.view().comparison.tracks_differ), "red"),
        ("Luhn fail", sum(1 for card in cards if card.view().luhn == "Fail"), "red"),
        ("Card type does not fit the stripe", sum(1 for card in cards if face_findings(card)), "red"),
        ("Share an account number or swipe with another card", sum(1 for card in cards if has_duplicates(session, card)), "red"),
        ("Track read errors", sum(1 for card in cards if card.view().tracks_read_error), "red"),
        ("Printed card not compared", sum(1 for card in cards if _printed_word(card) == "Not compared"), "amber"),
        ("Card type not recorded", sum(1 for card in cards if normalize_face(card.face_type) == "unknown"), "amber"),
    ]
    data = []
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]
    for row, (label, value, tone) in enumerate(counts):
        if value:
            shown = _color(str(value), tone, bold=True)
            text = _color(label, tone, bold=True)
            commands.append(("BACKGROUND", (0, row), (-1, row), RED_TINT if tone == "red" else AMBER_TINT))
        else:
            shown = _color("0", "muted")
            text = _escape(label)
        data.append([Paragraph(text, styles["cell"]), Paragraph(shown, styles["cell"])])
    table = Table(data, colWidths=[300, 50], hAlign="LEFT")
    table.setStyle(TableStyle(commands))
    return table


def _index_table(session: CaseSession, cards: list, styles) -> Table:
    header = [
        Paragraph(text, styles["cellBold"])
        for text in ("Exhibit", "Brand", "Last four", "Swiped date/time", "Luhn", "Tracks", "Printed", "Flags")
    ]
    rows = [header]
    if not cards:
        rows.append([Paragraph("—", styles["cell"])] + [Paragraph("", styles["cell"])] * 7)
    for number, card in enumerate(cards, start=1):
        parsed = card.view()
        dest = f"card-{number}"
        luhn = luhn_label(parsed.luhn)
        tracks = _tracks_word(parsed)
        printed = _printed_word(card)
        flags = _flags(session, card)
        rows.append(
            [
                _link(card_label(session, card), dest, styles["cell"]),
                _link(list_brand(parsed), dest, styles["cell"]),
                Paragraph(_escape(_ending(parsed.pan)), styles["cell"]),
                Paragraph(_escape(_clock(card.swiped_at)), styles["cell"]),
                Paragraph(_color(luhn, "red", True) if parsed.luhn == "Fail" else _escape(luhn), styles["cell"]),
                Paragraph(_color(tracks, "red", True) if tracks == "Differ" else _escape(tracks), styles["cell"]),
                Paragraph(
                    _color(printed, "red", True)
                    if printed == "Differs"
                    else _color(printed, "amber") if printed == "Not compared" else _escape(printed),
                    styles["cell"],
                ),
                Paragraph(_color(", ".join(flags), "red", True) if flags else _color("None", "muted"), styles["cell"]),
            ]
        )
    table = Table(rows, colWidths=[54, 60, 56, 84, 52, 50, 64, 100], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ROW),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
            ]
        )
    )
    return table


# ---------- each card ----------


def _findings_box(session: CaseSession, card, styles) -> Table:
    problems, cautions, routine = _key_findings(session, card)
    rows = [[Paragraph("Key findings", styles["boxTitle"])]]
    for item in problems:
        rows.append([Paragraph("■ " + _color(item, "red", True), styles["finding"])])
    for item in cautions:
        rows.append([Paragraph("■ " + _color(item, "amber"), styles["finding"])])
    if not problems and not cautions:
        rows.append([Paragraph(_color("No differences found.", "green", True), styles["finding"])])
    if routine:
        rows.append([Paragraph(_color("Also checked: " + "  ·  ".join(routine), "muted"), styles["finding"])])
    tint, edge = (RED_TINT, RED) if problems else (AMBER_TINT, AMBER) if cautions else (GREEN_TINT, GREEN)
    table = Table(rows, colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), tint),
                ("LINEBEFORE", (0, 0), (0, -1), 4, edge),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
            ]
        )
    )
    return table


_RESULT_WORDS = {
    "match": ("Matches", "green", False),
    "differs": ("Differs", "red", True),
    "blank": ("Not compared", "muted", False),
    "no_stripe": ("Not on the stripe", "muted", False),
    "unreadable": ("Date not readable", "amber", False),
}


def _comparison_table(card, mask: bool, styles) -> Table:
    parsed = card.view()
    data = normalize_printed(card.printed)
    states = printed_states(card)

    def stripe_account() -> str:
        one, two = parsed.track1.pan, parsed.track2.pan
        if one and two and one != two:
            return f"Track 1: {_escape(_account_text(one, mask))}<br/>Track 2: {_escape(_account_text(two, mask))}"
        return _escape(_account_text(parsed.pan, mask)) or _color("Not on the stripe", "muted")

    def stripe_name() -> str:
        if not parsed.name_on_stripe:
            return _color("Not on the stripe", "muted")
        shown = _escape(parsed.name or parsed.name_on_stripe)
        if parsed.name and parsed.name != parsed.name_on_stripe:
            shown += f'<br/><font size="7.5" color="{_HEX["muted"]}">as encoded: {_escape(parsed.name_on_stripe)}</font>'
        return shown

    def stripe_expiration() -> str:
        one, two = parsed.track1.expiration, parsed.track2.expiration
        if one and two and one != two:
            return (
                f"Track 1: {_escape(expiration_display(one) or one)}<br/>"
                f"Track 2: {_escape(expiration_display(two) or two)}"
            )
        shown = parsed.expiration_display
        if not shown:
            return _color("Not on the stripe", "muted")
        return _escape(shown) + (" " + _color("(expired)", "amber") if parsed.expired else "")

    def printed_value(name: str) -> tuple[str, bool]:
        """(markup, is_a_value). Placeholders are set in the normal font, values in the number font."""
        if data["matches"]:
            return _color("Same as the stripe", "muted"), False
        typed = data[f"{name}_text"].strip()
        if not typed:
            if name in data["earlier_differs"]:
                return _color("Marked as different (earlier version)", "muted"), False
            return _color("Not entered", "muted"), False
        if name == "account":
            digits = re.sub(r"\D", "", typed)
            if len(digits) >= 12:
                return _escape(mask_pan(digits) if mask else format_pan(digits)), True
        return _escape(typed), True

    header = [Paragraph(text, styles["cellBold"]) for text in ("Field", "On the stripe", "Printed on the card", "Result")]
    rows = [header]
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), ROW),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    stripe_values = {"account": stripe_account(), "name": stripe_name(), "expiration": stripe_expiration()}
    labels = {"account": "Account number", "name": "Name", "expiration": "Expiration"}
    for row, name in enumerate(PRINTED_FIELDS, start=1):
        word, tone, bold = _RESULT_WORDS[states[name]]
        value_style = styles["cellMono"] if name != "name" else styles["cell"]
        printed_markup, is_value = printed_value(name)
        stripe_markup = stripe_values[name]
        stripe_style = value_style if "Not on the stripe" not in stripe_markup else styles["cell"]
        rows.append(
            [
                Paragraph(_escape(labels[name]), styles["cellBold"]),
                Paragraph(stripe_markup, stripe_style),
                Paragraph(printed_markup, value_style if is_value else styles["cell"]),
                Paragraph(_color(word, tone, bold), styles["cell"]),
            ]
        )
        if states[name] == "differs":
            commands.append(("BACKGROUND", (0, row), (-1, row), RED_TINT))
    table = Table(rows, colWidths=[90, 165, 165, CONTENT_WIDTH - 420])
    table.setStyle(TableStyle(commands))
    return table


def _bank_rows(payload: dict | None) -> list[tuple[str, str, bool]]:
    if not payload:
        return [("Status", "Not looked up.", False)]
    result = BinResult.from_dict(payload)
    if result.error:
        rows = [("BIN", result.queried_digits or "", True), ("Result", result.error, False)]
    else:
        prepaid = None if result.prepaid is None else ("Yes" if result.prepaid else "No")
        rows = [
            ("BIN", result.queried_digits, True),
            ("Bank", result.bank_name, False),
            ("City", result.bank_city, False),
            ("Country", clean_country(result.country), False),
            ("Type", result.card_kind, False),
            ("Prepaid", prepaid, False),
            ("Scheme", result.scheme, False),
            ("Phone", result.bank_phone, False),
            ("URL", result.bank_url, False),
        ]
    rows += [("Lookup time", _clock(result.looked_up_at), False), ("Source", result.source_text(), False)]
    return [(label, value, mono) for label, value, mono in rows if value and value != "—"]


def _stripe_rows(parsed) -> list[tuple[str, str, bool]]:
    return [(label, value, mono) for label, value, mono in stripe_fields(parsed) if value and value.strip() != "—"]


def _track_rows(parsed) -> list[tuple[str, str, bool]]:
    comparison = parsed.comparison
    rows = [
        ("Account number", comparison.pan),
        ("Expiration", comparison.expiration),
        ("Service code", comparison.service_code),
        ("Track 3 account", comparison.track3_account),
    ]
    return [(label, value, False) for label, value in rows if value != "Not comparable"]


def _raw_box(card, parsed, styles) -> Table:
    rows = []
    for label, value in (
        ("Track 1", parsed.track1.raw),
        ("Track 2", parsed.track2.raw),
        ("Track 3", parsed.track3.raw),
        ("Full swipe as recorded", card.raw),
    ):
        rows.append([Paragraph(_escape(label), styles["label"])])
        rows.append([Preformatted(_wrap_raw(value or "Not present"), styles["raw"])])
    table = Table(rows, colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GREY_BOX),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ]
        )
    )
    return table


def _photo_image(path: Path, max_width: float, max_height: float):
    """A downsized, upright copy of a photo for the PDF. The original file is not changed."""
    source = None
    try:
        from PIL import Image as PILImage
        from PIL import ImageOps

        with PILImage.open(path) as picture:
            picture = ImageOps.exif_transpose(picture)
            picture.thumbnail((1400, 1400))
            if picture.mode not in ("RGB", "L"):
                picture = picture.convert("RGB")
            buffer = io.BytesIO()
            picture.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            source = buffer
    except Exception:
        source = str(path)
    try:
        width, height = ImageReader(source).getSize()
        if hasattr(source, "seek"):
            source.seek(0)
    except Exception:
        return None
    scale = min(max_width / width, max_height / height, 1.0)
    return Image(source, width=width * scale, height=height * scale)


def _photo_block(session: CaseSession, card, styles: dict[str, ParagraphStyle]) -> list:
    cells = []
    for photo in card.photos:
        side = PHOTO_SIDES.get(photo.get("side"), "Photo")
        path = photo_path(session, photo)
        caption = Paragraph(
            _escape(side),
            styles["small"],
        )
        picture = _photo_image(path, 240, 170) if path is not None and path.exists() else None
        if picture is None:
            picture = Paragraph(_escape(f"Photo file not found: {photo.get('file') or '—'}"), styles["small"])
        cells.append([picture, caption])
    if not cells:
        return []
    rows = []
    for start in range(0, len(cells), 2):
        pair = cells[start : start + 2]
        while len(pair) < 2:
            pair.append(["", ""])
        rows.append([pair[0][0], pair[1][0]])
        rows.append([pair[0][1], pair[1][1]])
    table = Table(rows, colWidths=[255, 255])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [table]


def _card_pages(session: CaseSession, card, number: int, options: ReportOptions, styles) -> list:
    parsed = card.view()
    dest = f"card-{number}"
    label = card_label(session, card)
    story: list = [
        PageBreak(),
        Destination(dest, label, 1, closed=True),
        Paragraph(_escape(f"{label}  ·  {_network(parsed)}  {_ending(parsed.pan)}"), styles["h1"]),
        Paragraph(
            _escape(f"{parsed.card_type}  ·  Swiped {_clock(card.swiped_at)}  ·  {luhn_label(parsed.luhn)}"),
            styles["meta"],
        ),
        _link("Back to index", "index", styles["link"]),
        Spacer(1, 6),
        _findings_box(session, card, styles),
    ]
    face = normalize_face(card.face_type)
    face_text = _color(FACE_TYPES[face], "amber") if face == "unknown" else _escape(FACE_TYPES[face])
    story.append(
        _section(
            Paragraph("Card", styles["section"]),
            _field_table([("Exhibit", _escape(card.exhibit.strip() or "—"), False), ("Card type", face_text, False)], styles, markup=True),
        )
    )
    story.append(
        _section(
            Paragraph("Stripe and printed card", styles["section"]),
            Destination(f"{dest}-compare", "Stripe and printed card", 2, closed=True),
            _comparison_table(card, options.mask_accounts, styles),
        )
    )
    story.append(_section(Paragraph("Stripe", styles["section"]), _field_table(_stripe_rows(parsed), styles)))
    story.append(_section(Paragraph("Issuing bank", styles["section"]), _field_table(_bank_rows(card.bin_lookup), styles)))
    track_rows = _track_rows(parsed)
    story.append(
        _section(
            Paragraph("Track comparison", styles["section"]),
            _field_table(track_rows, styles)
            if track_rows
            else Paragraph("Only one track was read, so there was nothing to compare.", styles["note"]),
        )
    )
    if card.note.strip():
        story.append(
            _section(
                Paragraph("Examiner note", styles["section"]),
                Paragraph(_escape(card.note).replace("\n", "<br/>"), styles["value"]),
            )
        )
    if options.include_photos and card.photos:
        story.append(
            _section(
                Paragraph("Photos", styles["section"]),
                Destination(f"{dest}-photos", "Photos", 2, closed=True),
                *_photo_block(session, card, styles),
            )
        )
    if options.include_raw:
        story.append(
            _section(
                Paragraph("Raw tracks", styles["section"]),
                Destination(f"{dest}-raw", "Raw tracks", 2, closed=True),
                _raw_box(card, parsed, styles),
            )
        )
    return story


def _notes_section(cards: list, styles) -> list:
    notes = []
    for card in cards:
        if card.bin_lookup:
            note = BinResult.from_dict(card.bin_lookup).source_note
            if note and note not in notes:
                notes.append(note)
    if not notes:
        return []
    return [
        _section(
            Paragraph("Notes", styles["section"]),
            *[Paragraph("■ " + _escape(note), styles["finding"]) for note in notes],
        )
    ]


def _signoff(session: CaseSession, styles) -> KeepTogether:
    line = "_" * 34
    rows = [
        [Paragraph("Examined by", styles["label"]), Paragraph(_escape(session.examiner) if session.examiner else line, styles["value"])],
        [Paragraph("Unit", styles["label"]), Paragraph(_escape(session.unit) if session.unit else line, styles["value"])],
        [Paragraph("Signature", styles["label"]), Paragraph(line, styles["value"])],
        [Paragraph("Date", styles["label"]), Paragraph(line, styles["value"])],
    ]
    table = Table(rows, colWidths=[130, 300], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return _section(Paragraph("Examiner", styles["section"]), Spacer(1, 2), table)


def build_story(session: CaseSession, options: ReportOptions | bool | None = None) -> list:
    options = _as_options(options)
    cards = cards_for_report(session, options.differs_only)
    body, bold, mono = _register_fonts()
    styles = _styles(body, bold, mono)
    story: list = [
        Destination("index", "Case report", 0, closed=False),
        Paragraph("Card Stripe Analysis Report", styles["title"]),
        Paragraph("Case information", styles["section"]),
        _case_block(session, cards, options, styles),
        Paragraph("Summary", styles["section"]),
        _summary_block(session, cards, styles),
        _section(
            Paragraph("Cards", styles["section"]),
            _index_table(session, cards, styles),
            Spacer(1, 4),
            Paragraph(
                "Select an exhibit to go to that card. Tracks: whether the data on track 1 and track 2 "
                "(and track 3, when present) agree. Printed: whether what is printed on the card matches the stripe. "
                "Flags: a track that could not be read, a card type that does not fit the stripe, or an account "
                "number found on more than one card in this case.",
                styles["small"],
            ),
        ),
    ]
    for number, card in enumerate(cards, start=1):
        story.extend(_card_pages(session, card, number, options, styles))
    story.append(Spacer(1, 14))
    story.extend(_notes_section(cards, styles))
    story.append(_signoff(session, styles))
    if options.include_glossary:
        story.append(PageBreak())
        story.append(Destination("glossary", "Appendix: Terms used in this report", 0, closed=True))
        story.append(Paragraph("Appendix: Terms used in this report", styles["h1"]))
        for topic in REPORT_TERMS:
            story.append(
                KeepTogether(
                    [Paragraph(_escape(topic["title"]), styles["topic"]), Paragraph(_escape(topic["body"]), styles["body"])]
                )
            )
    return story


def story_text(session: CaseSession, options: ReportOptions | bool | None = None) -> str:
    parts: list[str] = []
    for item in build_story(session, options):
        text = _flowable_text(item)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _flowable_text(item) -> str:
    if isinstance(item, Paragraph):
        return item.getPlainText()
    if isinstance(item, Preformatted):
        return "\n".join(item.lines)
    if isinstance(item, Table):
        bits: list[str] = []
        for row in item._cellvalues:
            for cell in row:
                if isinstance(cell, list):
                    bits.extend(_flowable_text(child) for child in cell)
                elif isinstance(cell, str):
                    bits.append(cell)
                elif cell is not None and not isinstance(cell, (int, float)):
                    bits.append(_flowable_text(cell))
        return "\n".join(bit for bit in bits if bit)
    if isinstance(item, KeepTogether):
        return "\n".join(_flowable_text(child) for child in item._content)
    return ""


def write_pdf(session: CaseSession, path: str | Path, options: ReportOptions | bool | None = None) -> None:
    options = _as_options(options)
    body, _bold, _mono = _register_fonts()
    document = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=64,
        bottomMargin=46,
        title=f"Card Stripe Analysis — {session.case_number}",
        author=session.examiner or "Card Stripe Examiner",
    )
    header = _header_painter(session, "Card Stripe Analysis")
    document.build(
        build_story(session, options),
        onFirstPage=header,
        onLaterPages=header,
        canvasmaker=numbered_canvas(body, _footer_text(options)),
    )
