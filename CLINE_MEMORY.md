# Cline Memory — KinoVolume Codebase Analysis

> Working memory file for codebase research. Compact as needed.

## Project Overview
- **Purpose**: Desktop tool for turning video into 2D images, 3D forms, printable models
- **Stack**: Python 3.11+, PySide6 (UI), OpenCV (video), NumPy/Pillow (image), PyVista/VTK (3D preview), trimesh (mesh export), ONNX Runtime (AI segmentation), ReportLab (PDF)
- **Modes**: Slice, Cuboid (Void/Fill), Cylinder, Rings, Slit-scan, Slit-tear
- **Architecture**: Single-process desktop app, QThread-based processors, central ProjectState

## File Map (Key Files)

| File | Role | Lines |
|------|------|-------|
| `main.py` | Entry point, creates QApplication + MainWindow | 19 |
| `config.py` | Constants (texture caps, model URLs, thresholds) | 20 |
| `models/project_state.py` | God-object: ALL state for ALL modes | 131 |
| `models/video_source.py` | cv2.VideoCapture wrapper | 60 |
| `processing/base_processor.py` | QThread base with progress/finished/error/cancelled signals | 25 |
| `processing/slice_processor.py` | Single + orthogonal slice, memmap-backed | 330 |
| `processing/cuboid_void_processor.py` | 6-face edge extraction, pre-allocated arrays | 113 |
| `processing/cuboid_fill_processor.py` | Full masked frames to disk, extraction support | 136 |
| `processing/cylinder_processor.py` | Perimeter sampling + caps, vectorized | 152 |
| `processing/rings_processor.py` | Polar LUT approach, batched vectorized render | 273 |
| `processing/slitscan_processor.py` | Planar cut, sweep, oblique modes | 615 |
| `processing/slittear_processor.py` | Drawn-line sampling, disk-based strips | 198 |
| `processing/chroma_processor.py` | Color-based alpha keying | 53 |
| `processing/object_detector.py` | Edge detect (Canny) + AI segment (U²-Net ONNX) | 429 |
| `processing/scene_detector.py` | Hard-cut detection via mean abs diff | 122 |
| `export/mesh_exporter.py` | OBJ/GLB export for all 3D modes | 1092 |
| `export/unfold_exporter.py` | Printable PDF (cuboid cross, cylinder strip+caps) | 538 |
| `ui/main_window.py` | Orchestrator: 1619 lines, massive mode branching | 1619 |
| `ui/preview/preview_3d.py` | PyVistaQt 3D viewer, all display_* methods | 2133 |
| `ui/preview/frame_viewer.py` | 2D frame display + mask overlay + drag interaction | 799 |
| `ui/preview/frame_scrubber.py` | Range slider + spinboxes + cut detection | 243 |
| `ui/preview/slice_preview.py` | 2D image viewer for results | (not read) |
| `ui/sidebar/*.py` | Mode-specific control panels | various |
| `ui/widgets/drawing_canvas.py` | Slit-tear line drawing model | (not read) |
| `utils/export_metadata.py` | JSON metadata save/load for reproducibility | 209 |

## Critical Findings

### 1. GPU Not Used (Major)
- **3D Preview**: Uses `pyvistaqt.QtInteractor` → VTK OpenGL backend. On macOS, VTK may fall back to **software rendering** if the OpenGL context isn't properly configured. No explicit GPU backend selection.
- **Anti-aliasing**: Tries SSAA → MSAA → FXAA fallback chain, but all may be software-rendered.
- **AI Segmentation**: `object_detector.py` line 227 tries `CoreMLExecutionProvider` but `onnxruntime` standard pip install does NOT include CoreML EP. Needs `onnxruntime-silicon` or explicit provider check.
- **Image Processing**: All NumPy/CPU. No use of `cv2.UMat` (OpenCL), no CuPy, no Numba.

### 2. Thread Safety (Critical)
- `VideoSource` wraps a single `cv2.VideoCapture` that is **shared** between:
  - Main thread: `frame_viewer.set_frame()` → `vs.get_frame()` (seek + read)
  - Processor thread: `vs.get_frame_range()` (sequential read)
  - Scene detector: opens its OWN `cv2.VideoCapture` (separate, OK)
- `cv2.VideoCapture` is **NOT thread-safe**. Concurrent seek+read from main thread and processor thread can cause:
  - Corrupted frames
  - Wrong frame indices
  - Crashes (rare but possible)
- **Fix**: Use a frame queue, a separate VideoCapture per thread, or a thread-safe wrapper with a lock.

