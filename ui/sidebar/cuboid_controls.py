from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from processing.object_detector import is_onnxruntime_available, is_model_available


# Minimum width/height of the mask in pixels.  Each border must leave at
# least this many pixels between itself and the opposite border so that
# the mask never collapses (or inverts) when dragging or typing values.
MIN_MASK_DIM = 10


class CuboidControls(QGroupBox):
    """Sidebar controls for Cuboid mode (Void & Fill with extraction options)."""

    settings_changed = Signal()
    borders_changed = Signal()
    eyedropper_requested = Signal()
    preview_mask_requested = Signal()
    prompt_point_requested = Signal()
    download_model_requested = Signal(str)  # model_name

    def __init__(self, project_state, parent=None):
        super().__init__("Cuboid Parameters", parent)
        self._state = project_state
        self._updating = False
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Mask Borders ---
        mask_group = QGroupBox("Mask Borders")
        mask_layout = QVBoxLayout(mask_group)

        border_row1 = QHBoxLayout()
        border_row1.addWidget(QLabel("Left:"))
        self.left_spin = QSpinBox()
        self.left_spin.setSuffix(" px")
        self.left_spin.setToolTip("Pixels inward from the left frame edge")
        border_row1.addWidget(self.left_spin)
        border_row1.addWidget(QLabel("Right:"))
        self.right_spin = QSpinBox()
        self.right_spin.setSuffix(" px")
        self.right_spin.setToolTip("Pixels inward from the right frame edge")
        border_row1.addWidget(self.right_spin)
        mask_layout.addLayout(border_row1)

        border_row2 = QHBoxLayout()
        border_row2.addWidget(QLabel("Top:"))
        self.top_spin = QSpinBox()
        self.top_spin.setSuffix(" px")
        self.top_spin.setToolTip("Pixels inward from the top frame edge")
        border_row2.addWidget(self.top_spin)
        border_row2.addWidget(QLabel("Bottom:"))
        self.bottom_spin = QSpinBox()
        self.bottom_spin.setSuffix(" px")
        self.bottom_spin.setToolTip("Pixels inward from the bottom frame edge")
        border_row2.addWidget(self.bottom_spin)
        mask_layout.addLayout(border_row2)

        layout.addWidget(mask_group)

        # --- Fill Mode ---
        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("Fill Mode:"))
        self.fill_combo = QComboBox()
        self.fill_combo.addItems(["Void (edges only)", "Fill (all pixels)"])
        self.fill_combo.setToolTip(
            "Void extracts only the surface pixels (fast, low memory).\n"
            "Fill captures all pixels per frame (slow, high disk usage)."
        )
        fill_row.addWidget(self.fill_combo)
        layout.addLayout(fill_row)

        # --- Extraction Mode (only visible when Fill is selected) ---
        self.extraction_group = QGroupBox("Extraction")
        extraction_layout = QVBoxLayout(self.extraction_group)

        ext_row = QHBoxLayout()
        ext_row.addWidget(QLabel("Method:"))
        self.extraction_combo = QComboBox()
        self.extraction_combo.addItems(["None", "Chroma Key", "Edge Detect", "AI Segment"])
        self.extraction_combo.setToolTip(
            "Choose how to separate foreground from background:\n"
            "• None — keep all pixels as-is\n"
            "• Chroma Key — make a selected color transparent\n"
            "• Edge Detect — Canny edge detection (fast, no download)\n"
            "• AI Segment — U²-Net neural network (best quality)"
        )
        ext_row.addWidget(self.extraction_combo)
        extraction_layout.addLayout(ext_row)

        # Stacked sub-panels for extraction-specific controls
        self.extraction_stack = QStackedWidget()

        # Index 0: None — empty placeholder
        self.extraction_stack.addWidget(QWidget())

        # Index 1: Chroma Key controls
        self._chroma_widget = self._build_chroma_panel()
        self.extraction_stack.addWidget(self._chroma_widget)

        # Index 2: Edge Detect controls
        self._edge_widget = self._build_edge_panel()
        self.extraction_stack.addWidget(self._edge_widget)

        # Index 3: AI Segment controls
        self._ai_widget = self._build_ai_panel()
        self.extraction_stack.addWidget(self._ai_widget)

        extraction_layout.addWidget(self.extraction_stack)

        # Shared controls: Invert + Point Prompt + Preview Mask
        shared_row = QHBoxLayout()
        self.invert_check = QCheckBox("Invert mask")
        self.invert_check.setToolTip("Swap foreground and background.")
        shared_row.addWidget(self.invert_check)
        shared_row.addStretch()

        self.prompt_btn = QPushButton("Select object")
        self.prompt_btn.setToolTip(
            "Click on the video frame to select a specific object.\n"
            "Only the object at the clicked point will be extracted.\n"
            "Without this, all detected foreground is extracted."
        )
        shared_row.addWidget(self.prompt_btn)
        extraction_layout.addLayout(shared_row)

        preview_row = QHBoxLayout()
        self.preview_mask_btn = QPushButton("Preview Mask")
        self.preview_mask_btn.setToolTip(
            "Run extraction on the current frame and show the mask overlay.\n"
            "This does NOT process all frames — just a quick preview."
        )
        preview_row.addWidget(self.preview_mask_btn)

        self.clear_prompt_btn = QPushButton("Clear point")
        self.clear_prompt_btn.setToolTip("Remove the point prompt and return to auto mode.")
        self.clear_prompt_btn.setEnabled(False)
        preview_row.addWidget(self.clear_prompt_btn)
        extraction_layout.addLayout(preview_row)

        # Hide invert/prompt/preview when extraction is None
        self._shared_controls = [
            self.invert_check, self.prompt_btn,
            self.preview_mask_btn, self.clear_prompt_btn,
        ]

        layout.addWidget(self.extraction_group)
        self.extraction_group.setVisible(False)  # hidden until Fill is selected

        # --- Preview checkbox ---
        self.preview_check = QCheckBox("Generate 3D preview after export")
        self.preview_check.setChecked(True)
        self.preview_check.setToolTip(
            "Creates an interactive 3D preview in the app.\n"
            "Deactivate for better performance with large videos."
        )
        layout.addWidget(self.preview_check)

        # --- Fill 3D visualization controls (visible when Fill is selected) ---
        self.fill_3d_group = QGroupBox("3D Fill Options")
        fill3d_layout = QVBoxLayout(self.fill_3d_group)
        fill3d_layout.setSpacing(4)

        # Frame density (every N frames / all frames)
        density_row = QHBoxLayout()
        density_row.addWidget(QLabel("Frames:"))
        self.fill_density_combo = QComboBox()
        self.fill_density_combo.addItems(["Every N frames", "All frames"])
        self.fill_density_combo.setToolTip("How many internal frames to display in 3D")
        density_row.addWidget(self.fill_density_combo)
        self.fill_density_spin = QSpinBox()
        self.fill_density_spin.setRange(2, 10000)
        self.fill_density_spin.setValue(10)
        self.fill_density_spin.setPrefix("N=")
        self.fill_density_spin.setFixedWidth(70)
        self.fill_density_spin.setToolTip("Show one frame every N frames")
        density_row.addWidget(self.fill_density_spin)
        fill3d_layout.addLayout(density_row)

        # Frame spacing (0.5×, 1×, 2×, etc.)
        spacing_row = QHBoxLayout()
        spacing_row.addWidget(QLabel("Spacing:"))
        self.fill_spacing_combo = QComboBox()
        self.fill_spacing_combo.addItems(["0.25×", "0.5×", "1×", "2×", "3×", "5×", "8×", "12×", "20×"])
        self.fill_spacing_combo.setCurrentIndex(2)  # default to "1×"
        self.fill_spacing_combo.setFixedWidth(70)
        self.fill_spacing_combo.setToolTip(
            "Distance between frames in 3D.\n"
            "0.25× = dense/continuous, 0.5× = tight, 1× = touching, 20× = wide gaps."
        )
        spacing_row.addWidget(self.fill_spacing_combo)
        spacing_row.addStretch()
        fill3d_layout.addLayout(spacing_row)

        self.fill_3d_group.setVisible(False)  # only visible when Fill mode is selected
        layout.addWidget(self.fill_3d_group)

        # --- Output info ---
        self.output_label = QLabel("Output: —")
        self.output_label.setObjectName("infoLabel")
        self.output_label.setWordWrap(True)
        layout.addWidget(self.output_label)

        layout.addStretch()

    # --- Chroma Key sub-panel ---

    def _build_chroma_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        # Color row
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self.chroma_swatch = QLabel()
        self.chroma_swatch.setFixedSize(24, 24)
        self.chroma_swatch.setStyleSheet(
            "background-color: #000000; border: 1px solid #3c3c3c; border-radius: 3px;"
        )
        color_row.addWidget(self.chroma_swatch)
        self.chroma_color_label = QLabel("(0, 0, 0)")
        self.chroma_color_label.setObjectName("infoLabel")
        color_row.addWidget(self.chroma_color_label)
        color_row.addStretch()
        self.chroma_pick_btn = QPushButton("Pick")
        self.chroma_pick_btn.setToolTip("Click on the video frame to sample a color.")
        color_row.addWidget(self.chroma_pick_btn)
        layout.addLayout(color_row)

        # Tolerance
        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Tolerance:"))
        self.chroma_tolerance = QSlider(Qt.Horizontal)
        self.chroma_tolerance.setRange(0, 100)
        self.chroma_tolerance.setValue(10)
        self.chroma_tolerance.setToolTip(
            "How similar a pixel must be to become transparent.\n"
            "0 = exact match only, 100 = everything."
        )
        tol_row.addWidget(self.chroma_tolerance)
        self.chroma_tol_label = QLabel("10%")
        self.chroma_tol_label.setFixedWidth(35)
        tol_row.addWidget(self.chroma_tol_label)
        layout.addLayout(tol_row)

        # Fade
        fade_row = QHBoxLayout()
        fade_row.addWidget(QLabel("Fade:"))
        self.chroma_fade = QSlider(Qt.Horizontal)
        self.chroma_fade.setRange(0, 100)
        self.chroma_fade.setValue(5)
        self.chroma_fade.setToolTip(
            "Smoothness of the transparency edge.\n"
            "0 = hard edge, higher = softer gradient."
        )
        fade_row.addWidget(self.chroma_fade)
        self.chroma_fade_label = QLabel("5%")
        self.chroma_fade_label.setFixedWidth(35)
        fade_row.addWidget(self.chroma_fade_label)
        layout.addLayout(fade_row)

        return widget

    # --- Edge Detect sub-panel ---

    def _build_edge_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        # Canny Low
        low_row = QHBoxLayout()
        low_row.addWidget(QLabel("Canny Low:"))
        self.edge_canny_low = QSlider(Qt.Horizontal)
        self.edge_canny_low.setRange(1, 255)
        self.edge_canny_low.setValue(50)
        self.edge_canny_low.setToolTip("Lower threshold for Canny edge detector.\nLower = more edges detected.")
        low_row.addWidget(self.edge_canny_low)
        self.edge_low_label = QLabel("50")
        self.edge_low_label.setFixedWidth(30)
        low_row.addWidget(self.edge_low_label)
        layout.addLayout(low_row)

        # Canny High
        high_row = QHBoxLayout()
        high_row.addWidget(QLabel("Canny High:"))
        self.edge_canny_high = QSlider(Qt.Horizontal)
        self.edge_canny_high.setRange(1, 255)
        self.edge_canny_high.setValue(150)
        self.edge_canny_high.setToolTip("Upper threshold for Canny edge detector.\nHigher = fewer, stronger edges.")
        high_row.addWidget(self.edge_canny_high)
        self.edge_high_label = QLabel("150")
        self.edge_high_label.setFixedWidth(30)
        high_row.addWidget(self.edge_high_label)
        layout.addLayout(high_row)

        # Dilate iterations
        dilate_row = QHBoxLayout()
        dilate_row.addWidget(QLabel("Close gaps:"))
        self.edge_dilate = QSlider(Qt.Horizontal)
        self.edge_dilate.setRange(0, 10)
        self.edge_dilate.setValue(2)
        self.edge_dilate.setToolTip("Morphological closing iterations.\nHigher = larger gaps filled.")
        dilate_row.addWidget(self.edge_dilate)
        self.edge_dilate_label = QLabel("2")
        self.edge_dilate_label.setFixedWidth(20)
        dilate_row.addWidget(self.edge_dilate_label)
        layout.addLayout(dilate_row)

        # Min area
        area_row = QHBoxLayout()
        area_row.addWidget(QLabel("Min area:"))
        self.edge_min_area = QSpinBox()
        self.edge_min_area.setRange(0, 100000)
        self.edge_min_area.setValue(500)
        self.edge_min_area.setSuffix(" px²")
        self.edge_min_area.setToolTip("Ignore contours smaller than this.\nFilters noise and small artifacts.")
        area_row.addWidget(self.edge_min_area)
        layout.addLayout(area_row)

        return widget

    # --- AI Segment sub-panel ---

    def _build_ai_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        # Model selector
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.addItems(["u2netp (fast, 5 MB)", "u2net (quality, 176 MB)"])
        self.ai_model_combo.setToolTip(
            "u2netp: Fast, small model — good for most cases.\n"
            "u2net: Higher quality but larger download and slower."
        )
        model_row.addWidget(self.ai_model_combo)
        layout.addLayout(model_row)

        # Download button (shown when model is not available)
        self.ai_download_btn = QPushButton("Download Model")
        self.ai_download_btn.setToolTip("Download the selected AI model (~5–176 MB).")
        layout.addWidget(self.ai_download_btn)

        # Status label
        self.ai_status_label = QLabel("")
        self.ai_status_label.setObjectName("infoLabel")
        self.ai_status_label.setWordWrap(True)
        layout.addWidget(self.ai_status_label)

        # Confidence threshold
        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("Confidence:"))
        self.ai_confidence = QSlider(Qt.Horizontal)
        self.ai_confidence.setRange(1, 99)
        self.ai_confidence.setValue(50)
        self.ai_confidence.setToolTip(
            "Threshold for the segmentation probability map.\n"
            "Lower = more pixels included, higher = stricter selection."
        )
        conf_row.addWidget(self.ai_confidence)
        self.ai_conf_label = QLabel("0.50")
        self.ai_conf_label.setFixedWidth(35)
        conf_row.addWidget(self.ai_conf_label)
        layout.addLayout(conf_row)

        # Check availability
        self._update_ai_status()

        return widget

    # --- Signal wiring ---

    def _connect_signals(self):
        for spin in (self.left_spin, self.right_spin, self.top_spin, self.bottom_spin):
            spin.valueChanged.connect(self._on_border_changed)

        self.fill_combo.currentIndexChanged.connect(self._on_fill_mode_changed)
        self.fill_density_combo.currentTextChanged.connect(self._on_fill_density_changed)
        self.fill_density_spin.valueChanged.connect(self._on_fill_density_spin_changed)
        self.fill_spacing_combo.currentTextChanged.connect(self._on_fill_spacing_changed)
        self.extraction_combo.currentIndexChanged.connect(self._on_extraction_changed)
        self.preview_check.toggled.connect(self._on_preview_toggled)

        # Chroma signals
        self.chroma_pick_btn.clicked.connect(self._on_chroma_pick)
        self.chroma_tolerance.valueChanged.connect(self._on_chroma_tol_changed)
        self.chroma_fade.valueChanged.connect(self._on_chroma_fade_changed)

        # Edge signals
        self.edge_canny_low.valueChanged.connect(
            lambda v: (self.edge_low_label.setText(str(v)), self._sync_extraction_to_state()))
        self.edge_canny_high.valueChanged.connect(
            lambda v: (self.edge_high_label.setText(str(v)), self._sync_extraction_to_state()))
        self.edge_dilate.valueChanged.connect(
            lambda v: (self.edge_dilate_label.setText(str(v)), self._sync_extraction_to_state()))
        self.edge_min_area.valueChanged.connect(lambda _: self._sync_extraction_to_state())

        # AI signals
        self.ai_model_combo.currentIndexChanged.connect(self._on_ai_model_changed)
        self.ai_confidence.valueChanged.connect(self._on_ai_confidence_changed)
        self.ai_download_btn.clicked.connect(self._on_download_model)

        # Shared extraction signals
        self.invert_check.toggled.connect(self._on_invert_changed)
        self.prompt_btn.clicked.connect(self._on_prompt_point_clicked)
        self.preview_mask_btn.clicked.connect(self._on_preview_mask_clicked)
        self.clear_prompt_btn.clicked.connect(self._on_clear_prompt)

        self._state.video_changed.connect(self._on_video_changed)
        self._state.settings_changed.connect(self._update_output_label)

    # --- Fill mode ---

    def _on_fill_mode_changed(self, index):
        is_fill = index == 1
        self._state.cuboid_fill_mode = "Fill" if is_fill else "Void"
        self.extraction_group.setVisible(is_fill)
        self.fill_3d_group.setVisible(is_fill)
        if not is_fill:
            # Reset extraction to None when switching to Void
            self.extraction_combo.setCurrentIndex(0)
            self._state.extraction_mode = "none"
            self._state.chroma_enabled = False
        self.settings_changed.emit()

    def _on_fill_density_changed(self, text):
        self.fill_density_spin.setVisible(text == "Every N frames")
        self._state.cuboid_fill_density_mode = text
        self._state.cuboid_fill_density_n = self.fill_density_spin.value()

    def _on_fill_density_spin_changed(self, value):
        self._state.cuboid_fill_density_n = value

    def _on_fill_spacing_changed(self, text):
        self._state.cuboid_fill_spacing = text

    # --- Extraction mode ---

    def _on_extraction_changed(self, index):
        self.extraction_stack.setCurrentIndex(index)
        mode_map = {0: "none", 1: "chroma", 2: "edge_detect", 3: "ai_segment"}
        mode = mode_map.get(index, "none")
        self._state.extraction_mode = mode
        self._state.chroma_enabled = (mode == "chroma")

        # Show/hide shared controls (invert, prompt, preview) for non-None modes
        visible = index > 0
        for w in self._shared_controls:
            w.setVisible(visible)
        # Chroma doesn't use point prompt or preview mask (it has its own eyedropper)
        chroma_mode = index == 1
        self.prompt_btn.setVisible(not chroma_mode and visible)
        self.clear_prompt_btn.setVisible(not chroma_mode and visible)
        self.preview_mask_btn.setVisible(visible)

        # Clear point prompt when switching modes
        self._state.extraction_prompt_point = None
        self.clear_prompt_btn.setEnabled(False)

        if index == 3:
            self._update_ai_status()

        self.settings_changed.emit()

    # --- Chroma Key ---

    def _on_chroma_pick(self):
        self.eyedropper_requested.emit()

    def _on_chroma_tol_changed(self, value):
        self.chroma_tol_label.setText(f"{value}%")
        self._state.chroma_tolerance = value / 100.0
        self.settings_changed.emit()

    def _on_chroma_fade_changed(self, value):
        self.chroma_fade_label.setText(f"{value}%")
        self._state.chroma_fade = value / 100.0
        self.settings_changed.emit()

    def set_chroma_color(self, r, g, b):
        """Called after eyedropper samples a pixel."""
        self._state.chroma_color = (r, g, b)
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        self.chroma_swatch.setStyleSheet(
            f"background-color: {hex_color}; border: 1px solid #3c3c3c; border-radius: 3px;"
        )
        self.chroma_color_label.setText(f"({r}, {g}, {b})")
        self.settings_changed.emit()

    # --- Edge Detect ---

    def _sync_extraction_to_state(self):
        self._state.edge_canny_low = self.edge_canny_low.value()
        self._state.edge_canny_high = self.edge_canny_high.value()
        self._state.edge_dilate = self.edge_dilate.value()
        self._state.edge_min_area = self.edge_min_area.value()
        self.settings_changed.emit()

    # --- AI Segment ---

    def _on_ai_model_changed(self, index):
        model_name = "u2netp" if index == 0 else "u2net"
        self._state.ai_model = model_name
        self._update_ai_status()
        self.settings_changed.emit()

    def _on_ai_confidence_changed(self, value):
        conf = value / 100.0
        self.ai_conf_label.setText(f"{conf:.2f}")
        self._state.ai_confidence = conf
        self.settings_changed.emit()

    def _on_download_model(self):
        model_name = "u2netp" if self.ai_model_combo.currentIndex() == 0 else "u2net"
        self.download_model_requested.emit(model_name)

    def _update_ai_status(self):
        """Update the AI panel status label and download button visibility."""
        if not is_onnxruntime_available():
            self.ai_status_label.setText(
                "⚠ onnxruntime not installed.\n"
                "Run: pip install onnxruntime"
            )
            self.ai_download_btn.setVisible(False)
            self.ai_confidence.setEnabled(False)
            return

        model_name = "u2netp" if self.ai_model_combo.currentIndex() == 0 else "u2net"
        if is_model_available(model_name):
            self.ai_status_label.setText(f"✓ Model ready ({model_name})")
            self.ai_download_btn.setVisible(False)
            self.ai_confidence.setEnabled(True)
        else:
            self.ai_status_label.setText(f"Model not downloaded yet.")
            self.ai_download_btn.setVisible(True)
            self.ai_confidence.setEnabled(False)

    def set_ai_download_complete(self):
        """Called after model download finishes."""
        self._update_ai_status()

    # --- Shared extraction controls ---

    def _on_invert_changed(self, checked):
        self._state.extraction_invert = checked
        self.settings_changed.emit()

    def _on_prompt_point_clicked(self):
        self.prompt_point_requested.emit()

    def set_prompt_point(self, x, y):
        """Called after user clicks on the frame for point prompt."""
        self._state.extraction_prompt_point = (x, y)
        self.clear_prompt_btn.setEnabled(True)
        self.prompt_btn.setText(f"Point: ({x}, {y})")
        self.settings_changed.emit()

    def _on_clear_prompt(self):
        self._state.extraction_prompt_point = None
        self.clear_prompt_btn.setEnabled(False)
        self.prompt_btn.setText("Select object")
        self.settings_changed.emit()

    def _on_preview_mask_clicked(self):
        self.preview_mask_requested.emit()

    # --- Borders, video change, etc. ---

    def _on_video_changed(self):
        vs = self._state.video_source
        if vs is None:
            return
        # Each border can go almost up to the opposite side of the frame:
        # its maximum is `dimension - opposite_border - MIN_MASK_DIM`.
        # That lets the user shrink the mask into a small window anywhere
        # in the frame (e.g. drag a tiny mask around past the centre line).
        for spin, dim in [
            (self.left_spin, vs.width),
            (self.right_spin, vs.width),
            (self.top_spin, vs.height),
            (self.bottom_spin, vs.height),
        ]:
            spin.blockSignals(True)
            spin.setRange(0, max(0, dim - MIN_MASK_DIM))
            spin.setValue(0)
            spin.blockSignals(False)
        self._sync_to_state()
        self._refresh_border_ranges()
        self._update_output_label()

    def _refresh_border_ranges(self):
        """Update each border spinbox's max so it can grow up to the
        opposite-side border (leaving ``MIN_MASK_DIM`` px of mask)."""
        vs = self._state.video_source
        if vs is None:
            return
        pairs = [
            (self.left_spin, self.right_spin, vs.width),
            (self.right_spin, self.left_spin, vs.width),
            (self.top_spin, self.bottom_spin, vs.height),
            (self.bottom_spin, self.top_spin, vs.height),
        ]
        for spin, opposite, dim in pairs:
            new_max = max(0, dim - opposite.value() - MIN_MASK_DIM)
            if spin.maximum() != new_max:
                spin.blockSignals(True)
                spin.setMaximum(new_max)
                spin.blockSignals(False)

    def _on_border_changed(self):
        if self._updating:
            return
        # Refresh ranges so each spinbox can be increased up to (frame
        # dimension - opposite_border - MIN_MASK_DIM) instead of being
        # capped at the centre of the frame.  This allows shrinking the
        # mask down to a small window anywhere in the frame.
        self._refresh_border_ranges()
        self._sync_to_state()
        self._update_output_label()
        self.borders_changed.emit()
        self.settings_changed.emit()

    def _on_preview_toggled(self, checked):
        self._state.cuboid_preview_enabled = checked

    def _sync_to_state(self):
        self._state.cuboid_border_left = self.left_spin.value()
        self._state.cuboid_border_right = self.right_spin.value()
        self._state.cuboid_border_top = self.top_spin.value()
        self._state.cuboid_border_bottom = self.bottom_spin.value()

    def _update_output_label(self):
        vs = self._state.video_source
        if vs is None:
            self.output_label.setText("Output: —")
            return

        l, r = self.left_spin.value(), self.right_spin.value()
        t, b = self.top_spin.value(), self.bottom_spin.value()
        mask_w = vs.width - l - r
        mask_h = vs.height - t - b

        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        self.output_label.setText(
            f"Mask: {mask_w} × {mask_h} px\n"
            f"Front/Back: {mask_w} × {mask_h}\n"
            f"Left/Right: {num_frames} × {mask_h}\n"
            f"Top/Bottom: {mask_w} × {num_frames}\n"
            f"({num_frames} frames sampled)"
        )

    def set_borders_from_drag(self, left, right, top, bottom):
        """Called by FrameViewer when mask edges are dragged."""
        self._updating = True
        # Temporarily widen each spinbox's range so the incoming dragged
        # values (which may exceed the previous opposite-border cap)
        # don't get clipped.  The proper opposite-border-aware ranges are
        # restored immediately afterwards.
        vs = self._state.video_source
        if vs is not None:
            for spin, dim in [
                (self.left_spin, vs.width),
                (self.right_spin, vs.width),
                (self.top_spin, vs.height),
                (self.bottom_spin, vs.height),
            ]:
                spin.setMaximum(max(0, dim - MIN_MASK_DIM))
        self.left_spin.setValue(left)
        self.right_spin.setValue(right)
        self.top_spin.setValue(top)
        self.bottom_spin.setValue(bottom)
        self._refresh_border_ranges()
        self._sync_to_state()
        self._update_output_label()
        self._updating = False
