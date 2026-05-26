"""Drawing canvas data model for slit-tear mode.

Stores polylines drawn by the user in frame coordinates.
Provides rasterization (Bresenham) for extracting pixel strips.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


# Auto-assigned colors for drawn lines
LINE_COLORS = [
    QColor(255, 60, 60),     # red
    QColor(60, 120, 255),    # blue
    QColor(60, 200, 60),     # green
    QColor(255, 255, 60),    # yellow
    QColor(60, 255, 255),    # cyan
    QColor(255, 60, 255),    # magenta
    QColor(255, 160, 40),    # orange
    QColor(160, 100, 255),   # purple
]


class DrawingCanvas(QObject):
    """Model for polylines drawn on the video frame.

    Each line is a list of (x, y) tuples in frame-pixel coordinates.
    """

    lines_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines = []          # completed polylines: list of list of (x, y)
        self._current_line = None  # line being drawn right now

    # ── public properties ─────────────────────────────────────────

    @property
    def lines(self):
        return list(self._lines)

    @property
    def current_line(self):
        return self._current_line

    @property
    def line_count(self):
        return len(self._lines)

    def get_color(self, index):
        return LINE_COLORS[index % len(LINE_COLORS)]

    # ── drawing API (called from FrameViewer mouse events) ────────

    def start_line(self, x, y):
        """Begin a new polyline at frame coordinate (x, y)."""
        self._current_line = [(int(x), int(y))]

    def add_point(self, x, y):
        """Append a point to the line being drawn."""
        if self._current_line is not None:
            self._current_line.append((int(x), int(y)))

    def end_line(self):
        """Finish the current line and store it."""
        if self._current_line and len(self._current_line) >= 2:
            self._lines.append(self._current_line)
            self._current_line = None
            self.lines_changed.emit()
        else:
            self._current_line = None

    # ── editing API ───────────────────────────────────────────────

    def undo(self):
        """Remove the last completed line."""
        if self._lines:
            self._lines.pop()
            self.lines_changed.emit()

    def clear(self):
        """Remove all lines."""
        self._lines.clear()
        self._current_line = None
        self.lines_changed.emit()

    # ── rasterization ─────────────────────────────────────────────

    @staticmethod
    def bresenham(x0, y0, x1, y1):
        """Bresenham's line algorithm — returns ordered list of (x, y)."""
        points = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            points.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
        return points

    @staticmethod
    def rasterize_polyline(points):
        """Convert a polyline (list of (x, y)) to ordered pixel coordinates.

        Adjacent duplicate pixels are removed.
        """
        if not points:
            return []
        if len(points) == 1:
            return [(int(points[0][0]), int(points[0][1]))]

        all_pixels = []
        for i in range(len(points) - 1):
            x0, y0 = int(points[i][0]), int(points[i][1])
            x1, y1 = int(points[i + 1][0]), int(points[i + 1][1])
            segment = DrawingCanvas.bresenham(x0, y0, x1, y1)
            # Skip first pixel of segment if it duplicates the last pixel
            if all_pixels and segment and segment[0] == all_pixels[-1]:
                segment = segment[1:]
            all_pixels.extend(segment)
        return all_pixels

    def rasterize_all(self):
        """Rasterize all completed lines.

        Returns a list of pixel-lists, one per line.
        """
        result = []
        for line in self._lines:
            pixels = self.rasterize_polyline(line)
            if pixels:
                result.append(pixels)
        return result
