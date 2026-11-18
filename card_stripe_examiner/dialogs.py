"""Dialogs: new case, paste, bank lookup, export and settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from card_stripe_examiner.report import ReportOptions
from card_stripe_examiner.widgets import NoScrollSpinBox, format_when, style_reject


def _dialog_frame(dialog: QDialog, title_text: str, sentence_text: str | None = None, width: int = 480):
    dialog.setWindowTitle(title_text)
    dialog.setMinimumWidth(width)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(12)
    title = QLabel(title_text)
    title.setObjectName("cardTitle")
    layout.addWidget(title)
    if sentence_text:
        sentence = QLabel(sentence_text)
        sentence.setWordWrap(True)
        sentence.setObjectName("hint")
        layout.addWidget(sentence)
    return layout


class NewSessionDialog(QDialog):
    def __init__(self, parent=None, intro: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New case")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("New case")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        sentence = QLabel(intro or "Cards you swipe are kept in this case until you save or export them.")
        sentence.setWordWrap(True)
        sentence.setObjectName("hint")
        layout.addWidget(sentence)
        form = QFormLayout()
        form.setSpacing(10)
        self.case = QLineEdit()
        self.case.setPlaceholderText("Required")
        self.examiner = QLineEdit()
        self.unit = QLineEdit()
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(72)
        self.notes.setPlaceholderText("Optional")
        form.addRow("Case number", self.case)
        form.addRow("Examiner", self.examiner)
        self.exhibit_prefix = QLineEdit()
        self.exhibit_prefix.setPlaceholderText("Optional, for example Item  or  26-1847-")
        self.first_exhibit = NoScrollSpinBox()
        self.first_exhibit.setRange(0, 999999)
        self.first_exhibit.setValue(1)
        form.addRow("Unit", self.unit)
        form.addRow("Exhibit prefix", self.exhibit_prefix)
        form.addRow("First exhibit number", self.first_exhibit)
        form.addRow("Session notes", self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        self.create = buttons.addButton("Create case", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        self.create.setEnabled(False)
        self.case.textChanged.connect(lambda text: self.create.setEnabled(bool(text.strip())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.case.setFocus()

    def values(self) -> dict:
        return {
            "case_number": self.case.text(),
            "examiner": self.examiner.text(),
            "unit": self.unit.text(),
            "notes": self.notes.toPlainText(),
            "exhibit_prefix": self.exhibit_prefix.text(),
            "first_exhibit": self.first_exhibit.value(),
        }


class PasteDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Paste swipe")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("Paste swipe")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        sentence = QLabel("Paste the raw characters the reader typed, including sentinels such as % ; + and ?.")
        sentence.setWordWrap(True)
        sentence.setObjectName("hint")
        layout.addWidget(sentence)
        self.box = QPlainTextEdit()
        self.box.setObjectName("rawBlock")
        self.box.setPlaceholderText("Paste the reader output here.")
        self.box.setMinimumHeight(140)
        layout.addWidget(self.box)
        buttons = QDialogButtonBox()
        add = buttons.addButton("Add card", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        add.setEnabled(False)
        self.box.textChanged.connect(lambda: add.setEnabled(bool(self.box.toPlainText().strip())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.box.toPlainText()


class BinConfirmDialog(QDialog):
    def __init__(self, digits: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Look up issuing bank")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("Look up issuing bank")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        sentence = QLabel(
            "These BINs are not in the offline BIN list. "
            "This sends only these digits to lookup.binlist.net. "
            "If an 8-digit prefix is not listed, the lookup retries with the first 6 digits. "
            "The rest of each account number, the cardholder name, the expiration, and the case information stay on this computer."
        )
        sentence.setWordWrap(True)
        sentence.setObjectName("hint")
        layout.addWidget(sentence)
        shown = QLabel("\n".join(digits))
        shown.setObjectName("binDigits")
        shown.setTextFormat(Qt.TextFormat.PlainText)
        shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(shown)
        buttons = QDialogButtonBox()
        label = "Send BIN" if len(digits) == 1 else "Send BINs"
        buttons.addButton(label, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ExportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export PDF")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("Export PDF")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        sentence = QLabel(
            "Choose what this PDF includes. Raw tracks contain full account numbers. "
            "The file is saved only in the folder you choose."
        )
        sentence.setWordWrap(True)
        layout.addWidget(sentence)
        cards_label = QLabel("Cards")
        cards_label.setObjectName("sectionTitle")
        layout.addWidget(cards_label)
        self.all_cards = QRadioButton("All cards")
        self.differs_only = QRadioButton("Only cards that differ from the printed card")
        self.all_cards.setChecked(True)
        layout.addWidget(self.all_cards)
        layout.addWidget(self.differs_only)
        self.mask = QCheckBox("Mask account numbers")
        self.raw = QCheckBox("Include raw tracks")
        self.raw.setChecked(True)
        raw_hint = QLabel("Raw tracks include the full swipe, including account numbers.")
        raw_hint.setObjectName("hint")
        raw_hint.setWordWrap(True)
        self.glossary = QCheckBox("Include appendix: terms used in this report")
        self.photos = QCheckBox("Include card photos")
        self.photos.setChecked(True)
        self.mask.toggled.connect(self._on_mask)
        layout.addWidget(self.mask)
        layout.addWidget(self.raw)
        layout.addWidget(raw_hint)
        layout.addWidget(self.photos)
        layout.addWidget(self.glossary)
        buttons = QDialogButtonBox()
        buttons.addButton("Choose folder", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_mask(self, on: bool) -> None:
        if on:
            self.raw.setChecked(False)

    def options(self) -> ReportOptions:
        return ReportOptions(
            differs_only=self.differs_only.isChecked(),
            mask_accounts=self.mask.isChecked(),
            include_raw=self.raw.isChecked(),
            include_glossary=self.glossary.isChecked(),
            include_photos=self.photos.isChecked(),
        )


class TokenDialog(QDialog):
    def __init__(self, token: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BIN service token")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("BIN service token")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        sentence = QLabel(
            "Optional token for lookup.binlist.net. It is stored encrypted for your Windows account and sent only "
            "as the authorization header on a BIN request."
        )
        sentence.setWordWrap(True)
        sentence.setObjectName("hint")
        layout.addWidget(sentence)
        self.token = QLineEdit(token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Leave blank if you do not have a token")
        layout.addWidget(self.token)
        buttons = QDialogButtonBox()
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        clear = buttons.addButton("Clear", QDialogButtonBox.ButtonRole.ResetRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        style_reject(clear)
        clear.clicked.connect(lambda: self.token.clear())
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self.token.text().strip()


class SpreadsheetDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = _dialog_frame(
            self,
            "Export spreadsheet",
            "One row per card with its exhibit, account, findings, printed-card comparison and issuing bank.",
        )
        self.xlsx = QRadioButton("Excel workbook (.xlsx) — keeps every digit of long account numbers")
        self.csv = QRadioButton("CSV (.csv) — for other programs; Excel may round long numbers")
        self.xlsx.setChecked(True)
        self.mask = QCheckBox("Mask account numbers")
        layout.addWidget(self.xlsx)
        layout.addWidget(self.csv)
        layout.addWidget(self.mask)
        buttons = QDialogButtonBox()
        buttons.addButton("Choose folder", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def file_format(self) -> str:
        return "xlsx" if self.xlsx.isChecked() else "csv"

    def masked(self) -> bool:
        return self.mask.isChecked()


class PacketDialog(QDialog):
    def __init__(self, unidentified: int, parent=None) -> None:
        super().__init__(parent)
        sentence = (
            "Cards grouped by issuing bank, one section per bank, with the accounts to request records for. "
            "Banks need the full account number to find their records."
        )
        if unidentified:
            sentence += (
                f" {unidentified} card{'s have' if unidentified != 1 else ' has'} no identified bank; "
                "look them up first to place them under their bank."
            )
        layout = _dialog_frame(self, "Issuer packet", sentence)
        self.mask = QCheckBox("Mask account numbers (for internal sharing only)")
        layout.addWidget(self.mask)
        buttons = QDialogButtonBox()
        buttons.addButton("Choose folder", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def masked(self) -> bool:
        return self.mask.isChecked()


class BinDatabaseDialog(QDialog):
    """Import or remove the offline BIN list."""

    def __init__(self, database, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        self.changed = False
        layout = _dialog_frame(
            self,
            "Offline BIN list",
            "Import a CSV list of BINs and issuing banks. Lookups check this list first and never leave this "
            "computer. The first row must name the columns, for example bin, issuer, brand, type, country.",
            width=520,
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.import_button = QPushButton("Import CSV")
        self.import_button.clicked.connect(self._import)
        self.remove_button = QPushButton("Remove list")
        self.remove_button.setObjectName("quiet")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.import_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        buttons = QDialogButtonBox()
        done = buttons.addButton("Done", QDialogButtonBox.ButtonRole.AcceptRole)
        style_reject(done)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self) -> None:
        info = self.database.info()
        if not info:
            self.status.setText("No offline list is installed. Lookups go to lookup.binlist.net after you confirm.")
            self.remove_button.setEnabled(False)
            return
        self.status.setText(
            f"Installed: {info.get('source_name', '—')}\n"
            f"{info.get('rows', '0')} BINs, imported {format_when(info.get('imported_at', ''))}\n"
            f"File SHA-256: {info.get('sha256', '—')}"
        )
        self.remove_button.setEnabled(True)

    def _import(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(self, "Import BIN list", "", "CSV file (*.csv *.txt)")
        if not path:
            return
        try:
            count = self.database.import_csv(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not import", str(exc))
            return
        self.changed = True
        self._refresh()
        QMessageBox.information(self, "BIN list imported", f"{count:,} BINs are available offline.")

    def _remove(self) -> None:
        try:
            self.database.clear()
        except OSError as exc:
            QMessageBox.warning(self, "Could not remove", str(exc))
            return
        self.changed = True
        self._refresh()


class RecoveryDialog(QDialog):
    """Offers cases that were open when the program last closed unexpectedly."""

    def __init__(self, recoveries: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.recoveries = recoveries
        self.action = "later"
        layout = _dialog_frame(
            self,
            "Recover unsaved case",
            "The program closed before these cases were saved. Recover one to keep its swipes.",
            width=540,
        )
        self.items = QListWidget()
        self.items.setObjectName("cardList")
        for entry in recoveries:
            text = (
                f"Case {entry['case_number']}   ·   {entry['cards']} card{'s' if entry['cards'] != 1 else ''}\n"
                f"Last autosaved {format_when(entry['saved_at'])}"
            )
            item = QListWidgetItem(text)
            self.items.addItem(item)
        self.items.setCurrentRow(0)
        layout.addWidget(self.items)
        buttons = QDialogButtonBox()
        recover = buttons.addButton("Recover", QDialogButtonBox.ButtonRole.AcceptRole)
        discard = buttons.addButton("Discard", QDialogButtonBox.ButtonRole.DestructiveRole)
        later = buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
        style_reject(discard)
        style_reject(later)
        recover.clicked.connect(lambda: self._done("recover"))
        discard.clicked.connect(lambda: self._done("discard"))
        later.clicked.connect(lambda: self._done("later"))
        layout.addWidget(buttons)

    def _done(self, action: str) -> None:
        self.action = action
        if action == "recover":
            self.accept()
        else:
            self.reject()

    def selected(self) -> dict | None:
        row = self.items.currentRow()
        return self.recoveries[row] if 0 <= row < len(self.recoveries) else None
