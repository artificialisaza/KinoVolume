"""Chroma-key color picker widget with eyedropper, tolerance, and fade controls."""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPixmap, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class ChromaColorPicker(QGroupBox):
    """Chroma-key controls: enable, color swatch, eyedropper, tolerance, fade."""

    settings_changed = Signal()
    eyedropper_requested = Signal()  # ask FrameViewer to enter eyedropper mode

    def __init__(self, parent=None):
        super().__init__("Chroma Key", parent)
        self._target_color = (0, 0, 0)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Enable checkbox
        self.enable_check = QCheckBox("Enable chroma transparency")
        self.enable_check.setToolTip(
            "Make pixels matching the selected color transparent.\n"
            "Only applies to Cuboid Fill mode outputs."
        )
        layout.addWidget(self.enable_check)

        # Color row: swatch + pick button
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))

        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(28, 28)
        self.color_swatch.setStyleSheet(
            "background-color: #000000; border: 1px solid #3c3c3c; border-radius: 3px;"
        )
        self.color_swatch.setToolTip("Currently selected chroma color")
        color_row.addWidget(self.color_swatch)

        self.color_label = QLabel("(0, 0, 0)")
        self.color_label.setObjectName("infoLabel")
        color_row.addWidget(self.color_label)
        color_row.addStretch()

        self.pick_btn = QPushButton("Pick from frame")
        self.pick_btn.setToolTip(
            "Click on the video frame to sample a color.\n"
            "The cursor will change to a crosshair."
        )
        color_row.addWidget(self.pick_btn)
        layout.addLayout(color_row)

        # Tolerance slider
        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Tolerance:"))
        self.tolerance_slider = QSlider()
        self.tolerance_slider.setOrientation(Qt.Horizontal)
        self.tolerance_slider.setRange(0, 100)
        self.tolerance_slider.setValue(10)
        self.tolerance_slider.setToolTip(
            "How similar a pixel must be to the target color to\n"
            "become transparent. 0 = exact match, 100 = everything."
        )
        tol_row.addWidget(self.tolerance_slider)
        self.tolerance_label = QLabel("10%")
        self.tolerance_label.setFixedWidth(35)
        tol_row.addWidget(self.tolerance_label)
        layout.addLayout(tol_row)

        # Fade slider
        fade_row = QHBoxLayout()
        fade_row.addWidget(QLabel("Fade:"))
        self.fade_slider = QSlider()
        self.fade_slider.setOrientation(Qt.Horizontal)
        self.fade_slider.setRange(0, 100)
        self.fade_slider.setValue(5)
        self.fade_slider.setToolTip(
            "Smoothness of the transparency edge.\n"
            "0 = hard edge, higher = softer gradient."
        )
        fade_row.addWidget(self.fade_slider)
        self.fade_label = QLabel("5%")
        self.fade_label.setFixedWidth(35)
        fade_row.addWidget(self.fade_label)
        layout.addLayout(fade_row)

        # Initially disabled until chroma is enabled
        self._set_controls_enabled(False)

    def _connect_signals(self):
        self.enable_check.toggled.connect(self._on_enable_toggled)
        self.pick_btn.clicked.connect(self._on_pick_clicked)
        self.tolerance_slider.valueChanged.connect(self._on_tolerance_changed)
        self.fade_slider.valueChanged.connect(self._on_fade_changed)

    def _on_enable_toggled(self, checked):
        self._set_controls_enabled(checked)
        self.settings_changed.emit()

    def _set_controls_enabled(self, enabled):
        self.pick_btn.setEnabled(enabled)
        self.tolerance_slider.setEnabled(enabled)
        self.fade_slider.setEnabled(enabled)
        self.color_swatch.setEnabled(enabled)

    def _on_pick_clicked(self):
        self.eyedropper_requested.emit()

    def _on_tolerance_changed(self, value):
        self.tolerance_label.setText(f"{value}%")
        self.settings_changed.emit()

    def _on_fade_changed(self, value):
        self.fade_label.setText(f"{value}%")
        self.settings_changed.emit()

    def set_color(self, r, g, b):
        """Set the target chroma color (called after eyedropper samples a pixel)."""
        self._target_color = (r, g, b)
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        self.color_swatch.setStyleSheet(
            f"background-color: {hex_color}; border: 1px solid #3c3c3c; border-radius: 3px;"
        )
        self.color_label.setText(f"({r}, {g}, {b})")
        self.settings_changed.emit()

    @property
    def is_enabled(self):
        return self.enable_check.isChecked()

    @property
    def target_color(self):
        return self._target_color

    @property
    def tolerance(self):
        return self.tolerance_slider.value() / 100.0

    @property
    def fade(self):
        return self.fade_slider.value() / 100.0
