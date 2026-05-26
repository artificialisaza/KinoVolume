"""Floating toolbar overlay shown in the upper-right corner of every preview pane.

Features
--------
- Zoom in / zoom out
- Pan arrows (left / right / up / down)  — shown when pan controls are needed
- Rotate CW / CCW                        — 2D only, shown/hidden by caller
- Background-colour picker               — popover with presets + custom colour
- Camera capture                         — saves the current view to captures/

Usage
-----
    toolbar = PreviewToolbar(parent_canvas)
    toolbar.zoom_in_clicked.connect(...)
    toolbar.zoom_out_clicked.connect(...)
    toolbar.pan_requested.connect(lambda dx, dy: ...)
    toolbar.rotate_cw_clicked.connect(...)
    toolbar.rotate_ccw_clicked.connect(...)
    toolbar.bg_color_changed.connect(lambda qcolor: ...)
    toolbar.capture_clicked.connect(...)
    # call toolbar.reposition() after parent resizes
"""

import os

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _icon(name: str) -> QIcon:
    base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(base, "resources", "icons", f"{name}.png")
    return QIcon(path)


# ---------------------------------------------------------------------------
# Compact square icon button
# ---------------------------------------------------------------------------

class _IconBtn(QPushButton):
    """Small square icon button for the toolbar."""

    def __init__(self, icon_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setIcon(_icon(icon_name))
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(28, 28)
        self.setToolTip(tooltip)
        self.setObjectName("previewToolbarBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)


# ---------------------------------------------------------------------------
# Background colour popover
# ---------------------------------------------------------------------------

class _BgColorPopover(QFrame):
    """Small popup panel with background-colour presets + custom picker.

    Emits `color_chosen(QColor)`.  Pass `None` for "default" (interface colour).
    """

    color_chosen = Signal(object)  # QColor | None

    # Preset entries: (label, QColor | None)
    _PRESETS = [
        ("Default", None),
        ("Black", QColor("#000000")),
        ("White", QColor("#ffffff")),
        ("Transparent", QColor(0, 0, 0, 0)),
    ]

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("bgColorPopover")
        self.setStyleSheet(
            "#bgColorPopover {"
            "  background: #2b2b2b;"
            "  border: 1px solid #4a4a4a;"
            "  border-radius: 6px;"
            "}"
            "#bgColorPopover QPushButton {"
            "  background: #333333;"
            "  color: #e0e0e0;"
            "  border: 1px solid #3c3c3c;"
            "  border-radius: 3px;"
            "  padding: 4px 8px;"
            "  font-size: 12px;"
            "  text-align: left;"
            "}"
            "#bgColorPopover QPushButton:hover {"
            "  background: #3c3c3c;"
            "  border-color: #703030;"
            "}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        for label, color in self._PRESETS:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            if color is not None:
                # Add a tiny colour swatch on the left via stylesheet
                css_color = color.name(QColor.HexArgb) if color.alpha() < 255 else color.name()
                swatch_style = (
                    f"#bgPreset_{label} {{"
                    f"  padding-left: 28px;"
                    f"  background-image: none;"
                    f"}}"
                )
                btn.setObjectName(f"bgPreset_{label}")
                # Draw the swatch by subclassing is overkill; use a coloured indicator role
                btn.setProperty("swatchColor", css_color)
            btn.clicked.connect(lambda _=False, c=color: self._emit(c))
            layout.addWidget(btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #4a4a4a;")
        layout.addWidget(sep)

        custom_btn = QPushButton("Custom colour…")
        custom_btn.setFixedHeight(26)
        custom_btn.clicked.connect(self._pick_custom)
        layout.addWidget(custom_btn)

        self.adjustSize()

    def _emit(self, color):
        self.color_chosen.emit(color)
        self.close()

    def _pick_custom(self):
        dlg = QColorDialog(self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, True)
        if dlg.exec():
            self.color_chosen.emit(dlg.selectedColor())
        self.close()


# ---------------------------------------------------------------------------
# Main toolbar widget
# ---------------------------------------------------------------------------

class PreviewToolbar(QWidget):
    """Floating icon toolbar anchored to the top-right of a parent canvas widget.

    Signals
    -------
    zoom_in_clicked()
    zoom_out_clicked()
    pan_requested(dx: int, dy: int)   -- dx/dy in pixels: e.g. (-20, 0) = pan left
    rotate_cw_clicked()
    rotate_ccw_clicked()
    bg_color_changed(color: QColor | None)  -- None = restore default
    capture_clicked()
    """

    zoom_in_clicked = Signal()
    zoom_out_clicked = Signal()
    pan_requested = Signal(int, int)
    rotate_cw_clicked = Signal()
    rotate_ccw_clicked = Signal()
    bg_color_changed = Signal(object)
    capture_clicked = Signal()
    info_clicked = Signal()
    straighten_clicked = Signal()
    invert_time_clicked = Signal()
    reset_view_clicked = Signal()
    wireframe_clicked = Signal()
    auto_rotate_clicked = Signal()
    clip_plane_clicked = Signal()

    PAN_STEP = 30  # pixels per arrow click

    def __init__(self, canvas: QWidget):
        super().__init__(canvas)
        self.setObjectName("previewToolbar")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        # Only button rules — background is drawn via paintEvent
        self.setStyleSheet(
            "#previewToolbar QWidget {"
            "  background: transparent;"
            "}"
            "QPushButton#previewToolbarBtn {"
            "  background: transparent;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QPushButton#previewToolbarBtn:hover {"
            "  background: rgba(80,80,80,180);"
            "}"
            "QPushButton#previewToolbarBtn:pressed {"
            "  background: rgba(100,100,100,220);"
            "}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)
        outer.setSpacing(2)

        # --- Collapse / expand toggle ---
        self._collapsed = False
        self._toggle_btn = QPushButton("—")
        self._toggle_btn.setFixedSize(28, 12)
        self._toggle_btn.setToolTip("Collapse / expand toolbar")
        self._toggle_btn.setObjectName("previewToolbarBtn")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setFocusPolicy(Qt.NoFocus)
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #aaa; font-size: 10px; }"
            "QPushButton:hover { background: rgba(80,80,80,180); border-radius: 3px; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        outer.addWidget(self._toggle_btn, 0, Qt.AlignHCenter)

        # Container for all collapsible rows
        self._body = QWidget()
        self._body.setAutoFillBackground(False)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(2)

        # --- Zoom row ---
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(2)
        self._zoom_in = _IconBtn("zoom-in", "Zoom in  (+)")
        self._zoom_out = _IconBtn("zoom-out", "Zoom out  (–)")
        zoom_row.addWidget(self._zoom_in)
        zoom_row.addWidget(self._zoom_out)
        body_layout.addLayout(zoom_row)

        # --- Pan arrows: 3×3 grid (centre = dead) ---
        self._pan_widget = QWidget()
        self._pan_widget.setAutoFillBackground(False)
        grid = QVBoxLayout(self._pan_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)

        def _spacer():
            s = QWidget()
            s.setFixedSize(28, 28)
            s.setAutoFillBackground(False)
            return s

        top_row = QHBoxLayout()
        top_row.setSpacing(2)
        self._pan_up = _IconBtn("arrow-up", "Pan up")
        top_row.addWidget(_spacer())
        top_row.addWidget(self._pan_up)
        top_row.addWidget(_spacer())
        grid.addLayout(top_row)

        mid_row = QHBoxLayout()
        mid_row.setSpacing(2)
        self._pan_left = _IconBtn("arrow-left", "Pan left")
        self._pan_right = _IconBtn("arrow-right", "Pan right")
        mid_row.addWidget(self._pan_left)
        mid_row.addWidget(_spacer())
        mid_row.addWidget(self._pan_right)
        grid.addLayout(mid_row)

        bot_row = QHBoxLayout()
        bot_row.setSpacing(2)
        self._pan_down = _IconBtn("arrow-down", "Pan down")
        bot_row.addWidget(_spacer())
        bot_row.addWidget(self._pan_down)
        bot_row.addWidget(_spacer())
        grid.addLayout(bot_row)

        body_layout.addWidget(self._pan_widget)

        # --- Rotate row (2D only, hidden by default) ---
        self._rotate_widget = QWidget()
        self._rotate_widget.setAutoFillBackground(False)
        rot_row = QHBoxLayout(self._rotate_widget)
        rot_row.setContentsMargins(0, 0, 0, 0)
        rot_row.setSpacing(2)
        self._rot_ccw = _IconBtn("rotate-ccw", "Rotate 90° counter-clockwise")
        self._rot_cw = _IconBtn("rotate-cw", "Rotate 90° clockwise")
        rot_row.addWidget(self._rot_ccw)
        rot_row.addWidget(self._rot_cw)
        self._rotate_widget.setVisible(False)
        body_layout.addWidget(self._rotate_widget)

        # --- Utility row: bg colour + capture ---
        self._util_widget = QWidget()
        self._util_widget.setAutoFillBackground(False)
        util_row = QHBoxLayout(self._util_widget)
        util_row.setContentsMargins(0, 0, 0, 0)
        util_row.setSpacing(2)
        self._bg_btn = _IconBtn("bg-color", "Change preview background colour")
        self._capture_btn = _IconBtn("camera", "Take a snapshot of the current view\n(saved to captures/ inside the output folder)")
        util_row.addWidget(self._bg_btn)
        util_row.addWidget(self._capture_btn)
        body_layout.addWidget(self._util_widget)

        # --- Info button (3D navigation help, hidden by default) ---
        self._info_widget = QWidget()
        self._info_widget.setAutoFillBackground(False)
        info_row = QHBoxLayout(self._info_widget)
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.setSpacing(2)
        self._info_btn = _IconBtn("info", "How to navigate the 3D view")
        info_row.addWidget(self._info_btn)
        self._info_widget.setVisible(False)
        body_layout.addWidget(self._info_widget)

        # --- 3D view tools row (hidden by default) ---
        self._view3d_widget = QWidget()
        self._view3d_widget.setAutoFillBackground(False)
        view3d_row = QHBoxLayout(self._view3d_widget)
        view3d_row.setContentsMargins(0, 0, 0, 0)
        view3d_row.setSpacing(2)
        self._straighten_btn = _IconBtn("straighten", "Straighten — align the object to its original orientation")
        self._invert_time_btn = _IconBtn("flip-time", "Invert time — flip the volume so the last frame\nbecomes the readable front")
        self._reset_view_btn = _IconBtn("reset-view", "Reset view — return to the default camera angle")
        view3d_row.addWidget(self._straighten_btn)
        view3d_row.addWidget(self._invert_time_btn)
        view3d_row.addWidget(self._reset_view_btn)
        self._view3d_widget.setVisible(False)
        body_layout.addWidget(self._view3d_widget)

        # --- 3D extras row: wireframe, auto-rotate, clip (hidden by default) ---
        self._view3d_extras = QWidget()
        self._view3d_extras.setAutoFillBackground(False)
        extras_row = QHBoxLayout(self._view3d_extras)
        extras_row.setContentsMargins(0, 0, 0, 0)
        extras_row.setSpacing(2)
        self._wireframe_btn = _IconBtn("wireframe", "Toggle wireframe / solid view")
        self._auto_rotate_btn = _IconBtn("auto-rotate", "Toggle turntable auto-rotation")
        self._clip_plane_btn = _IconBtn("clip-plane", "Toggle cross-section clipping plane")
        extras_row.addWidget(self._wireframe_btn)
        extras_row.addWidget(self._auto_rotate_btn)
        extras_row.addWidget(self._clip_plane_btn)
        self._view3d_extras.setVisible(False)
        body_layout.addWidget(self._view3d_extras)

        outer.addWidget(self._body)
        self.adjustSize()

        # Wire internal signals
        self._zoom_in.clicked.connect(self.zoom_in_clicked)
        self._zoom_out.clicked.connect(self.zoom_out_clicked)
        self._pan_up.clicked.connect(lambda: self.pan_requested.emit(0, -self.PAN_STEP))
        self._pan_down.clicked.connect(lambda: self.pan_requested.emit(0, self.PAN_STEP))
        self._pan_left.clicked.connect(lambda: self.pan_requested.emit(-self.PAN_STEP, 0))
        self._pan_right.clicked.connect(lambda: self.pan_requested.emit(self.PAN_STEP, 0))
        self._rot_cw.clicked.connect(self.rotate_cw_clicked)
        self._rot_ccw.clicked.connect(self.rotate_ccw_clicked)
        self._bg_btn.clicked.connect(self._show_bg_menu)
        self._capture_btn.clicked.connect(self.capture_clicked)
        self._info_btn.clicked.connect(self.info_clicked)
        self._straighten_btn.clicked.connect(self.straighten_clicked)
        self._invert_time_btn.clicked.connect(self.invert_time_clicked)
        self._reset_view_btn.clicked.connect(self.reset_view_clicked)
        self._wireframe_btn.clicked.connect(self.wireframe_clicked)
        self._auto_rotate_btn.clicked.connect(self.auto_rotate_clicked)
        self._clip_plane_btn.clicked.connect(self.clip_plane_clicked)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_rotate_visible(self, visible: bool):
        """Show or hide the rotation row (use for 2D preview only)."""
        self._rotate_widget.setVisible(visible)
        self.adjustSize()
        self.reposition()

    def set_pan_visible(self, visible: bool):
        """Show or hide the pan arrow grid."""
        self._pan_widget.setVisible(visible)
        self.adjustSize()
        self.reposition()

    def set_bg_visible(self, visible: bool):
        """Show or hide the background colour button."""
        self._bg_btn.setVisible(visible)
        self._util_widget.setVisible(
            self._bg_btn.isVisible() or self._capture_btn.isVisible()
        )
        self.adjustSize()
        self.reposition()

    def set_capture_visible(self, visible: bool):
        """Show or hide the camera capture button."""
        self._capture_btn.setVisible(visible)
        self._util_widget.setVisible(
            self._bg_btn.isVisible() or self._capture_btn.isVisible()
        )
        self.adjustSize()
        self.reposition()

    def set_info_visible(self, visible: bool):
        """Show or hide the 3D navigation info button."""
        self._info_widget.setVisible(visible)
        self.adjustSize()
        self.reposition()

    def set_view3d_visible(self, visible: bool):
        """Show or hide the 3D view-tools rows."""
        self._view3d_widget.setVisible(visible)
        self._view3d_extras.setVisible(visible)
        self.adjustSize()
        self.reposition()

    def reposition(self):
        """Anchor top-right of parent with 10 px margin."""
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 10
        x = parent.width() - self.width() - margin
        self.move(max(0, x), margin)
        self.raise_()

    def _toggle_collapse(self):
        """Collapse or expand the toolbar body."""
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        # Keep the line indicator unchanged in both states
        self.adjustSize()
        self.reposition()

    def paintEvent(self, event):
        """Draw opaque rounded background via QPainter (prevents VTK bleeding)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(30, 30, 30, 255))
        painter.setPen(QColor(70, 70, 70, 255))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8.0, 8.0)
        painter.end()
        super().paintEvent(event)

    # ------------------------------------------------------------------
    # Background colour menu
    # ------------------------------------------------------------------

    def _show_bg_menu(self):
        popover = _BgColorPopover(self)
        popover.color_chosen.connect(self.bg_color_changed)
        # Position below the bg button
        btn_pos = self._bg_btn.mapToGlobal(QPoint(0, self._bg_btn.height() + 4))
        popover.move(btn_pos)
        popover.show()
