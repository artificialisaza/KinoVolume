from PySide6.QtCore import Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QComboBox, QGroupBox, QLabel, QVBoxLayout


MODE_DESCRIPTIONS = {
    "Cuboid": "Extract a 3D rectangular prism from the video's spatial-temporal volume",
    "Cylinder": "Extract a cylindrical form from the video",
    "Rings": "Create a 2D dendrochronology ring visualization",
    "Slice": "Extract a strip of pixels across all frames into a 2D slit-scan image",
    "Slit-scan": "Sample a spatial-temporal cut plane through the video volume",
    "Slit-tear": "Draw arbitrary lines to extract multiple slits",
}

# Enabled modes
ENABLED_MODES = {"Cuboid", "Cylinder", "Rings", "Slice", "Slit-scan", "Slit-tear"}


class ModeSelector(QGroupBox):
    """Dropdown to switch between visualization modes."""

    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Mode", parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.combo = QComboBox()
        for mode in MODE_DESCRIPTIONS:
            self.combo.addItem(mode)

        # Disable future modes
        model = self.combo.model()
        for i in range(self.combo.count()):
            mode = self.combo.itemText(i)
            if mode not in ENABLED_MODES:
                item = model.item(i)
                item.setEnabled(False)

        # Default to Cuboid
        cuboid_idx = self.combo.findText("Cuboid")
        if cuboid_idx >= 0:
            self.combo.setCurrentIndex(cuboid_idx)

        self.combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.combo)

        self.description_label = QLabel(MODE_DESCRIPTIONS["Cuboid"])
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("infoLabel")
        layout.addWidget(self.description_label)

    def _on_mode_changed(self, mode: str):
        self.description_label.setText(MODE_DESCRIPTIONS.get(mode, ""))
        self.mode_changed.emit(mode)
