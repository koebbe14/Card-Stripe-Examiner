"""Shared widgets and small helpers for the window."""

from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from card_stripe_examiner.parse import last_four


class NoScrollComboBox(QComboBox):
    """A dropdown the mouse wheel cannot change by accident.

    The wheel only moves through the choices while the dropdown list is open. Otherwise the
    wheel event is passed on, so the page scrolls instead of the value changing."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollSpinBox(QSpinBox):
    """A number box the mouse wheel changes only after it is clicked into."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def set_attention(widget, on: bool) -> None:
    """Mark a field amber until the examiner fills it in."""
    if bool(widget.property("attention")) == on:
        return
    widget.setProperty("attention", on)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def input_heading(title: str):
    """Heading row for a panel the examiner fills in: title and an amber tag
    (hidden until needed) that says the entry is still missing."""
    from PySide6.QtWidgets import QHBoxLayout

    row = QHBoxLayout()
    row.setSpacing(8)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    attention = QLabel("Needs entry")
    attention.setObjectName("attentionTag")
    attention.setVisible(False)
    row.addWidget(heading)
    row.addWidget(attention)
    row.addStretch()
    return row, attention


def format_when(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value or "—"
    return moment.strftime("%b %d, %Y  %H:%M")


def format_clock(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value or "—"
    return moment.strftime("%H:%M")


def safe_filename(case: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "-", case).strip(" .")
    return cleaned or "case"


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)


def masked_last_four(pan: str | None) -> str:
    return f"•••• {last_four(pan)}"


def apply_kind(label: QLabel, kind: str) -> None:
    colors = {
        "listening": ("#CCFBF1", "#115E59"),
        "idle": ("#E2E8F0", "#334155"),
        "warn": ("#FEF3C7", "#92400E"),
        "bad": ("#FEE2E2", "#991B1B"),
    }
    background, foreground = colors.get(kind, colors["idle"])
    label.setStyleSheet(
        "QLabel {"
        f"background: {background}; color: {foreground};"
        "border-radius: 11px; padding: 4px 10px; font-weight: 600; font-size: 12px;"
        "}"
    )


def style_reject(button: QPushButton) -> None:
    button.setObjectName("quiet")
    button.style().unpolish(button)
    button.style().polish(button)


class Field(QWidget):
    def __init__(self, label: str, value: str, role: str = "value") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        caption = QLabel(label)
        caption.setObjectName("fieldLabel")
        caption.setWordWrap(True)
        shown = value if value else "—"
        text = QLabel(shown)
        text.setProperty("role", role)
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.style().unpolish(text)
        text.style().polish(text)
        self.value = text
        layout.addWidget(caption)
        layout.addWidget(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = self.value.width()
        if width < 20:
            return
        height = self.value.heightForWidth(width)
        if height > 0 and self.value.minimumHeight() != height:
            self.value.setMinimumHeight(height)


class Section(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(12)
        self.body.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        self.body.addWidget(heading)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(12)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)
        self.body.addLayout(self.grid)
        self._row = 0
        self._col = 0

    def add_field(self, label: str, value: str, mono: bool = False, account: bool = False) -> None:
        if self._col >= 3:
            self._col = 0
            self._row += 1
        role = "account" if account else "mono" if mono else "value"
        self.grid.addWidget(Field(label, value, role), self._row, self._col)
        self._col += 1

    def add_wide(self, label: str, value: str, mono: bool = False) -> Field:
        if self._col:
            self._row += 1
            self._col = 0
        role = "mono" if mono else "value"
        field = Field(label, value, role)
        self.grid.addWidget(field, self._row, 0, 1, 3)
        self._row += 1
        return field

    def add_rows(self, rows: list[tuple[str, str, bool]]) -> None:
        for label, value, mono in rows:
            account = bool(mono and label.startswith("Account"))
            text = value or ""
            if not account and ("\n" in text or len(text) > 48):
                self.add_wide(label, text, mono=mono)
            else:
                self.add_field(label, text, mono=mono, account=account)


class ScrollPane(QScrollArea):
    """Keeps the page as tall as its content so the pane scrolls instead of crushing fields."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 12, 0)
        self.host_layout.setSpacing(12)
        self.setWidget(self.host)
        self._fitting = False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.refit()

    def refit(self) -> None:
        if self._fitting:
            return
        self._fitting = True
        width = max(1, self.viewport().width() - 16)
        layout = self.host_layout
        layout.activate()
        height = layout.heightForWidth(width) if layout.hasHeightForWidth() else 0
        height = max(height, layout.sizeHint().height())
        if height > 0 and self.host.minimumHeight() != height:
            self.host.setMinimumHeight(height)
        self._fitting = False

    def refit_soon(self) -> None:
        QTimer.singleShot(0, self.refit)