### 3. Entanglement / God Object (Major)
- `ProjectState` (131 lines) holds ALL settings for ALL modes in one flat object.
- `MainWindow._on_generation_finished()` (lines 507-644) has 8+ mode-specific branches.
- `MainWindow._on_preview_toggle()` (lines 902-951) has 6+ mode-specific branches.
- `FrameViewer` has mode-specific overlay painting AND mouse handling for ALL 6 modes in one 799-line class.
- `Preview3D` has `display_cuboid`, `display_cuboid_fill`, `display_cylinder`, `display_slittear`, `display_orthogonal`, `display_slitscan_planar`, `display_slitscan_oblique`, `display_slitscan_void`, `display_slitscan_mask_selector` — all in one 2133-line class.
- `MeshExporter` has export methods for every mode in one 1092-line class.
- **Consequence**: Changing one mode's behavior risks breaking others. No isolation between modes.

### 4. Performance Bottlenecks

#### Video Decoding
- `slitscan_processor._run_planar_cut()` and `_run_slit_scan()` use `video_src.get_frame(f_idx)` which **seeks** for every frame. For H.264/H.265 video, seeking is 10-100x slower than sequential reading.
- `slitscan_processor._run_oblique_scan()` also seeks per unique frame in batch.
- **Fix**: Pre-compute frame indices, sort them, and read sequentially with minimal seeks.

#### Memory
- `slittear_processor.py`: Saves each frame strip as `.npy` to disk, then **loads them all back into RAM** for final assembly (line 124: `result = np.zeros((total_height, count, 3))`). This defeats the disk-based approach.
- `preview_3d.display_cuboid_fill()`: Loads ALL selected frame images into memory simultaneously as VTK textures. Hundreds of frames × full resolution = GBs of VRAM/RAM.
- `rings_processor.py`: Builds a LUT of `(num_rings, 4096, 3)` uint8 — for 1000 rings that's ~12MB, manageable. But the batch rendering creates multiple float32 arrays per batch.

#### Redundant Work
- Mesh export geometry is **duplicated** between `preview_3d.py` (display methods) and `mesh_exporter.py` (export methods). They must be kept in sync manually — a maintenance hazard.
- `main_window.py` loads face images from disk with `PILImage.open()` for BOTH mesh export AND 3D preview — double disk I/O for the same images.

### 5. Reliability Issues

#### Error Handling
- Processors catch all exceptions and emit `error.emit(str(e))` — no structured error types, no cleanup of partial outputs.
- `slittear_processor.py` doesn't clean up `_strips_tmp/` on error (only on success, line 141).
- `slitscan_processor.py` memmap cleanup is in `_cleanup()` but not called on all error paths.

#### Resource Management
- `VideoSource` is never explicitly closed when a new video is loaded — `ProjectState.set_video_source()` closes the old one, but if the processor is still running, this could cause a use-after-free.
- `Preview3D` widget is lazy-loaded but never destroyed — VTK render windows accumulate.
- ONNX session is a global singleton (`_onnx_session`) — never freed, model switching doesn't release the old model.

#### Cancellation
- `BaseProcessor.cancel()` sets a flag, but processors check it at different granularities. `slitscan_processor._run_oblique_scan()` checks per batch row, which could be slow to respond.
- No way to cancel mesh export or 3D preview loading.

### 6. Architecture Assessment

#### Python Choice
- **Appropriate for**: Research software, rapid prototyping, image processing (NumPy ecosystem), AI/ML (ONNX)
- **Pain points**: GIL limits true parallelism for CPU-bound work; VTK Python bindings are heavy; packaging is complex (PyInstaller spec)
- **Alternatives**: Rust/C++ core with Python UI (best of both worlds), or stay Python but use multiprocessing for processors
- **Verdict**: Python is fine for this project's scale. The issues are architectural, not language-level.

#### Threading Model
- QThread per processor is reasonable, but:
  - Only ONE processor can run at a time (no queue, no parallelism)
  - Shared VideoSource is unsafe
  - No progress for mesh export (happens on main thread, blocks UI)

#### State Management
- `ProjectState` as a QObject with signals is a reasonable pattern, but:
  - All mode state in one flat object = no encapsulation
  - No validation (e.g., `slit_position` can exceed frame width)
  - No serialization beyond the metadata helper
  - Settings persist across mode switches (could be feature or bug)

### 7. Code Quality Notes
- Consistent code style, good docstrings in most places
- `getattr(s, "field", default)` pattern used extensively for backward compat — suggests the state object evolved organically
- `main_window.py` imports inside methods (lazy imports) — reduces startup but makes dependencies hard to trace
- Tests only cover Slice and Cuboid Void processors — no tests for UI, 3D preview, mesh export, or other processors

