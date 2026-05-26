from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt


class SliceControls(QGroupBox):
    """Sidebar controls for Slice (Slit-Scan) mode."""

    settings_changed = Signal()
    slit_position_changed = Signal(int)
    ortho_position_changed = Signal(int)
    orthogonal_toggled = Signal(bool)

    def __init__(self, project_state, parent=None):
        super().__init__("Slice Parameters", parent)
        self._state = project_state
        self._updating = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Orientation
        orient_row = QHBoxLayout()
        orient_row.addWidget(QLabel("Orientation:"))
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItems(["Vertical", "Horizontal"])
        self.orientation_combo.setToolTip(
            "Vertical: slit runs top-to-bottom, output grows left-to-right.\n"
            "Horizontal: slit runs left-to-right, output grows top-to-bottom."
        )
        orient_row.addWidget(self.orientation_combo)
        layout.addLayout(orient_row)

        # Slit width
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Slit Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 99999)
        self.width_spin.setValue(1)
        self.width_spin.setSuffix(" px")
        self.width_spin.setToolTip(
            "Width of the strip extracted from each frame (in pixels).\n"
            "1 = single pixel column/row. Wider values capture more per frame."
        )
        width_row.addWidget(self.width_spin)
        layout.addLayout(width_row)

        # Slit position
        layout.addWidget(QLabel("Slit Position:"))
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 1920)
        self.position_slider.setToolTip("Drag to move the slit across the frame")
        layout.addWidget(self.position_slider)

        pos_row = QHBoxLayout()
        self.position_spin = QSpinBox()
        self.position_spin.setRange(0, 1920)
        self.position_spin.setSuffix(" px")
        self.position_spin.setToolTip("Pixel position of the slit's left edge (or top edge)")
        pos_row.addWidget(self.position_spin)
        pos_row.addStretch()
        layout.addLayout(pos_row)

        # Output size info
        self.output_label = QLabel("Output: —")
        self.output_label.setObjectName("infoLabel")
        self.output_label.setWordWrap(True)
        layout.addWidget(self.output_label)

        # Reverse time checkbox
        self.reverse_check = QCheckBox("Reverse time")
        self.reverse_check.setToolTip(
            "Sample frames in reverse order.\n"
            "Useful for extracting panoramas when the video pans left."
        )
        layout.addWidget(self.reverse_check)

        # Orthogonal mode
        self.orthogonal_check = QCheckBox("Orthogonal (two crossing slices)")
        self.orthogonal_check.setToolTip(
            "Generate two perpendicular slices that form a cross shape in 3D"
        )
        layout.addWidget(self.orthogonal_check)

        # Orthogonal controls container (hidden until checkbox is checked)
        self._ortho_container = QWidget()
        ortho_layout = QVBoxLayout(self._ortho_container)
        ortho_layout.setContentsMargins(0, 0, 0, 0)

        # Second slit position (perpendicular) — same format as main
        ortho_layout.addWidget(QLabel("Perpendicular Slit Position:"))
        self.ortho_slider = QSlider(Qt.Horizontal)
        self.ortho_slider.setRange(0, 1080)
        self.ortho_slider.setToolTip("Drag to move the perpendicular slit")
        ortho_layout.addWidget(self.ortho_slider)

        ortho_pos_row = QHBoxLayout()
        self.ortho_spin = QSpinBox()
        self.ortho_spin.setRange(0, 1080)
        self.ortho_spin.setSuffix(" px")
        self.ortho_spin.setToolTip("Pixel position of the perpendicular slit")
        ortho_pos_row.addWidget(self.ortho_spin)
        ortho_pos_row.addStretch()
        ortho_layout.addLayout(ortho_pos_row)

        # Display Frames
        df_row = QHBoxLayout()
        df_row.addWidget(QLabel("Display Frames:"))
        self.display_frames_combo = QComboBox()
        self.display_frames_combo.addItems([
            "None", "Central frame", "Every N frames",
            "N frames total", "Specific frames"
        ])
        self.display_frames_combo.setCurrentText("Central frame")
        self.display_frames_combo.setToolTip(
            "Which full video frames to show as cross\u2011section planes in 3D\n"
            "'Every N frames' = every Nth sampled frame\n"
            "'N frames total' = distribute exactly N frames evenly"
        )
        df_row.addWidget(self.display_frames_combo)
        ortho_layout.addLayout(df_row)

        # "Every N frames" input
        self._every_n_row = QWidget()
        every_n_layout = QHBoxLayout(self._every_n_row)
        every_n_layout.setContentsMargins(0, 0, 0, 0)
        every_n_layout.addWidget(QLabel("N:"))
        self.every_n_spin = QSpinBox()
        self.every_n_spin.setRange(1, 100000)
        self.every_n_spin.setValue(10)
        self.every_n_spin.setToolTip(
            "Every N frames: show one frame every N sampled frames\n"
            "N frames total: distribute exactly N frames evenly"
        )
        every_n_layout.addWidget(self.every_n_spin)
        self._every_n_row.setVisible(False)
        ortho_layout.addWidget(self._every_n_row)

        # "Specific frames" input
        self._specific_row = QWidget()
        specific_layout = QHBoxLayout(self._specific_row)
        specific_layout.setContentsMargins(0, 0, 0, 0)
        specific_layout.addWidget(QLabel("Frames:"))
        self.specific_edit = QLineEdit()
        self.specific_edit.setPlaceholderText("e.g. 104, 333, 578")
        self.specific_edit.setToolTip("Comma-separated frame numbers")
        specific_layout.addWidget(self.specific_edit)
        self._specific_row.setVisible(False)
        ortho_layout.addWidget(self._specific_row)

        self._ortho_container.setVisible(False)
        layout.addWidget(self._ortho_container)

        layout.addStretch()

    def _connect_signals(self):
        self.orientation_combo.currentTextChanged.connect(self._on_setting_changed)
        self.width_spin.valueChanged.connect(self._on_setting_changed)
        self.position_slider.valueChanged.connect(self._on_position_slider_changed)
        self.position_spin.valueChanged.connect(self._on_position_spin_changed)
        self.reverse_check.stateChanged.connect(self._on_setting_changed)
        self._state.video_changed.connect(self._on_video_changed)
        self._state.settings_changed.connect(self._update_output_label)
        # Orthogonal
        self.orthogonal_check.toggled.connect(self._on_orthogonal_toggled)
        self.ortho_slider.valueChanged.connect(self._on_ortho_slider_changed)
        self.ortho_spin.valueChanged.connect(self._on_ortho_spin_changed)
        self.display_frames_combo.currentTextChanged.connect(self._on_display_frames_changed)
        self.every_n_spin.valueChanged.connect(self._on_display_frames_setting_changed)
        self.specific_edit.textChanged.connect(self._on_display_frames_setting_changed)

    def _on_video_changed(self):
        vs = self._state.video_source
        if vs is None:
            return
        max_pos = vs.width - 1
        self.position_slider.setRange(0, max_pos)
        self.position_spin.setRange(0, max_pos)
        center = vs.width // 2
        self.position_slider.setValue(center)
        self.position_spin.setValue(center)
        # Orthogonal slit defaults to center of perpendicular axis
        ortho_max = vs.height - 1
        self.ortho_slider.setRange(0, ortho_max)
        self.ortho_spin.setRange(0, ortho_max)
        ortho_center = vs.height // 2
        self.ortho_slider.setValue(ortho_center)
        self.ortho_spin.setValue(ortho_center)
        self._state.ortho_position = ortho_center
        self._update_output_label()

    def _on_position_slider_changed(self, value):
        if self._updating:
            return
        self._updating = True
        self.position_spin.setValue(value)
        self._state.slit_position = value
        self.slit_position_changed.emit(value)
        self.settings_changed.emit()
        self._updating = False

    def _on_position_spin_changed(self, value):
        if self._updating:
            return
        self._updating = True
        self.position_slider.setValue(value)
        self._state.slit_position = value
        self.slit_position_changed.emit(value)
        self.settings_changed.emit()
        self._updating = False

    def _on_setting_changed(self):
        self._state.slit_width = self.width_spin.value()
        self._state.slit_orientation = self.orientation_combo.currentText()
        self._state.slice_reverse_time = self.reverse_check.isChecked()
        # Update position range based on width
        vs = self._state.video_source
        if vs:
            dim = vs.width if self._state.slit_orientation == "Vertical" else vs.height
            max_pos = max(0, dim - self.width_spin.value())
            self.position_slider.setRange(0, max_pos)
            self.position_spin.setRange(0, max_pos)
        self._update_output_label()
        self.settings_changed.emit()

    def _update_output_label(self):
        vs = self._state.video_source
        if vs is None:
            self.output_label.setText("Output: —")
            return

        slit_w = self.width_spin.value()
        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        if self.orientation_combo.currentText() == "Vertical":
            out_w = num_frames * slit_w
            out_h = vs.height
        else:
            out_w = vs.width
            out_h = num_frames * slit_w

        self.output_label.setText(
            f"Output: {out_w} × {out_h} px\n"
            f"({num_frames} frames sampled)"
        )

    def set_position_from_drag(self, pos: int):
        """Called by FrameViewer when the slit is dragged."""
        self._updating = True
        self.position_slider.setValue(pos)
        self.position_spin.setValue(pos)
        self._state.slit_position = pos
        self._updating = False

    def set_ortho_position_from_drag(self, pos: int):
        """Called by FrameViewer when the orthogonal slit is dragged."""
        self._updating = True
        self.ortho_slider.setValue(pos)
        self.ortho_spin.setValue(pos)
        self._state.ortho_position = pos
        self._updating = False

    # --- Orthogonal handlers ---

    def _on_orthogonal_toggled(self, checked):
        self._state.orthogonal_enabled = checked
        self._ortho_container.setVisible(checked)
        self.orthogonal_toggled.emit(checked)
        self.settings_changed.emit()

    def _on_ortho_slider_changed(self, value):
        if self._updating:
            return
        self._updating = True
        self.ortho_spin.setValue(value)
        self._state.ortho_position = value
        self.ortho_position_changed.emit(value)
        self.settings_changed.emit()
        self._updating = False

    def _on_ortho_spin_changed(self, value):
        if self._updating:
            return
        self._updating = True
        self.ortho_slider.setValue(value)
        self._state.ortho_position = value
        self.ortho_position_changed.emit(value)
        self.settings_changed.emit()
        self._updating = False

    def _on_display_frames_changed(self, text):
        self._state.display_frames_mode = text
        self._every_n_row.setVisible(text in ("Every N frames", "N frames total"))
        self._specific_row.setVisible(text == "Specific frames")
        self.settings_changed.emit()

    def _on_display_frames_setting_changed(self):
        self._state.display_frames_n = self.every_n_spin.value()
        self._state.display_frames_list = self.specific_edit.text()
        self.settings_changed.emit()

    def get_display_frame_indices(self):
        """Return list of frame indices to display as planes in 3D preview."""
        mode = self._state.display_frames_mode
        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate

        if mode == "None":
            return []
        elif mode == "Central frame":
            return [(initial + last) // 2]
        elif mode == "Every N frames":
            n = max(1, self._state.display_frames_n)
            # Step through sampled frames, not raw video frames
            return list(range(initial, last + 1, n * sampling))
        elif mode == "N frames total":
            n = max(1, self._state.display_frames_n)
            sampled_count = max(1, (last - initial) // sampling + 1)
            if n >= sampled_count:
                return list(range(initial, last + 1, sampling))
            step = max(1, (sampled_count - 1) / max(1, n - 1))
            indices = []
            for i in range(n):
                idx = initial + round(i * step) * sampling
                idx = min(idx, last)
                if idx not in indices:
                    indices.append(idx)
            return indices
        elif mode == "Specific frames":
            indices = []
            for part in self._state.display_frames_list.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part)
                    if initial <= idx <= last:
                        indices.append(idx)
            return indices
        return []
