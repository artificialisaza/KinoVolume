from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.range_slider import RangeSlider


class FrameScrubber(QWidget):
    """Navigation slider with frame range and sampling controls.

    The range slider has two handles that set the initial and last frame
    for generation.  Dragging either handle also displays that frame in
    the preview.
    """

    frame_requested = Signal(int)
    range_changed = Signal(int, int)
    sampling_changed = Signal(int)
    prev_cut_requested = Signal()
    next_cut_requested = Signal()
    shot_selected = Signal(int, int)  # (start, end) from double-click on a shot

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_count = 0
        self._fps = 30.0
        self._syncing = False  # guard against recursive updates
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)
        self._debounce_timer.timeout.connect(self._emit_frame_requested)
        self._pending_frame = 0

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 6)
        layout.setSpacing(4)

        # --- Range slider row ---
        self.slider = RangeSlider()
        self.slider.range_changed.connect(self._on_slider_range_changed)
        self.slider.handle_dragged.connect(self._on_handle_dragged)
        self.slider.shot_selected.connect(self._on_shot_selected)
        layout.addWidget(self.slider)

        # --- Info row ---
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self.frame_label = QLabel("Frame 0 / 0")
        self.frame_label.setMinimumWidth(140)
        info_row.addWidget(self.frame_label)

        self.timecode_label = QLabel("00:00.00")
        info_row.addWidget(self.timecode_label)

        info_row.addStretch()

        # Initial frame
        start_label = QLabel("Start:")
        start_label.setToolTip("First frame to include in generation")
        info_row.addWidget(start_label)
        self.initial_spin = QSpinBox()
        self.initial_spin.setRange(0, 0)
        self.initial_spin.setFixedWidth(70)
        self.initial_spin.setToolTip("First frame to include in generation")
        self.initial_spin.setKeyboardTracking(False)
        self.initial_spin.editingFinished.connect(
            lambda: self._on_spin_finished("initial")
        )
        info_row.addWidget(self.initial_spin)

        # Last frame
        end_label = QLabel("End:")
        end_label.setToolTip("Last frame to include in generation")
        info_row.addWidget(end_label)
        self.last_spin = QSpinBox()
        self.last_spin.setRange(0, 0)
        self.last_spin.setFixedWidth(70)
        self.last_spin.setToolTip("Last frame to include in generation")
        self.last_spin.setKeyboardTracking(False)
        self.last_spin.editingFinished.connect(
            lambda: self._on_spin_finished("last")
        )
        info_row.addWidget(self.last_spin)

        # Sampling rate
        skip_label = QLabel("Skip:")
        skip_label.setToolTip(
            "Process every Nth frame. 1 = all frames, "
            "2 = every other frame, 10 = every 10th frame.\n"
            "Higher values reduce processing time and memory usage."
        )
        info_row.addWidget(skip_label)
        self.sampling_spin = QSpinBox()
        self.sampling_spin.setRange(1, 1000)
        self.sampling_spin.setValue(1)
        self.sampling_spin.setFixedWidth(80)
        self.sampling_spin.setToolTip(
            "Process every Nth frame. 1 = all frames, "
            "2 = every other frame, 10 = every 10th frame.\n"
            "Higher values reduce processing time and memory usage."
        )
        self.sampling_spin.valueChanged.connect(
            lambda v: self.sampling_changed.emit(v)
        )
        info_row.addWidget(self.sampling_spin)

        # Prev / Next Cut buttons

        # Cut detection buttons (hidden for now)
        self.prev_cut_btn = QPushButton("◀ Prev Cut")
        self.prev_cut_btn.setToolTip(
            "Search backward from the current frame for the nearest scene cut."
        )
        self.prev_cut_btn.setFixedWidth(80)
        self.prev_cut_btn.clicked.connect(self.prev_cut_requested)
        self.prev_cut_btn.setVisible(False)
        info_row.addWidget(self.prev_cut_btn)

        self.next_cut_btn = QPushButton("Next Cut ▶")
        self.next_cut_btn.setToolTip(
            "Search forward from the current frame for the nearest scene cut."
        )
        self.next_cut_btn.setFixedWidth(80)
        self.next_cut_btn.clicked.connect(self.next_cut_requested)
        self.next_cut_btn.setVisible(False)
        info_row.addWidget(self.next_cut_btn)

        layout.addLayout(info_row)

    def configure(self, frame_count: int, fps: float):
        """Set up scrubber for a new video."""
        self._frame_count = frame_count
        self._fps = fps if fps > 0 else 30.0

        max_frame = max(0, frame_count - 1)

        self._syncing = True
        self.slider.set_range(0, max_frame)
        self.slider.set_low(0)
        self.slider.set_high(max_frame)
        self.slider.set_markers([])  # clear previous cut markers
        self.initial_spin.setRange(0, max_frame)
        self.initial_spin.setValue(0)
        self.last_spin.setRange(0, max_frame)
        self.last_spin.setValue(max_frame)
        self._syncing = False

        self._update_labels(0)
        self.frame_requested.emit(0)
        self.range_changed.emit(0, max_frame)

    # --- slider → spinboxes ---

    def _on_slider_range_changed(self, low, high):
        """Called when either slider handle moves."""
        if self._syncing:
            return
        self._syncing = True
        self.initial_spin.setValue(low)
        self.last_spin.setValue(high)
        self._syncing = False
        self.range_changed.emit(low, high)

    def _on_handle_dragged(self, value):
        """Show the frame under the handle being dragged."""
        self._update_labels(value)
        self._pending_frame = value
        self._debounce_timer.start()

    # --- spinboxes → slider ---

    def _on_spin_finished(self, source="initial"):
        """Called when a spinbox value is confirmed (Enter or focus lost)."""
        if self._syncing:
            return
        initial = self.initial_spin.value()
        last = self.last_spin.value()
        # Enforce initial < last
        if initial >= last:
            self._syncing = True
            if source == "initial":
                last = min(initial + 1, self.last_spin.maximum())
                self.last_spin.setValue(last)
            else:
                initial = max(last - 1, 0)
                self.initial_spin.setValue(initial)
            self._syncing = False
        self._syncing = True
        self.slider.set_low(initial)
        self.slider.set_high(last)
        self._syncing = False
        self.range_changed.emit(initial, last)
        # Show the frame that the user just edited
        value = initial if source == "initial" else last
        self._update_labels(value)
        self._pending_frame = value
        self._debounce_timer.start()

    def _emit_frame_requested(self):
        self.frame_requested.emit(self._pending_frame)

    def _update_labels(self, frame_index):
        self.frame_label.setText(
            f"Frame {frame_index} / {self._frame_count - 1}"
        )
        if self._fps > 0:
            total_seconds = frame_index / self._fps
            minutes = int(total_seconds) // 60
            secs = total_seconds % 60
            self.timecode_label.setText(f"{minutes:02d}:{secs:05.2f}")

    def set_cut_markers(self, markers):
        """Display cut detection markers on the range slider."""
        self.slider.set_markers(markers)

    def clear_cut_markers(self):
        """Remove all cut markers from the range slider."""
        self.slider.set_markers([])

    def _on_shot_selected(self, start, end):
        """When user double-clicks a shot segment, set range to that shot."""
        self._syncing = True
        self.slider.set_low(start)
        self.slider.set_high(end)
        self.initial_spin.setValue(start)
        self.last_spin.setValue(end)
        self._syncing = False
        self.range_changed.emit(start, end)
        self.shot_selected.emit(start, end)
        # Show the first frame of the selected shot
        self._update_labels(start)
        self._pending_frame = start
        self._debounce_timer.start()
