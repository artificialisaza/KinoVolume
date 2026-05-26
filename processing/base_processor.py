from PySide6.QtCore import QThread, Signal


class BaseProcessor(QThread):
    """Abstract base for all video processors.

    Subclasses implement run() and emit progress/finished/error.
    """

    progress = Signal(int, int)   # (current_count, total_count)
    finished = Signal(dict)       # result dict with paths, dimensions, etc.
    error = Signal(str)           # error message
    cancelled = Signal()          # emitted when cancel completes

    def __init__(self, project_state, output_dir, parent=None):
        super().__init__(parent)
        self._state = project_state
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled
