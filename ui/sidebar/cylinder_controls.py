"""Sidebar controls for Cylinder mode: center, radius, fill mode, preview."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)
from PySide6.QtCore import Qt


class CylinderControls(QGroupBox):
    """Sidebar controls for Cylinder visualization mode."""

    settings_changed = Signal()

    def __init__(self, project_state, parent=None):
        super().__init__("Cylinder Parameters", parent)
        self._state = project_state
        self._updating = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Center X
        cx_row = QHBoxLayout()
        cx_row.addWidget(QLabel("Center X:"))
        self.cx_spin = QSpinBox()
        self.cx_spin.setSuffix(" px")
        self.cx_spin.setToolTip("Horizontal center of the circle on the video frame")
        cx_row.addWidget(self.cx_spin)
        layout.addLayout(cx_row)

        # Center Y
        cy_row = QHBoxLayout()
        cy_row.addWidget(QLabel("Center Y:"))
        self.cy_spin = QSpinBox()
        self.cy_spin.setSuffix(" px")
        self.cy_spin.setToolTip("Vertical center of the circle on the video frame")
        cy_row.addWidget(self.cy_spin)
        layout.addLayout(cy_row)

        # Radius
        rad_row = QHBoxLayout()
        rad_row.addWidget(QLabel("Radius:"))
        self.radius_spin = QSpinBox()
        self.radius_spin.setSuffix(" px")
        self.radius_spin.setToolTip("Radius of the circular extraction area")
        rad_row.addWidget(self.radius_spin)
        layout.addLayout(rad_row)

        self.radius_slider = QSlider(Qt.Horizontal)
        self.radius_slider.setToolTip("Drag to adjust circle radius")
        layout.addWidget(self.radius_slider)

        # --- Render Preview Quality ---
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("3D Preview:"))
        self.preview_quality_combo = QComboBox()
        self.preview_quality_combo.addItems(["High", "Medium", "Low", "Full", "No preview"])
        self.preview_quality_combo.setToolTip(
            "Quality of the interactive 3D preview after export.\n"
            "Lower quality = faster.  'No preview' skips 3D entirely."
        )
        preview_row.addWidget(self.preview_quality_combo)
        layout.addLayout(preview_row)

        # Output info
        self.output_label = QLabel("Output: —")
        self.output_label.setObjectName("infoLabel")
        self.output_label.setWordWrap(True)
        layout.addWidget(self.output_label)

        layout.addStretch()

    def _connect_signals(self):
        self.cx_spin.valueChanged.connect(self._on_setting_changed)
        self.cy_spin.valueChanged.connect(self._on_setting_changed)
        self.radius_spin.valueChanged.connect(self._on_radius_spin_changed)
        self.radius_slider.valueChanged.connect(self._on_radius_slider_changed)
        self.preview_quality_combo.currentTextChanged.connect(self._on_preview_quality_changed)
        self._state.video_changed.connect(self._on_video_changed)
        self._state.settings_changed.connect(self._update_output_label)

    def _on_video_changed(self):
        vs = self._state.video_source
        if vs is None:
            return
        self._updating = True
        max_radius = min(vs.width, vs.height) // 2
        self.cx_spin.setRange(0, vs.width - 1)
        self.cx_spin.setValue(vs.width // 2)
        self.cy_spin.setRange(0, vs.height - 1)
        self.cy_spin.setValue(vs.height // 2)
        self.radius_spin.setRange(2, max_radius)
        self.radius_spin.setValue(max_radius // 2)
        self.radius_slider.setRange(2, max_radius)
        self.radius_slider.setValue(max_radius // 2)
        self._updating = False
        self._sync_to_state()
        self._update_output_label()

    def _on_setting_changed(self):
        if self._updating:
            return
        self._sync_to_state()
        self._update_output_label()
        self.settings_changed.emit()

    def _on_radius_spin_changed(self, value):
        if self._updating:
            return
        self._updating = True
        self.radius_slider.setValue(value)
        self._updating = False
        self._sync_to_state()
        self._update_output_label()
        self.settings_changed.emit()

    def _on_radius_slider_changed(self, value):
        if self._updating:
            return
        self._updating = True
        self.radius_spin.setValue(value)
        self._updating = False
        self._sync_to_state()
        self._update_output_label()
        self.settings_changed.emit()

    def _on_preview_quality_changed(self, text):
        self._state.cylinder_preview_quality = text

    def _sync_to_state(self):
        self._state.cylinder_center_x = self.cx_spin.value()
        self._state.cylinder_center_y = self.cy_spin.value()
        self._state.cylinder_radius = self.radius_spin.value()

    def _update_output_label(self):
        vs = self._state.video_source
        if vs is None:
            self.output_label.setText("Output: —")
            return

        radius = self.radius_spin.value()
        circumference = max(int(2 * 3.14159 * radius), 6)
        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        self.output_label.setText(
            f"Radius: {radius} px\n"
            f"Circumference: {circumference} px\n"
            f"Surface: {num_frames} × {circumference}\n"
            f"Caps: {radius * 2} × {radius * 2}\n"
            f"({num_frames} frames sampled)"
        )

    def set_center_from_drag(self, cx, cy):
        """Called by FrameViewer when circle center is dragged."""
        self._updating = True
        self.cx_spin.setValue(cx)
        self.cy_spin.setValue(cy)
        self._sync_to_state()
        self._update_output_label()
        self._updating = False

    def set_radius_from_drag(self, radius):
        """Called by FrameViewer when circle edge is dragged."""
        self._updating = True
        self.radius_spin.setValue(radius)
        self.radius_slider.setValue(radius)
        self._sync_to_state()
        self._update_output_label()
        self._updating = False
