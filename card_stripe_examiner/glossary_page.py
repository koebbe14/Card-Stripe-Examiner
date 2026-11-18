"""Glossary page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from card_stripe_examiner.glossary import GLOSSARY


class GlossaryPage(QWidget):
    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("glossaryPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        back = QPushButton("Back to case")
        back.setObjectName("quiet")
        back.clicked.connect(lambda: self.back_requested.emit())
        back.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        splitter = QSplitter()
        self.topics = QListWidget()
        self.topics.setObjectName("cardList")
        for topic in GLOSSARY:
            self.topics.addItem(topic["title"])
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 18)
        panel_layout.setSpacing(10)
        self.heading = QLabel()
        self.heading.setObjectName("cardTitle")
        self.heading.setWordWrap(True)
        self.body = QLabel()
        self.body.setObjectName("fieldValue")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        panel_layout.addWidget(self.heading)
        panel_layout.addWidget(self.body)
        panel_layout.addStretch()
        splitter.addWidget(self.topics)
        splitter.addWidget(panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 760])
        layout.addWidget(splitter, 1)
        self.topics.currentRowChanged.connect(self._show_topic)
        self.topics.setCurrentRow(0)

    def _show_topic(self, index: int) -> None:
        if index < 0 or index >= len(GLOSSARY):
            return
        topic = GLOSSARY[index]
        self.heading.setText(topic["title"])
        self.body.setText(topic["body"])