## Mode Summary Table

| Mode | Processor | 3D Preview | Mesh Export | PDF | Key Issue |
|------|-----------|------------|-------------|-----|-----------|
| Slice (single) | `SliceProcessor._run_single` | No | No | No | Memmap OK |
| Slice (orthogonal) | `SliceProcessor._run_orthogonal` | Yes (`display_orthogonal`) | Yes | No | Display frames seek separately |
| Cuboid Void | `CuboidVoidProcessor` | Yes (`display_cuboid`) | Yes | Yes | Pre-alloc OK |
| Cuboid Fill | `CuboidFillProcessor` | Yes (`display_cuboid_fill`) | Yes | No | Disk I/O per frame, 3D loads all frames |
| Cylinder | `CylinderProcessor` | Yes (`display_cylinder`) | Yes | Yes | Vectorized, OK |
| Rings | `RingsProcessor` | No | No | No | LUT approach efficient |
| Slit-scan (planar) | `SlitscanProcessor._run_planar_cut` | Yes (`display_slitscan_planar`) | Yes | No | **Seeks per frame** |
| Slit-scan (sweep) | `SlitscanProcessor._run_slit_scan` | No | No | No | **Seeks per frame** |
| Slit-scan (oblique) | `SlitscanProcessor._run_oblique_scan` | Yes (`display_slitscan_oblique_textured`) | No | No | Complex, batch OK |
| Slit-tear | `SlitTearProcessor` | Yes (`display_slittear`) | Yes | No | **Loads all strips back into RAM** |

## Additional Findings (Review Pass)

### Hardcoded Resolution Limits
- `slitscan_controls.py` lines 157-194: Border spinboxes hardcoded to `setRange(0, 1920)` and `setRange(0, 1080)`. This breaks for 4K+ video. The `_on_video_changed()` method updates ranges, but the initial `_build_ui()` defaults are wrong.

### Signal Reuse / Naming Issues
- `FrameViewer` emits `cuboid_border_dragged` for BOTH cuboid AND slitscan border drags (line 680). The signal name is misleading — slitscan has its own drag logic but reuses the cuboid signal name. This is an entanglement smell.

### Dead Code
- `MainWindow._show_slitscan_3d_preview()` (line 1513) — appears unused; oblique preview is handled by `_show_slitscan_3d_from_result()`.
- `MainWindow._show_slitscan_void_3d_preview()` (line 1542) — appears unused.
- `MainWindow._show_slitscan_mask_selector()` (line 1571) — appears unused (no caller found in main_window.py).
- `slitscan_controls._plane_pos_widget` — always hidden (`setVisible(False)` on line 275). The plane position control exists but is never shown to the user.

### Fragile Transparency System
- `preview_3d.py` has a complex depth-sorting system for cuboid fill transparency (`_fill_plane_groups`, `_fill_sort_dir`, `_update_fill_plane_order`). It manually removes and re-adds actors to the renderer to sort them back-to-front. This is fragile and could break with VTK updates. The system also has a 50ms deferred safety-net timer (line 764) to handle camera state that isn't available on first paint.

### Missing Validation
- `ProjectState` has no validation: `slit_position` can exceed frame width, `cuboid_border_left + cuboid_border_right` can exceed frame width, etc. Validation is done ad-hoc in UI controls and processors.
- `VideoSource.fps` can be 0 for some codecs, causing division by zero in `duration_seconds` (line 20 of video_source.py — guarded but only for the duration calc).

### Metadata System Gap
- `utils/export_metadata.py` `_build_state_snapshot()` doesn't capture slitscan settings (no `elif mode == "Slit-scan"` branch). Slitscan exports cannot be fully reconstructed from metadata.

## Compact Notes
- `PREVIEW_TEXTURE_MAX = 2048` in config.py, but preview_3d.py has its own quality presets up to 4096
- `SLITSCAN_MAX_OUTPUT = 12288` — very large output images possible
- `RINGS_MAX_OUTPUT_DIAMETER = 3072` — large square images
- `MEMORY_WARN_THRESHOLD_MB = 1024` — only warns for Slice and Cuboid, not other modes
- Cut detection buttons are hidden by default (`setVisible(False)`)
- `opencv-python-headless` used — no GUI features from OpenCV
- `SLITSCAN_MAX_OUTPUT` constant exists in config.py but is never referenced in the slitscan processor
- Tests use `MJPG` codec for synthetic video — may not reproduce seeking issues of H.264/H.265
