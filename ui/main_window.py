import os
import threading

from PySide6.QtCore import Qt, QMetaObject, Q_ARG, Slot, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _AdaptiveStack(QStackedWidget):
    """QStackedWidget that sizes to the *current* page, not the largest."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self._page_changed)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        w = self.currentWidget()
        if w:
            return w.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        w = self.currentWidget()
        if w:
            return w.minimumSizeHint()
        return super().minimumSizeHint()

    def _page_changed(self, _index):
        for i in range(self.count()):
            self.widget(i).setSizePolicy(
                QSizePolicy.Preferred,
                QSizePolicy.Ignored if i != _index else QSizePolicy.Preferred,
            )
        self.updateGeometry()
        self.adjustSize()

from config import APP_NAME, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT, SIDEBAR_WIDTH
from models.project_state import ProjectState
from ui.sidebar.video_panel import VideoPanel
from ui.sidebar.mode_selector import ModeSelector
from ui.sidebar.slice_controls import SliceControls
from ui.sidebar.cuboid_controls import CuboidControls
from ui.sidebar.cylinder_controls import CylinderControls
from ui.sidebar.rings_controls import RingsControls
from ui.sidebar.slittear_controls import SlitTearControls
from ui.sidebar.slitscan_controls import SlitscanControls
from ui.sidebar.export_controls import ExportControls
from ui.sidebar.generate_panel import GeneratePanel
from ui.preview.frame_viewer import FrameViewer
from ui.preview.frame_scrubber import FrameScrubber
from ui.widgets.drawing_canvas import DrawingCanvas
from processing.slice_processor import SliceProcessor
from processing.cuboid_void_processor import CuboidVoidProcessor
from processing.cuboid_fill_processor import CuboidFillProcessor
from processing.cylinder_processor import CylinderProcessor
from processing.rings_processor import RingsProcessor
from processing.slittear_processor import SlitTearProcessor
from processing.slitscan_processor import SlitscanProcessor


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        self.state = ProjectState(self)
        self._last_result = None

        # Drawing canvas model for Slit-Tear mode
        self._drawing_canvas = DrawingCanvas(self)

        self._load_stylesheet()
        self._build_ui()
        self._connect_signals()

    def _load_stylesheet(self):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        qss_path = os.path.join(base_dir, "resources", "styles", "theme.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r") as f:
                qss = f.read()
            # Resolve relative resource paths to absolute
            res_prefix = os.path.join(base_dir, "resources").replace("\\", "/")
            qss = qss.replace("url(resources/", f"url({res_prefix}/")
            self.setStyleSheet(qss)

    def _build_ui(self):
        # --- Sidebar (left) ---
        self.sidebar_widget = QWidget()
        self.sidebar_layout = QVBoxLayout(self.sidebar_widget)
        self.sidebar_layout.setContentsMargins(10, 8, 10, 8)
        self.sidebar_layout.setSpacing(6)

        # Video panel
        self.video_panel = VideoPanel()
        self.sidebar_layout.addWidget(self.video_panel)

        # Mode selector
        self.mode_selector = ModeSelector()
        self.sidebar_layout.addWidget(self.mode_selector)

        # Stacked widget for mode-specific control panels
        self.mode_controls_stack = _AdaptiveStack()
        self.slice_controls = SliceControls(self.state)
        self.cuboid_controls = CuboidControls(self.state)
        self.cylinder_controls = CylinderControls(self.state)
        self.rings_controls = RingsControls(self.state)
        self.slittear_controls = SlitTearControls(self.state)
        self.slitscan_controls = SlitscanControls(self.state)
        self.mode_controls_stack.addWidget(self.cuboid_controls)    # index 0
        self.mode_controls_stack.addWidget(self.cylinder_controls)  # index 1
        self.mode_controls_stack.addWidget(self.rings_controls)     # index 2
        self.mode_controls_stack.addWidget(self.slice_controls)     # index 3
        self.mode_controls_stack.addWidget(self.slitscan_controls)  # index 4
        self.mode_controls_stack.addWidget(self.slittear_controls)  # index 5
        # Default to Cuboid controls (index 0)
        self.mode_controls_stack.setCurrentIndex(0)
        self.sidebar_layout.addWidget(self.mode_controls_stack)

        # Export controls
        self.export_controls = ExportControls(self.state)
        self.sidebar_layout.addWidget(self.export_controls)

        # Generate panel
        self.generate_panel = GeneratePanel(self.state)
        self.sidebar_layout.addWidget(self.generate_panel)

        self.sidebar_layout.addStretch()

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(self.sidebar_widget)
        sidebar_scroll.setMinimumWidth(250)
        sidebar_scroll.setMaximumWidth(500)
        sidebar_scroll.resize(SIDEBAR_WIDTH, 0)
        self._sidebar_scroll = sidebar_scroll

        # --- Preview area (right) ---
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        # Preview toggle toolbar (top-left of preview area)
        self._preview_toolbar = QHBoxLayout()
        self._preview_toolbar.setContentsMargins(8, 4, 8, 4)
        self._preview_toolbar.setSpacing(4)

        self._btn_mask = QToolButton()
        self._btn_mask.setText("Mask Selection")
        self._btn_mask.setCheckable(True)
        self._btn_mask.setChecked(True)
        self._btn_mask.setToolTip("Show the video frame with mask overlay and frame range controls")

        self._btn_2d = QToolButton()
        self._btn_2d.setText("2D Preview")
        self._btn_2d.setCheckable(True)
        self._btn_2d.setToolTip("Show generated textures laid out flat (time on horizontal axis)")
        self._btn_2d.setEnabled(False)

        self._btn_3d = QToolButton()
        self._btn_3d.setText("3D Preview")
        self._btn_3d.setCheckable(True)
        self._btn_3d.setToolTip("Show the 3D cuboid preview (Cuboid mode only)")
        self._btn_3d.setEnabled(False)
        self._btn_3d.setVisible(False)

        self._preview_btn_group = QButtonGroup(self)
        self._preview_btn_group.setExclusive(True)
        self._preview_btn_group.addButton(self._btn_mask, 0)
        self._preview_btn_group.addButton(self._btn_2d, 1)
        self._preview_btn_group.addButton(self._btn_3d, 2)

        # Sidebar toggle button (hamburger icon, left of preview tabs)
        self._btn_sidebar = QToolButton()
        self._btn_sidebar.setIcon(
            QIcon(
                os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "resources", "icons", "hamburger.png",
                )
            )
        )
        self._btn_sidebar.setToolTip("Toggle sidebar")
        self._btn_sidebar.setCheckable(True)
        self._btn_sidebar.setChecked(True)
        self._preview_toolbar.addWidget(self._btn_sidebar)
        self._preview_toolbar.addSpacing(8)
        self._preview_toolbar.addWidget(self._btn_mask)
        self._preview_toolbar.addWidget(self._btn_2d)
        self._preview_toolbar.addWidget(self._btn_3d)
        self._preview_toolbar.addStretch()

        preview_layout.addLayout(self._preview_toolbar)

        # Stacked widget: page 0 = placeholder, page 1 = frame viewer
        self.preview_stack = QStackedWidget()

        # Page 0: placeholder
        placeholder = QLabel("Open a video file to begin")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #666666; font-size: 18px;")
        self.preview_stack.addWidget(placeholder)  # index 0

        # Page 1: frame viewer
        self.frame_viewer = FrameViewer()
        self.preview_stack.addWidget(self.frame_viewer)  # index 1

        # Lazy-loaded preview widgets
        self._preview_3d = None   # 3D cuboid viewer
        self._slice_preview = None  # 2D image viewer (slice or unfolded cuboid)

        preview_layout.addWidget(self.preview_stack, 1)

        # Frame scrubber (bottom of preview area)
        self.frame_scrubber = FrameScrubber()
        self.frame_scrubber.setFixedHeight(80)
        preview_layout.addWidget(self.frame_scrubber)

        # --- Splitter (resizable but not collapsible) ---
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(sidebar_scroll)
        self._splitter.addWidget(preview_container)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([SIDEBAR_WIDTH, self.width() - SIDEBAR_WIDTH])

        self.setCentralWidget(self._splitter)

    def _connect_signals(self):
        # Video loaded → update state, configure scrubber, show first frame
        self.video_panel.video_loaded.connect(self._on_video_loaded)

        # Frame scrubber → seek and display frame
        self.frame_scrubber.frame_requested.connect(self._on_frame_requested)
        self.frame_scrubber.range_changed.connect(self._on_range_changed)
        self.frame_scrubber.sampling_changed.connect(self._on_sampling_changed)
        self.frame_scrubber.prev_cut_requested.connect(self._on_prev_cut)
        self.frame_scrubber.next_cut_requested.connect(self._on_next_cut)

        # Mode changed → update state and swap control panels
        self.mode_selector.mode_changed.connect(self._on_mode_changed)

        # Update export panel visibility based on mode
        self.export_controls.set_mode(self.state.current_mode)

        # Slice controls settings changed → repaint overlay
        self.slice_controls.settings_changed.connect(self.frame_viewer.update)

        # Cuboid controls settings changed → repaint overlay
        self.cuboid_controls.settings_changed.connect(self.frame_viewer.update)
        self.cuboid_controls.settings_changed.connect(self.generate_panel.update_estimate)
        self.cuboid_controls.settings_changed.connect(self._on_chroma_settings_changed)

        # Cylinder controls settings changed → repaint overlay
        self.cylinder_controls.settings_changed.connect(self.frame_viewer.update)

        # Rings controls settings changed → repaint overlay
        self.rings_controls.settings_changed.connect(self.frame_viewer.update)

        # Slitscan controls settings changed → repaint overlay + update 3D button
        self.slitscan_controls.settings_changed.connect(self.frame_viewer.update)
        self.slitscan_controls.settings_changed.connect(self._on_slitscan_settings_changed)

        # Slit-Tear controls signals
        self.slittear_controls.settings_changed.connect(self.frame_viewer.update)
        self.slittear_controls.undo_requested.connect(self._on_slittear_undo)
        self.slittear_controls.clear_requested.connect(self._on_slittear_clear)
        self._drawing_canvas.lines_changed.connect(self._on_slittear_lines_changed)

        # FrameViewer drag signals → update sidebar spinboxes
        self.frame_viewer.slit_dragged.connect(self.slice_controls.set_position_from_drag)
        self.frame_viewer.ortho_slit_dragged.connect(self.slice_controls.set_ortho_position_from_drag)
        self.frame_viewer.cuboid_border_dragged.connect(self.cuboid_controls.set_borders_from_drag)
        # Slitscan uses same border-drag signal but routed to slitscan controls
        self.frame_viewer.cuboid_border_dragged.connect(self._on_slitscan_border_drag)

        # Eyedropper: cuboid chroma color picker
        self.cuboid_controls.eyedropper_requested.connect(
            self.frame_viewer.activate_eyedropper
        )
        self.frame_viewer.color_sampled.connect(self._on_color_sampled)

        # Object extraction: preview mask, point prompt, model download
        self.cuboid_controls.preview_mask_requested.connect(self._on_preview_mask)
        self.cuboid_controls.prompt_point_requested.connect(self._on_prompt_point_mode)
        self.cuboid_controls.download_model_requested.connect(self._on_download_model)
        self.frame_viewer.point_sampled.connect(self._on_point_sampled)

        # Orthogonal toggle → show/hide 3D button
        self.slice_controls.orthogonal_toggled.connect(self._on_orthogonal_toggled)

        # PDF export
        self.export_controls.export_pdf_clicked.connect(self._on_export_pdf)

        # Generate pipeline
        self.generate_panel.generate_btn.clicked.connect(self._on_generate)
        self.generate_panel.generation_finished.connect(self._on_generation_finished)
        self.generate_panel.generation_cancelled.connect(self._on_generation_cancelled)

        # Preview toggle buttons
        self._preview_btn_group.idClicked.connect(self._on_preview_toggle)

        # Sidebar toggle button
        self._btn_sidebar.toggled.connect(self._on_sidebar_toggle)

        # Load preview
        self.video_panel.preview_loaded.connect(self._on_preview_loaded)

    def _on_video_loaded(self, video_source):
        self.state.set_video_source(video_source)
        self.frame_scrubber.configure(video_source.frame_count, video_source.fps)
        # Switch to Mask Preview
        self._btn_mask.setChecked(True)
        self.preview_stack.setCurrentWidget(self.frame_viewer)
        self.frame_scrubber.setVisible(True)
        # Show the first frame
        frame = video_source.get_frame(0)
        if frame is not None:
            self.state.current_frame_index = 0
            self.frame_viewer.set_frame(frame)
        # Configure overlay for current mode
        self.frame_viewer.configure_for_mode(self.state.current_mode, self.state)
        # Clear slit-tear lines for the new video and reconnect canvas
        self._drawing_canvas.clear()
        if self.state.current_mode == "Slit-tear":
            self.frame_viewer.set_drawing_canvas(self._drawing_canvas)

    def _on_frame_requested(self, frame_index):
        vs = self.state.video_source
        if vs is None:
            return
        frame = vs.get_frame(frame_index)
        if frame is not None:
            self.state.current_frame_index = frame_index
            self.frame_viewer.set_frame(frame)

    def _on_range_changed(self, initial, last):
        self.state.initial_frame = initial
        self.state.last_frame = last
        self.state.settings_changed.emit()

    def _on_sampling_changed(self, rate):
        self.state.sampling_rate = rate
        self.state.settings_changed.emit()

    def _on_prev_cut(self):
        """Search backward from the current frame for the nearest cut."""
        if self.state.video_source is None:
            return
        video_path = self.state.video_source.file_path
        current = self.frame_scrubber.initial_spin.value()
        self.frame_scrubber.prev_cut_btn.setEnabled(False)
        self.frame_scrubber.prev_cut_btn.setText("…")

        def _run():
            from processing.scene_detector import find_next_cut
            cut = find_next_cut(video_path, current, direction=-1)
            self._pending_cut_result = ("prev", cut)
            QMetaObject.invokeMethod(
                self, "_apply_cut_result", Qt.QueuedConnection,
            )

        threading.Thread(target=_run, daemon=True).start()

    def _on_next_cut(self):
        """Search forward from the current frame for the nearest cut."""
        if self.state.video_source is None:
            return
        video_path = self.state.video_source.file_path
        current = self.frame_scrubber.last_spin.value()
        self.frame_scrubber.next_cut_btn.setEnabled(False)
        self.frame_scrubber.next_cut_btn.setText("…")

        def _run():
            from processing.scene_detector import find_next_cut
            cut = find_next_cut(video_path, current, direction=1)
            self._pending_cut_result = ("next", cut)
            QMetaObject.invokeMethod(
                self, "_apply_cut_result", Qt.QueuedConnection,
            )

        threading.Thread(target=_run, daemon=True).start()

    @Slot()
    def _apply_cut_result(self):
        """Apply a single cut result from a prev/next search (main thread)."""
        direction, cut = getattr(self, "_pending_cut_result", (None, None))
        if direction == "prev":
            self.frame_scrubber.prev_cut_btn.setEnabled(True)
            if cut is not None:
                self.frame_scrubber.prev_cut_btn.setText("◀ Prev Cut")
                self.frame_scrubber.initial_spin.setValue(cut)
                self.frame_scrubber._on_spin_finished("initial")
                # Add marker
                markers = list(self.frame_scrubber.slider._markers)
                if cut not in markers:
                    markers.append(cut)
                    self.frame_scrubber.set_cut_markers(sorted(markers))
            else:
                self.frame_scrubber.prev_cut_btn.setText("No cut")
                QTimer.singleShot(1500, lambda: self.frame_scrubber.prev_cut_btn.setText("◀ Prev Cut"))
        elif direction == "next":
            self.frame_scrubber.next_cut_btn.setEnabled(True)
            if cut is not None:
                self.frame_scrubber.next_cut_btn.setText("Next Cut ▶")
                self.frame_scrubber.last_spin.setValue(cut)
                self.frame_scrubber._on_spin_finished("last")
                # Add marker
                markers = list(self.frame_scrubber.slider._markers)
                if cut not in markers:
                    markers.append(cut)
                    self.frame_scrubber.set_cut_markers(sorted(markers))
            else:
                self.frame_scrubber.next_cut_btn.setText("No cut")
                QTimer.singleShot(1500, lambda: self.frame_scrubber.next_cut_btn.setText("Next Cut ▶"))

    def _on_mode_changed(self, mode):
        self.state.current_mode = mode
        self.state.mode_changed.emit(mode)
        # Swap mode-specific control panel
        mode_index = {"Cuboid": 0, "Cylinder": 1, "Rings": 2, "Slice": 3, "Slit-scan": 4, "Slit-tear": 5}.get(mode, 0)
        self.mode_controls_stack.setCurrentIndex(mode_index)
        # Configure overlay drawing for the active mode
        self.frame_viewer.configure_for_mode(mode, self.state)
        # Set up drawing canvas for Slit-tear mode
        if mode == "Slit-tear":
            self.frame_viewer.set_drawing_canvas(self._drawing_canvas)
        else:
            self.frame_viewer.set_drawing_canvas(None)
        # Show/hide 3D format option
        self.export_controls.set_mode(mode)
        # Show/hide 3D preview toggle
        show_3d = mode in ("Cuboid", "Cylinder", "Slit-scan", "Slit-tear")
        if mode == "Slice" and self.state.orthogonal_enabled:
            show_3d = True
        self._btn_3d.setVisible(show_3d)
        # For Slit-scan, 3D is only enabled after generation
        if mode == "Slit-scan":
            self._btn_3d.setEnabled(False)
        # Switch to Mask Preview when mode changes
        self._btn_mask.setChecked(True)
        self._on_preview_toggle(0)

    # --- Generate pipeline ---

    def _on_generate(self):
        if not self.generate_panel.validate():
            return
        if not self.generate_panel.warn_memory():
            return

        output_dir = self.export_controls.get_output_dir()
        if not output_dir:
            return
        os.makedirs(output_dir, exist_ok=True)

        mode = self.state.current_mode
        if mode == "Slice":
            processor = SliceProcessor(self.state, output_dir, parent=self)
        elif mode == "Cuboid":
            if self.state.cuboid_fill_mode == "Fill":
                processor = CuboidFillProcessor(self.state, output_dir, parent=self)
            else:
                processor = CuboidVoidProcessor(self.state, output_dir, parent=self)
        elif mode == "Cylinder":
            processor = CylinderProcessor(self.state, output_dir, parent=self)
        elif mode == "Rings":
            processor = RingsProcessor(self.state, output_dir, parent=self)
        elif mode == "Slit-tear":
            # Sync drawn lines to state before processing
            self.state.slittear_lines = self._drawing_canvas.lines
            if not self.state.slittear_lines:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "No Lines",
                    "Draw at least one line on the frame before generating.",
                )
                return
            processor = SlitTearProcessor(self.state, output_dir, parent=self)
        elif mode == "Slit-scan":
            processor = SlitscanProcessor(self.state, output_dir, parent=self)
        else:
            return

        # Disable controls during generation
        self._set_controls_enabled(False)
        self.generate_panel.start_with_processor(processor)

    def _on_generation_finished(self, result):
        self._set_controls_enabled(True)

        if not result:
            return

        # Store last generation result for preview toggling
        self._last_result = result

        # Auto-hide sidebar and frame scrubber when switching to result preview
        self.frame_scrubber.setVisible(False)
        self._set_sidebar_visible(False)

        # Propagate base output dir to preview widgets for captures
        captures_base = self.state.output_dir or os.path.join(
            os.path.expanduser("~"), "Desktop", "KinoVolume"
        )
        if captures_base:
            if self._slice_preview is not None:
                self._slice_preview.set_output_dir(captures_base)
            if self._preview_3d is not None:
                self._preview_3d.set_output_dir(captures_base)

        if self.state.current_mode == "Slice" and result.get("orthogonal"):
            # Orthogonal mode: two crossing slices
            self._export_orthogonal_mesh(result)
            self._btn_2d.setEnabled(True)
            self._btn_3d.setVisible(True)
            self._btn_3d.setEnabled(True)
            self._btn_3d.setChecked(True)
            self._show_orthogonal_3d_preview(result)

        elif self.state.current_mode == "Slice" and "image_path" in result:
            # Enable 2D preview and switch to it
            self._btn_2d.setEnabled(True)
            self._btn_2d.setChecked(True)
            self._show_slice_preview(result["image_path"])

        elif self.state.current_mode == "Slit-tear" and "image_path" in result:
            # Enable 2D preview and switch to it
            self._btn_2d.setEnabled(True)
            self._btn_2d.setChecked(True)
            self._show_slice_preview(result["image_path"])
            # Enable 3D preview if we have rasterized line data
            if "rasterized_lines" in result:
                self._btn_3d.setEnabled(True)
                try:
                    self._export_slittear_mesh(result)
                except Exception as e:
                    print(f"[Warning] Slit-tear mesh export failed: {e}")

        elif self.state.current_mode == "Cuboid" and result.get("fill_mode"):
            # Cuboid Fill mode — only per-frame images, no face textures
            self._btn_2d.setEnabled(False)
            self._btn_3d.setVisible(True)
            if self.state.cuboid_preview_enabled:
                self._btn_3d.setEnabled(True)
                self._btn_3d.setChecked(True)
                self._show_cuboid_fill_3d(result)
            try:
                self._export_cuboid_fill_mesh(result)
            except Exception as e:
                print(f"[Warning] Cuboid fill mesh export failed: {e}")

        elif self.state.current_mode == "Cuboid" and "face_paths" in result:
            # Cuboid Void mode — has face textures for unfold + 3D box
            try:
                self._export_cuboid_mesh(result)
            except Exception as e:
                print(f"[Warning] Cuboid mesh export failed: {e}")
            self._btn_2d.setEnabled(True)
            self._btn_3d.setVisible(True)
            self.export_controls.set_pdf_enabled(True)
            if self.state.cuboid_preview_enabled:
                self._btn_3d.setEnabled(True)
                self._btn_3d.setChecked(True)
                self._show_3d_preview(result)
            else:
                self._btn_2d.setChecked(True)
                self._show_unfolded_preview(result)

        elif self.state.current_mode == "Cylinder" and "face_paths" in result:
            try:
                self._export_cylinder_mesh(result)
            except Exception as e:
                print(f"[Warning] Cylinder mesh export failed: {e}")
            # Enable 2D + 3D preview
            self._btn_2d.setEnabled(True)
            self.export_controls.set_pdf_enabled(True)
            cyl_quality = getattr(self.state, "cylinder_preview_quality", "High")
            if cyl_quality != "No preview":
                self._btn_3d.setEnabled(True)
                self._btn_3d.setChecked(True)
                self._show_cylinder_3d_preview(result)
            else:
                surface_path = result["face_paths"].get("surface")
                if surface_path:
                    self._btn_2d.setChecked(True)
                    self._show_slice_preview(surface_path)

        elif self.state.current_mode == "Rings" and "image_path" in result:
            # Enable 2D preview and switch to it
            self._btn_2d.setEnabled(True)
            self._btn_2d.setChecked(True)
            self._show_slice_preview(result["image_path"])

        elif self.state.current_mode == "Slit-scan" and "image_path" in result:
            mask_type = result.get("mask_type", "")
            sampling_mode = result.get("sampling_mode", "")
            self._btn_2d.setEnabled(True)
            self._btn_3d.setVisible(True)

            # Enable 3D preview only for planar cut
            can_3d = (sampling_mode == "Planar cut (3D)")
            if can_3d:
                self._btn_3d.setEnabled(True)
                self._btn_3d.setChecked(True)
                self._show_slitscan_3d_from_result(result)
                try:
                    self._export_slitscan_planar_mesh(result)
                except Exception as e:
                    print(f"[Warning] Slitscan planar mesh export failed: {e}")
            else:
                self._btn_3d.setEnabled(False)
                self._btn_2d.setChecked(True)
                self._show_slice_preview(result["image_path"])

    def _on_generation_cancelled(self):
        self._set_controls_enabled(True)

    def _export_cuboid_mesh(self, result):
        import numpy as np
        from PIL import Image as PILImage
        from export.mesh_exporter import MeshExporter

        face_images = {}
        for name, path in result["face_paths"].items():
            face_images[name] = np.array(PILImage.open(path))

        exporter = MeshExporter()
        out_dir = result["output_dir"]
        dims = result["dimensions"]

        mesh_fmt = self.state.mesh_format
        if "OBJ" in mesh_fmt:
            exporter.export_obj(face_images, dims, os.path.join(out_dir, "cuboid.obj"))
        else:
            exporter.export_gltf(face_images, dims, os.path.join(out_dir, "cuboid.glb"))

    def _export_cylinder_mesh(self, result):
        import numpy as np
        from PIL import Image as PILImage
        from export.mesh_exporter import MeshExporter

        face_images = {}
        for name, path in result["face_paths"].items():
            face_images[name] = np.array(PILImage.open(path))

        exporter = MeshExporter()
        out_dir = result["output_dir"]
        dims = result["dimensions"]

        mesh_fmt = self.state.mesh_format
        if "OBJ" in mesh_fmt:
            exporter.export_cylinder_obj(face_images, dims, os.path.join(out_dir, "cylinder.obj"))
        else:
            exporter.export_cylinder_gltf(face_images, dims, os.path.join(out_dir, "cylinder.glb"))

    def _export_cuboid_fill_mesh(self, result):
        """Export cuboid fill as 3D mesh (stacked frame planes)."""
        from export.mesh_exporter import MeshExporter

        out_dir = result["output_dir"]
        frames_dir = result["frames_dir"]
        dims = result["dimensions"]
        exporter = MeshExporter()

        # Use state values set by the cuboid sidebar controls.
        density_mode = getattr(self.state, "cuboid_fill_density_mode", "Every N frames")
        if density_mode == "All frames":
            step = 1
        else:
            step = max(1, getattr(self.state, "cuboid_fill_density_n", 10))

        spacing_text = getattr(self.state, "cuboid_fill_spacing", "1×")
        spacing_factor = float(spacing_text.rstrip("×")) if spacing_text else 1.0
        pad_gaps = getattr(self.state, "cuboid_fill_pad_gaps", False)

        mesh_fmt = self.state.mesh_format
        if "OBJ" in mesh_fmt:
            exporter.export_cuboid_fill_obj(
                frames_dir, dims, os.path.join(out_dir, "cuboid_fill.obj"),
                step=step, spacing_factor=spacing_factor,
                pad_gaps=pad_gaps,
            )
        else:
            exporter.export_cuboid_fill_gltf(
                frames_dir, dims, os.path.join(out_dir, "cuboid_fill.glb"),
                step=step, spacing_factor=spacing_factor,
                pad_gaps=pad_gaps,
            )

    def _export_slittear_mesh(self, result):
        """Export slit-tear curtain meshes as 3D mesh."""
        import numpy as np
        from PIL import Image as PILImage
        from export.mesh_exporter import MeshExporter

        out_dir = result["output_dir"]
        img_path = result["image_path"]
        full_image = np.array(PILImage.open(img_path))

        lines = result.get("rasterized_lines", [])
        counts = result.get("line_pixel_counts", [])

        exporter = MeshExporter()
        mesh_fmt = self.state.mesh_format
        if "OBJ" in mesh_fmt:
            exporter.export_slittear_obj(
                full_image, lines, counts,
                result.get("frames_processed", 1),
                result.get("frame_width", 1920),
                result.get("frame_height", 1080),
                os.path.join(out_dir, "slittear.obj"),
            )
        else:
            exporter.export_slittear_gltf(
                full_image, lines, counts,
                result.get("frames_processed", 1),
                result.get("frame_width", 1920),
                result.get("frame_height", 1080),
                os.path.join(out_dir, "slittear.glb"),
            )

    def _export_slitscan_planar_mesh(self, result):
        """Export slitscan planar cut as 3D mesh (textured diagonal plane)."""
        import numpy as np
        from PIL import Image as PILImage
        from export.mesh_exporter import MeshExporter

        out_dir = result["output_dir"]
        img_path = result["image_path"]
        texture_image = np.array(PILImage.open(img_path))

        exporter = MeshExporter()
        mesh_fmt = self.state.mesh_format
        if "OBJ" in mesh_fmt:
            exporter.export_slitscan_planar_obj(
                texture_image,
                result.get("scan_direction", "L→R"),
                result.get("mask_type", "Vertical"),
                result.get("frame_width", 1920),
                result.get("frame_height", 1080),
                result.get("frames_processed", 1),
                os.path.join(out_dir, "slitscan_planar.obj"),
                mask_left=result.get("mask_left", 0),
                mask_right=result.get("mask_right", 0),
                mask_top=result.get("mask_top", 0),
                mask_bottom=result.get("mask_bottom", 0),
            )
        else:
            exporter.export_slitscan_planar_gltf(
                texture_image,
                result.get("scan_direction", "L→R"),
                result.get("mask_type", "Vertical"),
                result.get("frame_width", 1920),
                result.get("frame_height", 1080),
                result.get("frames_processed", 1),
                os.path.join(out_dir, "slitscan_planar.glb"),
                mask_left=result.get("mask_left", 0),
                mask_right=result.get("mask_right", 0),
                mask_top=result.get("mask_top", 0),
                mask_bottom=result.get("mask_bottom", 0),
            )

    def _show_cylinder_3d_preview(self, result):
        import numpy as np
        from PIL import Image as PILImage

        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        captures_base = result.get("output_dir", "")
        self._preview_3d.set_output_dir(captures_base)

        face_images = {}
        for name, path in result["face_paths"].items():
            face_images[name] = np.array(PILImage.open(path))

        quality = getattr(self.state, "cylinder_preview_quality", "High")
        self._preview_3d.set_quality_from_label(quality)
        self._preview_3d.display_cylinder(face_images, result["dimensions"])
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_3d_preview(self, result):
        import numpy as np
        from PIL import Image as PILImage

        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        captures_base = self.state.output_dir or os.path.join(
            os.path.expanduser("~"), "Desktop", "KinoVolume"
        )
        self._preview_3d.set_output_dir(captures_base)

        face_images = {}
        for name, path in result["face_paths"].items():
            face_images[name] = np.array(PILImage.open(path))

        self._preview_3d.set_quality_from_label("high")
        self._preview_3d.display_cuboid(face_images, result["dimensions"])
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_cuboid_fill_3d(self, result):
        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        captures_base = result.get("output_dir", "")
        self._preview_3d.set_output_dir(captures_base)

        # Sync sidebar fill settings to the 3D preview widget
        if hasattr(self.state, "cuboid_fill_density_mode"):
            idx = self._preview_3d._density_combo.findText(
                self.state.cuboid_fill_density_mode
            )
            if idx >= 0:
                self._preview_3d._density_combo.setCurrentIndex(idx)
            self._preview_3d._density_spin.setValue(
                getattr(self.state, "cuboid_fill_density_n", 10)
            )
        if hasattr(self.state, "cuboid_fill_spacing"):
            idx = self._preview_3d._spacing_combo.findText(
                self.state.cuboid_fill_spacing
            )
            if idx >= 0:
                self._preview_3d._spacing_combo.setCurrentIndex(idx)
        self._preview_3d._pad_gaps_check.setChecked(
            getattr(self.state, "cuboid_fill_pad_gaps", False)
        )

        self._preview_3d.set_quality_from_label("high")
        self._preview_3d.display_cuboid_fill(
            result["frames_dir"], result["dimensions"],
        )
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_slice_preview(self, image_path):
        if self._slice_preview is None:
            from ui.preview.slice_preview import SlicePreview
            self._slice_preview = SlicePreview()
            self.preview_stack.addWidget(self._slice_preview)
            captures_base = self.state.output_dir or os.path.join(
                os.path.expanduser("~"), "Desktop", "KinoVolume"
            )
            self._slice_preview.set_output_dir(captures_base)

        self._slice_preview.load_image(image_path)
        self.preview_stack.setCurrentWidget(self._slice_preview)

    def _show_unfolded_preview(self, result):
        """Show unfolded cuboid faces in the SlicePreview widget."""
        import numpy as np
        from PIL import Image as PILImage

        face_images = {}
        for name, path in result["face_paths"].items():
            face_images[name] = np.array(PILImage.open(path))

        if self._slice_preview is None:
            from ui.preview.slice_preview import SlicePreview
            self._slice_preview = SlicePreview()
            self.preview_stack.addWidget(self._slice_preview)

        self._slice_preview.load_cuboid_faces(face_images)
        self.preview_stack.setCurrentWidget(self._slice_preview)

    def _on_preview_toggle(self, btn_id):
        """Switch between Mask(0), 2D(1), and 3D(2) previews."""
        if btn_id == 0:
            # Mask preview = frame viewer + scrubber visible; auto-show sidebar
            self.frame_scrubber.setVisible(True)
            self._set_sidebar_visible(True)
            if self.state.video_source is not None:
                self.preview_stack.setCurrentWidget(self.frame_viewer)
            else:
                self.preview_stack.setCurrentIndex(0)
        elif btn_id == 1:
            # 2D preview — hide scrubber, auto-hide sidebar
            self.frame_scrubber.setVisible(False)
            self._set_sidebar_visible(False)
            result = getattr(self, "_last_result", None)
            if result is None:
                return
            if result.get("orthogonal"):
                # Stack both orthogonal images vertically
                self._show_orthogonal_2d_preview(result)
            elif self.state.current_mode == "Cylinder" and "face_paths" in result:
                surface_path = result["face_paths"].get("surface")
                if surface_path:
                    self._show_slice_preview(surface_path)
            elif "face_paths" in result:
                self._show_unfolded_preview(result)
            elif "image_path" in result:
                self._show_slice_preview(result["image_path"])
        elif btn_id == 2:
            # 3D preview — hide scrubber, auto-hide sidebar
            self.frame_scrubber.setVisible(False)
            self._set_sidebar_visible(False)
            result = getattr(self, "_last_result", None)
            if result and result.get("orthogonal"):
                self._show_orthogonal_3d_preview(result)
            elif result and result.get("fill_mode") and result.get("frames_dir"):
                self._show_cuboid_fill_3d(result)
            elif result and "face_paths" in result:
                if self.state.current_mode == "Cylinder":
                    self._show_cylinder_3d_preview(result)
                else:
                    self._show_3d_preview(result)
            elif result and "rasterized_lines" in result:
                self._show_slittear_3d_preview(result)
            elif result and result.get("sampling_mode") == "Planar cut (3D)":
                # Slitscan with textured 3D plane (post-generation)
                self._show_slitscan_3d_from_result(result)
            elif self.state.current_mode == "Slit-scan":
                # No pre-generation 3D preview — button should be disabled until generation
                pass

    def _set_sidebar_visible(self, visible):
        """Show or hide the sidebar and sync the hamburger toggle button."""
        self._sidebar_scroll.setVisible(visible)
        self._btn_sidebar.blockSignals(True)
        self._btn_sidebar.setChecked(visible)
        self._btn_sidebar.blockSignals(False)

    def _on_sidebar_toggle(self, checked):
        """Manual sidebar toggle via hamburger button."""
        self._sidebar_scroll.setVisible(checked)

    def _on_preview_loaded(self, folder_path):
        """Load a previously generated preview from a folder."""
        import numpy as np
        from PIL import Image as PILImage

        # Check if it's a cuboid output (has face PNGs)
        face_names = ["front", "back", "top", "bottom", "left", "right"]
        face_paths = {}
        for name in face_names:
            for ext in ("png", "tiff"):
                p = os.path.join(folder_path, f"{name}.{ext}")
                if os.path.exists(p):
                    face_paths[name] = p
                    break

        if len(face_paths) == 6:
            # Cuboid output — determine dimensions from face images
            front_img = np.array(PILImage.open(face_paths["front"]))
            top_img = np.array(PILImage.open(face_paths["top"]))
            dims = {
                "width": front_img.shape[1],
                "height": front_img.shape[0],
                "depth": top_img.shape[0],
            }
            result = {
                "output_dir": folder_path,
                "face_paths": face_paths,
                "dimensions": dims,
            }
            self._last_result = result
            self._btn_2d.setEnabled(True)
            self._btn_3d.setVisible(True)
            self._btn_3d.setEnabled(True)
            self._btn_3d.setChecked(True)
            self.export_controls.set_pdf_enabled(True)
            self._show_3d_preview(result)
            return

        # Check for slice output (single image file)
        for fname in sorted(os.listdir(folder_path)):
            if fname.lower().endswith((".png", ".tiff", ".tif")):
                # Skip face textures by name
                base = os.path.splitext(fname)[0].lower()
                if base in face_names:
                    continue
                img_path = os.path.join(folder_path, fname)
                result = {"image_path": img_path}
                self._last_result = result
                self._btn_2d.setEnabled(True)
                self._btn_2d.setChecked(True)
                self._show_slice_preview(img_path)
                return

    # --- Chroma helpers ---

    def _on_color_sampled(self, r, g, b):
        """Eyedropper picked a color — forward to the cuboid controls."""
        self.cuboid_controls.set_chroma_color(r, g, b)

    # --- Object extraction helpers ---

    def _on_preview_mask(self):
        """Run extraction on the current frame and show mask overlay."""
        frame = self.frame_viewer.current_frame()
        if frame is None:
            return

        s = self.state
        mode = s.extraction_mode
        if mode == "none":
            self.frame_viewer.show_mask_overlay(None)
            self._mask_overlay_active = False
            return

        self._mask_overlay_active = True

        # For chroma, generate a quick preview too
        if mode == "chroma":
            from processing.chroma_processor import apply_chroma_key
            rgba = apply_chroma_key(frame, s.chroma_color, s.chroma_tolerance, s.chroma_fade)
            # Extract alpha as mask for overlay
            mask = rgba[:, :, 3]
        else:
            from processing.object_detector import extract_mask
            mask = extract_mask(
                frame,
                mode=mode,
                prompt_point=s.extraction_prompt_point,
                invert=s.extraction_invert,
                canny_low=s.edge_canny_low,
                canny_high=s.edge_canny_high,
                dilate_iter=s.edge_dilate,
                min_area=s.edge_min_area,
                ai_model=s.ai_model,
                ai_confidence=s.ai_confidence,
            )

        self.frame_viewer.show_mask_overlay(mask, chroma_style=(mode == "chroma"))

    def _on_chroma_settings_changed(self):
        """Auto-refresh mask overlay when chroma settings change."""
        if self.state.extraction_mode == "chroma" and self._mask_overlay_active:
            self._on_preview_mask()

    _prompt_point_mode = False
    _mask_overlay_active = False

    def _on_prompt_point_mode(self):
        """Enter point-prompt mode: next click on frame picks extraction point."""
        self._prompt_point_mode = True
        self.frame_viewer.activate_point_prompt()

    def _on_point_sampled(self, x, y):
        """Handle click in point-prompt mode."""
        self._prompt_point_mode = False
        self.cuboid_controls.set_prompt_point(x, y)
        # Auto-run preview mask after setting the point
        self._on_preview_mask()

    def _on_download_model(self, model_name):
        """Download an AI model in a background thread."""
        from PySide6.QtWidgets import QMessageBox, QProgressDialog
        from PySide6.QtCore import QThread, Signal as QtSignal

        progress = QProgressDialog(
            f"Downloading {model_name} model…", "Cancel", 0, 100, self
        )
        progress.setWindowTitle("Model Download")
        progress.setMinimumDuration(0)
        progress.setValue(0)

        class DownloadWorker(QThread):
            progress_update = QtSignal(int, int)
            finished = QtSignal(str)   # path or empty on error
            error = QtSignal(str)

            def __init__(self, name):
                super().__init__()
                self._model_name = name

            def run(self):
                try:
                    from processing.object_detector import download_model
                    path = download_model(
                        self._model_name,
                        progress_callback=lambda dl, total: self.progress_update.emit(dl, total),
                    )
                    self.finished.emit(str(path))
                except Exception as e:
                    self.error.emit(str(e))

        worker = DownloadWorker(model_name)

        def on_progress(downloaded, total):
            if total > 0:
                progress.setValue(int(downloaded * 100 / total))
            else:
                progress.setValue(0)

        def on_finished(path):
            progress.close()
            self.cuboid_controls.set_ai_download_complete()
            QMessageBox.information(self, "Download Complete", f"Model saved to:\n{path}")
            worker.deleteLater()

        def on_error(msg):
            progress.close()
            QMessageBox.critical(self, "Download Failed", msg)
            worker.deleteLater()

        worker.progress_update.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        progress.canceled.connect(worker.terminate)
        worker.start()

    # --- Orthogonal helpers ---

    def _on_orthogonal_toggled(self, checked):
        """Show/hide 3D button when orthogonal checkbox is toggled."""
        if self.state.current_mode == "Slice":
            self._btn_3d.setVisible(checked)
            self.export_controls.mesh_row.setVisible(checked)

    def _export_orthogonal_mesh(self, result):
        import numpy as np
        from PIL import Image as PILImage
        from export.mesh_exporter import MeshExporter

        v_img = np.array(PILImage.open(result["vertical_path"]))
        h_img = np.array(PILImage.open(result["horizontal_path"]))

        exporter = MeshExporter()
        out_dir = result["output_dir"]
        mesh_fmt = self.state.mesh_format

        if "OBJ" in mesh_fmt:
            exporter.export_orthogonal_obj(
                v_img, h_img,
                result["slit_position"], result["ortho_position"],
                result["frame_width"], result["frame_height"],
                result["frames_processed"],
                os.path.join(out_dir, "orthogonal.obj"),
            )
        else:
            exporter.export_orthogonal_gltf(
                v_img, h_img,
                result["slit_position"], result["ortho_position"],
                result["frame_width"], result["frame_height"],
                result["frames_processed"],
                os.path.join(out_dir, "orthogonal.glb"),
            )

    def _show_orthogonal_3d_preview(self, result):
        import numpy as np
        from PIL import Image as PILImage

        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        v_img = np.array(PILImage.open(result["vertical_path"]))
        h_img = np.array(PILImage.open(result["horizontal_path"]))

        # Load display frames
        display_frames = {}
        for frame_idx, path in result.get("display_frames", {}).items():
            display_frames[frame_idx] = np.array(PILImage.open(path))

        self._preview_3d.display_orthogonal(
            v_img, h_img,
            result["slit_position"], result["ortho_position"],
            result["frame_width"], result["frame_height"],
            result["frames_processed"],
            display_frames=display_frames if display_frames else None,
            initial_frame=result.get("initial_frame", 0),
            last_frame=result.get("last_frame"),
        )
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_orthogonal_2d_preview(self, result):
        """Stack vertical and horizontal slice images vertically for 2D preview."""
        import numpy as np
        from PIL import Image as PILImage

        v_img = np.array(PILImage.open(result["vertical_path"]))
        h_img = np.array(PILImage.open(result["horizontal_path"]))

        # Stack vertically with a small gap
        gap = 4
        max_w = max(v_img.shape[1], h_img.shape[1])
        total_h = v_img.shape[0] + gap + h_img.shape[0]
        # Use interface background colour (30, 30, 30) instead of black
        combined = np.full((total_h, max_w, 3), 30, dtype=np.uint8)
        combined[:v_img.shape[0], :v_img.shape[1]] = v_img
        combined[v_img.shape[0] + gap:, :h_img.shape[1]] = h_img

        # Save temp combined image
        temp_path = os.path.join(result["output_dir"], "_orthogonal_combined.png")
        PILImage.fromarray(combined).save(temp_path)
        self._show_slice_preview(temp_path)

    # --- PDF export ---

    def _on_export_pdf(self):
        """Export a printable PDF unfold for the last cuboid or cylinder result."""
        result = getattr(self, "_last_result", None)
        if not result or "face_paths" not in result:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "No Result",
                "Generate a cuboid or cylinder first, then export PDF.",
            )
            return

        import numpy as np
        from PIL import Image as PILImage

        face_images = {}
        for name, path in result["face_paths"].items():
            face_images[name] = np.array(PILImage.open(path))

        paper = self.export_controls.paper_combo.currentText()
        scale_mode = self.export_controls.scale_combo.currentText().lower()
        out_dir = result.get("output_dir", "")
        vs = self.state.video_source
        video_name = ""
        if vs:
            video_name = os.path.splitext(os.path.basename(vs.file_path))[0]
        frame_range = f"{self.state.initial_frame}-{self.state.last_frame}"

        mode = self.state.current_mode

        if mode == "Cuboid":
            from export.unfold_exporter import export_cuboid_pdf
            pdf_path = self._unique_pdf_path(
                os.path.join(out_dir, "cuboid_unfold.pdf")
            )
            export_cuboid_pdf(
                face_images, result["dimensions"], pdf_path,
                paper_size=paper, video_name=video_name,
                frame_range=frame_range, scale_mode=scale_mode,
            )
        elif mode == "Cylinder":
            from export.unfold_exporter import export_cylinder_pdf
            pdf_path = self._unique_pdf_path(
                os.path.join(out_dir, "cylinder_unfold.pdf")
            )
            export_cylinder_pdf(
                face_images, result["dimensions"], pdf_path,
                paper_size=paper, video_name=video_name,
                frame_range=frame_range, scale_mode=scale_mode,
            )
        else:
            return

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "PDF Exported",
            f"Printable unfold saved to:\n{pdf_path}",
        )

    @staticmethod
    def _unique_pdf_path(path):
        """Return *path* if it doesn't exist, otherwise append _1, _2, … ."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(f"{base}_{i}{ext}"):
            i += 1
        return f"{base}_{i}{ext}"

    # --- Slit-Tear helpers ---

    def _on_slittear_undo(self):
        self._drawing_canvas.undo()

    def _on_slittear_clear(self):
        self._drawing_canvas.clear()

    def _on_slittear_lines_changed(self):
        """Called when the DrawingCanvas model's lines change."""
        self.slittear_controls.update_line_list(self._drawing_canvas)
        self.frame_viewer.update()

    def _show_slittear_3d_preview(self, result):
        """Show slit-tear curtain meshes in the 3D viewer."""
        import numpy as np
        from PIL import Image as PILImage

        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        vs = self.state.video_source
        if vs is None:
            return

        image_path = result.get("image_path")
        rasterized = result.get("rasterized_lines", [])
        pixel_counts = result.get("line_pixel_counts", [])
        depth = result.get("frames_processed", 1)

        if not image_path or not rasterized:
            return

        full_img = np.array(PILImage.open(image_path).convert("RGB"))

        self._preview_3d.display_slittear(
            full_img, rasterized, pixel_counts, depth,
            vs.width, vs.height,
        )
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_slitscan_3d_from_result(self, result):
        """Show slitscan 3D preview with textured plane after generation."""
        import numpy as np
        from PIL import Image as PILImage

        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        vs = self.state.video_source
        if vs is None:
            return

        captures_base = result.get("output_dir", "")
        self._preview_3d.set_output_dir(captures_base)
        self._preview_3d.set_quality_from_label("high")

        image_path = result.get("image_path")
        if not image_path:
            return
        tex_img = np.array(PILImage.open(image_path).convert("RGB"))

        sampling_mode = result.get("sampling_mode", "")
        mask_type = result.get("mask_type", "")
        depth = result.get("frames_processed", 1)

        if sampling_mode == "Oblique":
            oblique_points = result.get("oblique_points", [])
            if oblique_points:
                self._preview_3d.display_slitscan_oblique_textured(
                    tex_img, oblique_points,
                    vs.width, vs.height, depth,
                    initial_frame=self.state.initial_frame,
                    last_frame=self.state.last_frame,
                )
        elif sampling_mode == "Planar cut (3D)":
            scan_dir = result.get("scan_direction", "L→R")
            self._preview_3d.display_slitscan_planar(
                tex_img, scan_dir, mask_type,
                vs.width, vs.height, depth,
                mask_left=result.get("mask_left", 0),
                mask_right=result.get("mask_right", 0),
                mask_top=result.get("mask_top", 0),
                mask_bottom=result.get("mask_bottom", 0),
            )

        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_slitscan_3d_preview(self, result):
        """Show slitscan oblique 3D preview with void cuboid + cutting plane."""
        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        vs = self.state.video_source
        if vs is None:
            return

        oblique_points = result.get("oblique_points", [])
        if not oblique_points:
            return

        depth = result.get("frames_processed", 1)
        captures_base = result.get("output_dir", "")
        self._preview_3d.set_output_dir(captures_base)
        self._preview_3d.set_quality_from_label("high")
        self._preview_3d.display_slitscan_oblique(
            oblique_points, vs.width, vs.height, depth,
        )
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _on_slitscan_border_drag(self, left, right, top, bottom):
        """Route border drag to slitscan controls when in slitscan mode."""
        if self.state.current_mode == "Slit-scan":
            self.slitscan_controls.set_borders_from_drag(left, right, top, bottom)

    def _show_slitscan_void_3d_preview(self, result):
        """Show slitscan void cuboid 3D preview for vertical/horizontal."""
        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        vs = self.state.video_source
        if vs is None:
            return

        dims = {
            "width": result.get("frame_width", vs.width),
            "height": result.get("frame_height", vs.height),
            "depth": result.get("frames_processed", 1),
            "mask_type": result.get("mask_type", "Vertical"),
        }
        captures_base = result.get("output_dir", "")
        self._preview_3d.set_output_dir(captures_base)
        self._preview_3d.set_quality_from_label("high")
        self._preview_3d.display_slitscan_void(
            dims,
            result.get("mask_left", 0),
            result.get("mask_right", 0),
            result.get("mask_top", 0),
            result.get("mask_bottom", 0),
        )
        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _show_slitscan_mask_selector(self):
        """Show 3D wireframe preview for Slitscan Planar cut mode (pre-generation).

        Displays a wireframe cuboid with mask region visualization.
        """
        if self._preview_3d is None:
            from ui.preview.preview_3d import Preview3D
            self._preview_3d = Preview3D()
            self.preview_stack.addWidget(self._preview_3d)

        s = self.state
        vs = s.video_source
        if vs is None:
            return

        depth = max(1, (s.last_frame - s.initial_frame) // max(1, s.sampling_rate) + 1)

        dims = {
            "width": vs.width,
            "height": vs.height,
            "depth": depth,
            "mask_type": s.slitscan_mask_type,
        }
        self._preview_3d.display_slitscan_void(
            dims,
            s.slitscan_border_left,
            s.slitscan_border_right,
            s.slitscan_border_top,
            s.slitscan_border_bottom,
        )

        self.preview_stack.setCurrentWidget(self._preview_3d)

    def _on_slitscan_settings_changed(self):
        """Update 3D button when slitscan settings change.

        The 3D preview button is only enabled after generation completes.
        Pre-generation it stays disabled regardless of settings.
        """
        if self.state.current_mode != "Slit-scan":
            return
        # 3D is only enabled after generation — do nothing here

    def _set_controls_enabled(self, enabled):
        self.video_panel.setEnabled(enabled)
        self.mode_selector.setEnabled(enabled)
        self.mode_controls_stack.setEnabled(enabled)
        self.export_controls.setEnabled(enabled)
        self.frame_scrubber.setEnabled(enabled)
