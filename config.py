APP_NAME = "KinoVolume"
APP_VERSION = "0.1.0"
SIDEBAR_WIDTH = 380
MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 750
PREVIEW_TEXTURE_MAX = 2048  # max dimension for 3D preview textures
DEFAULT_IMAGE_FORMAT = "png"
SUPPORTED_VIDEO_FORMATS = [".mp4", ".avi", ".mov", ".mkv", ".webm"]
MEMORY_WARN_THRESHOLD_MB = 1024  # warn if estimated usage exceeds this
RINGS_MAX_OUTPUT_DIAMETER = 3072  # cap rings output image resolution
SLITSCAN_MAX_OUTPUT = 12288  # max pixels along time axis for slitscan output

# Object detection / extraction
DETECTION_MODEL_CACHE_DIR = "~/.cache/kinovolume/models"
DETECTION_U2NETP_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
DETECTION_U2NETP_FILENAME = "u2netp.onnx"
DETECTION_U2NET_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
DETECTION_U2NET_FILENAME = "u2net.onnx"
DETECTION_INPUT_SIZE = 320       # U²-Net input resolution
DETECTION_PREVIEW_MAX_SIZE = 512  # max size for single-frame mask preview