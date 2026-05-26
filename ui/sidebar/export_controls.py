import os
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ExportControls(QGroupBox):
    """Sidebar controls for export format and output directory."""

    export_pdf_clicked = Signal()
    settings_changed = Signal()

    def __init__(self, project_state, parent=None):
        super().__init__("Export", parent)
        self._state = project_state
        # Load last output dir
        try:
            from utils.settings import load_last_output_dir, save_last_output_dir
            last_dir = load_last_output_dir()
            if last_dir:
                self._state.output_dir = last_dir
        except Exception:
            pass
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Image format
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Image Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "TIFF"])
        self.format_combo.setToolTip(
            "PNG: fast, compact, widely supported.\n"
            "TIFF (LZW): archival quality, larger files."
        )
        fmt_row.addWidget(self.format_combo)
        layout.addLayout(fmt_row)

        # 3D mesh format
        self.mesh_row = QWidget()
        mesh_row = QHBoxLayout(self.mesh_row)
        mesh_row.setContentsMargins(0, 0, 0, 0)
        mesh_row.addWidget(QLabel("3D Format:"))
        self.mesh_combo = QComboBox()
        self.mesh_combo.addItems(["glTF/GLB", "OBJ (Wavefront)"])
        self.mesh_combo.setToolTip(
            "glTF/GLB: modern, single-file with embedded textures.\n"
            "OBJ: widely supported, separate texture files."
        )
        mesh_row.addWidget(self.mesh_combo)
        layout.addWidget(self.mesh_row)

        # Output directory
        layout.addWidget(QLabel("Output Directory:"))
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setPlaceholderText("Select a directory…")
        self.dir_edit.setToolTip("Where generated files will be saved")
        dir_row.addWidget(self.dir_edit)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setToolTip("Choose output directory")
        dir_row.addWidget(self.browse_btn)
        layout.addLayout(dir_row)

        # Auto-name subfolder
        self.auto_subfolder_check = QCheckBox("Auto-name subfolder")
        self.auto_subfolder_check.setChecked(True)
        self.auto_subfolder_check.setToolTip(
            "Creates a subfolder named {video}_{mode}_{timestamp}\n"
            "to keep each export run separate."
        )
        layout.addWidget(self.auto_subfolder_check)

        self.subfolder_label = QLabel("")
        self.subfolder_label.setObjectName("infoLabel")
        self.subfolder_label.setWordWrap(True)
        layout.addWidget(self.subfolder_label)

        # Printable unfold (PDF) section
        self.pdf_row = QWidget()
        pdf_layout = QVBoxLayout(self.pdf_row)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        pdf_layout.setSpacing(4)

        # Row 1: Label + Paper size
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(QLabel("Printable box unfold:"))
        row1.addStretch()
        row1.addWidget(QLabel("Paper:"))
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(["A4", "A3", "Letter", "Legal", "Tabloid"])
        self.paper_combo.setToolTip("Paper size for the printable unfold PDF")
        self.paper_combo.setMinimumWidth(70)
        row1.addWidget(self.paper_combo)
        pdf_layout.addLayout(row1)

        # Row 2: Scale + Export button
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("Scale:"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["Fit", "Stretch"])
        self.scale_combo.setToolTip(
            "Fit: uniform scale, proportions preserved.\n"
            "Stretch: temporal dimension fills the page."
        )
        self.scale_combo.setMinimumWidth(65)
        row2.addWidget(self.scale_combo)
        row2.addStretch()
        self.pdf_btn = QPushButton("Export PDF")
        self.pdf_btn.setToolTip("Export a printable cut-and-fold paper model")
        self.pdf_btn.setEnabled(False)
        row2.addWidget(self.pdf_btn)
        pdf_layout.addLayout(row2)

        self.pdf_row.setVisible(False)  # shown only for Cuboid / Cylinder
        layout.addWidget(self.pdf_row)

        # Set default output directory
        if not self._state.output_dir:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            default_dir = os.path.join(desktop, "KinoVolume")
            self._state.output_dir = default_dir
            self.dir_edit.setText(default_dir)

    def _connect_signals(self):
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self.mesh_combo.currentTextChanged.connect(self._on_mesh_changed)
        self.browse_btn.clicked.connect(self._browse_dir)
        self.auto_subfolder_check.toggled.connect(self._update_subfolder_label)
        self.pdf_btn.clicked.connect(self.export_pdf_clicked.emit)

    def _on_format_changed(self, text):
        self._state.image_format = text.lower()
        self.settings_changed.emit()

    def _on_mesh_changed(self, text):
        self._state.mesh_format = text
        self.settings_changed.emit()

    def _browse_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if chosen:
            self._state.output_dir = chosen
            self.dir_edit.setText(chosen)
            self._update_subfolder_label()
            self.settings_changed.emit()
            try:
                from utils.settings import save_last_output_dir
                save_last_output_dir(chosen)
            except Exception:
                pass

    def _update_subfolder_label(self):
        if not self.auto_subfolder_check.isChecked() or not self._state.output_dir:
            self.subfolder_label.setText("")
            return
        name = self._build_subfolder_name()
        self.subfolder_label.setText(f"→ {name}/")

    def _build_subfolder_name(self):
        vs = self._state.video_source
        video_name = "video"
        if vs:
            video_name = os.path.splitext(os.path.basename(vs.file_path))[0]
        mode = self._state.current_mode.lower()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{video_name}_{mode}_{stamp}"

    def set_mode(self, mode):
        """Show/hide 3D format and PDF unfold based on mode."""
        self.mesh_row.setVisible(mode in ("Cuboid", "Cylinder", "Slit-scan", "Slit-tear"))
        self.pdf_row.setVisible(mode in ("Cuboid", "Cylinder"))
        # Disable PDF button when switching modes (no result yet)
        self.pdf_btn.setEnabled(False)

    def set_pdf_enabled(self, enabled):
        """Enable or disable the PDF export button."""
        self.pdf_btn.setEnabled(enabled)

    def get_output_dir(self):
        """Return the final output directory (with auto-subfolder if enabled).

        If no directory has been selected, defaults to ~/Desktop/Deep-vid Visualizer.
        """
        base = self._state.output_dir
        if not base:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            base = os.path.join(desktop, "KinoVolume")
            self._state.output_dir = base
            self.dir_edit.setText(base)
        if self.auto_subfolder_check.isChecked():
            return os.path.join(base, self._build_subfolder_name())
        return base
