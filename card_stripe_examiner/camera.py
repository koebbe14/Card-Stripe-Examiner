"""Take a photo of the card with the computer's camera."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from card_stripe_examiner.widgets import NoScrollComboBox, style_reject

# An ID-1 card (bank and most gift cards) is 85.60 mm by 53.98 mm.
CARD_RATIO = 85.60 / 53.98
GUIDE_FILL = 0.82  # the outline uses this share of the preview's width (or height, if that is smaller)
PREVIEW_MIN = (720, 460)

PRIVACY_HELP = (
    "Check that the camera is connected and not in use by another program (such as Teams or Zoom). "
    "In Windows Settings, open Privacy & security > Camera and make sure camera access is on, "
    "including \"Let desktop apps access your camera\"."
)


def list_cameras():
    """The video inputs Windows reports. Empty when there is no camera or camera access is blocked."""
    try:
        from PySide6.QtMultimedia import QMediaDevices

        return list(QMediaDevices.videoInputs())
    except Exception:
        return []


def guide_rect(width: int, height: int) -> QRectF:
    """The card outline, centred, in image coordinates."""
    guide_width = width * GUIDE_FILL
    guide_height = guide_width / CARD_RATIO
    if guide_height > height * GUIDE_FILL:
        guide_height = height * GUIDE_FILL
        guide_width = guide_height * CARD_RATIO
    return QRectF((width - guide_width) / 2, (height - guide_height) / 2, guide_width, guide_height)


def crop_to_guide(image: QImage, margin: float = 0.04) -> QImage:
    """Crop to the outline plus a small margin, so the card's edges are not cut off."""
    rect = guide_rect(image.width(), image.height())
    rect.adjust(
        -rect.width() * margin,
        -rect.height() * margin,
        rect.width() * margin,
        rect.height() * margin,
    )
    rect = rect.intersected(QRectF(0, 0, image.width(), image.height()))
    return image.copy(rect.toAlignedRect())


