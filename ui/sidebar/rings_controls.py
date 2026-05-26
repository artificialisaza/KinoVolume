from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from config import RINGS_MAX_OUTPUT_DIAMETER


class RingsControls(QGroupBox):
    """Sidebar controls for Rings (Dendrochronology) mode."""

    settings_changed = Signal()

    def __init__(self, project_state, parent=None):
        super().__init__("Rings Parameters", parent)
        self._state = project_state
        self._updating = False
        self._build_ui()
        self._connect_signals()
        # Sync initial visibility to the default combo selection
        self._on_sampling_changed()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Center X
        cx_row = QHBoxLayout()
        cx_row.addWidget(QLabel("Center X:"))
        self.cx_spin = QSpinBox()
        self.cx_spin.setSuffix(" px")
        self.cx_spin.setToolTip("Horizontal center of the ring pattern on the video frame")
        cx_row.addWidget(self.cx_spin)
        layout.addLayout(cx_row)

        # Center Y
        cy_row = QHBoxLayout()
        cy_row.addWidget(QLabel("Center Y:"))
        self.cy_spin = QSpinBox()
        self.cy_spin.setSuffix(" px")
        self.cy_spin.setToolTip("Vertical center of the ring pattern on the video frame")
        cy_row.addWidget(self.cy_spin)
        layout.addLayout(cy_row)

        # Sampling mode
        samp_row = QHBoxLayout()
        samp_row.addWidget(QLabel("Sampling:"))
        self.sampling_combo = QComboBox()
        self.sampling_combo.addItems([
            "Fit to frame size",
            "All frames (scaled)",
            "Equal-area",
        ])
        self.sampling_combo.setToolTip(
            "Fit to frame size: skip frames so rings fit within the max radius.\n"
            "All frames (scaled): each frame = 1 ring, equal width.\n"
            "Equal-area: each frame = 1 ring with equal area "
            "(inner rings wider, outer rings thinner)."
        )
        samp_row.addWidget(self.sampling_combo)
        layout.addLayout(samp_row)
        # Default to "All frames (scaled)"
        self.sampling_combo.setCurrentIndex(1)

        # Max output resolution (visible only in "All frames" mode)
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("Max Resolution:"))
        self.max_res_spin = QSpinBox()
        self.max_res_spin.setRange(256, 32768)
        self.max_res_spin.setValue(RINGS_MAX_OUTPUT_DIAMETER)
        self.max_res_spin.setSingleStep(512)
        self.max_res_spin.setSuffix(" px")
        self.max_res_spin.setToolTip(
            "Maximum diameter of the output image in pixels.\n"
            "Frames beyond this limit are skipped.\n"
            "Higher values = larger file, more detail."
        )
        res_row.addWidget(self.max_res_spin)
        layout.addLayout(res_row)
        self._res_row_widgets = [res_row.itemAt(i).widget()
                                  for i in range(res_row.count())
                                  if res_row.itemAt(i).widget()]

        # Reverse time checkbox
        self.reverse_check = QCheckBox("Reverse time")
        self.reverse_check.setToolTip(
            "Sample the last video frame first (center of the ring)\n"
            "and the first frame last (outermost ring)."
        )
        layout.addWidget(self.reverse_check)

        # Info labels
        self.info_label = QLabel("Output: —")
        self.info_label.setObjectName("infoLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        layout.addStretch()

    def _connect_signals(self):
        self.cx_spin.valueChanged.connect(self._on_setting_changed)
        self.cy_spin.valueChanged.connect(self._on_setting_changed)
        self.sampling_combo.currentIndexChanged.connect(self._on_sampling_changed)
        self.max_res_spin.valueChanged.connect(self._on_setting_changed)
        self.reverse_check.stateChanged.connect(self._on_setting_changed)
        self._state.video_changed.connect(self._on_video_changed)
        self._state.settings_changed.connect(self._update_info)

    def _on_sampling_changed(self):
        """Show/hide max resolution spinbox based on sampling mode."""
        mode = self.sampling_combo.currentText()
        show_res = mode in ("All frames (scaled)", "Equal-area")
        for w in self._res_row_widgets:
            w.setVisible(show_res)
        self.max_res_spin.setVisible(show_res)
        self._on_setting_changed()

    def _on_video_changed(self):
        vs = self._state.video_source
        if vs is None:
            return
        self._updating = True
        self.cx_spin.setRange(0, vs.width - 1)
        self.cx_spin.setValue(vs.width // 2)
        self.cy_spin.setRange(0, vs.height - 1)
        self.cy_spin.setValue(vs.height // 2)
        self._updating = False
        self._sync_to_state()
        self._update_info()

    def _on_setting_changed(self):
        if self._updating:
            return
        self._sync_to_state()
        self._update_info()
        self.settings_changed.emit()

    def _sync_to_state(self):
        self._state.rings_center_x = self.cx_spin.value()
        self._state.rings_center_y = self.cy_spin.value()
        self._state.rings_sampling_mode = self.sampling_combo.currentText()
        self._state.rings_max_output = self.max_res_spin.value()
        self._state.rings_reverse_time = self.reverse_check.isChecked()

    def _update_info(self):
        vs = self._state.video_source
        if vs is None:
            self.info_label.setText("Output: —")
            return

        cx = self.cx_spin.value()
        cy = self.cy_spin.value()
        max_radius = min(cx, cy, vs.width - cx, vs.height - cy)
        max_radius = max(1, max_radius)

        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        sampling_mode = self.sampling_combo.currentText()

        if sampling_mode == "Fit to frame size":
            # Skip frames so total rings <= max_radius
            if num_frames > max_radius:
                effective_rings = max_radius
            else:
                effective_rings = num_frames
            diameter = effective_rings * 2
            used = effective_rings
            frames_note = f"Video frames: {num_frames}"
            if used < num_frames:
                frames_note += f" (only {used} will be used)"
            self.info_label.setText(
                f"Max radius: {max_radius} px\n"
                f"{frames_note}\n"
                f"Output: {diameter} × {diameter} px"
            )
        else:
            # "All frames (scaled)" and "Equal-area"
            diameter = num_frames * 2
            max_diam = self.max_res_spin.value()
            used = num_frames
            if diameter > max_diam:
                used = max_diam // 2
                diameter = max_diam
            # RGBA output (4 bytes per pixel)
            mode_note = ""
            if sampling_mode == "Equal-area":
                mode_note = "\nProjection: equal-area (inner rings wider)"
            frames_note = f"Video frames: {num_frames}"
            if used < num_frames:
                frames_note += f" (only {used} will be used)"
            self.info_label.setText(
                f"Max radius: {max_radius} px\n"
                f"{frames_note}\n"
                f"Output: {diameter} × {diameter} px"
                f"{mode_note}"
            )

    def set_center_from_drag(self, cx, cy):
        """Called by FrameViewer when the ring center is dragged."""
        self._updating = True
        self.cx_spin.setValue(cx)
        self.cy_spin.setValue(cy)
        self._sync_to_state()
        self._update_info()
        self._updating = False
