"""The detail tabs for the selected card."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from card_stripe_examiner.bin_lookup import BinResult, clean_country, prompt_digits
from card_stripe_examiner.parse import (
    account_fields,
    explain_service,
    expiration_display,
    format_pan,
    list_brand,
    luhn_label,
    stripe_fields,
)
from card_stripe_examiner.session import (
    FACE_TYPES,
    PHOTO_SIDES,
    PRINTED_STATES,
    card_findings,
    card_label,
    compare_printed_field,
    normalize_face,
    normalize_printed,
    photo_path,
)
from card_stripe_examiner.widgets import (
    format_when,
    format_clock,
    clear_layout,
    masked_last_four,
    NoScrollComboBox,
    Section,
    ScrollPane,
    input_heading,
    set_attention,
)


_STATE_COLORS = {
    "match": "#0F766E",
    "differs": "#B91C1C",
    "unreadable": "#B45309",
}


class PrintedPanel(QFrame):
    """One tick box when the plastic matches the stripe; otherwise type what is printed."""

    changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("inputPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._parsed = None
        self._earlier: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        heading_row, self.attention = input_heading("Printed card")
        self.attention.setText("Not checked yet")
        layout.addLayout(heading_row)
        self.matches = QCheckBox("Account number, name and expiration printed on the card match the stripe")
        self.matches.setObjectName("printedMatches")
        self.matches.toggled.connect(self._on_toggle)
        layout.addWidget(self.matches)
        self.entry = QWidget()
        entry = QVBoxLayout(self.entry)
        entry.setContentsMargins(0, 0, 0, 0)
        entry.setSpacing(8)
        hint = QLabel(
            "Type what is printed on the card. Each entry is compared with the stripe; "
            "leave a field blank if it is not printed or not readable."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        entry.addWidget(hint)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.inputs: dict[str, QLineEdit] = {}
        self.results: dict[str, QLabel] = {}
        for name, title, placeholder in (
            ("account", "Account number", "Account number as printed"),
            ("name", "Name", "Name as printed"),
            ("expiration", "Expiration", "MM/YY as printed"),
        ):
            column = QVBoxLayout()
            column.setSpacing(4)
            caption = QLabel(title)
            caption.setObjectName("fieldLabel")
            typed = QLineEdit()
            typed.setPlaceholderText(placeholder)
            typed.textChanged.connect(self._emit)
            result = QLabel()
            result.setWordWrap(True)
            column.addWidget(caption)
            column.addWidget(typed)
            column.addWidget(result)
            row.addLayout(column, 1)
            self.inputs[name] = typed
            self.results[name] = result
        entry.addLayout(row)
        layout.addWidget(self.entry)
        self._loading = False

    def load(self, payload, parsed=None) -> None:
        data = normalize_printed(payload)
        self._parsed = parsed
        self._earlier = list(data["earlier_differs"])
        self._loading = True
        self.matches.setChecked(data["matches"])
        for name, typed in self.inputs.items():
            typed.setText(data[f"{name}_text"])
        self._loading = False
        self.entry.setVisible(not data["matches"])
        self._show_results()

    def _on_toggle(self, checked: bool) -> None:
        self.entry.setVisible(not checked)
        self._emit()

    def _show_results(self) -> None:
        nothing_entered = not any(typed.text().strip() for typed in self.inputs.values())
        self.attention.setVisible(not self.matches.isChecked() and nothing_entered and not self._earlier)
        for name, label in self.results.items():
            text = self.inputs[name].text()
            if self._parsed is None:
                label.setText("")
                continue
            state = compare_printed_field(self._parsed, name, text)
            message = PRINTED_STATES[state]
            if state == "blank" and name in self._earlier:
                state = "differs"
                message = "Marked as different in an earlier version"
            elif state == "blank":
                message = ""
            label.setText(message)
            color = _STATE_COLORS.get(state, "#64748B")
            label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 12px; font-weight: 600; }}")

    def _emit(self, *_args) -> None:
        if self._loading:
            return
        self._show_results()
        self.changed.emit(self.value())

    def value(self) -> dict:
        data = {"matches": self.matches.isChecked(), "earlier_differs": list(self._earlier)}
        for name, typed in self.inputs.items():
            data[f"{name}_text"] = typed.text()
        return normalize_printed(data)


class SummaryTab(QWidget):
    note_changed = Signal(str)
    printed_changed = Signal(dict)
    lookup_requested = Signal()
    lookup_all_requested = Signal()
    token_requested = Signal()
    bin_database_requested = Signal()
    exhibit_changed = Signal(str)
    exhibit_committed = Signal()
    face_changed = Signal(str)
    photo_add_requested = Signal(str)
    photo_capture_requested = Signal(str)
    photo_remove_requested = Signal(str)
    photo_open_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._session = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        self.scroll = ScrollPane()
        self.host_layout = self.scroll.host_layout
        self.host_layout.addWidget(self._build_card_panel())
        # Account, then the printed card right below it so the two can be compared, then the rest.
        self.account_slot = QVBoxLayout()
        self.account_slot.setSpacing(12)
        self.host_layout.addLayout(self.account_slot)
        self.printed = PrintedPanel()
        self.printed.changed.connect(self._emit_printed)
        self.host_layout.addWidget(self.printed)
        self.sections = QVBoxLayout()
        self.sections.setSpacing(12)
        self.host_layout.addLayout(self.sections)
        self.host_layout.addWidget(self._build_photo_panel())
        note_panel = QFrame()
        note_panel.setObjectName("inputPanel")
        note_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        note_layout = QVBoxLayout(note_panel)
        note_layout.setContentsMargins(16, 14, 16, 16)
        heading, _unused = input_heading("Examiner note")
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Item number, recovery location, or other case note")
        self.note.setFixedHeight(88)
        self.note.textChanged.connect(self._emit_note)
        note_layout.addLayout(heading)
        note_layout.addWidget(self.note)
        self.host_layout.addWidget(note_panel)
        self.host_layout.addStretch()
        outer.addWidget(self.scroll)
        self._loading = False
        self._lookup_enabled = True

    def _build_card_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("inputPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        heading, self.card_attention = input_heading("Card")
        self.card_attention.setText("Choose the card type")
        layout.addLayout(heading)
        row = QHBoxLayout()
        row.setSpacing(16)
        exhibit_box = QVBoxLayout()
        exhibit_caption = QLabel("Exhibit")
        exhibit_caption.setObjectName("fieldLabel")
        self.exhibit = QLineEdit()
        self.exhibit.setPlaceholderText("Exhibit or item number")
        self.exhibit.textChanged.connect(self._emit_exhibit)
        self.exhibit.editingFinished.connect(lambda: self.exhibit_committed.emit())
        exhibit_box.addWidget(exhibit_caption)
        exhibit_box.addWidget(self.exhibit)
        face_box = QVBoxLayout()
        face_caption = QLabel("Card type (what the plastic is)")
        face_caption.setObjectName("fieldLabel")
        self.face = NoScrollComboBox()
        for key, label in FACE_TYPES.items():
            self.face.addItem(label, key)
        self.face.currentIndexChanged.connect(self._emit_face)
        face_box.addWidget(face_caption)
        face_box.addWidget(self.face)
        row.addLayout(exhibit_box, 1)
        row.addLayout(face_box, 2)
        layout.addLayout(row)
        return panel

    def _build_photo_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("inputPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        heading, _unused = input_heading("Photos")
        hint = QLabel(
            "Import a photo from a file, or capture one with the computer's camera. Photos are kept in a folder "
            "beside the saved case file; an imported photo's original file is not changed."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addLayout(heading)
        layout.addWidget(hint)
        self.photo_grid = QGridLayout()
        self.photo_grid.setHorizontalSpacing(16)
        self.photo_grid.setVerticalSpacing(12)
        layout.addLayout(self.photo_grid)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.photo_buttons = {}
        for side, label in PHOTO_SIDES.items():
            import_button = QPushButton(f"Import {label.lower()} photo")
            import_button.setObjectName("quiet")
            import_button.setToolTip(f"Choose a photo file of the {label.lower()} of the card")
            import_button.clicked.connect(lambda _checked=False, value=side: self.photo_add_requested.emit(value))
            capture_button = QPushButton(f"Capture {label.lower()} photo")
            capture_button.setObjectName("quiet")
            capture_button.setToolTip(f"Take a photo of the {label.lower()} of the card with the computer's camera")
            capture_button.clicked.connect(lambda _checked=False, value=side: self.photo_capture_requested.emit(value))
            self.photo_buttons[side] = (import_button, capture_button)
            row.addWidget(import_button)
            row.addWidget(capture_button)
            if side != list(PHOTO_SIDES)[-1]:
                row.addSpacing(12)
        row.addStretch()
        layout.addLayout(row)
        return panel

    def _fill_photos(self, card) -> None:
        clear_layout(self.photo_grid)
        if not card.photos:
            empty = QLabel("No photos.")
            empty.setObjectName("hint")
            self.photo_grid.addWidget(empty, 0, 0)
            return
        for index, photo in enumerate(card.photos):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            picture = QLabel()
            picture.setFixedSize(200, 130)
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            path = photo_path(self._session, photo) if self._session is not None else None
            pixmap = QPixmap(str(path)) if path is not None and path.exists() else QPixmap()
            if pixmap.isNull():
                picture.setText("Photo file not found")
                picture.setObjectName("hint")
            else:
                picture.setPixmap(
                    pixmap.scaled(
                        200,
                        130,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            caption = QLabel(f"{PHOTO_SIDES.get(photo.get('side'), 'Photo')}  ·  {photo.get('original_name') or ''}")
            caption.setObjectName("fieldLabel")
            caption.setWordWrap(True)
            buttons = QHBoxLayout()
            open_button = QPushButton("Open")
            open_button.setObjectName("quiet")
            open_button.clicked.connect(
                lambda _checked=False, file=photo.get("file", ""): self.photo_open_requested.emit(file)
            )
            remove_button = QPushButton("Remove")
            remove_button.setObjectName("quiet")
            remove_button.clicked.connect(
                lambda _checked=False, file=photo.get("file", ""): self.photo_remove_requested.emit(file)
            )
            buttons.addWidget(open_button)
            buttons.addWidget(remove_button)
            buttons.addStretch()
            cell.addWidget(picture)
            cell.addWidget(caption)
            cell.addLayout(buttons)
            self.photo_grid.addLayout(cell, index // 3, index % 3)

    def set_lookup_enabled(self, enabled: bool) -> None:
        self._lookup_enabled = enabled

    def show_card(self, card, lookup_enabled: bool = True, session=None) -> None:
        self._lookup_enabled = lookup_enabled
        self._session = session
        clear_layout(self.account_slot)
        clear_layout(self.sections)
        parsed = card.view()
        account = Section("Account")
        account.add_rows(account_fields(parsed))
        stripe = Section("Stripe")
        stripe.add_rows(stripe_fields(parsed))
        self._findings = stripe.add_wide("Findings", "\n".join(card_findings(card, session)) or "—")
        bank = Section("Issuing bank")
        self._fill_bank(bank, card, parsed)
        self.account_slot.addWidget(account)
        for section in (stripe, bank):
            self.sections.addWidget(section)
        self._loading = True
        self.exhibit.setText(card.exhibit)
        face_index = self.face.findData(normalize_face(card.face_type))
        self.face.setCurrentIndex(face_index if face_index >= 0 else 0)
        self._show_face_attention()
        self.printed.load(card.printed, parsed)
        self.note.setPlainText(card.note)
        self._loading = False
        self._fill_photos(card)
        self.scroll.refit_soon()

    def _fill_bank(self, bank: Section, card, parsed) -> None:
        digits = prompt_digits(parsed.pan)
        if not card.bin_lookup:
            bank.add_wide("Status", "Not looked up.")
            bank.add_field("BIN", digits or "—", mono=True)
        else:
            result = BinResult.from_dict(card.bin_lookup)
            if result.error:
                bank.add_wide("Result", result.error)
                bank.add_field("BIN", result.queried_digits or "—", mono=True)
                bank.add_wide("Source", result.source_text())
            else:
                prepaid = "—" if result.prepaid is None else ("Yes" if result.prepaid else "No")
                bank.add_field("Bank", result.bank_name or "—")
                bank.add_field("City", result.bank_city or "—")
                bank.add_field("Country", clean_country(result.country) or "—")
                bank.add_field("Type", result.card_kind or "—")
                bank.add_field("Prepaid", prepaid)
                bank.add_field("Scheme", result.scheme or "—")
                bank.add_wide("Phone", result.bank_phone or "—")
                bank.add_wide("URL", result.bank_url or "—")
                bank.add_field("BIN", result.queried_digits or "—", mono=True)
                bank.add_field("Lookup time", format_when(result.looked_up_at))
                bank.add_wide("Source", result.source_text())
                bank.add_wide("Note", result.source_note)
        row = QHBoxLayout()
        row.setSpacing(8)
        lookup = QPushButton("Look up bank")
        lookup.setObjectName("lookupButton")
        lookup.setEnabled(bool(parsed.pan) and self._lookup_enabled)
        lookup.clicked.connect(lambda: self.lookup_requested.emit())
        lookup_all = QPushButton("Look up all cards")
        lookup_all.setObjectName("quiet")
        lookup_all.setEnabled(self._lookup_enabled)
        lookup_all.clicked.connect(lambda: self.lookup_all_requested.emit())
        token = QPushButton("Service token")
        token.setObjectName("quiet")
        token.clicked.connect(lambda: self.token_requested.emit())
        offline = QPushButton("Offline BIN list")
        offline.setObjectName("quiet")
        offline.clicked.connect(lambda: self.bin_database_requested.emit())
        row.addWidget(lookup)
        row.addWidget(lookup_all)
        row.addWidget(token)
        row.addWidget(offline)
        row.addStretch()
        bank.body.addLayout(row)

    def _emit_note(self) -> None:
        if not self._loading:
            self.note_changed.emit(self.note.toPlainText())

    def set_findings(self, card) -> None:
        if getattr(self, "_findings", None) is None:
            return
        self._findings.value.setText("\n".join(card_findings(card, self._session)) or "—")
        self.scroll.refit_soon()

    def _emit_exhibit(self, text: str) -> None:
        if not self._loading:
            self.exhibit_changed.emit(text)

    def _show_face_attention(self) -> None:
        missing = normalize_face(self.face.currentData()) == "unknown"
        set_attention(self.face, missing)
        self.card_attention.setVisible(missing)

    def _emit_face(self, _index: int = 0) -> None:
        self._show_face_attention()
        if not self._loading:
            self.face_changed.emit(str(self.face.currentData() or "unknown"))

    def _emit_printed(self, payload: dict) -> None:
        if not self._loading:
            self.printed_changed.emit(payload)


class TracksTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        self.scroll = ScrollPane()
        self.layout_host = self.scroll.host_layout
        outer.addWidget(self.scroll)

    def show_card(self, card) -> None:
        clear_layout(self.layout_host)
        parsed = card.view()
        for title, track in (
            ("Track 1", parsed.track1),
            ("Track 2", parsed.track2),
            ("Track 3", parsed.track3),
        ):
            section = Section(title)
            if not track.present:
                section.add_wide("Status", "Not present")
            elif track.read_error:
                section.add_wide("Status", track.unrecognized_reason or "Read error. Swipe the card again.")
                block = QPlainTextEdit(track.raw or "")
                block.setReadOnly(True)
                block.setObjectName("rawBlock")
                block.setFixedHeight(48)
                section.body.addWidget(block)
            else:
                if track.recognized:
                    section.add_field("Layout", "Recognized")
                elif track.unrecognized_reason:
                    section.add_wide("Layout", track.unrecognized_reason)
                if track.format_code:
                    section.add_field("Format code", track.format_code, mono=True)
                if track.pan:
                    section.add_field("Account", format_pan(track.pan), account=True)
                    if track.luhn:
                        section.add_field("Luhn", luhn_label(track.luhn))
                if track.name:
                    section.add_field("Name on stripe", track.name)
                if track.expiration:
                    section.add_field("Expiration", expiration_display(track.expiration) or track.expiration, mono=True)
                if track.service_code:
                    section.add_field("Service code", track.service_code, mono=True)
                    section.add_wide("Service code meaning", "\n".join(explain_service(track.service_code)))
                if track.discretionary:
                    section.add_wide("Discretionary data", track.discretionary, mono=True)
                if track.country:
                    section.add_field("Country code", track.country, mono=True)
                if track.currency:
                    section.add_field("Currency code", track.currency, mono=True)
                if track.additional:
                    section.add_wide("Additional data", track.additional, mono=True)
                block = QPlainTextEdit(track.raw or "")
                block.setReadOnly(True)
                block.setObjectName("rawBlock")
                block.setFixedHeight(72)
                section.body.addWidget(block)
            self.layout_host.addWidget(section)
        self.layout_host.addStretch()
        self.scroll.refit_soon()


class RawTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        self.scroll = ScrollPane()
        self.layout_host = self.scroll.host_layout
        outer.addWidget(self.scroll)

    def show_card(self, card) -> None:
        clear_layout(self.layout_host)
        parsed = card.view()
        blocks = (
            ("Full swipe", card.raw),
            ("Track 1", parsed.track1.raw),
            ("Track 2", parsed.track2.raw),
            ("Track 3", parsed.track3.raw),
        )
        for label, value in blocks:
            panel = QFrame()
            panel.setObjectName("panel")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(16, 14, 16, 16)
            caption = QLabel(label)
            caption.setObjectName("sectionTitle")
            box = QPlainTextEdit(value or "Not present")
            box.setReadOnly(True)
            box.setObjectName("rawBlock")
            box.setFixedHeight(96 if label == "Full swipe" else 72)
            layout.addWidget(caption)
            layout.addWidget(box)
            self.layout_host.addWidget(panel)
        self.layout_host.addStretch()
        self.scroll.refit_soon()


class CompareTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.session = None
        self._ids: list[str] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        self.prompt = QLabel("Add another card to compare two reads.")
        self.prompt.setObjectName("emptyState")
        self.prompt.setWordWrap(True)
        self.controls = QWidget()
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self._caption("Card A"))
        self.combo_a = NoScrollComboBox()
        self.combo_b = NoScrollComboBox()
        controls.addWidget(self.combo_a, 1)
        controls.addSpacing(12)
        controls.addWidget(self._caption("Card B"))
        controls.addWidget(self.combo_b, 1)
        self.combo_a.currentIndexChanged.connect(self.refresh)
        self.combo_b.currentIndexChanged.connect(self.refresh)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.grid_host)
        layout.addWidget(self.prompt)
        layout.addWidget(self.controls)
        layout.addWidget(scroll, 1)
        self.prompt.setVisible(True)
        self.controls.setVisible(False)

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def set_session(self, session, selected_id: str | None, follow: bool) -> None:
        self.session = session
        cards = session.cards if session else []
        if len(cards) < 2:
            self.prompt.setVisible(True)
            self.controls.setVisible(False)
            self.grid_host.setVisible(False)
            return
        self.prompt.setVisible(False)
        self.controls.setVisible(True)
        self.grid_host.setVisible(True)
        ids = [card.id for card in cards]
        if ids != self._ids:
            self._ids = ids
            self.combo_a.blockSignals(True)
            self.combo_b.blockSignals(True)
            self.combo_a.clear()
            self.combo_b.clear()
            for index, card in enumerate(cards, start=1):
                label = self._label(index, card)
                self.combo_a.addItem(label, card.id)
                self.combo_b.addItem(label, card.id)
            self.combo_a.blockSignals(False)
            self.combo_b.blockSignals(False)
        if follow and selected_id:
            self._select(self.combo_a, selected_id)
        if self.combo_a.currentData() == self.combo_b.currentData():
            for index in range(self.combo_b.count()):
                if self.combo_b.itemData(index) != self.combo_a.currentData():
                    self.combo_b.blockSignals(True)
                    self.combo_b.setCurrentIndex(index)
                    self.combo_b.blockSignals(False)
                    break
        self.refresh()

    def _select(self, combo: QComboBox, card_id: str) -> None:
        index = combo.findData(card_id)
        if index >= 0 and combo.currentIndex() != index:
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _label(self, index: int, card) -> str:
        parsed = card.view()
        label = card_label(self.session, card) if card.exhibit.strip() else str(index)
        return f"{label}   {list_brand(parsed)}   {masked_last_four(parsed.pan)}   {format_clock(card.swiped_at)}"

    def _card(self, card_id: str):
        if not self.session:
            return None
        for card in self.session.cards:
            if card.id == card_id:
                return card
        return None

    def refresh(self, _index: int = 0) -> None:
        clear_layout(self.grid)
        left = self._card(self.combo_a.currentData())
        right = self._card(self.combo_b.currentData())
        if left is None or right is None:
            return
        rows = self._rows(left, right)
        for index, (label, value_a, value_b) in enumerate(rows):
            caption = QLabel(label)
            caption.setObjectName("fieldLabel")
            cell_a = self._value(value_a, label)
            cell_b = self._value(value_b, label)
            self.grid.addWidget(caption, index, 0)
            self.grid.addWidget(cell_a, index, 1)
            self.grid.addWidget(cell_b, index, 2)
            if label != "Exhibit" and (value_a or "—") != (value_b or "—"):
                mark = QLabel("Differs")
                mark.setObjectName("differs")
                self.grid.addWidget(mark, index, 3)

    def _value(self, text: str, label: str) -> QLabel:
        value = QLabel(text or "—")
        value.setWordWrap(True)
        value.setTextFormat(Qt.TextFormat.PlainText)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        mono = label in {"Account", "Service code", "Discretionary", "Track 1", "Track 2", "Track 3"}
        value.setProperty("role", "mono" if mono else "value")
        value.style().unpolish(value)
        value.style().polish(value)
        return value

    def _rows(self, left, right) -> list[tuple[str, str, str]]:
        first = left.view()
        second = right.view()

        def bank(card) -> str:
            if not card.bin_lookup:
                return "Not looked up."
            result = BinResult.from_dict(card.bin_lookup)
            if result.error:
                return result.error
            parts = [result.bank_name or "Bank name not listed"]
            if result.country:
                parts.append(clean_country(result.country))
            return ", ".join(parts)

        return [
            ("Exhibit", card_label(self.session, left), card_label(self.session, right)),
            ("Card type", FACE_TYPES[normalize_face(left.face_type)], FACE_TYPES[normalize_face(right.face_type)]),
            ("Brand", list_brand(first), list_brand(second)),
            ("Stripe format", first.card_type, second.card_type),
            ("Account", format_pan(first.pan) or "—", format_pan(second.pan) or "—"),
            ("Name", first.name or "—", second.name or "—"),
            ("Expiration", first.expiration_display or "—", second.expiration_display or "—"),
            ("Service code", first.service_code or "—", second.service_code or "—"),
            ("Discretionary", first.discretionary or "—", second.discretionary or "—"),
            ("Luhn", luhn_label(first.luhn), luhn_label(second.luhn)),
            ("Issuing bank", bank(left), bank(right)),
            ("Track 1", first.track1.raw or "Not present", second.track1.raw or "Not present"),
            ("Track 2", first.track2.raw or "Not present", second.track2.raw or "Not present"),
            ("Track 3", first.track3.raw or "Not present", second.track3.raw or "Not present"),
        ]
