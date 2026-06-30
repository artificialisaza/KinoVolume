from PySide6.QtCore import QThread, Signal


class BaseProcessor(QThread):
    """Abstract base for all video processors.

    Subclasses implement run() and emit progress/finished/error.

    Thread safety
    -------------
    Each processor creates its own :class:`~models.video_source.VideoSource`
    clone on construction so it never shares a ``cv2.VideoCapture`` with the
    main UI thread.  The clone is automatically closed when :meth:`run`
    finishes (via :meth:`cleanup`), even on errors or cancellation.
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
        # Create a thread-safe clone of the video source so the processor
        # thread never shares a cv2.VideoCapture with the main UI thread.
        self._video = None
        if project_state is not None and project_state.video_source is not None:
            self._video = project_state.video_source.clone()

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def cleanup(self):
        """Release processor-owned resources (called automatically after run)."""
        if self._video is not None:
            try:
                self._video.close()
            except Exception:
                pass
            self._video = None
