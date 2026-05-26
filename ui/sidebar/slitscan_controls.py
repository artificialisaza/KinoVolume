"""Sidebar controls for Slit-scan mode."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SlitscanControls(QGroupBox):
    """Sidebar panel for Slit-scan (spatial-temporal scan) mode."""

    settings_changed = Signal()

    def __init__(self, project_state, parent=None):
        super().__init__("Slit-scan Parameters", parent)
        self._state = project_state
        self._updating = False
        self._build_ui()
        self._connect_signals()
        self._on_mask_type_changed()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Mask type
        type_row = QHBoxLayout()
        mask_type_label = QLabel("Mask Type:")
        mask_type_label.setToolTip(
            "Vertical: scan lines travel left-to-right (or right-to-left) over time.\n"
            "Horizontal: scan lines travel top-to-bottom (or bottom-to-top) over time."
        )
        type_row.addWidget(mask_type_label)
        self.mask_type_combo = QComboBox()
        self.mask_type_combo.addItems(["Vertical", "Horizontal"])
        self.mask_type_combo.setToolTip(
            "Vertical: scan lines travel left-to-right (or right-to-left) over time.\n"
            "Horizontal: scan lines travel top-to-bottom (or bottom-to-top) over time."
        )
        type_row.addWidget(self.mask_type_combo)
        layout.addLayout(type_row)

        # Sampling mode (before scan direction so we can show/hide based on it)
        samp_row = QHBoxLayout()
        sampling_label = QLabel("Sampling:")
        sampling_label.setToolTip(
            "Planar cut (3D): diagonal plane cut through the video cube.\n"
            "  The slit sweeps edge-to-edge — visualisable as a 3D plane.\n"
            "All frames: slit sweeps across the mask — each frame = one output column/row.\n"
            "Fit to frame size: like 'All frames' but caps output to available pixels."
        )
        samp_row.addWidget(sampling_label)
        self.sampling_combo = QComboBox()
        self.sampling_combo.addItems(["Planar cut (3D)", "All frames", "Fit to frame size"])
        self.sampling_combo.setToolTip(
            "Planar cut (3D): diagonal plane cut through the video cube.\n"
            "  The slit sweeps edge-to-edge — visualisable as a 3D plane.\n"
            "All frames: slit sweeps across the mask — each frame = one output column/row.\n"
            "Fit to frame size: like 'All frames' but caps output to available pixels."
        )
        samp_row.addWidget(self.sampling_combo)
        layout.addLayout(samp_row)
        self.sampling_combo.setCurrentIndex(0)

        # Scan direction (wrapped so we can show/hide)
        self._scan_dir_widget = QWidget()
        sd_layout = QHBoxLayout(self._scan_dir_widget)
        sd_layout.setContentsMargins(0, 0, 0, 0)
        scan_dir_label = QLabel("Scan Direction:")
        scan_dir_label.setToolTip(
            "L→R: scan starts at left edge, moves right over time.\n"
            "R→L: scan starts at right edge, moves left over time.\n"
            "T→B: scan starts at top edge, moves down over time.\n"
            "B→T: scan starts at bottom edge, moves up over time."
        )
        sd_layout.addWidget(scan_dir_label)
        self.scan_dir_combo = QComboBox()
        self.scan_dir_combo.setToolTip(
            "L→R: scan starts at left edge, moves right over time.\n"
            "R→L: scan starts at right edge, moves left over time.\n"
            "T→B: scan starts at top edge, moves down over time.\n"
            "B→T: scan starts at bottom edge, moves up over time."
        )
        sd_layout.addWidget(self.scan_dir_combo)
        layout.addWidget(self._scan_dir_widget)

        # Slit width (wrapped so we can show/hide — only for All frames / Fit to frame size)
        self._width_widget = QWidget()
        width_row = QHBoxLayout(self._width_widget)
        width_row.setContentsMargins(0, 0, 0, 0)
        slit_width_label = QLabel("Slit Width:")
        slit_width_label.setToolTip(
            "Width of the strip extracted from each frame.\n"
            "1 = single pixel column/row. Wider values capture more per frame.\n"
            "Only used in 'All frames' or 'Fit to frame size' sampling modes."
        )
        width_row.addWidget(slit_width_label)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 99999)
        self.width_spin.setValue(1)
        self.width_spin.setSuffix(" px")
        self.width_spin.setToolTip(
            "Width of the strip extracted from each frame.\n"
            "1 = single pixel column/row. Wider values capture more per frame.\n"
            "Only used in 'All frames' or 'Fit to frame size' sampling modes."
        )
        width_row.addWidget(self.width_spin)
        layout.addWidget(self._width_widget)

        # Plane position (visible for Planar cut mode)
        self._plane_pos_widget = QWidget()
        pos_row = QHBoxLayout(self._plane_pos_widget)
        pos_row.setContentsMargins(0, 0, 0, 0)
        slit_pos_label = QLabel("Slit Position:")
        slit_pos_label.setToolTip(
            "Position of the fixed slit in the frame.\n"
            "Vertical: X coordinate. Horizontal: Y coordinate.\n"
            "The plane is extracted at this position across all frames."
        )
        pos_row.addWidget(slit_pos_label)
        self.plane_pos_spin = QSpinBox()
        self.plane_pos_spin.setRange(0, 99999)
        self.plane_pos_spin.setValue(0)
        self.plane_pos_spin.setSuffix(" px")
        self.plane_pos_spin.setToolTip(
            "Position of the fixed slit in the frame.\n"
            "Vertical: X coordinate. Horizontal: Y coordinate.\n"
            "The plane is extracted at this position across all frames."
        )
        pos_row.addWidget(self.plane_pos_spin)
        layout.addWidget(self._plane_pos_widget)

        # Mask border insets (like cuboid, visible for Vertical/Horizontal)
        self._mask_container = QWidget()
        mask_layout = QVBoxLayout(self._mask_container)
        mask_layout.setContentsMargins(0, 0, 0, 0)
        mask_borders_label = QLabel("Mask Borders (px from edge):")
        mask_borders_label.setToolTip(
            "Crop pixels from each edge of the frame to define the active scan region.\n"
            "Only pixels inside the borders are scanned."
        )
        mask_layout.addWidget(mask_borders_label)

        borders_grid = QHBoxLayout()

        # Left / Right
        lr_col = QVBoxLayout()
        lr_row = QHBoxLayout()
        lr_row.addWidget(QLabel("L:"))
        self.left_spin = QSpinBox()
        self.left_spin.setRange(0, 1920)
        self.left_spin.setValue(0)
        self.left_spin.setSuffix(" px")
        self.left_spin.setToolTip("Pixels to crop from the left edge")
        lr_row.addWidget(self.left_spin)
        lr_col.addLayout(lr_row)

        r_row = QHBoxLayout()
        r_row.addWidget(QLabel("R:"))
        self.right_spin = QSpinBox()
        self.right_spin.setRange(0, 1920)
        self.right_spin.setValue(0)
        self.right_spin.setSuffix(" px")
        self.right_spin.setToolTip("Pixels to crop from the right edge")
        r_row.addWidget(self.right_spin)
        lr_col.addLayout(r_row)
        borders_grid.addLayout(lr_col)

        # Top / Bottom
        tb_col = QVBoxLayout()
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("T:"))
        self.top_spin = QSpinBox()
        self.top_spin.setRange(0, 1080)
        self.top_spin.setValue(0)
        self.top_spin.setSuffix(" px")
        self.top_spin.setToolTip("Pixels to crop from the top edge")
        t_row.addWidget(self.top_spin)
        tb_col.addLayout(t_row)

        b_row = QHBoxLayout()
        b_row.addWidget(QLabel("B:"))
        self.bottom_spin = QSpinBox()
        self.bottom_spin.setRange(0, 1080)
        self.bottom_spin.setValue(0)
        self.bottom_spin.setSuffix(" px")
        self.bottom_spin.setToolTip("Pixels to crop from the bottom edge")
        b_row.addWidget(self.bottom_spin)
        tb_col.addLayout(b_row)
        borders_grid.addLayout(tb_col)

        mask_layout.addLayout(borders_grid)
        layout.addWidget(self._mask_container)

        # Reverse time checkbox
        self.reverse_check = QCheckBox("Reverse time")
        self.reverse_check.setToolTip(
            "Sample frames in reverse chronological order."
        )
        layout.addWidget(self.reverse_check)

        # Output info label
        self.info_label = QLabel("Output: —")
        self.info_label.setObjectName("infoLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        layout.addStretch()

    def _connect_signals(self):
        self.mask_type_combo.currentTextChanged.connect(self._on_mask_type_changed)
        self.sampling_combo.currentTextChanged.connect(self._on_sampling_changed)
        self.scan_dir_combo.currentTextChanged.connect(self._on_setting_changed)
        self.width_spin.valueChanged.connect(self._on_setting_changed)
        self.plane_pos_spin.valueChanged.connect(self._on_setting_changed)
        self.left_spin.valueChanged.connect(self._on_setting_changed)
        self.right_spin.valueChanged.connect(self._on_setting_changed)
        self.top_spin.valueChanged.connect(self._on_setting_changed)
        self.bottom_spin.valueChanged.connect(self._on_setting_changed)
        self.reverse_check.stateChanged.connect(self._on_setting_changed)
        self._state.video_changed.connect(self._on_video_changed)
        self._state.settings_changed.connect(self._update_info)

    def _on_mask_type_changed(self):
        mask_type = self.mask_type_combo.currentText()

        # Update scan direction combo options
        self.scan_dir_combo.blockSignals(True)
        self.scan_dir_combo.clear()
        if mask_type == "Vertical":
            self.scan_dir_combo.addItems(["L→R", "R→L"])
        else:
            self.scan_dir_combo.addItems(["T→B", "B→T"])
        self.scan_dir_combo.blockSignals(False)

        # Update sampling combo
        self.sampling_combo.blockSignals(True)
        current_sampling = self.sampling_combo.currentText()
        self.sampling_combo.clear()
        self.sampling_combo.addItems(["Planar cut (3D)", "All frames", "Fit to frame size"])
        # Restore previous selection if valid
        idx = self.sampling_combo.findText(current_sampling)
        if idx >= 0:
            self.sampling_combo.setCurrentIndex(idx)
        else:
            self.sampling_combo.setCurrentIndex(0)  # Default to Planar cut
        self.sampling_combo.blockSignals(False)

        # Show/hide controls based on mask type and sampling mode
        self._update_control_visibility()
        self._on_setting_changed()

    def _on_sampling_changed(self):
        """Handle sampling mode change - update visibility and settings."""
        self._update_control_visibility()
        self._on_setting_changed()

    def _update_control_visibility(self):
        """Show/hide controls based on current mask type and sampling mode."""
        sampling = self.sampling_combo.currentText()
        is_planar = sampling == "Planar cut (3D)"

        # Slit width: only visible for All frames / Fit to frame size
        self._width_widget.setVisible(not is_planar)

        # Scan direction, mask borders always visible
        self._scan_dir_widget.setVisible(True)
        self._mask_container.setVisible(True)
        self._plane_pos_widget.setVisible(False)

    def _on_video_changed(self):
        vs = self._state.video_source
        if vs is None:
            return
        self._updating = True
        self.left_spin.setRange(0, vs.width - 1)
        self.left_spin.setValue(0)
        self.right_spin.setRange(0, vs.width - 1)
        self.right_spin.setValue(0)
        self.top_spin.setRange(0, vs.height - 1)
        self.top_spin.setValue(0)
        self.bottom_spin.setRange(0, vs.height - 1)
        self.bottom_spin.setValue(0)
        # Set plane position defaults based on mask type
        mask_type = self.mask_type_combo.currentText()
        if mask_type == "Vertical":
            self.plane_pos_spin.setRange(0, vs.width - 1)
            self.plane_pos_spin.setValue(vs.width // 2)
        else:
            self.plane_pos_spin.setRange(0, vs.height - 1)
            self.plane_pos_spin.setValue(vs.height // 2)
        self._updating = False
        self._sync_to_state()
        self._update_info()

    def _on_setting_changed(self):
        if self._updating:
            return
        # Update plane_pos_spin range when mask type changes
        vs = self._state.video_source
        if vs is not None:
            mask_type = self.mask_type_combo.currentText()
            if mask_type == "Vertical":
                self.plane_pos_spin.setRange(0, vs.width - 1)
            elif mask_type == "Horizontal":
                self.plane_pos_spin.setRange(0, vs.height - 1)
        self._sync_to_state()
        self._update_info()
        self.settings_changed.emit()

    def _sync_to_state(self):
        s = self._state
        s.slitscan_mask_type = self.mask_type_combo.currentText()
        s.slitscan_slit_width = self.width_spin.value()
        s.slitscan_border_left = self.left_spin.value()
        s.slitscan_border_right = self.right_spin.value()
        s.slitscan_border_top = self.top_spin.value()
        s.slitscan_border_bottom = self.bottom_spin.value()
        s.slitscan_sampling_mode = self.sampling_combo.currentText()
        s.slitscan_scan_direction = self.scan_dir_combo.currentText()
        s.slitscan_reverse_time = self.reverse_check.isChecked()
        s.slitscan_plane_position = self.plane_pos_spin.value()

    def _update_info(self):
        vs = self._state.video_source
        if vs is None:
            self.info_label.setText("Output: —")
            return

        mask_type = self.mask_type_combo.currentText()
        slit_w = self.width_spin.value()
        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        l = self.left_spin.value()
        r = self.right_spin.value()
        t = self.top_spin.value()
        b = self.bottom_spin.value()
        mask_w = max(1, vs.width - l - r)
        mask_h = max(1, vs.height - t - b)

        sampling_mode = self.sampling_combo.currentText()

        if sampling_mode == "Planar cut (3D)":
            # Planar cut: diagonal sweep from edge to edge
            scan_dir = self.scan_dir_combo.currentText()
            if mask_type == "Vertical":
                out_w = num_frames * slit_w
                out_h = mask_h
                self.info_label.setText(
                    f"Diagonal plane ({scan_dir})\n"
                    f"Mask: {mask_w}×{mask_h} px\n"
                    f"Frames: {num_frames}\n"
                    f"Output: {out_w} × {out_h} px"
                )
            else:
                out_w = mask_w
                out_h = num_frames * slit_w
                self.info_label.setText(
                    f"Diagonal plane ({scan_dir})\n"
                    f"Mask: {mask_w}×{mask_h} px\n"
                    f"Frames: {num_frames}\n"
                    f"Output: {out_w} × {out_h} px"
                )
            return

        # All frames / Fit to frame size
        if mask_type == "Vertical":
            scan_range = mask_h
            max_scan = mask_w // max(1, slit_w)
        else:
            scan_range = mask_w
            max_scan = mask_h // max(1, slit_w)

        if sampling_mode == "Fit to frame size":
            used = min(num_frames, max_scan)
        else:
            used = num_frames

        if mask_type == "Vertical":
            out_w = used * slit_w
            out_h = mask_h
        else:
            out_w = mask_w
            out_h = used * slit_w

        frames_note = f"Video frames: {num_frames}"
        if used < num_frames:
            frames_note += f" (only {used} will be used)"
        self.info_label.setText(
            f"Mask: {mask_w}×{mask_h} px\n"
            f"{frames_note}\n"
            f"Output: {out_w} × {out_h} px"
        )

    def set_borders_from_drag(self, left, right, top, bottom):
        """Called by FrameViewer when mask borders are dragged."""
        self._updating = True
        self.left_spin.setValue(left)
        self.right_spin.setValue(right)
        self.top_spin.setValue(top)
        self.bottom_spin.setValue(bottom)
        self._sync_to_state()
        self._update_info()
        self._updating = False

    def set_plane_position_from_drag(self, pos):
        """Called when the slit position is dragged in Mask Selection view."""
        self._updating = True
        self.plane_pos_spin.setValue(pos)
        self._sync_to_state()
        self._update_info()
        self._updating = False
