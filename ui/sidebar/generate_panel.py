import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QLabel,
    QVBoxLayout,
)

from config import MEMORY_WARN_THRESHOLD_MB


class GeneratePanel(QGroupBox):
    """Generate button, progress bar, and cancel control."""

    generation_started = Signal()
    generation_finished = Signal(dict)
    generation_cancelled = Signal()

    def __init__(self, project_state, parent=None):
        super().__init__("Generate", parent)
        self._state = project_state
        self._processor = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Estimate warning (shown when fill mode for large outputs)
        self.estimate_label = QLabel("")
        self.estimate_label.setObjectName("estimateLabel")
        self.estimate_label.setWordWrap(True)
        self.estimate_label.setStyleSheet(
            "color: #d4a017; font-size: 11px; background: transparent;"
        )
        self.estimate_label.setVisible(False)
        layout.addWidget(self.estimate_label)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setObjectName("generateButton")
        self.generate_btn.setToolTip("Start processing the video with current settings")
        layout.addWidget(self.generate_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setToolTip("Stop the current generation")
        layout.addWidget(self.cancel_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("infoLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.generate_btn.clicked.connect(self._on_generate)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self._state.settings_changed.connect(self.update_estimate)
        self._state.video_changed.connect(self.update_estimate)
        self._state.mode_changed.connect(lambda _: self.update_estimate())

    def validate(self):
        """Check prerequisites before generation. Returns True if OK."""
        s = self._state
        if s.video_source is None:
            QMessageBox.critical(self, "Error", "Please load a video first.")
            return False
        if not s.output_dir:
            QMessageBox.critical(self, "Error", "Please select an output directory.")
            return False
        if s.initial_frame >= s.last_frame:
            QMessageBox.critical(
                self, "Error", "Initial frame must be before last frame."
            )
            return False
        return True

    def warn_memory(self):
        """Show warning if estimated memory is high. Returns False to abort."""
        s = self._state
        vs = s.video_source
        num_frames = max(1, (s.last_frame - s.initial_frame) // s.sampling_rate + 1)

        if s.current_mode == "Cuboid":
            mask_w = vs.width - s.cuboid_border_left - s.cuboid_border_right
            mask_h = vs.height - s.cuboid_border_top - s.cuboid_border_bottom
            edges_per_frame = (2 * mask_w + 2 * mask_h) * 3
            estimated_mb = (num_frames * edges_per_frame) / (1024 * 1024)
        elif s.current_mode == "Slice":
            strip_bytes = vs.height * s.slit_width * 3 if s.slit_orientation == "Vertical" else vs.width * s.slit_width * 3
            estimated_mb = (num_frames * strip_bytes) / (1024 * 1024)
        else:
            return True

        if estimated_mb > MEMORY_WARN_THRESHOLD_MB:
            reply = QMessageBox.warning(
                self,
                "High Memory Usage",
                f"Estimated memory: {estimated_mb:.0f} MB.\n\n"
                "Consider increasing the skip value. Continue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            return reply == QMessageBox.Yes
        return True

    def start_with_processor(self, processor):
        """Attach a processor, connect signals, and start it."""
        self._processor = processor
        processor.progress.connect(self._on_progress)
        processor.finished.connect(self._on_finished)
        processor.error.connect(self._on_error)
        processor.cancelled.connect(self._on_cancelled)

        self.generate_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Processing…")
        self.generation_started.emit()

        processor.start()

    def _on_generate(self):
        # MainWindow handles the actual pipeline orchestration
        # This just validates and emits
        pass

    def _on_cancel(self):
        if self._processor and self._processor.isRunning():
            self._processor.cancel()
            self.status_label.setText("Cancelling…")
            self.cancel_btn.setEnabled(False)

    def _on_cancelled(self):
        self._reset_ui()
        self.status_label.setText("Cancelled.")
        self.generation_cancelled.emit()

    def _on_progress(self, current, total):
        pct = int(100 * current / total) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Frame {current} / {total}…")

    def _on_finished(self, result):
        self._reset_ui()
        if result:
            self.status_label.setText(
                f"Done — {result.get('frames_processed', '?')} frames processed."
            )
        self.generation_finished.emit(result)

    def _on_error(self, message):
        self._reset_ui()
        self.status_label.setText(f"Error: {message}")
        QMessageBox.critical(self, "Generation Error", message)

    def _reset_ui(self):
        self._processor = None
        self.generate_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def update_estimate(self):
        """Compute and display disk space / performance estimate."""
        s = self._state
        vs = s.video_source
        if vs is None:
            self.estimate_label.setVisible(False)
            return

        # Only show for cuboid fill mode
        if s.current_mode != "Cuboid" or getattr(s, "cuboid_fill_mode", "Void") != "Fill":
            self.estimate_label.setVisible(False)
            return

        num_frames = max(1, (s.last_frame - s.initial_frame) // s.sampling_rate + 1)
        mask_w = vs.width - s.cuboid_border_left - s.cuboid_border_right
        mask_h = vs.height - s.cuboid_border_top - s.cuboid_border_bottom
        if mask_w < 2 or mask_h < 2:
            self.estimate_label.setVisible(False)
            return

        # Estimate bytes per frame: PNG is ~60% of raw for typical video frames
        extraction_mode = getattr(s, "extraction_mode", "none")
        chroma_on = getattr(s, "chroma_enabled", False)
        if chroma_on and extraction_mode == "none":
            extraction_mode = "chroma"
        channels = 4 if extraction_mode != "none" else 3
        raw_bytes = mask_w * mask_h * channels
        # PNG compression ratio ~0.5–0.7 for photographic content
        png_bytes = int(raw_bytes * 0.6)
        total_bytes = png_bytes * num_frames

        # Format size
        if total_bytes > 1024**3:
            size_str = f"{total_bytes / 1024**3:.1f} GB"
        else:
            size_str = f"{total_bytes / 1024**2:.0f} MB"

        warn_icon = "\u26a0"  # ⚠
        self.estimate_label.setText(
            f"{warn_icon} Fill mode: {num_frames} frames × {mask_w}×{mask_h} px\n"
            f"Estimated disk usage: {size_str}"
        )
        self.estimate_label.setVisible(True)
