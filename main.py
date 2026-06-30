import logging
import sys

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _configure_opengl():
    """Request a hardware-accelerated OpenGL context before QApplication is created.

    On macOS, Qt 6 defaults to OpenGL 4.1 Core Profile, but VTK may still fall
    back to software rendering if the surface format isn't set explicitly.
    Setting this *before* ``QApplication()`` ensures every QWindow (including
    the VTK render window inside ``QtInteractor``) inherits a hardware-accelerated
    context.
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)  # OpenGL 4.1 Core — the maximum on macOS
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSamples(4)  # 4× MSAA for smoother edges
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    QSurfaceFormat.setDefaultFormat(fmt)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _configure_opengl()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
