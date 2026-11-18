"""Visual system for the case workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

STYLESHEET = """
QMainWindow, QDialog {
    background: #F4F6F8;
    font-family: "Segoe UI";
    color: #1E293B;
}
QWidget#workspace, QWidget#glossaryPage, QWidget#detailRoot, QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
}
QWidget#header {
    background: #1B2838;
}
QLabel#appTitle {
    color: #F8FAFC;
    font-size: 18px;
    font-weight: 600;
    background: transparent;
}
QLabel#headerMeta, QLabel#headerNotes {
    color: #D5DEE8;
    font-size: 13px;
    background: transparent;
}
QLabel#statusPill {
    border-radius: 11px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 12px;
}
QLabel#statusPill[kind="listening"] {
    background: #CCFBF1;
    color: #115E59;
}
QLabel#statusPill[kind="idle"] {
    background: #E2E8F0;
    color: #334155;
}
QLabel#statusPill[kind="warn"] {
    background: #FEF3C7;
    color: #92400E;
}
QLabel#statusPill[kind="bad"] {
    background: #FEE2E2;
    color: #991B1B;
}
QPushButton#headerButton, QPushButton#headerPrimary {
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton#headerButton {
    background: transparent;
    color: #F8FAFC;
    border: 1px solid rgba(255, 255, 255, 0.28);
}
QPushButton#headerButton:hover {
    background: rgba(255, 255, 255, 0.08);
}
QPushButton#headerPrimary {
    background: #F8FAFC;
    color: #1B2838;
    border: none;
}
QPushButton#headerPrimary:hover {
    background: #E8EEF4;
}
QPushButton {
    background: #1B2838;
    color: #F8FAFC;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #243447;
}
QPushButton:disabled {
    background: #E2E8F0;
    color: #94A3B8;
}
QPushButton#quiet {
    background: #FFFFFF;
    color: #1B2838;
    border: 1px solid #CBD5E1;
}
QPushButton#quiet:hover {
    background: #F8FAFC;
}
QFrame#panel {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}
QLabel#sectionTitle {
    font-size: 13px;
    font-weight: 600;
    color: #334155;
}
QLabel#paneTitle {
    font-size: 16px;
    font-weight: 600;
    color: #334155;
}
QLabel#cardTitle {
    font-size: 22px;
    font-weight: 600;
    color: #0F172A;
}
QLabel#cardSubtitle, QLabel#hint, QLabel#fieldLabel, QLabel#sourceNote {
    color: #64748B;
}
QLabel#cardSubtitle {
    font-size: 13px;
}
QLabel#hint, QLabel#sourceNote, QLabel#fieldLabel {
    font-size: 12px;
}
QLabel#emptyState {
    color: #64748B;
    font-size: 15px;
}
QLabel[role="value"] {
    font-size: 14px;
    color: #0F172A;
}
QLabel[role="account"] {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 18px;
    color: #0F172A;
}
QLabel[role="mono"] {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 13px;
    color: #0F172A;
}
QLabel#differs {
    color: #92400E;
    font-weight: 600;
    font-size: 12px;
}
QListWidget#cardList {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget#cardList::item {
    border-radius: 6px;
    padding: 6px 8px;
    margin: 2px;
    color: #1E293B;
}
QListWidget#cardList::item:selected {
    background: #E8EEF4;
    color: #1E293B;
}
QListWidget#cardList::item:hover {
    background: #F8FAFC;
}
QPlainTextEdit#rawBlock {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 13px;
    padding: 8px;
    color: #0F172A;
}
/* Anything the examiner types into or chooses: light blue with a blue border,
   so it stands apart from the data read off the stripe. */
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #F2F7FF;
    border: 2px solid #93C5FD;
    border-radius: 6px;
    padding: 5px 8px;
    color: #0F172A;
    selection-background-color: #BFDBFE;
    selection-color: #0F172A;
}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover {
    border: 2px solid #3B82F6;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    background: #FFFFFF;
    border: 2px solid #1D4ED8;
}
/* A choice that has not been made yet. */
QComboBox[attention="true"] {
    background: #FFFBEB;
    border: 2px solid #F59E0B;
    color: #92400E;
    font-weight: 600;
}
QComboBox[attention="true"]:hover, QComboBox[attention="true"]:focus {
    border: 2px solid #D97706;
}
QFrame#inputPanel {
    background: #FFFFFF;
    border: 1px solid #BFDBFE;
    border-left: 5px solid #2563EB;
    border-radius: 8px;
}
QLabel#attentionTag {
    background: #FEF3C7;
    color: #92400E;
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}
QCheckBox#printedMatches {
    font-size: 14px;
    font-weight: 600;
    color: #1E3A8A;
    spacing: 8px;
}
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: #64748B;
    padding: 8px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: #1B2838;
    border-bottom: 2px solid #1B2838;
}
QTabBar::tab:hover {
    color: #1B2838;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px 2px 4px 2px;
}
QScrollBar::handle:vertical {
    background: #94A3B8;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #CBD5E1;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: transparent;
}
QLabel#binDigits {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 20px;
    color: #0F172A;
    background: transparent;
}
QLabel#chip {
    border-radius: 11px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 12px;
}
QLabel#chip[kind="listening"] {
    background: #CCFBF1;
    color: #115E59;
}
QLabel#chip[kind="idle"] {
    background: #E2E8F0;
    color: #334155;
}
QLabel#chip[kind="warn"] {
    background: #FEF3C7;
    color: #92400E;
}
QLabel#chip[kind="bad"] {
    background: #FEE2E2;
    color: #991B1B;
}
QSplitter::handle {
    background: transparent;
    width: 12px;
}
"""



RESOURCES = Path(__file__).resolve().parent / "resources"


def app_icon() -> QIcon:
    """The program icon. Falls back to a simple drawn icon if the icon files are missing."""
    icon = QIcon()
    for name in ("app.ico", "icon-256.png"):
        path = RESOURCES / name
        if path.exists():
            icon.addFile(str(path))
    if not icon.isNull():
        return icon
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1B2838"))
    painter.drawRoundedRect(1, 1, 30, 30, 6, 6)
    painter.setBrush(QColor("#F8FAFC"))
    painter.drawRoundedRect(7, 14, 18, 4, 1, 1)
    painter.end()
    return QIcon(pixmap)
