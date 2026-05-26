from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QCursor
from PySide6.QtWidgets import QWidget
import numpy as np


class FrameViewer(QWidget):
    """Displays a video frame scaled to fit, with optional mask overlay and drag."""

    # Emitted when the user drags the slice slit: (new_position)
    slit_dragged = Signal(int)
    # Emitted when the user drags the orthogonal slit: (new_position)
    ortho_slit_dragged = Signal(int)
    # Emitted when the user drags a cuboid border edge: (left, right, top, bottom)
    cuboid_border_dragged = Signal(int, int, int, int)
    # Emitted when the user drags the rings center: (cx, cy)
    rings_center_dragged = Signal(int, int)
    # Emitted when the user drags the cylinder center: (cx, cy)
    cylinder_center_dragged = Signal(int, int)
    # Emitted when the user drags the cylinder radius: (radius)
    cylinder_radius_dragged = Signal(int)
    # Emitted when the user drags the slitscan start position: (pos)
    slitscan_start_dragged = Signal(int)
    # Emitted when the user drags the slitscan end position: (pos)
    slitscan_end_dragged = Signal(int)
    # Emitted when eyedropper samples a color: (r, g, b)
    color_sampled = Signal(int, int, int)
    # Emitted when point-prompt mode picks a position: (x, y) in frame coords
    point_sampled = Signal(int, int)

    DRAG_THRESHOLD = 10  # pixels (in widget coords) to detect grab

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._frame_shape = None  # (H, W) of the original frame
        self._overlay_callback = None

        # Mapping between widget coordinates and frame pixel coordinates
        self.frame_rect = QRect()
        self.scale_factor = 1.0

        # Drag state
        self._dragging = None  # None, "slit", "ortho_slit", "left", "right", "top", "bottom",
                               # "rings_center", "cylinder_center", "cylinder_radius"
        self._drag_offset = 0

        # Eyedropper state
        self._eyedropper_active = False
        self._point_prompt_active = False
        self._current_frame = None  # keep reference to current RGB numpy array
        self._mask_overlay = None   # binary mask (H, W) uint8 for extraction preview
        self._mask_chroma_style = False  # if True, show original pixels vs black

        # Mode state for overlay drawing
        self._mode = "Slice"
        self._slice_state = None   # reference to ProjectState
        self._cuboid_state = None  # reference to ProjectState
        self._cylinder_state = None  # reference to ProjectState
        self._rings_state = None   # reference to ProjectState
        self._slittear_state = None  # reference to ProjectState

        # Slit-Tear drawing canvas model
        self._drawing_canvas = None

        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)

    def configure_for_mode(self, mode, project_state):
        """Set up overlay drawing for the given mode."""
        self._mode = mode
        self._slice_state = project_state if mode == "Slice" else None
        self._cuboid_state = project_state if mode == "Cuboid" else None
        self._cylinder_state = project_state if mode == "Cylinder" else None
        self._rings_state = project_state if mode == "Rings" else None
        self._slittear_state = project_state if mode == "Slit-tear" else None
        self._slitscan_state = project_state if mode == "Slit-scan" else None
        self.update()

    def set_frame(self, frame: np.ndarray):
        """Update the displayed frame from an RGB numpy array."""
        h, w, _ = frame.shape
        self._frame_shape = (h, w)
        self._current_frame = frame  # keep reference for eyedropper
        self._mask_overlay = None    # clear extraction mask on new frame
        bytes_per_line = 3 * w
        qimage = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimage.copy())
        self.update()

    def set_overlay_callback(self, callback):
        """Register a function: callback(QPainter, QRect, frame_w, frame_h)."""
        self._overlay_callback = callback
        self.update()

    def clear_overlay(self):
        self._overlay_callback = None
        self.update()

    def widget_to_frame(self, x, y):
        """Convert widget coordinates to frame pixel coordinates."""
        if self.scale_factor == 0:
            return 0, 0
        fx = (x - self.frame_rect.x()) / self.scale_factor
        fy = (y - self.frame_rect.y()) / self.scale_factor
        return fx, fy

    def frame_to_widget(self, fx, fy):
        """Convert frame pixel coordinates to widget coordinates."""
        wx = fx * self.scale_factor + self.frame_rect.x()
        wy = fy * self.scale_factor + self.frame_rect.y()
        return wx, wy

    def paintEvent(self, event):
        if self._pixmap is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Fill letterbox area with interface background colour
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        # Scale pixmap to fit widget while preserving aspect ratio
        widget_w, widget_h = self.width(), self.height()
        pix_w, pix_h = self._pixmap.width(), self._pixmap.height()

        scale_x = widget_w / pix_w
        scale_y = widget_h / pix_h
        self.scale_factor = min(scale_x, scale_y)

        draw_w = int(pix_w * self.scale_factor)
        draw_h = int(pix_h * self.scale_factor)
        draw_x = (widget_w - draw_w) // 2
        draw_y = (widget_h - draw_h) // 2

        self.frame_rect = QRect(draw_x, draw_y, draw_w, draw_h)
        painter.drawPixmap(self.frame_rect, self._pixmap)

        # Draw mode-specific overlay
        if self._frame_shape:
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            if self._mode == "Slice" and self._slice_state:
                self._paint_slice_overlay(painter, fw, fh)
            elif self._mode == "Cuboid" and self._cuboid_state:
                self._paint_cuboid_overlay(painter, fw, fh)
            elif self._mode == "Cylinder" and self._cylinder_state:
                self._paint_cylinder_overlay(painter, fw, fh)
            elif self._mode == "Rings" and self._rings_state:
                self._paint_rings_overlay(painter, fw, fh)
            elif self._mode == "Slit-tear" and self._slittear_state:
                self._paint_slittear_overlay(painter, fw, fh)
            elif self._mode == "Slit-scan" and hasattr(self, '_slitscan_state') and self._slitscan_state:
                self._paint_slitscan_overlay(painter, fw, fh)

        # Custom overlay callback (if set)
        if self._overlay_callback and self._frame_shape:
            self._overlay_callback(
                painter, self.frame_rect,
                self._frame_shape[1], self._frame_shape[0],
            )

        # Extraction mask overlay (semi-transparent red/green)
        if self._mask_overlay is not None and self._frame_shape:
            self._paint_mask_overlay(painter)

        painter.end()

    # --- Slice overlay ---
    def _paint_slice_overlay(self, painter, fw, fh):
        s = self._slice_state
        pos = s.slit_position
        width = s.slit_width
        orientation = s.slit_orientation

        # Primary slit (red)
        if orientation == "Vertical" or getattr(s, "orthogonal_enabled", False):
            x1, y1 = self.frame_to_widget(pos, 0)
            x2, y2 = self.frame_to_widget(pos + width, fh)
            rect = QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))
            painter.fillRect(rect, QColor(255, 0, 0, 80))
            painter.setPen(QPen(QColor(255, 0, 0, 180), 1))
            painter.drawRect(rect)

        if orientation == "Horizontal" and not getattr(s, "orthogonal_enabled", False):
            x1, y1 = self.frame_to_widget(0, pos)
            x2, y2 = self.frame_to_widget(fw, pos + width)
            rect = QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))
            painter.fillRect(rect, QColor(255, 0, 0, 80))
            painter.setPen(QPen(QColor(255, 0, 0, 180), 1))
            painter.drawRect(rect)

        # Orthogonal second slit (blue)
        if getattr(s, "orthogonal_enabled", False):
            ortho_pos = getattr(s, "ortho_position", 0)
            x1, y1 = self.frame_to_widget(0, ortho_pos)
            x2, y2 = self.frame_to_widget(fw, ortho_pos + width)
            rect = QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))
            painter.fillRect(rect, QColor(0, 100, 255, 80))
            painter.setPen(QPen(QColor(0, 100, 255, 180), 1))
            painter.drawRect(rect)

    # --- Cuboid overlay ---
    def _paint_cuboid_overlay(self, painter, fw, fh):
        s = self._cuboid_state
        l, r = s.cuboid_border_left, s.cuboid_border_right
        t, b = s.cuboid_border_top, s.cuboid_border_bottom

        x1, y1 = self.frame_to_widget(l, t)
        x2, y2 = self.frame_to_widget(fw - r, fh - b)

        rect = QRect(int(x1), int(y1), int(x2 - x1), int(y2 - y1))
        # Draw each border line 1px inset so edges at 0 are fully visible
        pen = QPen(QColor(255, 0, 0, 180), 2)
        painter.setPen(pen)
        lx = int(x1) + 1
        rx = int(x2) - 1
        ty = int(y1) + 1
        by = int(y2) - 1
        painter.drawLine(lx, int(y1), lx, int(y2))  # left
        painter.drawLine(rx, int(y1), rx, int(y2))  # right
        painter.drawLine(int(x1), ty, int(x2), ty)  # top
        painter.drawLine(int(x1), by, int(x2), by)  # bottom

    # --- Cylinder overlay ---
    def _paint_cylinder_overlay(self, painter, fw, fh):
        s = self._cylinder_state
        cx = s.cylinder_center_x
        cy = s.cylinder_center_y
        radius = s.cylinder_radius

        wcx, wcy = self.frame_to_widget(cx, cy)
        wr = radius * self.scale_factor

        painter.setPen(QPen(QColor(255, 0, 0, 180), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(int(wcx - wr), int(wcy - wr), int(wr * 2), int(wr * 2))

        # Center crosshair
        cross_size = 10
        painter.setPen(QPen(QColor(255, 0, 0, 200), 2))
        painter.drawLine(int(wcx - cross_size), int(wcy), int(wcx + cross_size), int(wcy))
        painter.drawLine(int(wcx), int(wcy - cross_size), int(wcx), int(wcy + cross_size))

    # --- Rings overlay ---
    def _paint_rings_overlay(self, painter, fw, fh):
        s = self._rings_state
        cx = s.rings_center_x
        cy = s.rings_center_y
        max_radius = min(cx, cy, fw - cx, fh - cy)
        max_radius = max(1, max_radius)

        # Draw concentric rings preview (show 5-8 evenly spaced rings)
        wcx, wcy = self.frame_to_widget(cx, cy)
        num_preview_rings = min(8, max_radius)
        for i in range(1, num_preview_rings + 1):
            r = int(max_radius * i / num_preview_rings)
            wr = r * self.scale_factor
            painter.setPen(QPen(QColor(255, 0, 0, 60), 1))
            painter.drawEllipse(int(wcx - wr), int(wcy - wr), int(wr * 2), int(wr * 2))

        # Draw outermost ring with stronger color
        outer_wr = max_radius * self.scale_factor
        painter.setPen(QPen(QColor(255, 0, 0, 150), 2))
        painter.drawEllipse(int(wcx - outer_wr), int(wcy - outer_wr),
                            int(outer_wr * 2), int(outer_wr * 2))

        # Draw center crosshair
        cross_size = 10
        painter.setPen(QPen(QColor(255, 0, 0, 200), 2))
        painter.drawLine(int(wcx - cross_size), int(wcy), int(wcx + cross_size), int(wcy))
        painter.drawLine(int(wcx), int(wcy - cross_size), int(wcx), int(wcy + cross_size))

    # --- Slitscan overlay ---
    def _paint_slitscan_overlay(self, painter, fw, fh):
        """Draw red rectangle mask with internal sequence lines or slit position."""
        s = self._slitscan_state
        if s is None:
            return
        mask_type = s.slitscan_mask_type
        if mask_type in ("Vertical", "Horizontal"):
            l = s.slitscan_border_left
            r = s.slitscan_border_right
            t = s.slitscan_border_top
            b = s.slitscan_border_bottom
            is_vertical = mask_type == "Vertical"
            x1, y1 = self.frame_to_widget(l, t)
            x2, y2 = self.frame_to_widget(fw - r, fh - b)
            rx, ry = int(x1), int(y1)
            rw, rh = int(x2 - x1), int(y2 - y1)
            if rw < 2 or rh < 2:
                return

            # Draw border rectangle (red, like cuboid void)
            pen = QPen(QColor(255, 0, 0, 180), 2)
            painter.setPen(pen)
            lx = int(x1) + 1
            rx_edge = int(x2) - 1
            ty = int(y1) + 1
            by = int(y2) - 1
            painter.drawLine(lx, int(y1), lx, int(y2))     # left
            painter.drawLine(rx_edge, int(y1), rx_edge, int(y2))  # right
            painter.drawLine(int(x1), ty, int(x2), ty)     # top
            painter.drawLine(int(x1), by, int(x2), by)     # bottom

            # Draw internal sequence lines (same for all H/V sampling modes)
            num_lines = 6
            inner_pen = QPen(QColor(255, 60, 60, 100), 1)
            painter.setPen(inner_pen)
            for i in range(1, num_lines):
                t_param = i / num_lines
                if is_vertical:
                    line_x = int(x1) + int(rw * t_param)
                    painter.drawLine(line_x, int(y1), line_x, int(y2))
                else:
                    line_y = int(y1) + int(rh * t_param)
                    painter.drawLine(int(x1), line_y, int(x2), line_y)

        elif mask_type == "Oblique":
            painter.setPen(QPen(QColor(255, 255, 0, 200)))
            cx, cy = self.frame_to_widget(fw // 2, fh // 2)
            painter.drawText(
                int(cx) - 120, int(cy),
                "Oblique — use 3D Mask Selector to define cut plane"
            )

    # --- Slit-Tear overlay ---
    def _paint_slittear_overlay(self, painter, fw, fh):
        if self._drawing_canvas is None:
            return
        from ui.widgets.drawing_canvas import LINE_COLORS

        # Draw completed lines
        for i, line in enumerate(self._drawing_canvas.lines):
            self._draw_polyline(painter, line, LINE_COLORS[i % len(LINE_COLORS)], 200)

        # Draw line currently being drawn
        current = self._drawing_canvas.current_line
        if current and len(current) >= 2:
            idx = self._drawing_canvas.line_count
            color = LINE_COLORS[idx % len(LINE_COLORS)]
            self._draw_polyline(painter, current, color, 140)

    def _draw_polyline(self, painter, points, color, alpha):
        """Draw a polyline on the overlay in widget coordinates."""
        pen = QPen(QColor(color.red(), color.green(), color.blue(), alpha), 2)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            x1, y1 = self.frame_to_widget(points[i][0], points[i][1])
            x2, y2 = self.frame_to_widget(points[i + 1][0], points[i + 1][1])
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _paint_mask_overlay(self, painter):
        """Draw extraction mask as a semi-transparent colored overlay.

        Default: green tint on foreground (mask=255), red tint on background.
        Chroma style: original pixels for foreground, darkened for background.
        """
        mask = self._mask_overlay
        if mask is None:
            return

        h, w = mask.shape[:2]
        fg = mask > 127

        if self._mask_chroma_style and self._current_frame is not None:
            # Show original color where selected, darken background to near-black
            frame = self._current_frame
            overlay = np.zeros((h, w, 4), dtype=np.uint8)
            # Background: dark semi-transparent overlay to dim the image
            overlay[~fg] = [0, 0, 0, 200]
            # Foreground: fully transparent (original frame shows through)
            overlay[fg] = [0, 0, 0, 0]
        else:
            # Green/red tint mode for edge detect / AI segment
            overlay = np.zeros((h, w, 4), dtype=np.uint8)
            # Foreground: green tint at 40% opacity
            overlay[fg] = [0, 200, 0, 100]
            # Background: red tint at 30% opacity
            overlay[~fg] = [200, 0, 0, 75]

        # Convert to QImage and draw onto the frame rect
        qimg = QImage(overlay.data, w, h, w * 4, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        painter.drawPixmap(self.frame_rect, pixmap)

    def set_drawing_canvas(self, canvas):
        """Set the DrawingCanvas model for Slit-tear mode."""
        self._drawing_canvas = canvas

    def activate_eyedropper(self):
        """Enter eyedropper mode: next click samples a pixel color."""
        self._eyedropper_active = True
        self.setCursor(Qt.CrossCursor)

    def activate_point_prompt(self):
        """Enter point-prompt mode: next click picks an (x, y) extraction point."""
        self._point_prompt_active = True
        self.setCursor(Qt.CrossCursor)

    def current_frame(self):
        """Return the current displayed frame as RGB numpy array, or None."""
        return self._current_frame

    def show_mask_overlay(self, mask, chroma_style=False):
        """Show a semi-transparent mask overlay on the current frame.

        Args:
            mask: binary uint8 (H, W) — 255 = foreground, 0 = background
                  or None to clear the overlay.
            chroma_style: if True, show original pixels for foreground and
                          darken background to near-black instead of green/red.
        """
        self._mask_overlay = mask
        self._mask_chroma_style = chroma_style
        self.update()

    # --- Mouse interaction for dragging ---
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self._frame_shape is None:
            return
        mx, my = event.position().x(), event.position().y()
        fx, fy = self.widget_to_frame(mx, my)

        # Eyedropper mode: sample the pixel color and exit
        if self._eyedropper_active:
            self._eyedropper_active = False
            self.setCursor(Qt.ArrowCursor)
            if self._current_frame is not None:
                ix, iy = int(fx), int(fy)
                h, w = self._frame_shape
                if 0 <= ix < w and 0 <= iy < h:
                    r, g, b = self._current_frame[iy, ix, :3]
                    self.color_sampled.emit(int(r), int(g), int(b))
            return

        # Point-prompt mode: emit frame coordinates and exit
        if self._point_prompt_active:
            self._point_prompt_active = False
            self.setCursor(Qt.ArrowCursor)
            if self._current_frame is not None:
                ix, iy = int(fx), int(fy)
                h, w = self._frame_shape
                ix = max(0, min(ix, w - 1))
                iy = max(0, min(iy, h - 1))
                self.point_sampled.emit(ix, iy)
            return

        thresh = self.DRAG_THRESHOLD / self.scale_factor if self.scale_factor > 0 else 10

        if self._mode == "Slice" and self._slice_state:
            s = self._slice_state
            pos = s.slit_position
            w = s.slit_width
            ortho_on = getattr(s, "orthogonal_enabled", False)

            if ortho_on:
                # In orthogonal mode: vertical slit (red) + horizontal slit (blue)
                ortho_pos = getattr(s, "ortho_position", 0)
                # Check horizontal slit (blue) first (narrower grab area)
                if abs(fy - (ortho_pos + w / 2)) < (w / 2 + thresh):
                    self._dragging = "ortho_slit"
                    self._drag_offset = fy - ortho_pos
                elif abs(fx - (pos + w / 2)) < (w / 2 + thresh):
                    self._dragging = "slit"
                    self._drag_offset = fx - pos
            elif s.slit_orientation == "Vertical":
                if abs(fx - (pos + w / 2)) < (w / 2 + thresh):
                    self._dragging = "slit"
                    self._drag_offset = fx - pos
            else:
                if abs(fy - (pos + w / 2)) < (w / 2 + thresh):
                    self._dragging = "slit"
                    self._drag_offset = fy - pos

        elif self._mode == "Cuboid" and self._cuboid_state:
            s = self._cuboid_state
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            l, r, t, b = s.cuboid_border_left, s.cuboid_border_right, s.cuboid_border_top, s.cuboid_border_bottom
            right_edge = fw - r
            bottom_edge = fh - b

            # Check each edge (prioritize closest)
            if abs(fx - l) < thresh and t <= fy <= bottom_edge:
                self._dragging = "left"
            elif abs(fx - right_edge) < thresh and t <= fy <= bottom_edge:
                self._dragging = "right"
            elif abs(fy - t) < thresh and l <= fx <= right_edge:
                self._dragging = "top"
            elif abs(fy - bottom_edge) < thresh and l <= fx <= right_edge:
                self._dragging = "bottom"
            elif l < fx < right_edge and t < fy < bottom_edge:
                # Inside rectangle but not near an edge → move whole mask
                self._dragging = "cuboid_move"
                self._drag_start_fx = fx
                self._drag_start_fy = fy
                self._drag_start_borders = (l, r, t, b)

        elif self._mode == "Rings" and self._rings_state:
            s = self._rings_state
            cx, cy = s.rings_center_x, s.rings_center_y
            dist = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
            if dist < thresh * 3:  # generous grab area for center
                self._dragging = "rings_center"

        elif self._mode == "Cylinder" and self._cylinder_state:
            s = self._cylinder_state
            cx, cy = s.cylinder_center_x, s.cylinder_center_y
            radius = s.cylinder_radius
            dist = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
            # Check if near the circle edge (for radius drag)
            if abs(dist - radius) < thresh:
                self._dragging = "cylinder_radius"
            # Check if near center (for center drag)
            elif dist < thresh * 3:
                self._dragging = "cylinder_center"

        elif self._mode == "Slit-scan" and self._slitscan_state:
            s = self._slitscan_state
            mask_type = s.slitscan_mask_type
            if mask_type not in ("Vertical", "Horizontal"):
                return
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            l, r, t, b = s.slitscan_border_left, s.slitscan_border_right, s.slitscan_border_top, s.slitscan_border_bottom
            right_edge = fw - r
            bottom_edge = fh - b
            if abs(fx - l) < thresh and t <= fy <= bottom_edge:
                self._dragging = "slitscan_left"
            elif abs(fx - right_edge) < thresh and t <= fy <= bottom_edge:
                self._dragging = "slitscan_right"
            elif abs(fy - t) < thresh and l <= fx <= right_edge:
                self._dragging = "slitscan_top"
            elif abs(fy - bottom_edge) < thresh and l <= fx <= right_edge:
                self._dragging = "slitscan_bottom"
            elif l < fx < right_edge and t < fy < bottom_edge:
                self._dragging = "slitscan_move"
                self._drag_start_fx = fx
                self._drag_start_fy = fy
                self._drag_start_borders = (l, r, t, b)

        elif self._mode == "Slit-tear" and self._drawing_canvas is not None:
            # Start drawing a new line
            fh_max, fw_max = self._frame_shape
            if 0 <= fx < fw_max and 0 <= fy < fh_max:
                self._dragging = "slittear_draw"
                self._drawing_canvas.start_line(fx, fy)
                self.update()

    def mouseMoveEvent(self, event):
        mx, my = event.position().x(), event.position().y()
        fx, fy = self.widget_to_frame(mx, my)

        if self._dragging is None:
            self._update_cursor(fx, fy)
            return

        if self._mode == "Slice" and self._dragging == "slit":
            s = self._slice_state
            ortho_on = getattr(s, "orthogonal_enabled", False)
            if ortho_on or s.slit_orientation == "Vertical":
                new_pos = int(fx - self._drag_offset)
                max_pos = self._frame_shape[1] - s.slit_width
            else:
                new_pos = int(fy - self._drag_offset)
                max_pos = self._frame_shape[0] - s.slit_width
            new_pos = max(0, min(new_pos, max_pos))
            s.slit_position = new_pos
            self.slit_dragged.emit(new_pos)
            self.update()

        elif self._mode == "Slice" and self._dragging == "ortho_slit":
            s = self._slice_state
            new_pos = int(fy - self._drag_offset)
            max_pos = self._frame_shape[0] - s.slit_width
            new_pos = max(0, min(new_pos, max_pos))
            s.ortho_position = new_pos
            self.ortho_slit_dragged.emit(new_pos)
            self.update()

        elif self._mode == "Cuboid" and self._cuboid_state:
            s = self._cuboid_state
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            l, r, t, b = s.cuboid_border_left, s.cuboid_border_right, s.cuboid_border_top, s.cuboid_border_bottom
            min_mask = 10

            if self._dragging == "cuboid_move":
                # Move entire rectangle by delta from drag start
                ol, or_, ot, ob = self._drag_start_borders
                dx = int(fx - self._drag_start_fx)
                dy = int(fy - self._drag_start_fy)
                nl = ol + dx
                nr = or_ - dx
                nt = ot + dy
                nb = ob - dy
                # Clamp so rectangle stays in frame
                if nl < 0:
                    nr += nl; nl = 0
                if nr < 0:
                    nl += nr; nr = 0
                if nt < 0:
                    nb += nt; nt = 0
                if nb < 0:
                    nt += nb; nb = 0
                l, r, t, b = nl, nr, nt, nb
            elif self._dragging == "left":
                l = max(0, min(int(fx), fw - r - min_mask))
            elif self._dragging == "right":
                r = max(0, min(int(fw - fx), fw - l - min_mask))
            elif self._dragging == "top":
                t = max(0, min(int(fy), fh - b - min_mask))
            elif self._dragging == "bottom":
                b = max(0, min(int(fh - fy), fh - t - min_mask))

            s.cuboid_border_left = l
            s.cuboid_border_right = r
            s.cuboid_border_top = t
            s.cuboid_border_bottom = b
            self.cuboid_border_dragged.emit(l, r, t, b)
            self.update()

        elif self._mode == "Rings" and self._dragging == "rings_center":
            s = self._rings_state
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            new_cx = max(1, min(int(fx), fw - 2))
            new_cy = max(1, min(int(fy), fh - 2))
            s.rings_center_x = new_cx
            s.rings_center_y = new_cy
            self.rings_center_dragged.emit(new_cx, new_cy)
            self.update()

        elif self._mode == "Cylinder" and self._cylinder_state:
            s = self._cylinder_state
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            if self._dragging == "cylinder_center":
                new_cx = max(1, min(int(fx), fw - 2))
                new_cy = max(1, min(int(fy), fh - 2))
                s.cylinder_center_x = new_cx
                s.cylinder_center_y = new_cy
                self.cylinder_center_dragged.emit(new_cx, new_cy)
                self.update()
            elif self._dragging == "cylinder_radius":
                cx, cy = s.cylinder_center_x, s.cylinder_center_y
                new_r = int(((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5)
                max_r = min(fw, fh) // 2
                new_r = max(2, min(new_r, max_r))
                s.cylinder_radius = new_r
                self.cylinder_radius_dragged.emit(new_r)
                self.update()

        elif self._mode == "Slit-scan" and self._slitscan_state and self._dragging in ("slitscan_left", "slitscan_right", "slitscan_top", "slitscan_bottom", "slitscan_move"):
            s = self._slitscan_state
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            l, r, t, b = s.slitscan_border_left, s.slitscan_border_right, s.slitscan_border_top, s.slitscan_border_bottom
            min_mask = 10
            if self._dragging == "slitscan_move":
                ol, or_, ot, ob = self._drag_start_borders
                dx = int(fx - self._drag_start_fx)
                dy = int(fy - self._drag_start_fy)
                nl = ol + dx
                nr = or_ - dx
                nt = ot + dy
                nb = ob - dy
                if nl < 0: nr += nl; nl = 0
                if nr < 0: nl += nr; nr = 0
                if nt < 0: nb += nt; nt = 0
                if nb < 0: nt += nb; nb = 0
                l, r, t, b = nl, nr, nt, nb
            elif self._dragging == "slitscan_left":
                l = max(0, min(int(fx), fw - r - min_mask))
            elif self._dragging == "slitscan_right":
                r = max(0, min(int(fw - fx), fw - l - min_mask))
            elif self._dragging == "slitscan_top":
                t = max(0, min(int(fy), fh - b - min_mask))
            elif self._dragging == "slitscan_bottom":
                b = max(0, min(int(fh - fy), fh - t - min_mask))
            s.slitscan_border_left = l
            s.slitscan_border_right = r
            s.slitscan_border_top = t
            s.slitscan_border_bottom = b
            self.cuboid_border_dragged.emit(l, r, t, b)
            self.update()

        elif self._dragging == "slittear_draw" and self._drawing_canvas is not None:
            self._drawing_canvas.add_point(fx, fy)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._dragging == "slittear_draw" and self._drawing_canvas is not None:
                self._drawing_canvas.end_line()
                self.update()
            self._dragging = None
            self.setCursor(Qt.ArrowCursor)

    def _update_cursor(self, fx, fy):
        """Change cursor when hovering near draggable elements."""
        if self._frame_shape is None:
            return
        thresh = self.DRAG_THRESHOLD / self.scale_factor if self.scale_factor > 0 else 10

        if self._mode == "Slice" and self._slice_state:
            s = self._slice_state
            pos = s.slit_position
            w = s.slit_width
            ortho_on = getattr(s, "orthogonal_enabled", False)

            if ortho_on:
                ortho_pos = getattr(s, "ortho_position", 0)
                if abs(fy - (ortho_pos + w / 2)) < (w / 2 + thresh):
                    self.setCursor(Qt.SizeVerCursor)
                    return
                if abs(fx - (pos + w / 2)) < (w / 2 + thresh):
                    self.setCursor(Qt.SizeHorCursor)
                    return
            elif s.slit_orientation == "Vertical":
                if abs(fx - (pos + w / 2)) < (w / 2 + thresh):
                    self.setCursor(Qt.SizeHorCursor)
                    return
            else:
                if abs(fy - (pos + w / 2)) < (w / 2 + thresh):
                    self.setCursor(Qt.SizeVerCursor)
                    return

        elif self._mode == "Cuboid" and self._cuboid_state:
            s = self._cuboid_state
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            l = s.cuboid_border_left
            right_edge = fw - s.cuboid_border_right
            t = s.cuboid_border_top
            bottom_edge = fh - s.cuboid_border_bottom

            if abs(fx - l) < thresh and t <= fy <= bottom_edge:
                self.setCursor(Qt.SizeHorCursor)
                return
            if abs(fx - right_edge) < thresh and t <= fy <= bottom_edge:
                self.setCursor(Qt.SizeHorCursor)
                return
            if abs(fy - t) < thresh and l <= fx <= right_edge:
                self.setCursor(Qt.SizeVerCursor)
                return
            if abs(fy - bottom_edge) < thresh and l <= fx <= right_edge:
                self.setCursor(Qt.SizeVerCursor)
                return
            if l < fx < right_edge and t < fy < bottom_edge:
                self.setCursor(Qt.SizeAllCursor)
                return

        elif self._mode == "Rings" and self._rings_state:
            s = self._rings_state
            cx, cy = s.rings_center_x, s.rings_center_y
            dist = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
            if dist < thresh * 3:
                self.setCursor(Qt.SizeAllCursor)
                return

        elif self._mode == "Cylinder" and self._cylinder_state:
            s = self._cylinder_state
            cx, cy = s.cylinder_center_x, s.cylinder_center_y
            radius = s.cylinder_radius
            dist = ((fx - cx) ** 2 + (fy - cy) ** 2) ** 0.5
            if abs(dist - radius) < thresh:
                self.setCursor(Qt.SizeHorCursor)
                return
            elif dist < thresh * 3:
                self.setCursor(Qt.SizeAllCursor)
                return

        elif self._mode == "Slit-scan" and self._slitscan_state:
            s = self._slitscan_state
            if s.slitscan_mask_type not in ("Vertical", "Horizontal"):
                self.setCursor(Qt.ArrowCursor)
                return
            fw, fh = self._frame_shape[1], self._frame_shape[0]
            l = s.slitscan_border_left
            right_edge = fw - s.slitscan_border_right
            t = s.slitscan_border_top
            bottom_edge = fh - s.slitscan_border_bottom
            if abs(fx - l) < thresh and t <= fy <= bottom_edge:
                self.setCursor(Qt.SizeHorCursor)
                return
            if abs(fx - right_edge) < thresh and t <= fy <= bottom_edge:
                self.setCursor(Qt.SizeHorCursor)
                return
            if abs(fy - t) < thresh and l <= fx <= right_edge:
                self.setCursor(Qt.SizeVerCursor)
                return
            if abs(fy - bottom_edge) < thresh and l <= fx <= right_edge:
                self.setCursor(Qt.SizeVerCursor)
                return
            if l < fx < right_edge and t < fy < bottom_edge:
                self.setCursor(Qt.SizeAllCursor)
                return

        elif self._mode == "Slit-tear":
            # Always show crosshair in slit-tear mode to indicate drawing
            self.setCursor(Qt.CrossCursor)
            return

        self.setCursor(Qt.ArrowCursor)
