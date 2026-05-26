"""Sidebar controls for Slit-tear mode."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class SlitTearControls(QGroupBox):
    """Sidebar panel for the Slit-tear (free-drawing) mode."""

    settings_changed = Signal()
    clear_requested = Signal()
    undo_requested = Signal()

    def __init__(self, project_state, parent=None):
        super().__init__("Slit-tear Parameters", parent)
        self._state = project_state
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Instructions
        info = QLabel("Click and drag on the frame to draw lines.")
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Line width
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Line Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 10)
        self.width_spin.setValue(1)
        self.width_spin.setSuffix(" px")
        self.width_spin.setToolTip(
            "Pixel band width around the drawn path.\n"
            "1 = exactly the drawn pixels.\n"
            "Higher values capture a wider perpendicular band."
        )
        width_row.addWidget(self.width_spin)
        layout.addLayout(width_row)

        # Line list
        layout.addWidget(QLabel("Drawn Lines:"))
        self.line_list = QListWidget()
        self.line_list.setMaximumHeight(140)
        self.line_list.setToolTip("Each drawn line and its pixel count")
        layout.addWidget(self.line_list)

        # Undo / Clear buttons
        btn_row = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setToolTip("Remove the last drawn line (Ctrl+Z)")
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setToolTip("Remove all drawn lines")
        btn_row.addWidget(self.undo_btn)
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

        # Output size info
        self.output_label = QLabel("Output: —")
        self.output_label.setObjectName("infoLabel")
        self.output_label.setWordWrap(True)
        layout.addWidget(self.output_label)

        layout.addStretch()

    def _connect_signals(self):
        self.width_spin.valueChanged.connect(self._on_width_changed)
        self.undo_btn.clicked.connect(self._on_undo)
        self.clear_btn.clicked.connect(self._on_clear)
        self._state.settings_changed.connect(self._update_output_label)

    def _on_width_changed(self, value):
        self._state.slittear_line_width = value
        self.settings_changed.emit()
        self._update_output_label()

    def _on_undo(self):
        self.undo_requested.emit()

    def _on_clear(self):
        self.clear_requested.emit()

    # ── called externally when lines change ───────────────────────

    def update_line_list(self, drawing_canvas):
        """Refresh the line list from the DrawingCanvas model."""
        from ui.widgets.drawing_canvas import DrawingCanvas as DC

        self.line_list.clear()
        rasterized = drawing_canvas.rasterize_all()
        for i, pixels in enumerate(rasterized):
            color = drawing_canvas.get_color(i)
            item = QListWidgetItem(f"Line {i + 1}: {len(pixels)} px")
            item.setForeground(color)
            self.line_list.addItem(item)

        # Sync lines to project state for the processor
        self._state.slittear_lines = drawing_canvas.lines
        self._update_output_label()

    def _update_output_label(self):
        vs = self._state.video_source
        lines = getattr(self._state, "slittear_lines", [])
        if not vs or not lines:
            self.output_label.setText("Output: —")
            return

        from ui.widgets.drawing_canvas import DrawingCanvas

        total_pixels = 0
        for line in lines:
            total_pixels += len(DrawingCanvas.rasterize_polyline(line))

        width = getattr(self._state, "slittear_line_width", 1)
        if width > 1:
            total_pixels *= width

        separators = max(0, len(lines) - 1)
        height = total_pixels + separators

        initial = self._state.initial_frame
        last = self._state.last_frame
        sampling = self._state.sampling_rate
        num_frames = max(1, (last - initial) // sampling + 1)

        self.output_label.setText(
            f"Output: {num_frames} × {height} px\n"
            f"({len(lines)} line{'s' if len(lines) != 1 else ''}, "
            f"{total_pixels} sampled pixels)"
        )
