from PySide6.QtCore import QObject, Signal

from config import DEFAULT_IMAGE_FORMAT


class ProjectState(QObject):
    """Central state object shared across all UI panels."""

    video_changed = Signal()
    mode_changed = Signal(str)
    frame_changed = Signal(int)
    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Video
        self.video_source = None

        # Mode
        self.current_mode = "Cuboid"

        # Frame navigation
        self.current_frame_index = 0
        self.initial_frame = 0
        self.last_frame = 0
        self.sampling_rate = 1

        # Slice mode settings (Step 1.7)
        self.slit_position = 0
        self.slit_width = 1
        self.slit_orientation = "Vertical"
        self.slice_reverse_time = False

        # Orthogonal mode settings (Step 2.6)
        self.orthogonal_enabled = False
        self.ortho_position = 0       # position of the second (perpendicular) slit
        self.ortho_width = 1
        # Display frames: "None", "Central frame", "Every N frames", "Specific frames"
        self.display_frames_mode = "Central frame"
        self.display_frames_n = 100       # for "Every N frames"
        self.display_frames_list = ""     # for "Specific frames" (comma-separated)

        # Cuboid mode settings (Step 1.8)
        self.cuboid_border_left = 0
        self.cuboid_border_right = 0
        self.cuboid_border_top = 0
        self.cuboid_border_bottom = 0
        self.cuboid_fill_mode = "Void"
        self.cuboid_preview_enabled = True
        self.cuboid_fill_density_mode = "Every N frames"  # "Every N frames" or "All frames"
        self.cuboid_fill_density_n = 10       # show every N frames in 3D
        self.cuboid_fill_spacing = "1×"       # spacing preset ("0×", "1×", "2×", …)
        self.cuboid_fill_pad_gaps = False     # thicken frames to eliminate gaps

        # Chroma-key settings
        self.chroma_enabled = False
        self.chroma_color = (0, 0, 0)
        self.chroma_tolerance = 0.1
        self.chroma_fade = 0.05

        # Extraction mode: "none", "chroma", "edge_detect", "ai_segment"
        self.extraction_mode = "none"

        # Edge detection settings
        self.edge_canny_low = 50
        self.edge_canny_high = 150
        self.edge_dilate = 2
        self.edge_min_area = 500

        # AI segmentation settings
        self.ai_model = "u2netp"       # "u2netp" (fast) or "u2net" (quality)
        self.ai_confidence = 0.5

        # Extraction point prompt (None = auto, (x, y) = user-clicked point)
        self.extraction_prompt_point = None
        self.extraction_invert = False

        # Cylinder mode settings
        self.cylinder_center_x = 0
        self.cylinder_center_y = 0
        self.cylinder_radius = 100
        self.cylinder_fill_mode = "Void"
        self.cylinder_preview_enabled = True
        self.cylinder_preview_quality = "High"

        # Rings mode settings
        self.rings_center_x = 0
        self.rings_center_y = 0
        self.rings_sampling_mode = "All frames (scaled)"
        self.rings_max_output = 3072
        self.rings_reverse_time = False

        # Slit-tear mode settings (Step 3.2)
        self.slittear_lines = []       # list of polylines [(x,y), ...]
        self.slittear_line_width = 1   # perpendicular band width in px

        # Slit-scan mode settings
        self.slitscan_mask_type = "Vertical"         # "Vertical", "Horizontal", "Oblique"
        self.slitscan_slit_width = 1                 # slit width in px
        self.slitscan_border_left = 0                # mask insets from frame edges
        self.slitscan_border_right = 0
        self.slitscan_border_top = 0
        self.slitscan_border_bottom = 0
        self.slitscan_sampling_mode = "Planar cut (3D)"  # "Planar cut (3D)", "All frames" or "Fit to frame size"
        self.slitscan_scan_direction = "L→R"         # "L→R", "R→L" (Vertical) or "T→B", "B→T" (Horizontal)
        self.slitscan_reverse_time = False           # sample frames in reverse order
        self.slitscan_plane_position = 0             # slit position for planar cut mode (x for V, y for H)
        self.slitscan_oblique_points = []            # list of 4 (x, y, t) control points defining the cut plane
        self.slitscan_oblique_output_w = 0           # user-defined output width for oblique (0 = auto)
        self.slitscan_oblique_output_h = 0           # user-defined output height for oblique (0 = auto)

        # Export settings
        self.image_format = DEFAULT_IMAGE_FORMAT
        self.mesh_format = "glTF/GLB"
        self.output_dir = ""

    def set_video_source(self, video_source):
        """Set a new video source and reset frame state."""
        if self.video_source is not None:
            self.video_source.close()
        self.video_source = video_source
        self.current_frame_index = 0
        self.initial_frame = 0
        if video_source is not None:
            self.last_frame = video_source.frame_count - 1
            # Default slit position to center
            self.slit_position = video_source.width // 2
        else:
            self.last_frame = 0
        self.video_changed.emit()
