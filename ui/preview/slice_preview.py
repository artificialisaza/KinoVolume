"""2D image viewer for slice output and unfolded cuboid with fit/1:1/fill modes,
zoom, pan, rotate, background colour picker, snapshot capture, and per-face
visibility toggles."""

import os

import numpy as np
from PIL import Image

from PySide6.QtCore import Qt, QPointF, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.preview_toolbar import PreviewToolbar


def _icon_path(name):
    """Resolve path to a resource icon."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base, "resources", "icons", f"{name}.png")


class SlicePreview(QWidget):
    """Displays a generated slice image or unfolded cuboid faces."""

    FIT = "fit"
    ACTUAL = "1:1"
    FILL = "fill"

    ZOOM_STEP = 1.25

    # Background colour: None → use interface default (#1e1e1e)
    _DEFAULT_BG = QColor("#1e1e1e")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._mode = self.FIT
        self._custom_scale = 1.0
        self._offset = QPointF(0, 0)
        self._drag_start = None
        self._drag_offset = QPointF(0, 0)
        self._bg_color = QColor(self._DEFAULT_BG)
        self._rotation = 0  # 0 / 90 / 180 / 270

        # Capture output directory (set by main_window after generation)
        self._output_dir = None

        # Cuboid unfolded state
        self._face_images = None
        self._face_visible = {"right": True, "top": True, "left": True, "bottom": True}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Canvas area
        self._canvas = _Canvas(self)
        layout.addWidget(self._canvas, 1)

        # Floating toolbar (overlaid on canvas, top-right)
        self._toolbar_widget = PreviewToolbar(self._canvas)
        self._toolbar_widget.set_rotate_visible(True)   # 2D always has rotation
        self._toolbar_widget.set_pan_visible(True)
        self._toolbar_widget.set_bg_visible(False)      # 2D preview: no bg change
        self._toolbar_widget.set_capture_visible(False) # 2D preview: no capture
        self._toolbar_widget.zoom_in_clicked.connect(self._zoom_in)
        self._toolbar_widget.zoom_out_clicked.connect(self._zoom_out)
        self._toolbar_widget.pan_requested.connect(self._pan)
        self._toolbar_widget.rotate_cw_clicked.connect(self._rotate_cw)
        self._toolbar_widget.rotate_ccw_clicked.connect(self._rotate_ccw)

        # Bottom toolbar
        self._bottom_bar = QHBoxLayout()
        self._bottom_bar.setContentsMargins(8, 4, 8, 4)

        # Save button (bottom-left) — saves the current 2D preview image
        self._save_btn = QPushButton("Save")
        self._save_btn.setToolTip("Save the current 2D preview as PNG")
        self._save_btn.setObjectName("previewBarBtn")
        self._save_btn.setFixedWidth(44)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._save_preview)
        self._bottom_bar.addWidget(self._save_btn)

        # View mode buttons
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setToolTip("Scale image to fit within the view")
        self._fit_btn.setObjectName("previewBarBtn")
        self._actual_btn = QPushButton("1:1")
        self._actual_btn.setToolTip("Show image at actual pixel size (drag to pan)")
        self._actual_btn.setObjectName("previewBarBtn")
        self._fill_btn = QPushButton("Fill")
        self._fill_btn.setToolTip("Scale image to fill the view height (drag to pan)")
        self._fill_btn.setObjectName("previewBarBtn")
        for btn in (self._fit_btn, self._actual_btn, self._fill_btn):
            btn.setFixedWidth(40)
        self._fit_btn.clicked.connect(lambda: self._set_mode(self.FIT))
        self._actual_btn.clicked.connect(lambda: self._set_mode(self.ACTUAL))
        self._fill_btn.clicked.connect(lambda: self._set_mode(self.FILL))

        self._bottom_bar.addStretch()
        self._bottom_bar.addWidget(self._fit_btn)
        self._bottom_bar.addWidget(self._actual_btn)
        self._bottom_bar.addWidget(self._fill_btn)

        # Spacer between view buttons and face toggles
        self._bottom_bar.addStretch()

        # Face toggle buttons (right side) — hidden until cuboid mode
        # Behaviour: click one → solo that face; click another → add it;
        # click the only visible one → reset to show all.
        self._face_btns = {}
        for label in ("R", "T", "L", "B"):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedWidth(28)
            btn.setObjectName("faceToggleBtn")
            name = {"R": "right", "T": "top", "L": "left", "B": "bottom"}[label]
            btn.setToolTip(f"Solo / toggle {name} face")
            btn.clicked.connect(lambda _checked, n=name: self._on_face_btn(n))
            self._face_btns[name] = btn
            btn.setVisible(False)
            self._bottom_bar.addWidget(btn)

        # Spacer between face toggles and Flip button
        self._flip_spacer = QWidget()
        self._flip_spacer.setFixedWidth(12)
        self._flip_spacer.setVisible(False)
        self._bottom_bar.addWidget(self._flip_spacer)

        # Auto-flip toggle — hidden until cuboid mode
        self._auto_flip_btn = QPushButton("Flip")
        self._auto_flip_btn.setCheckable(True)
        self._auto_flip_btn.setChecked(True)
        self._auto_flip_btn.setFixedWidth(38)
        self._auto_flip_btn.setObjectName("faceToggleBtn")
        self._auto_flip_btn.setToolTip("Auto-flip faces for continuous unfolded view")
        self._auto_flip_btn.setVisible(False)
        self._auto_flip_btn.clicked.connect(self._on_auto_flip_toggled)
        self._bottom_bar.addWidget(self._auto_flip_btn)

        layout.addLayout(self._bottom_bar)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_output_dir(self, output_dir: str):
        """Tell the preview where to save capture images."""
        self._output_dir = output_dir

    def load_image(self, path):
        """Load and display a single image (slice mode)."""
        self._face_images = None
        self._hide_face_toggles()
        self._rotation = 0
        pil_img = Image.open(path)
        # Composite RGBA over the current background colour so transparency
        # is rendered correctly instead of showing black corners.
        if pil_img.mode == "RGBA":
            bg = self._bg_color
            bg_rgb = (bg.red(), bg.green(), bg.blue())
            background = Image.new("RGB", pil_img.size, bg_rgb)
            background.paste(pil_img, mask=pil_img.split()[3])
            pil_img = background
        else:
            pil_img = pil_img.convert("RGB")
        arr = np.array(pil_img)
        self._set_pixmap_from_array(arr)

    def load_cuboid_faces(self, face_images):
        """Load cuboid face images for unfolded 2D preview.

        face_images: dict name->(H,W,3) uint8 numpy array
        """
        self._face_images = {k: v.copy() for k, v in face_images.items()}
        self._face_visible = {"right": True, "top": True, "left": True, "bottom": True}
        self._show_face_toggles()
        self._rebuild_unfolded()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rebuild_unfolded(self):
        """Compose the visible face strips into one image and display."""
        if self._face_images is None:
            return

        def _to_rgb(img):
            if img.ndim == 3 and img.shape[2] == 4:
                return img[:, :, :3]
            return img

        # Order: Right, Top, Left, Bottom
        # top/bottom: (num_frames, mask_w, C) -> rotate so time = horizontal
        top = np.rot90(_to_rgb(self._face_images["top"]), k=1)
        bottom = np.rot90(_to_rgb(self._face_images["bottom"]), k=1)
        left = _to_rgb(self._face_images["left"])
        right = _to_rgb(self._face_images["right"])

        # Apply continuity flips when auto-flip is enabled
        if self._auto_flip_btn.isChecked():
            bottom = np.flipud(bottom)
            right = np.flipud(right)

        order = [
            ("right", right),
            ("top", top),
            ("left", left),
            ("bottom", bottom),
        ]

        visible = [(n, img) for n, img in order if self._face_visible.get(n, True)]
        if not visible:
            self._set_pixmap_from_array(np.zeros((100, 100, 3), dtype=np.uint8))
            return

        max_w = max(img.shape[1] for _, img in visible)
        separator = np.full((2, max_w, 3), 50, dtype=np.uint8)

        parts = []
        for i, (_name, img) in enumerate(visible):
            if i > 0:
                parts.append(separator)
            if img.shape[1] < max_w:
                pad = np.full((img.shape[0], max_w - img.shape[1], 3), 30, dtype=np.uint8)
                img = np.hstack([img, pad])
            parts.append(img)

        combined = np.vstack(parts)
        self._set_pixmap_from_array(combined)

    def _set_pixmap_from_array(self, arr):
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        arr = np.ascontiguousarray(arr)
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimg.copy())
        self._offset = QPointF(0, 0)
        self._custom_scale = 1.0
        self._save_btn.setVisible(True)
        self._canvas.update()

    def _set_mode(self, mode):
        self._mode = mode
        self._offset = QPointF(0, 0)
        self._custom_scale = 1.0
        self._canvas.update()

    def _zoom_in(self):
        self._mode = self.ACTUAL
        old_scale = self._custom_scale
        self._custom_scale *= self.ZOOM_STEP
        # Scale offset so the viewport centre stays anchored
        ratio = self._custom_scale / old_scale
        self._offset = QPointF(self._offset.x() * ratio, self._offset.y() * ratio)
        self._canvas.update()

    def _zoom_out(self):
        self._mode = self.ACTUAL
        old_scale = self._custom_scale
        new_scale = self._custom_scale / self.ZOOM_STEP
        # Ensure the image stays at least 16 px in its smaller dimension
        if self._pixmap is not None:
            pw, ph = self._pixmap.width(), self._pixmap.height()
            min_dim = min(pw, ph) if min(pw, ph) > 0 else 1
            floor = 16.0 / min_dim
            new_scale = max(new_scale, floor)
        new_scale = max(new_scale, 0.01)
        self._custom_scale = new_scale
        # Scale offset so the viewport centre stays anchored
        ratio = self._custom_scale / old_scale if old_scale > 0 else 1.0
        self._offset = QPointF(self._offset.x() * ratio, self._offset.y() * ratio)
        self._canvas.update()

    def _pan(self, dx: int, dy: int):
        """Pan the view by (dx, dy).  Viewport convention: positive dx = pan view RIGHT
        (image shifts LEFT to reveal content on the right).  Rotation-aware."""
        import math
        if self._mode == self.FIT:
            self._mode = self.ACTUAL  # switch to pannable mode
        # Negate: toolbar emits +step for right, but we want image to move LEFT
        sdx, sdy = -dx, -dy
        # Map the desired screen-space image delta into the rotated offset space
        a = math.radians(self._rotation)
        ca, sa = math.cos(a), math.sin(a)
        self._offset += QPointF(ca * sdx + sa * sdy, -sa * sdx + ca * sdy)
        self._canvas.update()

    def _rotate_cw(self):
        self._rotation = (self._rotation + 90) % 360
        self._offset = QPointF(0, 0)
        self._canvas.update()

    def _rotate_ccw(self):
        self._rotation = (self._rotation - 90) % 360
        self._offset = QPointF(0, 0)
        self._canvas.update()

    def _set_bg_color(self, color):
        """Set preview background.  ``None`` resets to interface default."""
        self._bg_color = QColor(self._DEFAULT_BG) if color is None else color
        self._canvas.update()

    def _capture(self):
        """Save a PNG snapshot of the current canvas to Captures/ subfolder."""
        import datetime
        base_dir = self._output_dir
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser("~"), "Desktop",
                                    "KinoVolume")
        captures_dir = os.path.join(base_dir, "Captures")
        os.makedirs(captures_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(captures_dir, f"capture_{ts}.png")
        pixmap = self._canvas.grab()
        pixmap.save(path, "PNG")

    # ------------------------------------------------------------------
    # Face toggle logic  (solo / add / reset)
    # ------------------------------------------------------------------

    def _on_face_btn(self, name):
        """Handle face button click with solo-first-then-add logic.

        - All visible + click one  → solo that face.
        - Some visible + click hidden one → add it.
        - Click the only visible face → reset: show all.
        """
        all_visible = all(self._face_visible.values())
        currently_visible = self._face_visible[name]
        num_visible = sum(self._face_visible.values())

        if all_visible:
            # Solo: show only the clicked face
            for k in self._face_visible:
                self._face_visible[k] = (k == name)
            # Auto-disable flip when soloing a flipped face
            if name in ("right", "bottom"):
                self._auto_flip_btn.setChecked(False)
            else:
                self._auto_flip_btn.setChecked(True)
        elif currently_visible and num_visible == 1:
            # Only this one is visible → reset to all
            for k in self._face_visible:
                self._face_visible[k] = True
            self._auto_flip_btn.setChecked(True)
        elif not currently_visible:
            # Add this face
            self._face_visible[name] = True
        else:
            # Remove this face (others still visible)
            self._face_visible[name] = False

        self._sync_face_buttons()
        self._rebuild_unfolded()

    def _on_auto_flip_toggled(self):
        """Rebuild the unfolded view when auto-flip is toggled."""
        self._rebuild_unfolded()

    def _sync_face_buttons(self):
        """Update button checked state to match _face_visible."""
        for k, btn in self._face_btns.items():
            btn.setChecked(self._face_visible[k])

    def _show_face_toggles(self):
        for btn in self._face_btns.values():
            btn.setVisible(True)
            btn.setChecked(True)
        self._flip_spacer.setVisible(True)
        self._auto_flip_btn.setVisible(True)
        self._auto_flip_btn.setChecked(True)

    def _hide_face_toggles(self):
        for btn in self._face_btns.values():
            btn.setVisible(False)
        self._flip_spacer.setVisible(False)
        self._auto_flip_btn.setVisible(False)

    def _save_preview(self):
        """Save the current 2D preview pixmap as a timestamped PNG."""
        import datetime
        if self._pixmap is None:
            return
        base_dir = self._output_dir
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser("~"), "Desktop",
                                    "KinoVolume")
        captures_dir = os.path.join(base_dir, "Captures")
        os.makedirs(captures_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(captures_dir, f"preview_2d_{ts}.png")
        self._pixmap.save(path, "PNG")

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._toolbar_widget.reposition()


class _Canvas(QWidget):
    """Internal painting surface for SlicePreview."""

    def __init__(self, preview):
        super().__init__(preview)
        self._preview = preview
        self.setMouseTracking(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._preview._toolbar_widget.reposition()

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF
        p = self._preview
        if p._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Fill background (respects user colour choice)
        bg = p._bg_color
        if bg.alpha() == 0:
            # Transparent: draw a checkerboard pattern
            self._draw_checkerboard(painter)
        else:
            painter.fillRect(self.rect(), bg)

        cw, ch = self.width(), self.height()

        # Apply rotation transform around canvas centre
        rotation = p._rotation
        if rotation:
            painter.translate(cw / 2, ch / 2)
            painter.rotate(rotation)
            painter.translate(-cw / 2, -ch / 2)

        pw, ph = p._pixmap.width(), p._pixmap.height()
        if pw == 0 or ph == 0 or cw == 0 or ch == 0:
            painter.end()
            return

        if p._mode == SlicePreview.FIT:
            scale = min(cw / pw, ch / ph)
        elif p._mode == SlicePreview.FILL:
            scale = max(cw / pw, ch / ph)
        else:  # 1:1
            scale = p._custom_scale

        sw, sh = pw * scale, ph * scale
        x = (cw - sw) / 2 + p._offset.x()
        y = (ch - sh) / 2 + p._offset.y()

        painter.drawPixmap(QRectF(x, y, sw, sh), p._pixmap, QRectF(0, 0, pw, ph))
        painter.end()

    def _draw_checkerboard(self, painter):
        """Draw a grey checkerboard to indicate transparency."""
        from PySide6.QtGui import QBrush
        size = 12
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#555555"))
        painter.setPen(Qt.NoPen)
        dark = QColor("#444444")
        for row in range(0, h // size + 1):
            for col in range(0, w // size + 1):
                if (row + col) % 2 == 0:
                    painter.fillRect(col * size, row * size, size, size, dark)

    def mousePressEvent(self, event):
        p = self._preview
        if event.button() == Qt.LeftButton and p._mode != SlicePreview.FIT:
            p._drag_start = event.position()
            p._drag_offset = QPointF(p._offset)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        p = self._preview
        if p._drag_start is not None:
            delta = event.position() - p._drag_start
            # Rotate the screen-space delta into offset-space so panning
            # tracks the cursor correctly regardless of image rotation.
            import math
            a = math.radians(p._rotation)
            ca, sa = math.cos(a), math.sin(a)
            rdx = ca * delta.x() + sa * delta.y()
            rdy = -sa * delta.x() + ca * delta.y()
            if p._mode == SlicePreview.FILL:
                p._offset = QPointF(p._drag_offset.x() + rdx, 0)
            else:
                p._offset = QPointF(p._drag_offset.x() + rdx,
                                    p._drag_offset.y() + rdy)
            self.update()
        elif p._mode != SlicePreview.FIT:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        p = self._preview
        if event.button() == Qt.LeftButton:
            p._drag_start = None
            if p._mode != SlicePreview.FIT:
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