def save_capture(image: QImage, folder: str | Path | None = None) -> Path:
    """Write the capture as a JPEG in a temporary folder and return its path."""
    folder = Path(folder) if folder else Path(tempfile.mkdtemp(prefix="cse-capture-"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"camera-capture-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jpg"
    if not image.save(str(path), "JPG", 92):
        raise OSError("The captured photo could not be saved.")
    return path


def capture_name(when: datetime | None = None) -> str:
    moment = when or datetime.now()
    return f"Camera capture {moment.strftime('%m/%d/%Y %H:%M')}"


class CameraDialog(QDialog):
    """Live camera preview with a card outline. Capture, check the still, then use it or retake."""

    def __init__(self, side_label: str, parent=None, start: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Capture {side_label.lower()} of card")
        self.setMinimumSize(780, 640)
        self._camera = None
        self._session = None
        self._sink = None
        self._latest: QImage | None = None
        self._captured: QImage | None = None
        self._rotation = 0
        self._cameras = list_cameras()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        title = QLabel(f"Capture the {side_label.lower()} of the card")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.hint = QLabel(
            "Hold the card flat and line it up inside the outline. Avoid glare from lights or windows, "
            "then choose Capture (or press the space bar)."
        )
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.camera_box = NoScrollComboBox()
        for device in self._cameras:
            self.camera_box.addItem(device.description(), device.id())
        self.camera_box.setVisible(len(self._cameras) > 1)
        self.camera_box.currentIndexChanged.connect(self._switch_camera)
        camera_caption = QLabel("Camera")
        camera_caption.setObjectName("fieldLabel")
        camera_caption.setVisible(len(self._cameras) > 1)
        self.rotate_button = QPushButton("Rotate")
        self.rotate_button.setObjectName("quiet")
        self.rotate_button.setToolTip("Turn the picture a quarter turn clockwise")
        self.rotate_button.clicked.connect(self._rotate)
        self.crop = QCheckBox("Crop to the card outline")
        self.crop.setChecked(True)
        self.crop.toggled.connect(self._crop_changed)
        controls.addWidget(camera_caption)
        controls.addWidget(self.camera_box, 1)
        controls.addWidget(self.rotate_button)
        controls.addWidget(self.crop)
        if len(self._cameras) <= 1:
            controls.insertStretch(2, 1)
        layout.addLayout(controls)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(*PREVIEW_MIN)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("QLabel { background: #0F172A; color: #CBD5E1; border-radius: 8px; }")
        layout.addWidget(self.preview, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.capture_button = QPushButton("Capture")
        self.capture_button.clicked.connect(self._capture)
        self.retake_button = QPushButton("Retake")
        self.retake_button.setObjectName("quiet")
        self.retake_button.clicked.connect(self._retake)
        self.use_button = QPushButton("Use photo")
        self.use_button.clicked.connect(self._use)
        cancel = QPushButton("Cancel")
        style_reject(cancel)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.retake_button)
        buttons.addWidget(self.capture_button)
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._space)

        self._show_live_controls()
        if not self._cameras:
            self._show_problem("No camera was found. " + PRIVACY_HELP)
            self.capture_button.setEnabled(False)
        elif start:
            QTimer.singleShot(0, self._start_camera)
        else:
            self.preview.setText("Camera not started.")

    # ----- camera -----

    def _start_camera(self) -> None:
        from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QVideoSink

        self._stop_camera()
        index = max(0, self.camera_box.currentIndex())
        device = self._cameras[index]
        self.preview.setText("Starting the camera…")
        camera = QCamera(device)
        best = self._best_format(device)
        if best is not None:
            camera.setCameraFormat(best)
        session = QMediaCaptureSession()
        sink = QVideoSink()
        session.setCamera(camera)
        session.setVideoSink(sink)
        sink.videoFrameChanged.connect(self._on_frame)
        camera.errorOccurred.connect(self._on_error)
        self._camera, self._session, self._sink = camera, session, sink
        camera.start()
        QTimer.singleShot(6000, self._check_started)

    @staticmethod
    def _best_format(device):
        """The sharpest format up to 1920 x 1080 at 15 frames a second or more."""
        best = None
        best_pixels = 0
        for fmt in device.videoFormats():
            size = fmt.resolution()
            pixels = size.width() * size.height()
            if size.width() > 1920 or size.height() > 1080 or fmt.maxFrameRate() < 15:
                continue
            if pixels > best_pixels:
                best, best_pixels = fmt, pixels
        return best

    def _check_started(self) -> None:
        if self._camera is not None and self._latest is None and self._captured is None:
            self._show_problem("The camera did not send a picture. " + PRIVACY_HELP)

    def _stop_camera(self) -> None:
        if self._sink is not None:
            try:
                self._sink.videoFrameChanged.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
        if self._camera is not None:
            self._camera.stop()
        self._camera = self._session = self._sink = None
        self._latest = None

    def _switch_camera(self, _index: int = 0) -> None:
        if self._captured is None and self._cameras:
            self._start_camera()

    def _on_error(self, _error=None, message: str = "") -> None:
        detail = f" ({message})" if message else ""
        self._show_problem(f"The camera could not be used{detail}. " + PRIVACY_HELP)

    def _show_problem(self, text: str) -> None:
        self.preview.setText("No camera picture")
        self.status.setText(text)
        self.status.setStyleSheet("QLabel { color: #B45309; font-weight: 600; }")

    # ----- frames -----

    def _oriented(self, image: QImage) -> QImage:
        if not self._rotation:
            return image
        return image.transformed(QTransform().rotate(self._rotation))

    def _on_frame(self, frame) -> None:
        if self._captured is not None:
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._latest = self._oriented(image)
        if self.status.text():
            self.status.setText("")
        self._paint(self._latest, guide=True)

    def _paint(self, image: QImage, guide: bool) -> None:
        target = self.preview.size()
        pixmap = QPixmap.fromImage(image).scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        if guide:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = guide_rect(pixmap.width(), pixmap.height())
            shade = QColor(0, 0, 0, 90)
            painter.fillRect(QRectF(0, 0, pixmap.width(), rect.top()), shade)
            painter.fillRect(QRectF(0, rect.bottom(), pixmap.width(), pixmap.height() - rect.bottom()), shade)
            painter.fillRect(QRectF(0, rect.top(), rect.left(), rect.height()), shade)
            painter.fillRect(QRectF(rect.right(), rect.top(), pixmap.width() - rect.right(), rect.height()), shade)
            painter.setPen(QPen(QColor("#5EEAD4"), 3))
            painter.drawRoundedRect(rect, 14, 14)
            painter.end()
        self.preview.setPixmap(pixmap)

    def _rotate(self) -> None:
        self._rotation = (self._rotation + 90) % 360
        if self._captured is not None:
            self._captured = self._captured.transformed(QTransform().rotate(90))
            self._paint(self._shown_capture(), guide=False)

    # ----- capture -----

    def _space(self) -> None:
        if self._captured is None and self.capture_button.isEnabled():
            self._capture()

    def _capture(self) -> None:
        if self._latest is None:
            self.status.setText("Wait for the camera picture to appear, then capture.")
            return
        self._captured = self._latest.copy()
        self._paint(self._shown_capture(), guide=False)
        self._show_still_controls()
        self.status.setStyleSheet("")
        self.status.setText("Check that the card is sharp and readable. Use the photo or retake it.")

    def _shown_capture(self) -> QImage:
        if self._captured is None:
            return QImage()
        return crop_to_guide(self._captured) if self.crop.isChecked() else self._captured

    def _crop_changed(self, _checked: bool) -> None:
        if self._captured is not None:
            self._paint(self._shown_capture(), guide=False)

    def _retake(self) -> None:
        self._captured = None
        self.status.setText("")
        self._show_live_controls()

    def _use(self) -> None:
        if self._captured is None:
            return
        self.accept()

    def image(self) -> QImage | None:
        """The photo to keep, cropped if that option is on."""
        if self._captured is None:
            return None
        return self._shown_capture()

    def _show_live_controls(self) -> None:
        self.capture_button.setVisible(True)
        self.retake_button.setVisible(False)
        self.use_button.setVisible(False)
        self.crop.setEnabled(True)
        self.camera_box.setEnabled(True)

    def _show_still_controls(self) -> None:
        self.capture_button.setVisible(False)
        self.retake_button.setVisible(True)
        self.use_button.setVisible(True)
        self.camera_box.setEnabled(False)
        self.use_button.setDefault(True)

    # ----- closing -----

    def done(self, result: int) -> None:
        self._stop_camera()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_camera()
        super().closeEvent(event)
