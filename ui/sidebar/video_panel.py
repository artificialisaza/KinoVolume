import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from config import SUPPORTED_VIDEO_FORMATS
from models.video_source import VideoSource


class VideoPanel(QGroupBox):
    """Sidebar panel for loading video files and displaying metadata."""

    video_loaded = Signal(object)
    preview_loaded = Signal(str)  # folder path

    def __init__(self, parent=None):
        super().__init__("Video", parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.open_button = QPushButton("Open Video")
        self.open_button.clicked.connect(self._on_open_clicked)
        layout.addWidget(self.open_button)

        # Load preview (optional)
        self.load_preview_btn = QPushButton("Load Preview…")
        self.load_preview_btn.setToolTip(
            "Load a previously generated output folder\n"
            "(requires metadata.json) to restore 2D/3D previews."
        )
        self.load_preview_btn.setObjectName("secondaryButton")
        self.load_preview_btn.clicked.connect(self._on_load_preview_clicked)
        layout.addWidget(self.load_preview_btn)

        # Info labels
        self.file_label = QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("infoLabel")
        layout.addWidget(self.file_label)

        self.info_label = QLabel("")
        self.info_label.setObjectName("infoLabel")
        layout.addWidget(self.info_label)

    def _on_open_clicked(self):
        extensions = " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_FORMATS)
        file_filter = f"Video Files ({extensions});;All Files (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video File", "", file_filter
        )
        if not path:
            return

        try:
            video_source = VideoSource(path)
        except ValueError as e:
            QMessageBox.critical(self, "Cannot Open Video", str(e))
            return

        self._display_metadata(video_source)
        self.video_loaded.emit(video_source)

    def _display_metadata(self, vs: VideoSource):
        filename = os.path.basename(vs.file_path)
        self.file_label.setText(filename)

        minutes = int(vs.duration_seconds) // 60
        seconds = vs.duration_seconds % 60
        self.info_label.setText(
            f"Frames: {vs.frame_count}\n"
            f"FPS: {vs.fps:.2f}\n"
            f"Size: {vs.width} × {vs.height}\n"
            f"Duration: {minutes:02d}:{seconds:05.2f}"
        )

    def _on_load_preview_clicked(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select a previously generated output folder"
        )
        if folder:
            self.preview_loaded.emit(folder)
