"""Card Stripe Examiner window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QSettings,
    Qt,
    QSize,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from card_stripe_examiner import __version__, autosave, protect
from card_stripe_examiner.bin_lookup import DiskCache, prompt_digits
from card_stripe_examiner.capture import ReaderCapture
from card_stripe_examiner.exports import UNIDENTIFIED, issuer_groups, write_csv, write_issuer_packet, write_xlsx
from card_stripe_examiner.offline_bins import OfflineBinDatabase
from card_stripe_examiner.parse import all_tracks_failed, list_brand, luhn_label, parse_swipe
from card_stripe_examiner.report import ReportOptions, write_pdf
from card_stripe_examiner.session import (
    PHOTO_SIDES,
    add_card,
    add_photo,
    card_label,
    cards_for_report,
    face_findings,
    has_duplicates,
    photo_path,
    remove_photo,
    load_session,
    new_session,
    normalize_printed,
    printed_differs,
    automatic_exhibit_number,
    case_store,
    in_store,
    store_path,
    remove_card_and_renumber,
    save_session,
)
from card_stripe_examiner.theme import STYLESHEET, app_icon
from card_stripe_examiner.widgets import (
    format_when,
    format_clock,
    safe_filename,
    masked_last_four,
    apply_kind,
    style_reject,
)
from card_stripe_examiner.camera import CameraDialog, capture_name, save_capture
from card_stripe_examiner.dialogs import (
    NewSessionDialog,
    PasteDialog,
    BinConfirmDialog,
    BinDatabaseDialog,
    ExportDialog,
    PacketDialog,
    RecoveryDialog,
    SpreadsheetDialog,
    TokenDialog,
)
from card_stripe_examiner.tabs import (
    SummaryTab,
    TracksTab,
    RawTab,
    CompareTab,
)
from card_stripe_examiner.glossary_page import GlossaryPage
from card_stripe_examiner.workers import LookupThread


class MainWindow(QMainWindow):
    def __init__(self, check_recovery: bool = True) -> None:
        super().__init__()
        self._check_recovery = check_recovery
        self.settings = QSettings("CardStripeExaminer", "CardStripeExaminer")
        self.session = None
        self.dirty = False
        self._selected_id = None
        self._compare_anchor = None
        self._pending_raw = None
        self._flashing = False
        self._lookup_running = False
        self._worker = None
        self._token = protect.load_token(self.settings)
        self.cache = DiskCache()
        self.offline = OfflineBinDatabase()
        self.reader = ReaderCapture()
        self.setWindowTitle("Card Stripe Examiner")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self._build()
        self.reader.swipe_ready.connect(self.add_swipe)
        self.reader.bound.connect(lambda _name: self._refresh_status())
        self.reader.unavailable.connect(self._reader_unavailable)
        self.reader.activity.connect(lambda: self._set_status("warn", "Reading swipe"))
        self.reader.rejected.connect(lambda message: self._flash("bad", message))
        QApplication.instance().installEventFilter(self)
        self.reader.attach(int(self.winId()))
        self._refresh_status()
        QShortcut(QKeySequence.StandardKey.Save, self, self.save_session)
        QShortcut(QKeySequence.StandardKey.New, self, self.new_session)
        QShortcut(QKeySequence.StandardKey.Open, self, self.open_session)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(autosave.INTERVAL_MS)
        self.autosave_timer.timeout.connect(lambda: self._autosave())
        self.autosave_timer.start()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_header())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_workspace())
        self.glossary_page = GlossaryPage()
        self.glossary_page.back_requested.connect(self.show_case)
        self.stack.addWidget(self.glossary_page)
        shell.addWidget(self.stack, 1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header.setStyleSheet(
            "QWidget#header { background: #1B2838; }"
            "QLabel#appTitle { color: #F8FAFC; font-size: 18px; font-weight: 600; background: transparent; }"
            "QLabel#headerMeta, QLabel#headerNotes { color: #D5DEE8; font-size: 13px; background: transparent; }"
            "QPushButton#headerButton { background: transparent; color: #F8FAFC; border: 1px solid rgba(255,255,255,0.35);"
            " border-radius: 6px; padding: 6px 12px; font-weight: 600; }"
            "QPushButton#headerButton:hover { background: rgba(255,255,255,0.10); }"
            "QPushButton#headerPrimary { background: #F8FAFC; color: #1B2838; border: none;"
            " border-radius: 6px; padding: 6px 14px; font-weight: 600; }"
            "QPushButton#headerPrimary:hover { background: #E8EEF4; }"
        )
        layout = QVBoxLayout(header)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("Card Stripe Examiner")
        title.setObjectName("appTitle")
        self.meta = QLabel("No case open")
        self.meta.setObjectName("headerMeta")
        self.notes = QLabel()
        self.notes.setObjectName("headerNotes")
        self.notes.setWordWrap(True)
        self.notes.setVisible(False)
        titles.addWidget(title)
        titles.addWidget(self.meta)
        titles.addWidget(self.notes)
        top.addLayout(titles, 1)
        self.identify_button = QPushButton("Identify reader")
        self.identify_button.setObjectName("headerButton")
        self.identify_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.identify_button.setToolTip("Swipe once so this case listens only to that reader.")
        self.identify_button.clicked.connect(lambda: self.identify_reader())
        self.status_pill = QLabel("No case")
        self.status_pill.setObjectName("statusPill")
        apply_kind(self.status_pill, "idle")
        top.addWidget(self.identify_button, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.new_button = self._header_button("New", self.new_session, "New case (Ctrl+N)")
        self.open_button = self._header_button("Open", self.open_session, "Open a saved case (Ctrl+O)")
        self.save_button = self._header_button("Save", self.save_session, "Save this case to the case store (Ctrl+S)")
        self.folder_button = self._header_button(
            "Case folder", self.open_case_folder, "Show this case's folder (case file and photos) in File Explorer"
        )
        self.glossary_button = self._header_button("Glossary", self.show_glossary, "Definitions for the fields in this case")
        self.sheet_button = self._header_button(
            "Spreadsheet", self.export_spreadsheet, "Export one row per card to Excel or CSV"
        )
        self.packet_button = self._header_button(
            "Issuer packet", self.export_packet, "Cards grouped by issuing bank, for records requests"
        )
        self.export_button = self._header_button("Export PDF", self.export_pdf, "Export a case report", primary=True)
        for button in (self.new_button, self.open_button, self.save_button, self.folder_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.glossary_button)
        buttons.addWidget(self.sheet_button)
        buttons.addWidget(self.packet_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)
        self.save_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.sheet_button.setEnabled(False)
        self.packet_button.setEnabled(False)
        return header

    def _header_button(self, text: str, slot, tip: str, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("headerPrimary" if primary else "headerButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        button.clicked.connect(lambda _checked=False, target=slot: target())
        return button

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace.setObjectName("workspace")
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 860])
        layout.addWidget(splitter)
        return workspace

    def _build_list(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 8, 16)
        layout.setSpacing(10)
        title_row = QHBoxLayout()
        heading = QLabel("Cards")
        heading.setObjectName("paneTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("hint")
        title_row.addWidget(heading)
        title_row.addStretch()
        title_row.addWidget(self.count_label)
        layout.addLayout(title_row)
        self.list_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        message = QLabel("Swipe a card to add it to this case.")
        message.setObjectName("emptyState")
        message.setWordWrap(True)
        empty_layout.addStretch()
        empty_layout.addWidget(message)
        empty_layout.addStretch()
        self.card_list = QListWidget()
        self.card_list.setObjectName("cardList")
        self.card_list.currentItemChanged.connect(lambda _current, _previous: self._on_select())
        self.list_stack.addWidget(empty)
        self.list_stack.addWidget(self.card_list)
        layout.addWidget(self.list_stack, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.paste_button = QPushButton("Paste swipe")
        self.paste_button.setObjectName("quiet")
        self.paste_button.clicked.connect(lambda: self.paste_swipe())
        self.remove_button = QPushButton("Remove card")
        self.remove_button.setObjectName("quiet")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(lambda: self.remove_selected_card())
        actions.addWidget(self.paste_button)
        actions.addWidget(self.remove_button)
        hint = QLabel("Click Identify reader and swipe. The card is captured from the reader itself.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addLayout(actions)
        layout.addWidget(hint)
        return panel

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("detailRoot")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 16, 16, 16)
        self.detail_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        message = QLabel("Select a card to see the account, the stripe fields, and the raw tracks.")
        message.setObjectName("emptyState")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        empty_layout.addWidget(message)
        empty_layout.addStretch()
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(8)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.card_title = QLabel()
        self.card_title.setObjectName("cardTitle")
        self.card_subtitle = QLabel()
        self.card_subtitle.setObjectName("cardSubtitle")
        titles.addWidget(self.card_title)
        titles.addWidget(self.card_subtitle)
        heading.addLayout(titles, 1)
        self.printed_chip = QLabel("Differs from printed card")
        self.printed_chip.setObjectName("chip")
        apply_kind(self.printed_chip, "bad")
        self.printed_chip.setVisible(False)
        self.differ_chip = QLabel("Tracks differ")
        self.differ_chip.setObjectName("chip")
        apply_kind(self.differ_chip, "warn")
        self.luhn_chip = QLabel()
        self.luhn_chip.setObjectName("chip")
        self.read_chip = QLabel("Read error")
        self.read_chip.setObjectName("chip")
        apply_kind(self.read_chip, "bad")
        self.read_chip.setVisible(False)
        self.face_chip = QLabel("Card type does not fit stripe")
        self.face_chip.setObjectName("chip")
        apply_kind(self.face_chip, "bad")
        self.face_chip.setVisible(False)
        self.dup_chip = QLabel("Account on another card")
        self.dup_chip.setObjectName("chip")
        apply_kind(self.dup_chip, "warn")
        self.dup_chip.setVisible(False)
        heading.addWidget(self.read_chip, 0, Qt.AlignmentFlag.AlignTop)
        heading.addWidget(self.face_chip, 0, Qt.AlignmentFlag.AlignTop)
        heading.addWidget(self.dup_chip, 0, Qt.AlignmentFlag.AlignTop)
        heading.addWidget(self.printed_chip, 0, Qt.AlignmentFlag.AlignTop)
        heading.addWidget(self.differ_chip, 0, Qt.AlignmentFlag.AlignTop)
        heading.addWidget(self.luhn_chip, 0, Qt.AlignmentFlag.AlignTop)
        detail_layout.addLayout(heading)
        self.summary = SummaryTab()
        self.tracks = TracksTab()
        self.raw = RawTab()
        self.compare = CompareTab()
        self.summary.note_changed.connect(self._on_note)
        self.summary.printed_changed.connect(self._on_printed)
        self.summary.lookup_requested.connect(self.lookup_current)
        self.summary.lookup_all_requested.connect(self.lookup_all)
        self.summary.token_requested.connect(self.edit_token)
        self.summary.bin_database_requested.connect(self.edit_bin_database)
        self.summary.exhibit_changed.connect(self._on_exhibit)
        self.summary.exhibit_committed.connect(self._on_exhibit_committed)
        self.summary.face_changed.connect(self._on_face)
        self.summary.photo_add_requested.connect(self.add_card_photo)
        self.summary.photo_capture_requested.connect(self.capture_card_photo)
        self.summary.photo_remove_requested.connect(self.remove_card_photo)
        self.summary.photo_open_requested.connect(self.open_card_photo)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.tracks, "Tracks")
        self.tabs.addTab(self.raw, "Raw")
        self.tabs.addTab(self.compare, "Compare")
        detail_layout.addWidget(self.tabs, 1)
        self.detail_stack.addWidget(empty)
        self.detail_stack.addWidget(detail)
        layout.addWidget(self.detail_stack)
        return panel

    def _set_status(self, kind: str, text: str) -> None:
        self.status_pill.setText(text)
        apply_kind(self.status_pill, kind)

    def _refresh_status(self) -> None:
        if self._flashing or self._lookup_running:
            return
        if self.reader.identifying:
            self._set_status("warn", "Swipe the reader once")
        elif self.session is None:
            self._set_status("idle", "No case")
        elif self.reader.listening:
            self._set_status("listening", "Listening")
        else:
            self._set_status("idle", "Reader not identified")

    def _flash(self, kind: str, text: str) -> None:
        self._flashing = True
        self._set_status(kind, text)
        QTimer.singleShot(3500, self._end_flash)

    def _end_flash(self) -> None:
        self._flashing = False
        self._refresh_status()

    def _reader_unavailable(self) -> None:
        self._refresh_status()

    def _refresh_header(self) -> None:
        if self.session is None:
            self.setWindowTitle("Card Stripe Examiner")
            self.meta.setText("No case open")
            self.notes.setVisible(False)
            self.save_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.sheet_button.setEnabled(False)
            self.packet_button.setEnabled(False)
            return
        self.setWindowTitle(f"Card Stripe Examiner — {self.session.case_number}")
        parts = [f"Case {self.session.case_number}"]
        if self.session.examiner:
            parts.append(self.session.examiner)
        if self.session.unit:
            parts.append(self.session.unit)
        self.meta.setText("   ·   ".join(parts))
        self.notes.setVisible(bool(self.session.notes))
        self.notes.setText(self.session.notes)
        self.save_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.sheet_button.setEnabled(True)
        self.packet_button.setEnabled(True)

    def _refresh_list(self) -> None:
        self.card_list.blockSignals(True)
        self.card_list.clear()
        cards = self.session.cards if self.session else []
        self.list_stack.setCurrentIndex(1 if cards else 0)
        self.count_label.setText(str(len(cards)) if cards else "")
        self.remove_button.setEnabled(bool(self._selected_id) and bool(cards))
        selected = None
        for card in cards:
            parsed = card.view()
            line_one = f"{card_label(self.session, card)}    {list_brand(parsed)}    {masked_last_four(parsed.pan)}"
            details = [format_clock(card.swiped_at), luhn_label(parsed.luhn)]
            flags = []
            if parsed.tracks_read_error:
                flags.append("Read error")
            if printed_differs(card):
                flags.append("Differs from printed card")
            if face_findings(card):
                flags.append("Card type mismatch")
            if parsed.comparison.tracks_differ:
                flags.append("Tracks differ")
            if has_duplicates(self.session, card):
                flags.append("Duplicate")
            lines = [line_one, "  ·  ".join(details)]
            if flags:
                lines.append("  ·  ".join(flags))
            item = QListWidgetItem("\n".join(lines))
            item.setData(Qt.ItemDataRole.UserRole, card.id)
            item.setSizeHint(QSize(240, 22 + 18 * len(lines)))
            self.card_list.addItem(item)
            if card.id == self._selected_id:
                selected = item
        if selected is not None:
            self.card_list.setCurrentItem(selected)
        self.card_list.blockSignals(False)

    def _card(self, card_id: str):
        if not self.session:
            return None
        for card in self.session.cards:
            if card.id == card_id:
                return card
        return None

    def _current(self):
        return self._card(self._selected_id) if self._selected_id else None

    def _show_empty_detail(self) -> None:
        self.detail_stack.setCurrentIndex(0)
        self.remove_button.setEnabled(False)

    def _show_card(self, card, follow_compare: bool = False) -> None:
        parsed = card.view()
        self.detail_stack.setCurrentIndex(1)
        self.card_title.setText(
            f"{card_label(self.session, card)}    {list_brand(parsed)}    {masked_last_four(parsed.pan)}"
        )
        self.card_subtitle.setText(
            f"{parsed.card_type}   ·   Swiped {format_when(card.swiped_at)}   ·   {luhn_label(parsed.luhn)}"
        )
        kind = {"Pass": "listening", "Fail": "bad"}.get(parsed.luhn, "idle")
        self.luhn_chip.setText(luhn_label(parsed.luhn))
        apply_kind(self.luhn_chip, kind)
        self.printed_chip.setVisible(printed_differs(card))
        self.differ_chip.setVisible(parsed.comparison.tracks_differ)
        self._refresh_chips(card)
        self.summary.show_card(card, lookup_enabled=not self._lookup_running, session=self.session)
        self.tracks.show_card(card)
        self.raw.show_card(card)
        follow = follow_compare or self._compare_anchor != card.id
        self._compare_anchor = card.id
        self.compare.set_session(self.session, card.id, follow)
        self._selected_id = card.id

    def _on_select(self) -> None:
        item = self.card_list.currentItem()
        if item is None:
            return
        card = self._card(item.data(Qt.ItemDataRole.UserRole))
        if card is not None:
            self._show_card(card, follow_compare=True)

    def _on_note(self, text: str) -> None:
        card = self._current()
        if card is None or card.note == text:
            return
        card.note = text
        self.dirty = True

    def _on_printed(self, payload: dict) -> None:
        card = self._current()
        if card is None:
            return
        card.printed = normalize_printed(payload)
        self.dirty = True
        self.printed_chip.setVisible(printed_differs(card))
        self._refresh_list()
        self.summary.set_findings(card)

    def _refresh_chips(self, card) -> None:
        parsed = card.view()
        self.read_chip.setVisible(bool(parsed.tracks_read_error))
        self.face_chip.setVisible(bool(face_findings(card)))
        self.dup_chip.setVisible(has_duplicates(self.session, card))

    def _on_exhibit(self, text: str) -> None:
        card = self._current()
        if card is None or card.exhibit == text:
            return
        card.exhibit = text
        self.dirty = True

    def _on_exhibit_committed(self) -> None:
        card = self._current()
        if card is None:
            return
        parsed = card.view()
        self.card_title.setText(
            f"{card_label(self.session, card)}    {list_brand(parsed)}    {masked_last_four(parsed.pan)}"
        )
        self._refresh_list()
        self.summary.set_findings(card)
        self.compare.set_session(self.session, card.id, False)

    def _on_face(self, face: str) -> None:
        card = self._current()
        if card is None or card.face_type == face:
            return
        card.face_type = face
        self.dirty = True
        self._refresh_chips(card)
        self._refresh_list()
        self.summary.set_findings(card)

    def _ready_for_photos(self) -> bool:
        """Photos live beside the case file, so the case must be saved first."""
        if self.session is None or self._current() is None:
            return False
        if self.session.path and in_store(self.session.path):
            return True
        # Photos are kept in the case's folder, so save the case there first.
        return self.save_session()

    def capture_card_photo(self, side: str) -> None:
        if not self._ready_for_photos():
            return
        card = self._current()
        dialog = CameraDialog(PHOTO_SIDES.get(side, "Photo"), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        image = dialog.image()
        if image is None or image.isNull():
            return
        try:
            temporary = save_capture(image)
            try:
                add_photo(self.session, card, temporary, side, origin="camera", original_name=capture_name())
            finally:
                try:
                    temporary.unlink()
                    temporary.parent.rmdir()
                except OSError:
                    pass
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not add photo", str(exc))
            return
        self.dirty = True
        self._show_card(card)
        self._autosave(force=True)

    def add_card_photo(self, side: str) -> None:
        if not self._ready_for_photos():
            return
        card = self._current()
        path, _selected = QFileDialog.getOpenFileName(
            self,
            f"Import {side} photo",
            "",
            "Photos (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp)",
        )
        if not path:
            return
        try:
            add_photo(self.session, card, path, side)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not add photo", str(exc))
            return
        self.dirty = True
        self._show_card(card)
        self._autosave(force=True)

    def remove_card_photo(self, file: str) -> None:
        card = self._current()
        if card is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Remove this photo?")
        box.setText(
            "Take this photo off the card? The case's copy of the photo is deleted from the case folder when you "
            "save. An imported photo's original file is not affected."
        )
        box.addButton("Remove", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        style_reject(cancel)
        box.exec()
        if box.clickedButton() is cancel:
            return
        if remove_photo(card, file, self.session):
            self.dirty = True
            self._show_card(card)
            self._autosave(force=True)

    def open_card_photo(self, file: str) -> None:
        card = self._current()
        if self.session is None or card is None:
            return
        for photo in card.photos:
            if photo.get("file") == file:
                path = photo_path(self.session, photo)
                if path is None or not path.exists():
                    QMessageBox.warning(self, "Photo not found", f"The photo file was not found:\n{file}")
                    return
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return

    def create_session(
        self,
        case_number: str,
        examiner: str = "",
        unit: str = "",
        notes: str = "",
        exhibit_prefix: str = "",
        first_exhibit: int = 1,
    ) -> None:
        self.session = new_session(
            case_number,
            examiner,
            unit,
            notes,
            exhibit_prefix=exhibit_prefix,
            first_exhibit=first_exhibit,
        )
        self.dirty = False
        self._selected_id = None
        self._compare_anchor = None
        self._refresh_header()
        self._refresh_list()
        self._show_empty_detail()
        self.compare.set_session(self.session, None, True)
        self._refresh_status()

    def new_session(self) -> None:
        if not self._confirm_discard():
            return
        intro = "A card was just read. Enter a case number to keep it." if self._pending_raw else None
        dialog = NewSessionDialog(self, intro)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if self._pending_raw:
                self._pending_raw = None
                QMessageBox.information(
                    self,
                    "Swipe not kept",
                    "The swipe was not added because no case is open.",
                )
            return
        values = dialog.values()
        self.create_session(
            values["case_number"],
            values["examiner"],
            values["unit"],
            values["notes"],
            values.get("exhibit_prefix", ""),
            values.get("first_exhibit", 1),
        )
        if self._pending_raw:
            raw = self._pending_raw
            self._pending_raw = None
            self.add_swipe(raw)

    def add_swipe(self, raw: str):
        if self.session is None:
            self._pending_raw = raw
            self.new_session()
            return None
        text = (raw or "").strip()
        if not text:
            self._flash("bad", "Empty read")
            return None
        if all_tracks_failed(parse_swipe(text)):
            self._flash("bad", "Read error on every track — swipe again")
            return None
        card = add_card(self.session, text)
        self.dirty = True
        self._selected_id = card.id
        self._refresh_list()
        self._show_card(card, follow_compare=True)
        parsed = card.view()
        if parsed.tracks_read_error:
            self._flash("bad", f"{', '.join(parsed.tracks_read_error)} read error — swipe again")
        elif has_duplicates(self.session, card):
            self._flash("warn", "Account number already in this case")
        elif not any(sentinel in text for sentinel in "%;+"):
            self._flash("warn", "No sentinels — saved as raw")
        else:
            self._refresh_status()
        self._autosave(force=True)
        return card.id

    def paste_swipe(self) -> None:
        dialog = PasteDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.add_swipe(dialog.text())

    def remove_selected_card(self) -> None:
        if self.session is None:
            return
        card = self._current()
        if card is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Remove this card?")
        later = [
            other
            for other in self.session.cards[self.session.cards.index(card) + 1 :]
            if automatic_exhibit_number(self.session, other.exhibit) is not None
        ]
        text = "Remove this card from the case? This does not change the saved file until you save."
        if card.photos:
            count = len(card.photos)
            text += (
                f"\n\nIts {count} photo{'s' if count != 1 else ''} will be deleted from the case folder when you save. "
                "An imported photo's original file is not affected."
            )
        if later and automatic_exhibit_number(self.session, card.exhibit) is not None:
            text += (
                f"\n\nThe {len(later)} card{'s' if len(later) != 1 else ''} swiped after it will be renumbered "
                "so the exhibit numbers have no gap."
            )
        box.setText(text)
        box.addButton("Remove", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        style_reject(cancel)
        box.exec()
        if box.clickedButton() is cancel:
            return
        index, renumbered = remove_card_and_renumber(self.session, card.id)
        self.dirty = True
        if index < 0:
            return
        if renumbered:
            first_old, first_new = renumbered[0]
            more = f" and {len(renumbered) - 1} more" if len(renumbered) > 1 else ""
            self._flash("warn", f"Renumbered: {first_old} is now {first_new}{more}")
        self._autosave(force=True)
        if self.session.cards:
            next_card = self.session.cards[min(index, len(self.session.cards) - 1)]
            self._selected_id = next_card.id
            self._refresh_list()
            self._show_card(next_card, follow_compare=True)
        else:
            self._selected_id = None
            self._compare_anchor = None
            self._refresh_list()
            self._show_empty_detail()
            self.compare.set_session(self.session, None, True)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and QApplication.activeModalWidget() is None:
            if self.reader.take_legacy_key():
                return True
            enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or event.text() in "\r\n"
            focus = QApplication.focusWidget()
            focus_is_text = isinstance(focus, (QPlainTextEdit, QLineEdit))
            if self.reader.offer_qt_key(event.text(), enter, focus_is_text, event.isAutoRepeat()):
                return True
        return super().eventFilter(watched, event)

    def identify_reader(self) -> None:
        self.reader.attach(int(self.winId()))
        self.reader.begin_identify()
        self.activateWindow()
        self.raise_()
        self._set_status("warn", "Swipe the reader once")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.reader.attach(int(self.winId()))
        if self._check_recovery:
            self._check_recovery = False
            QTimer.singleShot(0, self._offer_recovery)

    def _autosave(self, force: bool = False) -> None:
        if self.session is None or not (self.dirty or force):
            return
        try:
            autosave.write_recovery(self.session)
        except OSError:
            pass

    def _clear_recovery(self) -> None:
        try:
            autosave.clear_recovery(self.session)
        except OSError:
            pass

    def _offer_recovery(self) -> None:
        found = autosave.find_recoveries()
        if not found or self.session is not None:
            return
        dialog = RecoveryDialog(found, self)
        dialog.exec()
        entry = dialog.selected()
        if entry is None or dialog.action == "later":
            return
        if dialog.action == "discard":
            box = QMessageBox(self)
            box.setWindowTitle("Discard unsaved case?")
            box.setText(f"Discard the unsaved swipes in case {entry['case_number']}? This cannot be undone.")
            discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
            cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            style_reject(cancel)
            box.exec()
            if box.clickedButton() is discard:
                autosave.discard_recovery(entry["file"])
            return
        try:
            session = autosave.load_recovery(entry["file"])
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not recover", str(exc))
            return
        self._load_into_window(session, dirty=True)

    def nativeEvent(self, eventType, message):  # noqa: N802
        self.reader.handle_native(message)
        return super().nativeEvent(eventType, message)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Save this case?")
        box.setText("Save changes to this case before continuing?")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Don't save", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel:
            return False
        if clicked is save:
            return self.save_session()
        self._clear_recovery()
        return True

    def _save_target(self) -> str | None:
        """Where this case is saved: its folder in the case store. None if the user cancels."""
        current = self.session.path
        if current and in_store(current):
            return current
        target = store_path(self.session.case_number)
        if not target.exists():
            return str(target)
        box = QMessageBox(self)
        box.setWindowTitle("A case with this number is already saved")
        box.setText(
            f"A case numbered {self.session.case_number} is already saved in the case store:\n{target.parent}\n\n"
            "Replace that saved case with this one, or save this one as a separate copy?"
        )
        copy = box.addButton("Save as a separate copy", QMessageBox.ButtonRole.AcceptRole)
        replace = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        style_reject(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace:
            return str(target)
        if clicked is copy:
            number = 2
            while store_path(self.session.case_number, copy=number).exists():
                number += 1
            return str(store_path(self.session.case_number, copy=number))
        return None

    def save_session(self) -> bool:
        if self.session is None:
            return False
        previous = self.session.path
        target = self._save_target()
        if target is None:
            return False
        try:
            save_session(self.session, target)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return False
        self.dirty = False
        self._clear_recovery()
        if previous and not in_store(previous):
            QMessageBox.information(
                self,
                "Case saved to the case store",
                f"This case is now saved in:\n{Path(target).parent}\n\n"
                f"The file you opened was not changed:\n{previous}",
            )
        else:
            self._flash("listening", "Saved")
        return True

    def save_session_as(self) -> bool:
        return self.save_session()

    def open_case_folder(self) -> None:
        folder = Path(self.session.path).parent if self.session and self.session.path else case_store()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_session(self) -> None:
        if not self._confirm_discard():
            return
        store = case_store()
        store.mkdir(parents=True, exist_ok=True)
        path, _selected = QFileDialog.getOpenFileName(self, "Open case", str(store), "Card session (*.json)")
        if not path:
            return
        try:
            session = load_session(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not open", str(exc))
            return
        self._load_into_window(session, dirty=False)

    def _load_into_window(self, session, dirty: bool = False) -> None:
        self.session = session
        self.dirty = dirty
        self._selected_id = self.session.cards[-1].id if self.session.cards else None
        self._compare_anchor = None
        self._refresh_header()
        self._refresh_list()
        current = self._current()
        if current:
            self._show_card(current, follow_compare=True)
        else:
            self._show_empty_detail()
        self.show_case()
        self._refresh_status()

    def export_pdf(self) -> None:
        if self.session is None:
            return
        dialog = ExportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.options()
        selected = cards_for_report(self.session, options.differs_only)
        if not selected:
            QMessageBox.information(
                self,
                "Nothing to export",
                "No cards in this case differ from the printed card.",
            )
            return
        default = f"{safe_filename(self.session.case_number)}-stripe-report.pdf"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            self._export_title(options),
            default,
            "PDF report (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.export_to(path, options)
        except OSError as exc:
            QMessageBox.warning(self, "Could not export", str(exc))
            return
        QMessageBox.information(self, "Report saved", self._export_saved_message(options))

    def _export_title(self, options: ReportOptions) -> str:
        if options.mask_accounts and not options.include_raw:
            return "Save PDF — account numbers are masked"
        if options.include_raw:
            return "Save PDF — contains full account numbers"
        return "Save PDF — contains full account numbers"

    def _export_saved_message(self, options: ReportOptions) -> str:
        if options.include_raw:
            if options.mask_accounts:
                return "The PDF was saved. Raw tracks contain full account numbers."
            return "The PDF was saved. It contains full account numbers."
        if options.mask_accounts:
            return "The PDF was saved. Account numbers are masked."
        return "The PDF was saved. It contains full account numbers."

    def export_to(self, path: str, options: ReportOptions | bool = False) -> None:
        if self.session is None:
            raise RuntimeError("No case is open.")
        if isinstance(options, bool):
            options = ReportOptions(include_glossary=options)
        write_pdf(self.session, path, options)

    def export_spreadsheet(self) -> None:
        if self.session is None:
            return
        dialog = SpreadsheetDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        extension = dialog.file_format()
        masked = dialog.masked()
        default = f"{safe_filename(self.session.case_number)}-cards.{extension}"
        label = "Excel workbook (*.xlsx)" if extension == "xlsx" else "CSV file (*.csv)"
        title = "Save spreadsheet — account numbers are masked" if masked else "Save spreadsheet — contains full account numbers"
        path, _selected = QFileDialog.getSaveFileName(self, title, default, label)
        if not path:
            return
        if not path.lower().endswith(f".{extension}"):
            path += f".{extension}"
        try:
            if extension == "xlsx":
                count = write_xlsx(self.session, path, mask=masked)
            else:
                count = write_csv(self.session, path, mask=masked)
        except OSError as exc:
            QMessageBox.warning(self, "Could not export", str(exc))
            return
        note = "Account numbers are masked." if masked else "It contains full account numbers."
        QMessageBox.information(self, "Spreadsheet saved", f"{count} card{'s' if count != 1 else ''} exported. {note}")

    def export_packet(self) -> None:
        if self.session is None:
            return
        groups = issuer_groups(self.session)
        if not groups:
            QMessageBox.information(self, "Nothing to export", "No card in this case has an account number.")
            return
        unidentified = sum(len(cards) for name, _bank, cards in groups if name == UNIDENTIFIED)
        dialog = PacketDialog(unidentified, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        masked = dialog.masked()
        default = f"{safe_filename(self.session.case_number)}-issuer-packet.pdf"
        title = "Save issuer packet — account numbers are masked" if masked else "Save issuer packet — contains full account numbers"
        path, _selected = QFileDialog.getSaveFileName(self, title, default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            banks = write_issuer_packet(self.session, path, mask=masked)
        except OSError as exc:
            QMessageBox.warning(self, "Could not export", str(exc))
            return
        QMessageBox.information(
            self,
            "Issuer packet saved",
            f"The packet lists {banks} issuer group{'s' if banks != 1 else ''}. "
            + ("Account numbers are masked." if masked else "It contains full account numbers."),
        )

    def show_glossary(self) -> None:
        self.stack.setCurrentIndex(1)

    def show_case(self) -> None:
        self.stack.setCurrentIndex(0)

    def select_tab(self, name: str) -> None:
        labels = ["Summary", "Tracks", "Raw", "Compare"]
        self.tabs.setCurrentIndex(labels.index(name))

    def edit_token(self) -> None:
        dialog = TokenDialog(self._token, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._token = dialog.value()
        if not protect.save_token(self.settings, self._token):
            QMessageBox.information(
                self,
                "Token kept for this session",
                "The token could not be stored securely on this system. It will be used until the program closes.",
            )

    def edit_bin_database(self) -> None:
        dialog = BinDatabaseDialog(self.offline, self)
        dialog.exec()

    def lookup_current(self) -> None:
        card = self._current()
        if card is not None:
            self._start_lookup([card])

    def lookup_all(self) -> None:
        if self.session is not None:
            self._start_lookup(list(self.session.cards))

    def _start_lookup(self, cards) -> None:
        if self._lookup_running:
            return
        ready = []
        needed = []
        seen = []
        for card in cards:
            parsed = card.view()
            digits = prompt_digits(parsed.pan)
            if not digits:
                continue
            offline = self.offline.lookup(parsed.pan)
            if offline is not None:
                ready.append((card.id, offline.to_dict()))
                continue
            cached = self.cache.get(digits)
            if cached is not None:
                ready.append((card.id, cached.to_dict()))
            else:
                if digits not in seen:
                    seen.append(digits)
                needed.append((card.id, parsed.pan))
        for card_id, payload in ready:
            found = self._card(card_id)
            if found is not None:
                found.bin_lookup = payload
                self.dirty = True
        if not needed:
            current = self._current()
            if current is not None and ready:
                self._show_card(current)
            return
        dialog = BinConfirmDialog(seen, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            current = self._current()
            if current is not None and ready:
                self._show_card(current)
            return
        self._lookup_running = True
        self._set_status("warn", "Looking up BIN")
        current = self._current()
        if current is not None:
            self.summary.show_card(current, lookup_enabled=False, session=self.session)
        self._worker = LookupThread(needed, self._token.strip() or None, self.cache)
        self._worker.finished_ok.connect(self._lookup_finished)
        self._worker.start()

    def _lookup_finished(self, results) -> None:
        for card_id, payload in results:
            card = self._card(card_id)
            if card is not None:
                card.bin_lookup = payload
        self.dirty = True
        self._lookup_running = False
        self._worker = None
        current = self._current()
        if current is not None:
            self._show_card(current)
        self._refresh_status()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        QApplication.instance().removeEventFilter(self)
        event.accept()


def _set_windows_app_id() -> None:
    """Group the window under its own taskbar button with the program icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CardStripeExaminer.App")
    except Exception:
        pass


def main() -> None:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
    app.setApplicationName("Card Stripe Examiner")
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
