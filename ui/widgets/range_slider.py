"""Two-handle range slider for selecting start/end frame range."""

from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QWidget


class RangeSlider(QWidget):
    """A slider with two draggable handles for selecting a range [low, high]."""

    range_changed = Signal(int, int)
    handle_dragged = Signal(int)  # emits the value of whichever handle is being dragged
    shot_selected = Signal(int, int)  # emits (start, end) of the clicked shot segment

    HANDLE_WIDTH = 12
    HANDLE_HEIGHT = 20
    TRACK_HEIGHT = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 100
        self._low = 0
        self._high = 100
        self._dragging = None  # "low", "high", or None
        self._markers = []  # list of int frame indices for cut markers
        self.setMinimumHeight(self.HANDLE_HEIGHT + 4)
        self.setFixedHeight(self.HANDLE_HEIGHT + 4)
        self.setCursor(Qt.PointingHandCursor)

    def set_range(self, minimum, maximum):
        self._minimum = minimum
        self._maximum = max(minimum, maximum)
        self._low = max(self._low, minimum)
        self._high = min(self._high, maximum)
        self.update()

    def set_low(self, value):
        value = max(self._minimum, min(value, self._high))
        if value != self._low:
            self._low = value
            self.update()

    def set_high(self, value):
        value = max(self._low, min(value, self._maximum))
        if value != self._high:
            self._high = value
            self.update()

    def low(self):
        return self._low

    def high(self):
        return self._high

    def set_markers(self, markers):
        """Set cut detection marker positions (list of int frame indices)."""
        self._markers = sorted(markers)
        self.update()

    def markers(self):
        return list(self._markers)

    def _val_to_x(self, value):
        """Map a value to a pixel x-coordinate."""
        span = self._maximum - self._minimum
        if span <= 0:
            return self.HANDLE_WIDTH // 2
        usable = self.width() - self.HANDLE_WIDTH
        return round(self.HANDLE_WIDTH / 2 + (value - self._minimum) / span * usable)

    def _x_to_val(self, x):
        """Map a pixel x-coordinate to a value."""
        usable = self.width() - self.HANDLE_WIDTH
        if usable <= 0:
            return self._minimum
        frac = (x - self.HANDLE_WIDTH // 2) / usable
        frac = max(0.0, min(1.0, frac))
        return round(self._minimum + frac * (self._maximum - self._minimum))

    def _handle_rect(self, value):
        cx = self._val_to_x(value)
        top = (self.height() - self.HANDLE_HEIGHT) // 2
        return QRect(cx - self.HANDLE_WIDTH // 2, top, self.HANDLE_WIDTH, self.HANDLE_HEIGHT)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        mid_y = self.height() // 2
        track_y = mid_y - self.TRACK_HEIGHT // 2

        # Background track
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#3a3a3a")))
        p.drawRoundedRect(
            self.HANDLE_WIDTH // 2, track_y,
            self.width() - self.HANDLE_WIDTH, self.TRACK_HEIGHT,
            2, 2,
        )

        # Selected range highlight
        x_low = self._val_to_x(self._low)
        x_high = self._val_to_x(self._high)
        p.setBrush(QBrush(QColor("#b83030")))
        p.drawRect(x_low, track_y, x_high - x_low, self.TRACK_HEIGHT)

        # Cut detection markers (vertical lines across the track)
        if self._markers:
            marker_pen = QPen(QColor("#ffcc00"), 1)
            p.setPen(marker_pen)
            for m in self._markers:
                if self._minimum <= m <= self._maximum:
                    mx = self._val_to_x(m)
                    p.drawLine(mx, track_y - 3, mx, track_y + self.TRACK_HEIGHT + 3)

        # Handles
        for val, label in [(self._low, "low"), (self._high, "high")]:
            rect = self._handle_rect(val)
            is_active = self._dragging == label
            color = QColor("#ff4444") if is_active else QColor("#cc3333")
            p.setBrush(QBrush(color))
            p.setPen(QPen(QColor("#222222"), 1))
            p.drawRoundedRect(rect, 3, 3)

        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        x = pos.x()

        low_rect = self._handle_rect(self._low)
        high_rect = self._handle_rect(self._high)
        dist_low = abs(x - low_rect.center().x())
        dist_high = abs(x - high_rect.center().x())

        # Pick the closer handle; if they overlap, prefer the one closer to click
        if low_rect.contains(int(x), int(pos.y())) or high_rect.contains(int(x), int(pos.y())):
            self._dragging = "low" if dist_low <= dist_high else "high"
        elif dist_low < dist_high:
            self._dragging = "low"
        else:
            self._dragging = "high"

        self._move_handle(x)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_handle(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = None
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Double-click between markers to select that shot segment."""
        if not self._markers or event.button() != Qt.LeftButton:
            return
        val = self._x_to_val(event.position().x())
        # Build boundaries: [minimum, *markers, maximum]
        bounds = [self._minimum] + self._markers + [self._maximum]
        for i in range(len(bounds) - 1):
            if bounds[i] <= val <= bounds[i + 1]:
                start = bounds[i]
                end = bounds[i + 1]
                self.shot_selected.emit(start, end)
                break

    def _move_handle(self, x):
        val = self._x_to_val(x)
        if self._dragging == "low":
            val = min(val, self._high)
            val = max(val, self._minimum)
            if val != self._low:
                self._low = val
                self.update()
                self.range_changed.emit(self._low, self._high)
                self.handle_dragged.emit(val)
        elif self._dragging == "high":
            val = max(val, self._low)
            val = min(val, self._maximum)
            if val != self._high:
                self._high = val
                self.update()
                self.range_changed.emit(self._low, self._high)
                self.handle_dragged.emit(val)
