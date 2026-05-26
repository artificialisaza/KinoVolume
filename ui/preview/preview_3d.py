"""Interactive 3D preview using PyVistaQt for cuboid visualization."""

import os

import numpy as np
from PIL import Image
import pyvista as pv
from pyvistaqt import QtInteractor

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

from config import PREVIEW_TEXTURE_MAX
from ui.widgets.preview_toolbar import PreviewToolbar

# Preview quality presets: label → max texture dimension (0 = unlimited)
_QUALITY_PRESETS = {
    "Low (512)": 512,
    "Medium (1024)": 1024,
    "High (2048)": 2048,
    "Ultra (4096)": 4096,
    "Full": 0,
}


class _RoundedPanel(QWidget):
    """Opaque dark panel with rounded corners via QPainter."""

    def __init__(self, parent=None, radius=6):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._radius = radius

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Fully opaque to prevent VTK framebuffer bleeding
        painter.setBrush(QColor(30, 30, 30, 255))
        painter.setPen(QColor(60, 60, 60, 255))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1),
                                float(self._radius), float(self._radius))
        painter.end()
        super().paintEvent(event)


class Preview3D(QWidget):
    """Embeddable 3D preview widget for textured cuboid display."""

    # Emitted when oblique control points are moved in the 3D mask selector.
    # Carries a list of 4 (x, y, t) tuples.
    oblique_points_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._output_dir = None  # set by main_window after generation
        self._last_display_call = None  # (method_name, args, kwargs) for re-render
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- 3D plotter fills the widget ---
        self.plotter = QtInteractor(self)
        self.plotter.set_background("#1e1e1e")
        # Enable supersampling antialiasing to smooth visible edges of textured
        # cuboids and cylinders.  SSAA gives the best quality for crisp edges
        # at the cost of a small performance hit; falls back gracefully if the
        # active VTK backend doesn't support it.
        try:
            self.plotter.enable_anti_aliasing("ssaa")
        except Exception:
            try:
                self.plotter.enable_anti_aliasing("msaa", multi_samples=8)
            except Exception:
                try:
                    self.plotter.enable_anti_aliasing("fxaa")
                except Exception:
                    pass
        # Smooth polygon and line rendering as a secondary defence against
        # jagged edges on textured face borders.
        try:
            ren = self.plotter.renderer
            ren.SetUseFXAA(True)
        except Exception:
            pass
        layout.addWidget(self.plotter.interactor)

        # --- Floating preview toolbar (top-right) ---
        self._toolbar = PreviewToolbar(self)
        self._toolbar.set_rotate_visible(False)   # no 2D rotation in 3D view
        self._toolbar.set_pan_visible(False)       # VTK handles 3D pan natively
        self._toolbar.set_info_visible(True)       # show navigation help button
        self._toolbar.set_view3d_visible(True)     # straighten / invert / reset
        self._toolbar.zoom_in_clicked.connect(self._do_zoom_in)
        self._toolbar.zoom_out_clicked.connect(self._do_zoom_out)
        self._toolbar.bg_color_changed.connect(self._set_bg_color)
        self._toolbar.capture_clicked.connect(self._capture)
        self._toolbar.info_clicked.connect(self._show_info_popup)
        self._toolbar.straighten_clicked.connect(self._straighten_view)
        self._toolbar.invert_time_clicked.connect(self._invert_time)
        self._toolbar.reset_view_clicked.connect(self._reset_camera)
        self._toolbar.wireframe_clicked.connect(self._toggle_wireframe)
        self._toolbar.auto_rotate_clicked.connect(self._toggle_auto_rotate)
        self._toolbar.clip_plane_clicked.connect(self._toggle_clip_plane)
        self._time_inverted = False
        self._wireframe_on = False
        self._auto_rotate_on = False
        self._clip_plane_on = False

        # --- Floating overlay container (bottom-right) ---
        self._overlay = _RoundedPanel(self, radius=6)
        self._overlay.setObjectName("preview3dOverlay")
        self._overlay.setStyleSheet(
            "#preview3dOverlay QLabel { background: transparent; color: #ccc; font-size: 11px; }"
            "#preview3dOverlay QSlider { background: transparent; }"
            "#preview3dOverlay QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }"
            "#preview3dOverlay QSlider::handle:horizontal { background: #703030; width: 10px; margin: -4px 0; border-radius: 5px; }"
            "#preview3dOverlay QSlider::sub-page:horizontal { background: #703030; border-radius: 2px; }"
            "#preview3dOverlay QComboBox { background: #323232; font-size: 11px; border: 1px solid #555; padding: 2px 4px; }"
            "#preview3dOverlay QSpinBox { background: #323232; font-size: 11px; border: 1px solid #555; padding: 2px 4px; }"
            "#preview3dOverlay QPushButton { background: #323232; font-size: 11px; border: 1px solid #555; padding: 2px 6px; }"
        )
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(8, 6, 8, 6)
        overlay_layout.setSpacing(4)

        # --- Collapse / expand toggle row ---
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addStretch()
        self._overlay_toggle = QPushButton("—")
        self._overlay_toggle.setFixedSize(28, 12)
        self._overlay_toggle.setToolTip("Collapse / expand panel")
        self._overlay_toggle.setCursor(Qt.PointingHandCursor)
        self._overlay_toggle.setFocusPolicy(Qt.NoFocus)
        self._overlay_toggle.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #aaa; font-size: 10px; }"
            "QPushButton:hover { background: rgba(80,80,80,180); border-radius: 3px; }"
        )
        self._overlay_toggle.clicked.connect(self._toggle_overlay_collapse)
        toggle_row.addWidget(self._overlay_toggle)
        overlay_layout.addLayout(toggle_row)

        # Container for collapsible overlay body
        self._overlay_body = QWidget()
        self._overlay_body.setAutoFillBackground(False)
        overlay_body_layout = QVBoxLayout(self._overlay_body)
        overlay_body_layout.setContentsMargins(0, 0, 0, 0)
        overlay_body_layout.setSpacing(4)
        self._overlay_collapsed = False

        # Opacity row
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(4)
        ol = QLabel("Opacity:")
        opacity_row.addWidget(ol)
        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setFixedWidth(100)
        self._opacity_slider.setToolTip("Adjust mesh transparency (5–100 %)")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self._opacity_slider)
        self._opacity_label = QLabel("100 %")
        self._opacity_label.setFixedWidth(36)
        opacity_row.addWidget(self._opacity_label)
        overlay_body_layout.addLayout(opacity_row)

        # Blend mode row (visible only for cuboid fill)
        self._blend_row = QWidget()
        blend_layout = QHBoxLayout(self._blend_row)
        blend_layout.setContentsMargins(0, 0, 0, 0)
        blend_layout.setSpacing(4)
        bl = QLabel("Blend:")
        blend_layout.addWidget(bl)
        self._blend_combo = QComboBox()
        self._blend_combo.addItems(["Standard", "Depth fade", "X-ray"])
        self._blend_combo.setFixedWidth(100)
        self._blend_combo.setToolTip(
            "Standard — uniform opacity for all frames\n"
            "Depth fade — near frames opaque, far frames fade out\n"
            "X-ray — additive blending, bright on dark background"
        )
        self._blend_combo.currentTextChanged.connect(self._on_blend_changed)
        blend_layout.addWidget(self._blend_combo)
        self._blend_row.setVisible(False)
        overlay_body_layout.addWidget(self._blend_row)

        # Preview Quality row
        quality_row = QHBoxLayout()
        quality_row.setSpacing(4)
        ql = QLabel("Quality:")
        quality_row.addWidget(ql)
        self._quality_combo = QComboBox()
        self._quality_combo.addItems(list(_QUALITY_PRESETS.keys()))
        default_idx = list(_QUALITY_PRESETS.keys()).index("High (2048)")
        self._quality_combo.setCurrentIndex(default_idx)
        self._quality_combo.setFixedWidth(120)
        self._quality_combo.setToolTip(
            "Max texture resolution for preview.  Lower = faster, higher = sharper.\n"
            "Captures use the current preview quality."
        )
        self._quality_combo.currentTextChanged.connect(self._on_quality_changed)
        quality_row.addWidget(self._quality_combo)
        overlay_body_layout.addLayout(quality_row)

        # Frame density row (visible only for cuboid fill)
        self._density_row = QWidget()
        density_layout = QHBoxLayout(self._density_row)
        density_layout.setContentsMargins(0, 0, 0, 0)
        density_layout.setSpacing(4)
        dl = QLabel("Frames:")
        density_layout.addWidget(dl)
        self._density_combo = QComboBox()
        self._density_combo.addItems(["Every N frames", "All frames"])
        self._density_combo.setFixedWidth(120)
        self._density_combo.setToolTip("How many internal frames to display")
        density_layout.addWidget(self._density_combo)
        self._density_spin = QSpinBox()
        self._density_spin.setRange(2, 10000)
        self._density_spin.setValue(10)
        self._density_spin.setPrefix("N=")
        self._density_spin.setFixedWidth(70)
        self._density_spin.setToolTip("Show one frame every N frames")
        density_layout.addWidget(self._density_spin)
        self._density_row.setVisible(False)
        overlay_body_layout.addWidget(self._density_row)

        # Frame spacing row (visible only for cuboid fill)
        self._spacing_row = QWidget()
        spacing_layout = QHBoxLayout(self._spacing_row)
        spacing_layout.setContentsMargins(0, 0, 0, 0)
        spacing_layout.setSpacing(4)
        sl = QLabel("Spacing:")
        spacing_layout.addWidget(sl)
        self._spacing_combo = QComboBox()
        self._spacing_combo.addItems([
            "0.25×", "0.5×", "1×", "2×", "3×", "5×", "8×", "12×", "20×",
        ])
        self._spacing_combo.setFixedWidth(70)
        self._spacing_combo.setToolTip(
            "Distance between frames.\n"
            "1× = literal stacking, 20× = wide gaps."
        )
        spacing_layout.addWidget(self._spacing_combo)
        self._spacing_row.setVisible(False)
        overlay_body_layout.addWidget(self._spacing_row)

        # Pad gaps checkbox for cuboid fill
        self._pad_gaps_row = QWidget()
        pad_gaps_layout = QHBoxLayout(self._pad_gaps_row)
        pad_gaps_layout.setContentsMargins(0, 0, 0, 0)
        self._pad_gaps_check = QCheckBox("Pad frames (no gaps)")
        self._pad_gaps_check.setToolTip(
            "Thicken each frame into a thin box that fills the\n"
            "space to the next frame, creating a continuous volume."
        )
        self._pad_gaps_check.toggled.connect(self._on_pad_gaps_changed)
        pad_gaps_layout.addWidget(self._pad_gaps_check)
        self._pad_gaps_row.setVisible(False)
        overlay_body_layout.addWidget(self._pad_gaps_row)

        # Single Apply button (visible only for cuboid fill)
        self._apply_row = QWidget()
        apply_layout = QHBoxLayout(self._apply_row)
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.setSpacing(4)
        apply_layout.addStretch()
        self._fill_apply_btn = QPushButton("Apply")
        self._fill_apply_btn.setFixedWidth(60)
        self._fill_apply_btn.setToolTip("Reload 3D preview with updated frames / spacing settings")
        self._fill_apply_btn.clicked.connect(self._on_fill_apply)
        apply_layout.addWidget(self._fill_apply_btn)
        self._apply_row.setVisible(False)
        overlay_body_layout.addWidget(self._apply_row)

        overlay_layout.addWidget(self._overlay_body)
        self._overlay.adjustSize()

        self._density_combo.currentTextChanged.connect(self._on_density_mode_changed)

        self._dims = None
        self._mesh_actors = []
        self._fill_data = None
        self._bg_transparent = False  # track transparent background for captures

        # State for re-rendering at different quality levels / full-quality capture
        self._current_max_tex = PREVIEW_TEXTURE_MAX
        self._last_display_call = None   # (method_name, args, kwargs)
        self._capturing = False          # True while doing a full-quality capture

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlay()
        self._toolbar.reposition()

    def _position_overlay(self):
        self._overlay.adjustSize()
        margin = 10
        x = self.width() - self._overlay.width() - margin
        y = self.height() - self._overlay.height() - margin
        self._overlay.move(max(0, x), max(0, y))
        self._overlay.raise_()

    def _toggle_overlay_collapse(self):
        """Collapse or expand the overlay panel body."""
        self._overlay_collapsed = not self._overlay_collapsed
        self._overlay_body.setVisible(not self._overlay_collapsed)
        # Keep the line indicator unchanged in both states
        self._position_overlay()

    # ------------------------------------------------------------------
    # New toolbar methods
    # ------------------------------------------------------------------

    def set_output_dir(self, output_dir: str):
        """Tell the preview where to save capture images."""
        self._output_dir = output_dir

    def set_quality_from_label(self, label: str):
        """Apply a quality level from the sidebar dropdown label.

        Accepted labels: Full, High, Medium, Low (case-insensitive).
        """
        mapping = {
            "full": "Full",
            "high": "High (2048)",
            "medium": "Medium (1024)",
            "low": "Low (512)",
        }
        key = mapping.get(label.lower())
        if key is not None:
            idx = self._quality_combo.findText(key)
            if idx >= 0:
                self._quality_combo.setCurrentIndex(idx)
            max_dim = _QUALITY_PRESETS.get(key, PREVIEW_TEXTURE_MAX)
            self._current_max_tex = max_dim

    def _do_zoom_in(self):
        self.plotter.camera.zoom(1.3)
        self.plotter.render()

    def _do_zoom_out(self):
        self.plotter.camera.zoom(1 / 1.3)
        self.plotter.render()

    def _set_bg_color(self, color):
        """Change the 3D plotter background colour.  ``None`` = interface default."""
        if color is None:
            self.plotter.set_background("#1e1e1e")
            self._bg_transparent = False
        elif color.alpha() == 0:
            # Transparent background: use black for display, flag for capture
            self.plotter.set_background("#000000")
            self._bg_transparent = True
        else:
            self.plotter.set_background(color.name())
            self._bg_transparent = False
        self.plotter.render()

    def _capture(self):
        """Save a PNG screenshot of the 3D view at the current preview quality."""
        import datetime
        base_dir = self._output_dir
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser("~"), "Desktop",
                                    "KinoVolume")
        captures_dir = os.path.join(base_dir, "Captures")
        os.makedirs(captures_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(captures_dir, f"capture_{ts}.png")

        self.plotter.screenshot(
            path, transparent_background=self._bg_transparent,
        )

    def _on_quality_changed(self, text):
        """Re-render the current scene at the newly selected quality level."""
        max_dim = _QUALITY_PRESETS.get(text, PREVIEW_TEXTURE_MAX)
        self._current_max_tex = max_dim
        if self._last_display_call is not None:
            saved_cam = self.plotter.camera_position
            saved_opacity = self._opacity_slider.value()
            method_name, args, kwargs = self._last_display_call
            getattr(self, method_name)(*args, **kwargs)
            self.plotter.camera_position = saved_cam
            self._opacity_slider.setValue(saved_opacity)

    def _show_info_popup(self):
        """Show a small popup with 3D navigation instructions."""
        from PySide6.QtWidgets import QFrame, QLabel
        popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(
            "QFrame {"
            "  background: #2b2b2b;"
            "  border: 1px solid #4a4a4a;"
            "  border-radius: 6px;"
            "  padding: 4px;"
            "}"
            "QLabel { background: transparent; color: #e0e0e0; font-size: 12px; }"
        )
        label = QLabel(
            "<b>3D Navigation</b><br><br>"
            "<b>Rotate:</b>&nbsp;&nbsp; Left-click + drag<br>"
            "<b>Pan:</b>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; Shift + left-click drag,<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;or middle-click + drag<br>"
            "<b>Zoom:</b>&nbsp;&nbsp;&nbsp;&nbsp; Scroll wheel<br>"
            "<b>Reset:</b>&nbsp;&nbsp;&nbsp;&nbsp; \u2018Reset Camera\u2019 button",
            popup,
        )
        label.setContentsMargins(10, 8, 10, 8)
        label.setWordWrap(False)
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(popup)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(label)
        popup.adjustSize()
        # Position below the info button
        btn_pos = self._toolbar._info_btn.mapToGlobal(
            QPoint(0, self._toolbar._info_btn.height() + 4)
        )
        popup.move(btn_pos)
        popup.show()

    def display_cuboid(self, face_images, dimensions):
        """Render a textured cuboid from 6 face images.

        face_images: dict  name→(H,W,3) uint8 numpy array
        dimensions:  dict  {"width": W, "height": H, "depth": D}
        """
        if not self._capturing:
            self._last_display_call = (
                "display_cuboid", (face_images, dimensions), {},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)

        W = float(dimensions["width"])
        H = float(dimensions["height"])
        D = float(dimensions["depth"])
        self._dims = (W, H, D)

        # Downscale textures that exceed the max preview size
        scaled = {}
        for name, img in face_images.items():
            scaled[name] = self._downscale(img)

        # Correct for camera viewing convention (camera right-vector has
        # negative x, so front-facing faces appear horizontally mirrored).
        scaled["front"] = np.fliplr(scaled["front"])
        scaled["bottom"] = np.fliplr(scaled["bottom"])
        scaled["left"], scaled["right"] = scaled["right"], scaled["left"]

        # When time is inverted: front↔back swap + flip time on sides.
        # front/back are XY spatial faces: the new front needs camera
        # correction (np.fliplr), the old front's flip is undone.
        # left/right: cols = time → np.fliplr.
        # top/bottom: rows = time → np.flipud.
        if self._time_inverted:
            scaled["front"], scaled["back"] = (
                np.fliplr(scaled["back"]),
                np.fliplr(scaled["front"]),
            )
            scaled["left"] = np.fliplr(scaled["left"])
            scaled["right"] = np.fliplr(scaled["right"])
            scaled["top"] = np.flipud(scaled["top"])
            scaled["bottom"] = np.flipud(scaled["bottom"])

        # Define each face with explicit vertices and UV coordinates.
        # UVs assume standard convention: u=0,v=0 → bottom-left of image.
        # After side texture transpose: left/right are (mask_h, num_frames, 3)
        # cols=time, rows=height.
        face_defs = {
            "front": {
                "verts": [(0,0,0), (W,0,0), (W,H,0), (0,H,0)],
                "uvs": [(0,0), (1,0), (1,1), (0,1)],
            },
            "back": {
                "verts": [(W,0,D), (0,0,D), (0,H,D), (W,H,D)],
                "uvs": [(0,0), (1,0), (1,1), (0,1)],
            },
            "top": {
                "verts": [(0,H,0), (W,H,0), (W,H,D), (0,H,D)],
                "uvs": [(1,1), (0,1), (0,0), (1,0)],
            },
            "bottom": {
                "verts": [(0,0,D), (W,0,D), (W,0,0), (0,0,0)],
                "uvs": [(0,0), (1,0), (1,1), (0,1)],
            },
            "left": {
                "verts": [(0,0,D), (0,0,0), (0,H,0), (0,H,D)],
                "uvs": [(1,0), (0,0), (0,1), (1,1)],
            },
            "right": {
                "verts": [(W,0,0), (W,0,D), (W,H,D), (W,H,0)],
                "uvs": [(0,0), (1,0), (1,1), (0,1)],
            },
        }

        for name, fdef in face_defs.items():
            verts = np.array(fdef["verts"], dtype=np.float32)
            faces = np.array([4, 0, 1, 2, 3], dtype=np.int32)
            mesh = pv.PolyData(verts, faces)
            mesh.active_texture_coordinates = np.array(fdef["uvs"], dtype=np.float32)
            texture = pv.numpy_to_texture(scaled[name])
            actor = self.plotter.add_mesh(mesh, texture=texture, smooth_shading=False)
            self._mesh_actors.append(actor)

        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None
        self._reset_camera()
        self._apply_opacity()

    def display_cuboid_fill(self, slices_dir, dimensions, step=None):
        """Render stacked frame planes to visualise a filled cuboid volume.

        Args:
            slices_dir: path to directory of numbered frame images
            dimensions: dict {\"width\", \"height\", \"depth\"} (depth = total frames)
            step: show every *step*-th frame.  ``None`` → use density widget value.
        """
        import glob

        if not self._capturing:
            self._last_display_call = (
                "display_cuboid_fill", (slices_dir, dimensions), {"step": step},
            )

        self.plotter.clear()
        self._mesh_actors.clear()

        W = float(dimensions["width"])
        H = float(dimensions["height"])
        total = int(dimensions["depth"])

        # Scale depth so the cuboid has reasonable proportions in 3D.
        # Raw depth = frame count (e.g. 30) while W/H are pixels (e.g. 1920×1080).
        # Use a proportion that makes depth ~40% of the longest spatial axis.
        max_spatial = max(W, H, 1.0)
        base_D = max_spatial * 0.4 * total / max(total, 1)

        # Apply user spacing factor from combo (e.g. "5×" → 5.0)
        spacing_text = self._spacing_combo.currentText().rstrip("×")
        try:
            spacing_factor = float(spacing_text)
        except ValueError:
            spacing_factor = 1.0
        D = base_D * spacing_factor

        self._dims = (W, H, D)

        # Resolve step
        if step is None:
            if self._density_combo.currentText() == "Every N frames":
                step = max(1, self._density_spin.value())
            else:
                step = 1

        # Store for re-renders via Apply button
        self._fill_data = (slices_dir, dimensions)
        self._density_row.setVisible(True)
        self._spacing_row.setVisible(True)
        self._pad_gaps_row.setVisible(True)
        self._blend_row.setVisible(True)
        self._apply_row.setVisible(True)

        # Gather sorted frame image paths — only use the expected count
        paths = sorted(glob.glob(os.path.join(slices_dir, "frame_*.png")))
        if not paths:
            paths = sorted(glob.glob(os.path.join(slices_dir, "frame_*.tiff")))
        if not paths:
            print("[Preview3D] No frame images found in", slices_dir)
            self._reset_camera()
            return

        # Trim to the expected frame count to ignore leftover files
        if len(paths) > total:
            paths = paths[:total]

        # Auto-adjust step if it would give us fewer than 2 frames
        if step > 1 and len(paths) // step < 2 and len(paths) >= 2:
            step = max(1, len(paths) // 10) or 1

        # Select subset
        selected = paths[::step]

        # Compute gap thickness between consecutive planes
        if len(selected) > 1:
            plane_gap = D / max(1, len(paths) - 1)
        else:
            plane_gap = 0.0

        pad_gaps = self._pad_gaps_check.isChecked()

        for i, path in enumerate(selected):
            try:
                frame_img = np.array(Image.open(path))
            except Exception as exc:
                print(f"[Preview3D] Failed to load {path}: {exc}")
                continue

            if self._time_inverted:
                frame_img = np.fliplr(frame_img)

            idx = i * step
            z = D * idx / max(1, len(paths) - 1)

            has_alpha = frame_img.ndim == 3 and frame_img.shape[2] == 4

            if pad_gaps and plane_gap > 0:
                # Build a thin 3D box: the frame texture on the front
                # and back faces fills the gap to the next plane.
                half_g = plane_gap / 2.0
                z_min = z - half_g
                z_max = z + half_g

                # 8 vertices: 4 at z_min (back), 4 at z_max (front)
                bverts = np.array([
                    [0, 0, z_min], [W, 0, z_min], [W, H, z_min], [0, H, z_min],
                    [0, 0, z_max], [W, 0, z_max], [W, H, z_max], [0, H, z_max],
                ], dtype=np.float32)
                tex_img = self._downscale(frame_img)
                texture = pv.numpy_to_texture(tex_img)

                opacity = 1.0
                if has_alpha:
                    opacity = 0.95

                # Front face (z=z_max): outward-facing
                front_verts = bverts[[4, 5, 6, 7], :]
                front_uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
                front_mesh = pv.PolyData(front_verts, np.array([4, 0, 1, 2, 3], dtype=np.int32))
                front_mesh.active_texture_coordinates = front_uvs
                actor = self.plotter.add_mesh(
                    front_mesh, texture=texture, smooth_shading=False, opacity=opacity,
                )
                self._mesh_actors.append(actor)

                # Back face (z=z_min): inward-facing
                back_verts = bverts[[0, 3, 2, 1], :]
                back_uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
                back_mesh = pv.PolyData(back_verts, np.array([4, 0, 1, 2, 3], dtype=np.int32))
                back_mesh.active_texture_coordinates = back_uvs
                actor = self.plotter.add_mesh(
                    back_mesh, texture=texture, smooth_shading=False, opacity=opacity,
                )
                self._mesh_actors.append(actor)
            else:
                verts = np.array([
                    [0, 0, z], [W, 0, z], [W, H, z], [0, H, z],
                ], dtype=np.float32)
                faces = np.array([4, 0, 1, 2, 3], dtype=np.int32)
                uvs = np.array([
                    [0, 0], [1, 0], [1, 1], [0, 1],
                ], dtype=np.float32)
                mesh = pv.PolyData(verts, faces)
                mesh.active_texture_coordinates = uvs

                tex_img = self._downscale(frame_img)
                texture = pv.numpy_to_texture(tex_img)

                opacity = 1.0
                if has_alpha:
                    opacity = 0.95

                actor = self.plotter.add_mesh(
                    mesh, texture=texture, smooth_shading=False, opacity=opacity,
                )
                self._mesh_actors.append(actor)

        self._reset_camera()
        self._apply_opacity()

    def _on_density_mode_changed(self, text):
        self._density_spin.setVisible(text == "Every N frames")

    def _on_pad_gaps_changed(self, checked):
        """Re-render with updated pad gaps setting."""
        self._on_fill_apply()

    def _on_fill_apply(self):
        """Re-render cuboid fill with current frame density + spacing settings."""
        if self._fill_data is None:
            return
        slices_dir, dimensions = self._fill_data
        self.display_cuboid_fill(slices_dir, dimensions)

    def _reset_camera(self):
        """Set camera to 3/4 view showing front, top, and right faces."""
        if self._dims is None:
            return
        W, H, D = self._dims
        cx, cy, cz = W / 2, H / 2, D / 2
        diag = np.sqrt(W**2 + H**2 + D**2)
        cam_pos = (cx + diag * 0.7, cy + diag * 0.5, cz - diag * 1.2)
        self.plotter.camera_position = [cam_pos, (cx, cy, cz), (0, 1, 0)]
        self.plotter.reset_camera_clipping_range()
        self._position_overlay()

    def _straighten_view(self):
        """Snap the camera to the nearest axis-aligned orientation.

        Preserves the current distance from the focal point but rotates
        the viewpoint so the object appears upright and aligned —
        like pressing "north-up" on a GPS map.
        """
        if self._dims is None:
            return
        cam_pos, focal, up = self.plotter.camera_position
        cam_pos = np.array(cam_pos, dtype=float)
        focal = np.array(focal, dtype=float)
        direction = cam_pos - focal
        dist = np.linalg.norm(direction)
        if dist < 1e-6:
            return

        # Normalise and snap to nearest axis
        normed = direction / dist
        # Find the dominant axis
        abs_dir = np.abs(normed)
        axis = int(np.argmax(abs_dir))
        snapped = np.zeros(3)
        snapped[axis] = np.sign(normed[axis]) * 1.0

        new_cam = focal + snapped * dist
        self.plotter.camera_position = [
            tuple(new_cam), tuple(focal), (0, 1, 0),
        ]
        self.plotter.reset_camera_clipping_range()

    def _invert_time(self):
        """Flip the volume horizontally (mirror X) to invert time direction."""
        self._time_inverted = not self._time_inverted
        if self._last_display_call is not None:
            saved_cam = self.plotter.camera_position
            method_name, args, kwargs = self._last_display_call
            getattr(self, method_name)(*args, **kwargs)
            self.plotter.camera_position = saved_cam

    # ------------------------------------------------------------------
    # Navigation extras
    # ------------------------------------------------------------------

    def _toggle_wireframe(self):
        """Toggle between solid and wireframe rendering for all meshes."""
        self._wireframe_on = not self._wireframe_on
        style = "wireframe" if self._wireframe_on else "surface"
        for actor in self._mesh_actors:
            try:
                actor.GetProperty().SetRepresentationToWireframe() if self._wireframe_on \
                    else actor.GetProperty().SetRepresentationToSurface()
            except Exception:
                pass
        self.plotter.render()

    def _toggle_auto_rotate(self):
        """Start or stop a slow turntable rotation."""
        self._auto_rotate_on = not self._auto_rotate_on
        if self._auto_rotate_on:
            if not hasattr(self, "_rotate_timer"):
                self._rotate_timer = QTimer(self)
                self._rotate_timer.setInterval(30)  # ~33 fps
                self._rotate_timer.timeout.connect(self._auto_rotate_step)
            self._rotate_timer.start()
        else:
            if hasattr(self, "_rotate_timer"):
                self._rotate_timer.stop()

    def _auto_rotate_step(self):
        """Rotate the camera around the focal point in a turntable orbit."""
        try:
            import math
            cam = self.plotter.camera
            fp = list(cam.focal_point)
            pos = list(cam.position)
            # Compute horizontal offset from focal point
            dx = pos[0] - fp[0]
            dz = pos[2] - fp[2]
            radius = math.sqrt(dx * dx + dz * dz)
            if radius < 1e-6:
                return
            angle = math.atan2(dz, dx) + math.radians(1)
            cam.position = (
                fp[0] + radius * math.cos(angle),
                pos[1],
                fp[2] + radius * math.sin(angle),
            )
            cam.focal_point = fp
            cam.up = (0, 1, 0)
            self.plotter.render()
        except Exception:
            if hasattr(self, "_rotate_timer"):
                self._rotate_timer.stop()
            self._auto_rotate_on = False

    def _toggle_clip_plane(self):
        """Toggle an interactive clipping plane widget on/off."""
        self._clip_plane_on = not self._clip_plane_on
        if self._clip_plane_on:
            if self._dims is None:
                self._clip_plane_on = False
                return
            W, H, D = self._dims
            origin = (W / 2, H / 2, D / 2)
            normal = (0, 0, 1)
            try:
                self.plotter.add_clip_plane_widget(
                    normal=normal,
                    origin=origin,
                    interaction_event="always",
                    normal_rotation=True,
                )
            except Exception:
                self._clip_plane_on = False
        else:
            try:
                self.plotter.clear_plane_widgets()
            except Exception:
                pass

    def _on_opacity_changed(self, value):
        """Apply opacity from slider to all tracked mesh actors."""
        self._opacity_label.setText(f"{value} %")
        self._apply_opacity()

    def _on_blend_changed(self, text):
        """Re-apply opacity with the new blend mode."""
        self._apply_opacity()

    def _apply_opacity(self):
        """Apply current slider opacity to all mesh actors, respecting blend mode."""
        value = self._opacity_slider.value()
        base_opacity = value / 100.0
        blend = self._blend_combo.currentText() if self._blend_row.isVisible() else "Standard"
        n = len(self._mesh_actors)

        for idx, actor in enumerate(self._mesh_actors):
            prop = actor.GetProperty()
            if blend == "Depth fade" and n > 1:
                # Near planes (low idx) get full opacity, far planes fade out
                t = idx / (n - 1)  # 0.0 = nearest, 1.0 = farthest
                opacity = base_opacity * (1.0 - 0.85 * t)
            elif blend == "X-ray":
                # Additive blending: low opacity + additive composite
                opacity = base_opacity * 0.4
            else:
                opacity = base_opacity
            prop.SetOpacity(max(0.02, opacity))
        self.plotter.render()

    def _downscale(self, img):
        """Downscale image if any dimension exceeds the current quality limit."""
        limit = self._current_max_tex
        if limit <= 0:
            return img  # Full quality — no downscale
        h, w = img.shape[:2]
        max_dim = max(h, w)
        if max_dim <= limit:
            return img
        scale = limit / max_dim
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        pil_img = Image.fromarray(img)
        pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
        return np.array(pil_img)

    def display_cylinder(self, face_images, dimensions):
        """Render a textured cylinder from surface + cap images.

        face_images: dict with "surface", "cap_front", "cap_back"
        dimensions:  dict with "radius", "depth" (num_frames), "circumference"
        """
        if not self._capturing:
            self._last_display_call = (
                "display_cylinder", (face_images, dimensions), {},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        radius = float(dimensions["radius"])
        depth = float(dimensions["depth"])
        circumference = int(dimensions["circumference"])
        self._dims = (radius * 2, radius * 2, depth)

        surface_img = self._downscale(face_images["surface"])
        cap_front_img = self._downscale(face_images["cap_front"])
        cap_back_img = self._downscale(face_images["cap_back"])

        # Correct for camera viewing convention: the camera right-vector
        # has negative x, so flat faces appear horizontally mirrored.
        # Only flip the caps (flat discs); the tube wraps around the
        # circumference so flipping it reverses the texture direction.
        cap_front_img = np.fliplr(cap_front_img)
        cap_back_img = np.fliplr(cap_back_img)

        # When time is inverted, reverse the time axis of the tube
        # (rows = frames) and swap the caps.
        if self._time_inverted:
            surface_img = np.flipud(surface_img)
            cap_front_img, cap_back_img = cap_back_img, cap_front_img

        # Cap preview segments to a reasonable count for rendering
        n_seg = min(circumference, 128)
        thetas = np.linspace(0, 2 * np.pi, n_seg + 1)  # duplicate first vertex for UV seam

        # Vertices: 2 rows of (n_seg+1) vertices
        verts = []
        uvs = []
        for i in range(n_seg + 1):
            # Shift u by 0.5 to rotate the tube texture 180°.
            # Let u run past 1.0 (0.5 → 1.5) — VTK's default texture
            # wrapping handles the transition seamlessly, avoiding the
            # backwards-wrap artifact that % 1.0 would create at the seam.
            u = i / n_seg + 0.5
            x = radius + radius * np.cos(thetas[i])
            y = radius + radius * np.sin(thetas[i])
            # Front ring (z=0) → v=1 (top of texture = first frame)
            verts.append([x, y, 0])
            uvs.append([u, 1.0])
            # Back ring (z=depth) → v=0 (bottom of texture = last frame)
            verts.append([x, y, depth])
            uvs.append([u, 0.0])

        verts = np.array(verts, dtype=np.float32)
        uvs = np.array(uvs, dtype=np.float32)

        # Faces: quads as triangle pairs
        faces = []
        for i in range(n_seg):
            v0 = i * 2        # front ring vertex i
            v1 = i * 2 + 1    # back ring vertex i
            v2 = (i + 1) * 2  # front ring vertex i+1
            v3 = (i + 1) * 2 + 1  # back ring vertex i+1
            faces.extend([3, v0, v2, v3])
            faces.extend([3, v0, v3, v1])
        faces = np.array(faces, dtype=np.int32)

        surface_mesh = pv.PolyData(verts, faces)
        surface_mesh.active_texture_coordinates = uvs
        surface_tex = pv.numpy_to_texture(surface_img)
        actor = self.plotter.add_mesh(surface_mesh, texture=surface_tex, smooth_shading=False)
        self._mesh_actors.append(actor)

        # Front cap (z=0) — circular disc
        self._add_cap_mesh(cap_front_img, radius, 0.0, n_seg, thetas)
        # Back cap (z=depth) — circular disc
        self._add_cap_mesh(cap_back_img, radius, depth, n_seg, thetas)

        self._reset_camera()
        self._apply_opacity()

    def _add_cap_mesh(self, cap_img, radius, z, n_seg, thetas):
        """Add a circular cap mesh at the given z position."""
        # Fan triangles from center to perimeter
        center = [radius, radius, z]
        verts = [center]
        uvs = [[0.5, 0.5]]  # center UV

        for i in range(n_seg + 1):
            x = radius + radius * np.cos(thetas[i])
            y = radius + radius * np.sin(thetas[i])
            verts.append([x, y, z])
            # UV: map circle to texture coordinates
            u = 0.5 + 0.5 * np.cos(thetas[i])
            v = 0.5 + 0.5 * np.sin(thetas[i])
            uvs.append([u, v])

        verts = np.array(verts, dtype=np.float32)
        uvs = np.array(uvs, dtype=np.float32)

        faces = []
        for i in range(n_seg):
            # Triangle: center(0), perimeter[i+1], perimeter[i+2]
            if z == 0:
                faces.extend([3, 0, i + 2, i + 1])  # front-facing winding
            else:
                faces.extend([3, 0, i + 1, i + 2])  # back-facing winding
        faces = np.array(faces, dtype=np.int32)

        mesh = pv.PolyData(verts, faces)
        mesh.active_texture_coordinates = uvs
        texture = pv.numpy_to_texture(cap_img)
        actor = self.plotter.add_mesh(mesh, texture=texture, smooth_shading=True)
        self._mesh_actors.append(actor)

    def display_slittear(self, full_image, rasterized_lines, pixel_counts,
                         depth, frame_width, frame_height):
        """Render slit-tear curtain meshes in 3D space.

        Each drawn line becomes a vertical "curtain" surface that traces
        the line path in XY and extends along Z (time axis).

        Args:
            full_image:       (H, W, 3) uint8 — the composited 2D output
            rasterized_lines: list of list of (x, y) — rasterized pixel coords
            pixel_counts:     list of int — pixel count per line
            depth:            int — number of processed frames (Z extent)
            frame_width:      int — video frame width (X extent)
            frame_height:     int — video frame height (Y extent)
        """
        if not self._capturing:
            self._last_display_call = (
                "display_slittear",
                (full_image, rasterized_lines, pixel_counts,
                 depth, frame_width, frame_height),
                {},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)
        self._dims = (W, H, D)

        # Draw a wireframe cuboid to show the video volume
        box_verts = np.array([
            [0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0],
            [0, 0, D], [W, 0, D], [W, H, D], [0, H, D],
        ], dtype=np.float32)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        for a, b in edges:
            line = pv.Line(box_verts[a], box_verts[b])
            self.plotter.add_mesh(line, color="#555555", line_width=1)

        # Build a curtain mesh for each drawn line
        row_offset = 0  # row offset into full_image for this line
        for line_idx, pixels in enumerate(rasterized_lines):
            n = len(pixels)
            if n < 2:
                row_offset += pixel_counts[line_idx] + (1 if line_idx > 0 else 0)
                continue

            # Extract this line's portion of the full texture image
            sep = 1 if line_idx > 0 else 0
            start_row = row_offset + sep
            end_row = start_row + pixel_counts[line_idx]
            line_texture = full_image[start_row:end_row, :, :]
            row_offset = end_row

            # Subsample long lines for performance (max ~500 mesh segments)
            step = max(1, n // 500)
            sampled_indices = list(range(0, n, step))
            if sampled_indices[-1] != n - 1:
                sampled_indices.append(n - 1)
            ns = len(sampled_indices)

            # Build vertices: two rows (Z=0 and Z=D)
            # When time is inverted, swap Z so the first drawn segment
            # appears at the far end of the curtain.
            if self._time_inverted:
                z_near, z_far = D, 0.0
            else:
                z_near, z_far = 0.0, D

            verts = np.zeros((ns * 2, 3), dtype=np.float32)
            uvs = np.zeros((ns * 2, 2), dtype=np.float32)
            for j, idx in enumerate(sampled_indices):
                px, py = pixels[idx]
                # Y is flipped: frame y=0 is top, 3D y=H is top
                verts[j] = [px, H - py, z_near]
                verts[ns + j] = [px, H - py, z_far]
                v_coord = 1.0 - idx / max(1, n - 1)
                uvs[j] = [0.0, v_coord]
                uvs[ns + j] = [1.0, v_coord]

            # Build faces (quads as 2 triangles each)
            faces = []
            for j in range(ns - 1):
                # Quad: j, j+1, ns+j+1, ns+j
                faces.extend([3, j, j + 1, ns + j + 1])
                faces.extend([3, j, ns + j + 1, ns + j])
            faces = np.array(faces, dtype=np.int32)

            mesh = pv.PolyData(verts, faces)
            mesh.active_texture_coordinates = uvs

            tex_img = self._downscale(line_texture)
            texture = pv.numpy_to_texture(tex_img)
            actor = self.plotter.add_mesh(
                mesh, texture=texture, smooth_shading=False,
                show_edges=False,
            )
            self._mesh_actors.append(actor)

        self._reset_camera()
        self._apply_opacity()

    def display_orthogonal(self, v_image, h_image, slit_pos, ortho_pos,
                           frame_width, frame_height, depth,
                           display_frames=None, initial_frame=0,
                           last_frame=None):
        """Render two perpendicular textured planes forming a cross.

        Args:
            v_image:      (H, W, 3) vertical slice image (H=frame_height, W=depth*slit_width)
            h_image:      (H, W, 3) horizontal slice image (H=depth*slit_width, W=frame_width)
            slit_pos:     X position of vertical slit in the video frame
            ortho_pos:    Y position of horizontal slit in the video frame
            frame_width:  video frame width
            frame_height: video frame height
            depth:        number of processed frames (Z extent)
            display_frames: dict {frame_idx: (H,W,3) numpy} or None
        """
        if not self._capturing:
            self._last_display_call = (
                "display_orthogonal",
                (v_image, h_image, slit_pos, ortho_pos,
                 frame_width, frame_height, depth),
                {"display_frames": display_frames,
                 "initial_frame": initial_frame,
                 "last_frame": last_frame},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)
        self._dims = (W, H, D)

        # — Vertical plane (YZ plane at X = slit_pos) —
        vx = float(slit_pos)
        v_verts = np.array([
            [vx, 0, 0], [vx, 0, D], [vx, H, D], [vx, H, 0],
        ], dtype=np.float32)
        v_faces = np.array([4, 0, 1, 2, 3], dtype=np.int32)
        # UV: u runs along Z (time), v runs along Y (height)
        v_uvs = np.array([
            [0, 0], [1, 0], [1, 1], [0, 1],
        ], dtype=np.float32)
        v_mesh = pv.PolyData(v_verts, v_faces)
        v_mesh.active_texture_coordinates = v_uvs
        v_tex = pv.numpy_to_texture(self._downscale(v_image))
        actor = self.plotter.add_mesh(v_mesh, texture=v_tex, smooth_shading=False)
        self._mesh_actors.append(actor)

        # — Horizontal plane (XZ plane at Y = ortho_pos) —
        # Y is flipped: frame y=0 is top, 3D y=H is top
        hy = H - float(ortho_pos)
        h_verts = np.array([
            [0, hy, 0], [W, hy, 0], [W, hy, D], [0, hy, D],
        ], dtype=np.float32)
        h_faces = np.array([4, 0, 1, 2, 3], dtype=np.int32)
        # UV: u runs along X, v runs along Z (time)
        h_uvs = np.array([
            [0, 1], [1, 1], [1, 0], [0, 0],
        ], dtype=np.float32)
        h_mesh = pv.PolyData(h_verts, h_faces)
        h_mesh.active_texture_coordinates = h_uvs
        h_tex = pv.numpy_to_texture(self._downscale(h_image))
        actor = self.plotter.add_mesh(h_mesh, texture=h_tex, smooth_shading=False)
        self._mesh_actors.append(actor)

        # — Display frames as semi-transparent textured planes —
        if display_frames:
            self._add_orthogonal_display_frames(
                display_frames, W, H, D, depth,
                initial_frame=initial_frame, last_frame=last_frame,
            )

        # Use the standard 3/4 view (front-facing) so the first frame faces the camera
        self._reset_camera()
        self._apply_opacity()

    def _add_orthogonal_display_frames(self, display_frames, W, H, D,
                                        total_frames, initial_frame=0,
                                        last_frame=None):
        """Add semi-transparent frame planes at proportional Z positions."""
        if last_frame is None:
            last_frame = initial_frame + total_frames - 1
        frame_span = max(1, last_frame - initial_frame)

        for frame_idx, frame_img in display_frames.items():
            # Z position proportional to frame index within the full processed range
            z = D * (frame_idx - initial_frame) / frame_span

            # Flip horizontally to match camera viewing convention
            flipped = np.fliplr(frame_img)

            verts = np.array([
                [0, 0, z], [W, 0, z], [W, H, z], [0, H, z],
            ], dtype=np.float32)
            faces = np.array([4, 0, 1, 2, 3], dtype=np.int32)
            uvs = np.array([
                [0, 0], [1, 0], [1, 1], [0, 1],
            ], dtype=np.float32)
            mesh = pv.PolyData(verts, faces)
            mesh.active_texture_coordinates = uvs
            tex = pv.numpy_to_texture(self._downscale(flipped))
            actor = self.plotter.add_mesh(
                mesh, texture=tex, smooth_shading=False, opacity=0.85,
            )
            self._mesh_actors.append(actor)

    def display_slitscan_oblique(self, oblique_points, frame_width, frame_height, depth):
        """Render a void cuboid with the oblique cutting plane.

        Args:
            oblique_points: list of 4 (x, y, frame_idx) tuples — quad corners
            frame_width: int — video frame width
            frame_height: int — video frame height
            depth: int — total processed frame count
        """
        if not self._capturing:
            self._last_display_call = (
                "display_slitscan_oblique",
                (oblique_points, frame_width, frame_height, depth),
                {},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)
        self._dims = (W, H, D)

        # Draw void cuboid wireframe
        box_verts = np.array([
            [0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0],
            [0, 0, D], [W, 0, D], [W, H, D], [0, H, D],
        ], dtype=np.float32)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        for a, b in edges:
            line = pv.Line(box_verts[a], box_verts[b])
            self.plotter.add_mesh(line, color="#555555", line_width=1)

        # Draw the 4 control points as colored spheres
        colors = ["#ff0000", "#00ff00", "#0000ff", "#ffff00"]  # RGBC
        labels = ["P00 (0,0)", "P10 (1,0)", "P11 (1,1)", "P01 (0,1)"]
        point_actors = []
        for i, (pt, color, label) in enumerate(zip(oblique_points, colors, labels)):
            x, y, frame_idx = pt
            z = D * frame_idx / max(1, depth)
            sphere = pv.Sphere(radius=max(W, H) * 0.015, center=(x, H - y, z))
            actor = self.plotter.add_mesh(sphere, color=color)
            point_actors.append(actor)
            # Add label
            self.plotter.add_point_labels(
                np.array([[x, H - y + max(W, H) * 0.03, z]]),
                [label],
                font_size=10,
                text_color=color,
                point_size=0,
                shape_opacity=0,
            )

        # Build quad surface mesh from the 4 points
        if len(oblique_points) >= 4:
            pts = []
            for pt in oblique_points:
                x, y, frame_idx = pt
                z = D * frame_idx / max(1, depth) if depth > 0 else 0
                # Y flip: frame y=0 is top, 3D y=H is top
                pts.append([x, H - y, z])

            verts = np.array(pts, dtype=np.float32)
            # Two triangles for the quad
            faces = np.array([3, 0, 1, 2, 3, 0, 2, 3], dtype=np.int32)
            uvs = np.array([
                [0, 0], [1, 0], [1, 1], [0, 1],
            ], dtype=np.float32)
            quad_mesh = pv.PolyData(verts, faces)
            quad_mesh.active_texture_coordinates = uvs
            actor = self.plotter.add_mesh(
                quad_mesh, color="#cc4444", opacity=0.35,
                show_edges=True, edge_color="#ff6666",
            )
            self._mesh_actors.append(actor)

        self._mesh_actors.extend(point_actors)
        self._reset_camera()
        self._apply_opacity()

    def display_slitscan_void(self, dimensions, mask_left, mask_right, mask_top,
                               mask_bottom, slit_positions=None):
        """Render void cuboid for vertical/horizontal slitscan.

        Args:
            dimensions: dict {"width", "height", "depth", "mask_type"}
            mask_left/right/top/bottom: insets in pixels
            slit_positions: optional list of slit positions to draw as lines
        """
        if not self._capturing:
            self._last_display_call = (
                "display_slitscan_void",
                (dimensions, mask_left, mask_right, mask_top, mask_bottom),
                {"slit_positions": slit_positions},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(dimensions["width"])
        H = float(dimensions["height"])
        D = float(dimensions.get("depth", 1))
        self._dims = (W, H, D)

        # Wireframe cuboid
        box_verts = np.array([
            [0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0],
            [0, 0, D], [W, 0, D], [W, H, D], [0, H, D],
        ], dtype=np.float32)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        for a, b in edges:
            line = pv.Line(box_verts[a], box_verts[b])
            self.plotter.add_mesh(line, color="#555555", line_width=1)

        # Mask region: semi-transparent plane at Z=0 showing mask bounds
        ml = max(0, mask_left)
        mr = max(0, mask_right)
        mt = max(0, mask_top)
        mb = max(0, mask_bottom)
        mx1 = ml
        mx2 = W - mr
        my1 = mt
        my2 = H - mb

        # Front marker plane (Z=0)
        mask_verts = np.array([
            [mx1, H - my1, 0], [mx2, H - my1, 0],
            [mx2, H - my2, 0], [mx1, H - my2, 0],
        ], dtype=np.float32)
        mask_faces = np.array([4, 0, 1, 2, 3], dtype=np.int32)
        mask_uvs = np.array([
            [0, 0], [1, 0], [1, 1], [0, 1],
        ], dtype=np.float32)
        mask_mesh = pv.PolyData(mask_verts, mask_faces)
        mask_mesh.active_texture_coordinates = mask_uvs
        actor = self.plotter.add_mesh(
            mask_mesh, color="#cc3333", opacity=0.3,
            show_edges=True, edge_color="#ff4444",
        )
        self._mesh_actors.append(actor)

        # Back marker plane (Z=D)
        back_verts = np.array([
            [mx1, H - my1, D], [mx2, H - my1, D],
            [mx2, H - my2, D], [mx1, H - my2, D],
        ], dtype=np.float32)
        back_mesh = pv.PolyData(back_verts, mask_faces)
        back_mesh.active_texture_coordinates = mask_uvs
        actor = self.plotter.add_mesh(
            back_mesh, color="#cc3333", opacity=0.3,
            show_edges=True, edge_color="#ff4444",
        )
        self._mesh_actors.append(actor)

        # Draw connector lines between front and back mask corners
        for i in range(4):
            line = pv.Line(
                [mask_verts[i][0], mask_verts[i][1], 0],
                [back_verts[i][0], back_verts[i][1], D],
            )
            self.plotter.add_mesh(line, color="#884444", line_width=1)

        self._reset_camera()
        self._apply_opacity()

    # ------------------------------------------------------------------
    # Slitscan: Interactive 3D Mask Selector (oblique mode)
    # ------------------------------------------------------------------

    def display_slitscan_mask_selector(self, oblique_points, frame_width,
                                        frame_height, depth, initial_frame=0,
                                        last_frame=None):
        """Show an interactive 3D mask selector for defining the oblique cut plane.

        Four draggable sphere widgets allow the user to position control points
        in (x, y, t) space within the video volume wireframe.

        Args:
            oblique_points: list of 4 (x, y, frame_idx) tuples
            frame_width, frame_height: video frame dimensions
            depth: number of sampled frames (visual Z extent of wireframe)
            initial_frame: absolute start frame index
            last_frame: absolute end frame index
        """
        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)
        self._dims = (W, H, D)

        if last_frame is None:
            last_frame = initial_frame + depth - 1
        frame_span = max(1, last_frame - initial_frame)

        # Store for sphere callbacks
        self._mask_sel_W = W
        self._mask_sel_H = H
        self._mask_sel_D = D
        self._mask_sel_initial = initial_frame
        self._mask_sel_last = last_frame
        self._mask_sel_frame_span = frame_span
        self._mask_sel_points = list(oblique_points)

        # Draw wireframe cuboid
        box_verts = np.array([
            [0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0],
            [0, 0, D], [W, 0, D], [W, H, D], [0, H, D],
        ], dtype=np.float32)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        for a, b in edges:
            line = pv.Line(box_verts[a], box_verts[b])
            self.plotter.add_mesh(line, color="#555555", line_width=1)

        # Build and store the translucent quad for the cut plane
        self._mask_sel_quad_actor = None
        self._update_mask_selector_quad()

        # Add draggable sphere widgets for each control point
        colors_hex = ["#ff4444", "#44ff44", "#4444ff", "#ffff44"]
        colors_rgb = [(1, 0.27, 0.27), (0.27, 1, 0.27), (0.27, 0.27, 1), (1, 1, 0.27)]
        labels = ["P0 (top-left)", "P1 (top-right)", "P2 (bot-right)", "P3 (bot-left)"]
        sphere_radius = max(W, H, D) * 0.02

        self._sphere_widgets = []
        for i, pt in enumerate(oblique_points):
            x, y, frame_idx = pt
            z = D * (frame_idx - initial_frame) / frame_span if frame_span > 0 else 0
            center = (
                float(np.clip(x, 0, W)),
                float(H - np.clip(y, 0, H)),
                float(np.clip(z, 0, D)),
            )

            def make_callback(idx):
                def callback(new_center):
                    self._on_mask_sphere_moved(idx, new_center)
                return callback

            widget = self.plotter.add_sphere_widget(
                make_callback(i),
                center=center,
                radius=sphere_radius,
                color=colors_rgb[i],
                test_callback=False,
            )
            self._sphere_widgets.append(widget)

            # Static label near each sphere
            self.plotter.add_point_labels(
                np.array([[center[0], center[1] + sphere_radius * 2, center[2]]]),
                [labels[i]],
                font_size=9,
                text_color=colors_hex[i],
                point_size=0,
                shape_opacity=0,
            )

        self._reset_camera()

    def _on_mask_sphere_moved(self, point_idx, new_center):
        """Handle a sphere widget being dragged in the 3D mask selector."""
        W = self._mask_sel_W
        H = self._mask_sel_H
        D = self._mask_sel_D
        initial = self._mask_sel_initial
        frame_span = self._mask_sel_frame_span

        # Clamp to cuboid bounds
        x_3d = float(np.clip(new_center[0], 0, W))
        y_3d = float(np.clip(new_center[1], 0, H))
        z_3d = float(np.clip(new_center[2], 0, D))

        # Convert back to (frame_x, frame_y, frame_idx)
        frame_x = x_3d
        frame_y = H - y_3d  # un-flip Y
        frame_idx = initial + (z_3d / D) * frame_span if D > 0 else initial

        self._mask_sel_points[point_idx] = (frame_x, frame_y, frame_idx)

        # Update the translucent quad
        self._update_mask_selector_quad()

        # Emit signal with updated points
        self.oblique_points_changed.emit(
            [tuple(p) for p in self._mask_sel_points]
        )

    def _update_mask_selector_quad(self):
        """Redraw the translucent quad surface for the current mask selector points."""
        if not hasattr(self, '_mask_sel_points') or len(self._mask_sel_points) < 4:
            return
        W = self._mask_sel_W
        H = self._mask_sel_H
        D = self._mask_sel_D
        initial = self._mask_sel_initial
        frame_span = self._mask_sel_frame_span

        # Remove old quad if it exists
        if hasattr(self, '_mask_sel_quad_actor') and self._mask_sel_quad_actor is not None:
            try:
                self.plotter.remove_actor(self._mask_sel_quad_actor)
            except Exception:
                pass

        pts_3d = []
        for pt in self._mask_sel_points:
            x, y, fi = pt
            z = D * (fi - initial) / frame_span if frame_span > 0 else 0
            pts_3d.append([
                float(np.clip(x, 0, W)),
                float(H - np.clip(y, 0, H)),
                float(np.clip(z, 0, D)),
            ])

        verts = np.array(pts_3d, dtype=np.float32)
        faces = np.array([3, 0, 1, 2, 3, 0, 2, 3], dtype=np.int32)
        quad_mesh = pv.PolyData(verts, faces)
        self._mask_sel_quad_actor = self.plotter.add_mesh(
            quad_mesh, color="#cc4444", opacity=0.3,
            show_edges=True, edge_color="#ff6666", line_width=2,
        )
        self.plotter.render()

    # ------------------------------------------------------------------
    # Slitscan: Planar cut 3D preview (H/V with texture)
    # ------------------------------------------------------------------

    def display_slitscan_planar(self, texture_image, scan_direction,
                                 mask_type, frame_width, frame_height, depth,
                                 mask_left=0, mask_right=0,
                                 mask_top=0, mask_bottom=0):
        """Render a textured diagonal plane cut inside a wireframe cuboid.

        The plane sweeps diagonally from one edge of the mask to the other
        across the time axis (Z), creating a diagonal slice through the cube.

        Args:
            texture_image: (H, W, 3) uint8 — the generated slitscan image
            scan_direction: str — "L→R", "R→L", "T→B", "B→T"
            mask_type: "Vertical" or "Horizontal"
            frame_width, frame_height: video resolution
            depth: number of sampled frames
            mask_left/right/top/bottom: border insets
        """
        if not self._capturing:
            self._last_display_call = (
                "display_slitscan_planar",
                (texture_image, scan_direction, mask_type,
                 frame_width, frame_height, depth),
                {"mask_left": mask_left, "mask_right": mask_right,
                 "mask_top": mask_top, "mask_bottom": mask_bottom},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)
        self._dims = (W, H, D)

        # Wireframe cuboid
        box_verts = np.array([
            [0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0],
            [0, 0, D], [W, 0, D], [W, H, D], [0, H, D],
        ], dtype=np.float32)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        for a, b in edges:
            line = pv.Line(box_verts[a], box_verts[b])
            self.plotter.add_mesh(line, color="#555555", line_width=1)

        # Mask region bounds
        my1 = float(mask_top)
        my2 = float(frame_height - mask_bottom)
        mx1 = float(mask_left)
        mx2 = float(frame_width - mask_right)

        # Build a diagonal plane: the slit sweeps from one edge to the other
        # across time (Z axis). We subdivide into a grid for proper texture mapping.
        n_sub = 32
        u_arr = np.linspace(0, 1, n_sub + 1, dtype=np.float32)
        v_arr = np.linspace(0, 1, n_sub + 1, dtype=np.float32)

        if mask_type == "Vertical":
            # Slit sweeps horizontally: at Z=0 slit is at start_x, at Z=D at end_x
            if scan_direction in ("L→R", ""):
                start_x, end_x = mx1, mx2
            else:
                start_x, end_x = mx2, mx1

            # Mirror X to compensate for VTK camera right-vector convention
            # (camera right-vector has negative x, so YZ-plane faces appear mirrored).
            start_x_m = W - start_x
            end_x_m = W - end_x

            # 4 corners of the diagonal plane
            p0 = np.array([start_x_m, H - my1, 0], dtype=np.float32)  # top-near
            p1 = np.array([end_x_m,   H - my1, D], dtype=np.float32)  # top-far
            p2 = np.array([end_x_m,   H - my2, D], dtype=np.float32)  # bot-far
            p3 = np.array([start_x_m, H - my2, 0], dtype=np.float32)  # bot-near
        else:
            # Slit sweeps vertically
            if scan_direction in ("T→B", ""):
                start_y, end_y = my1, my2
            else:
                start_y, end_y = my2, my1

            p0 = np.array([mx1, H - start_y, 0], dtype=np.float32)
            p1 = np.array([mx2, H - start_y, 0], dtype=np.float32)
            p2 = np.array([mx2, H - end_y,   D], dtype=np.float32)
            p3 = np.array([mx1, H - end_y,   D], dtype=np.float32)

        # When time is inverted: reverse the plane's sweep direction
        # AND counter-flip the texture's time axis so the image stays
        # visually unchanged while the plane shifts.
        if self._time_inverted:
            if mask_type == "Vertical":
                start_x, end_x = end_x, start_x
                start_x_m = W - start_x
                end_x_m = W - end_x
                p0 = np.array([start_x_m, H - my1, 0], dtype=np.float32)
                p1 = np.array([end_x_m,   H - my1, D], dtype=np.float32)
                p2 = np.array([end_x_m,   H - my2, D], dtype=np.float32)
                p3 = np.array([start_x_m, H - my2, 0], dtype=np.float32)
                texture_image = np.fliplr(texture_image)
            else:
                start_y, end_y = end_y, start_y
                p0 = np.array([mx1, H - start_y, 0], dtype=np.float32)
                p1 = np.array([mx2, H - start_y, 0], dtype=np.float32)
                p2 = np.array([mx2, H - end_y,   D], dtype=np.float32)
                p3 = np.array([mx1, H - end_y,   D], dtype=np.float32)
                texture_image = np.flipud(texture_image)

        # Subdivide quad into grid mesh
        verts = []
        uvs = []
        for vi in range(n_sub + 1):
            for ui in range(n_sub + 1):
                u, v = u_arr[ui], v_arr[vi]
                pt = ((1 - u) * (1 - v) * p0 + u * (1 - v) * p1
                      + u * v * p2 + (1 - u) * v * p3)
                verts.append(pt)
                uvs.append([u, 1.0 - v])  # flip V for texture orientation
        verts = np.array(verts, dtype=np.float32)
        uvs = np.array(uvs, dtype=np.float32)

        faces = []
        for vi in range(n_sub):
            for ui in range(n_sub):
                i0 = vi * (n_sub + 1) + ui
                i1 = i0 + 1
                i2 = i0 + (n_sub + 1) + 1
                i3 = i0 + (n_sub + 1)
                faces.extend([3, i0, i1, i2])
                faces.extend([3, i0, i2, i3])
        faces = np.array(faces, dtype=np.int32)

        mesh = pv.PolyData(verts, faces)
        mesh.active_texture_coordinates = uvs

        # Correct for camera viewing convention: the camera right-vector has
        # negative x, so XZ-plane faces (horizontal mask) appear horizontally
        # mirrored.  YZ-plane faces (vertical mask) are handled by mirroring
        # the geometry coordinates above.
        tex_src = texture_image
        if mask_type == "Horizontal":
            tex_src = np.fliplr(texture_image)
        tex_img = self._downscale(tex_src)
        texture = pv.numpy_to_texture(tex_img)
        actor = self.plotter.add_mesh(mesh, texture=texture, smooth_shading=False)
        self._mesh_actors.append(actor)

        self._reset_camera()
        self._apply_opacity()

    # ------------------------------------------------------------------
    # Slitscan: Oblique 3D preview with texture (post-generation)
    # ------------------------------------------------------------------

    def display_slitscan_oblique_textured(self, texture_image, oblique_points,
                                           frame_width, frame_height, depth,
                                           initial_frame=0, last_frame=None):
        """Render the oblique cut plane with the generated texture.

        Args:
            texture_image: (H, W, 3) uint8 — the generated oblique slitscan
            oblique_points: list of 4 (x, y, frame_idx) tuples
            frame_width, frame_height: video resolution
            depth: number of sampled frames
            initial_frame, last_frame: absolute frame range
        """
        if not self._capturing:
            self._last_display_call = (
                "display_slitscan_oblique_textured",
                (texture_image, oblique_points, frame_width, frame_height, depth),
                {"initial_frame": initial_frame, "last_frame": last_frame},
            )

        self.plotter.clear()
        self._mesh_actors.clear()
        self._opacity_slider.setValue(100)
        self._density_row.setVisible(False)
        self._spacing_row.setVisible(False)
        self._blend_row.setVisible(False)
        self._apply_row.setVisible(False)
        self._fill_data = None

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)
        self._dims = (W, H, D)

        if last_frame is None:
            last_frame = initial_frame + depth - 1
        frame_span = max(1, last_frame - initial_frame)

        # Wireframe cuboid
        box_verts = np.array([
            [0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0],
            [0, 0, D], [W, 0, D], [W, H, D], [0, H, D],
        ], dtype=np.float32)
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        for a, b in edges:
            line = pv.Line(box_verts[a], box_verts[b])
            self.plotter.add_mesh(line, color="#555555", line_width=1)

        # When time is inverted, reverse the Z ordering of the quad
        # corners so the plane sweeps in the opposite direction.
        if self._time_inverted:
            # Reverse the quad: swap top-edge (0,1) with bottom-edge (2,3)
            oblique_points = [
                oblique_points[2], oblique_points[3],
                oblique_points[0], oblique_points[1],
            ]

        # Build textured quad from the 4 oblique points
        if len(oblique_points) >= 4:
            pts_3d = []
            for pt in oblique_points:
                x, y, fi = pt
                z = D * (fi - initial_frame) / frame_span if frame_span > 0 else 0
                pts_3d.append([
                    float(np.clip(x, 0, W)),
                    float(H - np.clip(y, 0, H)),
                    float(np.clip(z, 0, D)),
                ])

            # Subdivide the quad into a grid for better texture mapping
            n_sub = 32
            u_arr = np.linspace(0, 1, n_sub + 1, dtype=np.float32)
            v_arr = np.linspace(0, 1, n_sub + 1, dtype=np.float32)
            p0, p1, p2, p3 = [np.array(p) for p in pts_3d]

            verts = []
            uvs = []
            for vi in range(n_sub + 1):
                for ui in range(n_sub + 1):
                    u, v = u_arr[ui], v_arr[vi]
                    pt = ((1 - u) * (1 - v) * p0 + u * (1 - v) * p1
                          + u * v * p2 + (1 - u) * v * p3)
                    verts.append(pt)
                    uvs.append([u, v])

            verts = np.array(verts, dtype=np.float32)
            uvs = np.array(uvs, dtype=np.float32)

            faces = []
            for vi in range(n_sub):
                for ui in range(n_sub):
                    i0 = vi * (n_sub + 1) + ui
                    i1 = i0 + 1
                    i2 = i0 + (n_sub + 1) + 1
                    i3 = i0 + (n_sub + 1)
                    faces.extend([3, i0, i1, i2])
                    faces.extend([3, i0, i2, i3])
            faces = np.array(faces, dtype=np.int32)

            mesh = pv.PolyData(verts, faces)
            mesh.active_texture_coordinates = uvs

            tex_img = self._downscale(texture_image)
            texture = pv.numpy_to_texture(tex_img)
            actor = self.plotter.add_mesh(mesh, texture=texture, smooth_shading=False)
            self._mesh_actors.append(actor)

        self._reset_camera()
        self._apply_opacity()

    def close(self):
        self.plotter.close()
        super().close()
