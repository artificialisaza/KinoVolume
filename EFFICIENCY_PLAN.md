# KinoVolume — Efficiency & Reliability Plan

> **Author**: Engineering analysis  
> **Date**: 2026-06-30  
> **Status**: Ready for implementation  
> **Scope**: Full codebase efficiency, GPU utilization, architecture, reliability

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Diagnosis Overview](#2-diagnosis-overview)
3. [Discussion: Levels of Intervention](#3-discussion-levels-of-intervention)
4. [Plan A — Deep Structural Overhaul](#4-plan-a--deep-structural-overhaul)
5. [Plan B — Incremental Improvements](#5-plan-b--incremental-improvements)
6. [Implementation Roadmap](#6-implementation-roadmap)
7. [Risk Assessment](#7-risk-assessment)
8. [Appendix: Detailed Findings](#8-appendix-detailed-findings)

---

## 1. Executive Summary

KinoVolume is a well-conceived research tool with a clean mode taxonomy and thoughtful UX. However, it has **four systemic issues** that affect efficiency, reliability, and maintainability:

| Issue | Severity | Impact |
|-------|----------|--------|
| **GPU not utilized** | High | 3D preview and AI segmentation run on CPU; interactive performance is poor on macOS |
| **Thread-unsafe video access** | Critical | Shared `cv2.VideoCapture` between UI and processor threads can corrupt frames or crash |
| **Mode entanglement** | High | All modes share one state object, one main window, one 3D viewer, one mesh exporter — changes in one mode risk breaking others |
| **Performance bottlenecks** | Medium | Slit-scan seeks per frame; slit-tear loads all strips back into RAM; 3D fill loads all textures simultaneously |

**How structural is this plan?**  
Plan A (deep) proposes a **moderate-to-large refactor** — splitting the god objects into per-mode modules, introducing a plugin/strategy architecture, and adding a GPU-accelerated rendering path. It changes ~40-50% of the codebase structure but preserves all existing functionality. Plan B (incremental) makes **targeted fixes** within the existing architecture, changing ~10-15% of files with minimal risk.

**Recommendation**: Start with Plan B's critical fixes (GPU, thread safety, seek optimization), then progressively implement Plan A as features are added.

---

## 2. Diagnosis Overview

### 2.1 GPU Utilization

#### 3D Preview (PyVista/VTK)
- **Current**: `pyvistaqt.QtInteractor` creates a VTK render window. On macOS, VTK's OpenGL backend may fall back to **software rendering** (Mesa or CPU) if:
  - The Qt OpenGL context isn't properly shared
  - VTK was built without Metal/OpenGL support
  - The `QSurfaceFormat` doesn't request an adequate OpenGL version
- **Evidence**: No `QSurfaceFormat` setup in `main.py`; no VTK GPU backend verification; anti-aliasing fallback chain suggests rendering issues have been encountered
- **Impact**: 3D preview is slow, especially with large textures and many frame planes (Cuboid Fill)

#### AI Segmentation (ONNX Runtime)
- **Current**: `object_detector.py` line 224-230 lists `CoreMLExecutionProvider` as preferred, but:
  - Standard `pip install onnxruntime` does **not** include CoreML EP
  - Need `onnxruntime-silicon` (Apple Silicon) or `onnxruntime` built with CoreML
  - No runtime check or user-facing message about which provider is active
- **Impact**: U²-Net inference runs entirely on CPU, which is 5-20x slower than Apple Neural Engine / GPU

#### Image Processing
- **Current**: All NumPy on CPU. OpenCV operations (Canny, resize, morphology) use CPU defaults.
- **Potential**: `cv2.UMat` enables OpenCL acceleration for many operations; not used anywhere

### 2.2 Thread Safety

```
┌─────────────────────────────────────────────────────┐
│                    Main Thread                       │
│  FrameViewer.set_frame() → vs.get_frame(idx)         │
│  (seek + read on shared VideoCapture)                │
└────────────────────┬────────────────────────────────┘
                     │ concurrent access
┌────────────────────▼────────────────────────────────┐
│              Processor Thread (QThread)              │
│  vs.get_frame_range(start, end, step)                │
│  (sequential read on SAME VideoCapture)              │
└─────────────────────────────────────────────────────┘
```

`cv2.VideoCapture` is **not thread-safe**. The main thread (frame scrubber) and the processor thread both call methods on the same `VideoSource._cap` object. This can cause:
- **Frame corruption**: Concurrent seek + read returns wrong pixels
- **Wrong frame indices**: `CAP_PROP_POS_FRAMES` is shared state
- **Crashes**: Rare but possible with certain codecs

### 2.3 Mode Entanglement

The codebase has **five god objects** that contain logic for all six modes:

| Object | Lines | Modes Handled |
|--------|-------|---------------|
| `ProjectState` | 131 | All 6 modes (flat fields) |
| `MainWindow` | 1619 | All 6 modes (branching in 10+ methods) |
| `Preview3D` | 2133 | 5 modes (9 display methods) |
| `FrameViewer` | 799 | All 6 modes (overlay + mouse) |
| `MeshExporter` | 1092 | 5 modes (10+ export methods) |

**Consequences**:
- Changing Cuboid's 3D preview risks breaking Cylinder's 3D preview (shared `Preview3D`)
- Adding a new mode requires editing 5+ files with mode-specific branches
- Testing one mode in isolation is impossible
- The `if mode == "Cuboid" ... elif mode == "Slice" ...` pattern appears 20+ times

### 2.4 Performance Bottlenecks

| Bottleneck | Location | Impact | Fix Difficulty |
|------------|----------|--------|----------------|
| Per-frame seeking | `slitscan_processor.py` lines 165, 328 | 10-100x slower than sequential read for compressed video | Low |
| Slit-tear RAM assembly | `slittear_processor.py` line 124 | OOM on large frame counts | Low |
| 3D fill texture overload | `preview_3d.py` `display_cuboid_fill` | GBs of VRAM/RAM for hundreds of frames | Medium |
| Double disk I/O | `main_window.py` loads images twice (mesh + preview) | 2x disk reads | Low |
| No frame caching | `slitscan_oblique` re-reads frames | Redundant decoding | Medium |
| Mesh export blocks UI | `main_window.py` export methods | UI freezes during export | Medium |

---

## 3. Discussion: Levels of Intervention

Efficiency and reliability can be tackled at multiple levels. Here is a discussion of each, with trade-offs.

### Level 0: Configuration & Environment (Lowest effort, immediate impact)

**What**: Fix GPU usage by configuring the environment correctly, without changing code logic.

- **VTK GPU**: Set `QSurfaceFormat` to request OpenGL 4.1+ (or Metal via ANGLE) before creating QApplication. Verify VTK is using hardware acceleration with `vtkRenderWindow.GetReport()`.
- **ONNX GPU**: Install `onnxruntime-silicon` on Apple Silicon, or add `onnxruntime-gpu` on other platforms. Add a runtime check that logs which execution provider is active.
- **OpenCV OpenCL**: Enable `cv2.UMat` for Canny, resize, morphology in `object_detector.py`.

**Pros**: Minimal code changes, immediate performance gain.  
**Cons**: Doesn't fix architectural issues; GPU availability varies by machine.  
**Effort**: 1-2 sessions.  
**Codebase change**: <5%.

### Level 1: Targeted Algorithmic Fixes (Low effort, high ROI)

**What**: Fix specific performance bottlenecks within the existing architecture.

- **Slit-scan sequential read**: Replace per-frame `get_frame(f_idx)` with sorted sequential reading.
- **Slit-tear streaming assembly**: Write final image directly via memmap instead of loading all strips.
- **3D fill texture management**: Implement texture streaming / LOD for `display_cuboid_fill`.
- **Cache face images**: Load face images once, pass to both mesh exporter and 3D preview.
- **Move mesh export to worker thread**: Prevent UI freeze.

**Pros**: High impact on specific modes, low risk.  
**Cons**: Doesn't address entanglement or thread safety.  
**Effort**: 2-3 sessions.  
**Codebase change**: ~10%.

### Level 2: Thread Safety & Resource Management (Medium effort, critical reliability)

**What**: Fix the shared `VideoSource` problem and resource leaks.

- **Thread-safe VideoSource**: Add a `threading.Lock` around all `cv2.VideoCapture` operations, OR create a separate `VideoCapture` per thread (recommended).
- **Processor isolation**: Each processor gets its own `VideoSource` instance opened from the same file path.
- **Resource cleanup**: Explicitly close VTK render windows, ONNX sessions, and temp files on error paths.
- **Cancellation**: Add cancellation checks at finer granularity; allow canceling mesh export.

**Pros**: Eliminates crash/corruption risk, improves reliability.  
**Cons**: Requires careful testing of all processor paths.  
**Effort**: 2-3 sessions.  
**Codebase change**: ~10-15%.

### Level 3: Mode Disentanglement (High effort, high maintainability)

**What**: Split god objects into per-mode modules using a strategy/plugin pattern.

- **Per-mode state classes**: `SliceState`, `CuboidState`, `CylinderState`, etc., with a common interface.
- **Per-mode preview controllers**: `CuboidPreview`, `CylinderPreview`, etc., each owning its 3D rendering logic.
- **Per-mode mesh exporters**: Split `MeshExporter` into mode-specific exporter classes.
- **Mode registry**: A central registry that maps mode name → state class, controls panel, preview controller, exporter.
- **MainWindow slimming**: Remove mode-specific branching; delegate to mode controllers.

**Pros**: Isolation between modes, testable units, easier to add modes.  
**Cons**: Large refactor, high risk of regressions, requires comprehensive tests.  
**Effort**: 5-8 sessions.  
**Codebase change**: ~40-50%.

### Level 4: Core Engine Rewrite (Highest effort, transformative)

**What**: Rewrite the processing core in a compiled language (Rust/C++) with Python bindings.

- **Rust core**: Video decoding (ffmpeg), image processing (image crate), mesh export.
- **Python UI**: Keep PySide6 UI, call Rust via PyO3 bindings.
- **GPU compute**: Use wgpu or metal-rs for GPU-accelerated image processing.
- **True parallelism**: Rust's ownership model enables safe parallel processing.

**Pros**: 10-100x performance for CPU-bound work, true parallelism, memory safety.  
**Cons**: Massive effort, steep learning curve, packaging complexity.  
**Effort**: 15-20+ sessions.  
**Codebase change**: ~80% (core rewritten, UI preserved).

### Recommendation

| Priority | Level | What to Do |
|----------|-------|------------|
| **1 (now)** | Level 0 | Fix GPU configuration — immediate user-visible impact |
| **2 (now)** | Level 2 | Fix thread safety — critical reliability risk |
| **3 (next)** | Level 1 | Fix algorithmic bottlenecks — high ROI |
| **4 (ongoing)** | Level 3 | Disentangle modes — as features are added |
| **5 (future)** | Level 4 | Consider Rust core — only if Python performance is fundamentally insufficient |

---

## 4. Plan A — Deep Structural Overhaul

### Phase A1: GPU Acceleration (Level 0 + Level 1 GPU)

#### A1.1: VTK/Metal GPU Configuration
**Files**: `main.py`, `ui/preview/preview_3d.py`  
**Changes**:
1. In `main.py`, before `QApplication()`:
   ```python
   from PySide6.QtGui import QSurfaceFormat
   fmt = QSurfaceFormat()
   fmt.setVersion(4, 1)  # OpenGL 4.1 Core (macOS max)
   fmt.setProfile(QSurfaceFormat.CoreProfile)
   fmt.setSamples(4)  # MSAA
   QSurfaceFormat.setDefaultFormat(fmt)
   ```
2. In `Preview3D.__init__`, after creating `QtInteractor`:
   ```python
   # Verify hardware rendering
   ren_win = self.plotter.render_window
   if hasattr(ren_win, 'GetReport'):
       report = ren_win.GetReport()
       if 'Software' in report or 'Mesa' in report:
           logger.warning("VTK is using software rendering — 3D preview will be slow")
   ```
3. Set VTK to prefer Metal/OpenGL:
   ```python
   # In Preview3D.__init__
   try:
       vtkRenderWindow.SetGlobalMaximumMultiSampleSamples(8)
   except Exception:
       pass
   ```

#### A1.2: ONNX CoreML/GPU Provider
**Files**: `pyproject.toml`, `processing/object_detector.py`  
**Changes**:
1. In `pyproject.toml`, add platform-specific dependency:
   ```toml
   [project.optional-dependencies]
   macos = ["onnxruntime-silicon>=1.16"]
   ```
2. In `object_detector._get_onnx_session()`:
   ```python
   providers = ort.get_available_providers()
   logger.info("Available ONNX providers: %s", providers)
   
   preferred = []
   # CoreML for Apple Silicon (Apple Neural Engine / GPU)
   if "CoreMLExecutionProvider" in providers:
       preferred.append("CoreMLExecutionProvider")
   # Metal for Apple GPU
   if "MetalPerformanceShadersExecutionProvider" in providers:
       preferred.append("MetalPerformanceShadersExecutionProvider")
   # CUDA for NVIDIA
   if "CUDAExecutionProvider" in providers:
       preferred.append("CUDAExecutionProvider")
   preferred.append("CPUExecutionProvider")
   
   session = ort.InferenceSession(str(path), providers=preferred)
   # Log which provider was actually used
   actual = session.get_providers()
   logger.info("ONNX session using providers: %s", actual)
   ```
3. Add user-facing status: show active provider in the AI panel status label.

#### A1.3: OpenCV OpenCL Acceleration
**Files**: `processing/object_detector.py`  
**Changes**:
1. Wrap Canny, GaussianBlur, dilate, erode inputs with `cv2.UMat`:
   ```python
   gray_umat = cv2.UMat(gray)
   blurred = cv2.GaussianBlur(gray_umat, (5, 5), 0)
   edges = cv2.Canny(blurred, canny_low, canny_high)
   # Convert back only when needed
   edges_np = edges.get()
   ```
2. Check `cv2.ocl.haveOpenCL()` at startup and log status.

---

### Phase A2: Thread Safety (Level 2)

#### A2.1: Thread-Safe VideoSource
**Files**: `models/video_source.py`, `processing/base_processor.py`  
**Changes**:
1. Add a `clone()` method to `VideoSource` that opens a new `VideoCapture` from the same path:
   ```python
   def clone(self) -> "VideoSource":
       """Create a new VideoSource for the same file (thread-safe)."""
       return VideoSource(self.file_path)
   ```
2. In `BaseProcessor.__init__`, create a processor-specific VideoSource:
   ```python
   def __init__(self, project_state, output_dir, parent=None):
       super().__init__(parent)
       self._state = project_state
       self._output_dir = output_dir
       self._cancelled = False
       self._video = project_state.video_source.clone()  # Thread-safe copy
   ```
3. Replace all `s.video_source` / `vs` references in processors with `self._video`.
4. Close `self._video` in a `finally` block or `cleanup()` method.

#### A2.2: Resource Cleanup
**Files**: All processors, `ui/preview/preview_3d.py`  
**Changes**:
1. Add `cleanup()` to `BaseProcessor`:
   ```python
   def cleanup(self):
       if hasattr(self, '_video') and self._video is not None:
           self._video.close()
   ```
2. Call `cleanup()` in `run()` finally block (override in subclasses or add to base).
3. In `Preview3D`, add `destroy_widget()` that calls `self.plotter.close()` and removes VTK references.
4. In `object_detector`, add `release_onnx_session()` to free the global singleton.

---

### Phase A3: Performance Bottlenecks (Level 1)

#### A3.1: Slit-scan Sequential Reading
**Files**: `processing/slitscan_processor.py`  
**Changes**:
1. In `_run_planar_cut()` and `_run_slit_scan()`, replace the per-frame seek loop:
   ```python
   # OLD: for col, f_idx in enumerate(frame_indices):
   #          fd = video_src.get_frame(f_idx)  # SEEK per frame
   
   # NEW: Sort unique frame indices, read sequentially, cache
   unique_indices = sorted(set(frame_indices))
   frame_cache = {}
   for f_idx, frame in self._video.get_frame_range(
       min(unique_indices), max(unique_indices), 1
   ):
       if f_idx in unique_indices:
           frame_cache[f_idx] = frame
       if self.is_cancelled():
           break
   
   # Then use frame_cache[f_idx] in the column loop
   ```
2. For oblique mode, the existing batch approach is already reasonable but should use `clone()`.

#### A3.2: Slit-tear Streaming Assembly
**Files**: `processing/slittear_processor.py`  
**Changes**:
1. Replace the load-all-strips-into-RAM approach with a memmap:
   ```python
   # Create memmap for final result
   result = np.memmap(
       tmp_path, dtype=np.uint8, mode="w+",
       shape=(total_height, count, 3),
   )
   # Stream strips directly into memmap columns
   for i in range(count):
       strip = np.load(os.path.join(strips_dir, f"s_{i:06d}.npy"))
       result[:, i] = strip
   # Save image from memmap
   self._save_image(result, out_path, fmt)
   del result
   os.remove(tmp_path)
   ```
2. Clean up `_strips_tmp/` in a `finally` block, not just on success.

#### A3.3: 3D Fill Texture Streaming
**Files**: `ui/preview/preview_3d.py`  
**Changes**:
1. In `display_cuboid_fill()`, implement texture LOD:
   - For >50 frames, automatically reduce texture resolution per plane
   - Use a texture pool that reuses VTK texture objects
   - Implement on-demand loading: only load textures for visible planes
2. Add a frame count warning:
   ```python
   if len(selected) > 100:
       logger.warning("Loading %d frame planes — consider increasing step", len(selected))
   ```

#### A3.4: Cache Face Images
**Files**: `ui/main_window.py`  
**Changes**:
1. Load face images once in `_on_generation_finished()` and pass the arrays to both mesh export and 3D preview:
   ```python
   face_images = {}
   for name, path in result["face_paths"].items():
       face_images[name] = np.array(PILImage.open(path))
   
   # Pass to mesh exporter
   self._export_cuboid_mesh(result, face_images=face_images)
   # Pass to 3D preview
   self._show_3d_preview(result, face_images=face_images)
   ```

#### A3.5: Mesh Export in Worker Thread
**Files**: `ui/main_window.py`, new `export/export_worker.py`  
**Changes**:
1. Create `ExportWorker(QThread)` that runs mesh export off the main thread:
   ```python
   class ExportWorker(QThread):
       progress = Signal(int, int)
       finished = Signal(str)  # output path
       error = Signal(str)
       
       def __init__(self, export_fn, *args, **kwargs):
           ...
       def run(self):
           try:
               result = self._fn(*self._args, **self._kwargs)
               self.finished.emit(result)
           except Exception as e:
               self.error.emit(str(e))
   ```
2. Replace direct export calls with `ExportWorker` instances.

---

### Phase A4: Mode Disentanglement (Level 3)

#### A4.1: Per-Mode State Classes
**Files**: New `models/mode_states.py`, modify `models/project_state.py`  
**Changes**:
1. Create base interface:
   ```python
   class ModeState(QObject):
       settings_changed = Signal()
       def validate(self, video_source) -> list[str]: ...
       def to_dict(self) -> dict: ...
       def from_dict(self, data: dict): ...
   ```
2. Create per-mode states:
   ```python
   class SliceState(ModeState):
       def __init__(self):
           self.slit_position = 0
           self.slit_width = 1
           self.slit_orientation = "Vertical"
           self.orthogonal_enabled = False
           # ... only slice fields
   
   class CuboidState(ModeState):
       def __init__(self):
           self.border_left = 0
           # ... only cuboid fields
   ```
3. `ProjectState` becomes a container:
   ```python
   class ProjectState(QObject):
       def __init__(self):
           self.video_source = None
           self.current_mode = "Cuboid"
           self.initial_frame = 0
           self.last_frame = 0
           self.sampling_rate = 1
           self.image_format = "png"
           self.mesh_format = "glTF/GLB"
           self.output_dir = ""
           
           self.mode_states = {
               "Slice": SliceState(),
               "Cuboid": CuboidState(),
               "Cylinder": CylinderState(),
               "Rings": RingsState(),
               "Slit-scan": SlitscanState(),
               "Slit-tear": SlitTearState(),
           }
       
       @property
       def current_mode_state(self) -> ModeState:
           return self.mode_states[self.current_mode]
   ```

#### A4.2: Per-Mode Preview Controllers
**Files**: New `ui/preview/mode_previews/` directory  
**Changes**:
1. Create base interface:
   ```python
   class ModePreview(ABC):
       @abstractmethod
       def display(self, plotter, result, state, video_source): ...
       @abstractmethod
       def can_handle(self, result: dict) -> bool: ...
   ```
2. Create per-mode preview classes:
   - `CuboidVoidPreview` — owns `display_cuboid` logic
   - `CuboidFillPreview` — owns `display_cuboid_fill` logic
   - `CylinderPreview` — owns `display_cylinder` logic
   - `SliceOrthogonalPreview` — owns `display_orthogonal` logic
   - `SlitscanPlanarPreview` — owns `display_slitscan_planar` logic
   - `SlitTearPreview` — owns `display_slittear` logic
3. `Preview3D` becomes a thin shell:
   ```python
   class Preview3D(QWidget):
       def __init__(self):
           self.plotter = QtInteractor(self)
           self._previews = {}  # mode_name → ModePreview
           self._active_preview = None
       
       def display(self, mode, result, state, video_source):
           preview = self._previews.get(mode)
           if preview:
               self._active_preview = preview
               preview.display(self.plotter, result, state, video_source)
   ```

#### A4.3: Per-Mode Mesh Exporters
**Files**: New `export/mode_exporters/` directory  
**Changes**:
1. Split `MeshExporter` into:
   - `CuboidMeshExporter` — `export_obj`, `export_gltf`
   - `CylinderMeshExporter` — `export_cylinder_obj`, `export_cylinder_gltf`
   - `OrthogonalMeshExporter` — `export_orthogonal_obj`, `export_orthogonal_gltf`
   - `CuboidFillMeshExporter` — `export_cuboid_fill_obj`, `export_cuboid_fill_gltf`
   - `SlitTearMeshExporter` — `export_slittear_obj`, `export_slittear_gltf`
   - `SlitscanPlanarMeshExporter` — `export_slitscan_planar_obj`, `export_slitscan_planar_gltf`
2. Each exporter owns its geometry builder — **shared with the preview controller** via a common geometry module.

#### A4.4: Shared Geometry Module
**Files**: New `export/geometry.py`  
**Changes**:
1. Extract geometry-building code that is duplicated between `preview_3d.py` and `mesh_exporter.py`:
   ```python
   def build_cuboid_faces(W, H, D) -> dict[str, dict]:
       """Return face definitions (verts, uvs, faces) for a cuboid."""
   
   def build_cylinder_surface(radius, depth, n_seg) -> tuple[verts, uvs, faces]:
       """Return cylinder surface geometry."""
   
   def build_planar_plane(scan_dir, mask_type, W, H, D, mask_bounds) -> tuple[verts, uvs, faces]:
       """Return diagonal plane geometry."""
   ```
2. Both preview controllers and mesh exporters import from this module.

#### A4.5: Mode Registry
**Files**: New `ui/mode_registry.py`  
**Changes**:
1. Central registry:
   ```python
   MODE_REGISTRY = {
       "Slice": ModeConfig(
           state_class=SliceState,
           controls_class=SliceControls,
           processor_class=SliceProcessor,
           preview_controller=SlicePreviewController,
           mesh_exporter=None,
           pdf_exporter=None,
       ),
       "Cuboid": ModeConfig(
           state_class=CuboidState,
           controls_class=CuboidControls,
           processor_class=lambda s: (CuboidFillProcessor if s.fill_mode == "Fill" else CuboidVoidProcessor),
           preview_controller=lambda s: (CuboidFillPreview if s.fill_mode == "Fill" else CuboidVoidPreview),
           mesh_exporter=CuboidMeshExporter,
           pdf_exporter=export_cuboid_pdf,
       ),
       # ... etc
   }
   ```
2. `MainWindow` uses the registry instead of hardcoded if/elif chains.

#### A4.6: MainWindow Slimming
**Files**: `ui/main_window.py`  
**Changes**:
1. Replace `_on_generation_finished()` mode branching with:
   ```python
   def _on_generation_finished(self, result):
       mode = self.state.current_mode
       config = MODE_REGISTRY[mode]
       config.handle_generation_finished(result, self.state, self)
   ```
2. Replace `_on_preview_toggle()` with delegation to the active preview controller.
3. Remove all `if mode == "..."` branches — delegate to mode configs.

---

## 5. Plan B — Incremental Improvements

> For when a full refactor isn't feasible. Each item is independent and can be done in isolation.

### B1: Fix GPU Configuration (1 session)
- [ ] Add `QSurfaceFormat` in `main.py` for OpenGL 4.1 Core
- [ ] Add VTK rendering backend check in `Preview3D.__init__`
- [ ] Log a warning if software rendering is detected
- [ ] Document `onnxruntime-silicon` in README for Apple Silicon users
- [ ] Add ONNX provider logging in `object_detector.py`

### B2: Fix Thread Safety (1-2 sessions)
- [ ] Add `clone()` to `VideoSource`
- [ ] Create per-thread `VideoSource` in `BaseProcessor`
- [ ] Replace `s.video_source` with `self._video` in all processors
- [ ] Close processor's `VideoSource` in `finally` block
- [ ] Add lock to `VideoSource.get_frame()` as defense-in-depth

### B3: Fix Slit-scan Seeking (1 session)
- [ ] In `_run_planar_cut()`: sort frame indices, read sequentially, cache
- [ ] In `_run_slit_scan()`: same approach
- [ ] Benchmark before/after with a compressed video

### B4: Fix Slit-tear Memory (1 session)
- [ ] Replace RAM assembly with memmap in `slittear_processor.py`
- [ ] Move `shutil.rmtree(strips_dir)` to `finally` block
- [ ] Add cleanup for temp files on error

### B5: Fix 3D Fill Texture Overload (1-2 sessions)
- [ ] Add automatic texture downscaling for >50 frame planes
- [ ] Add frame count warning in UI
- [ ] Implement texture object reuse (don't create new VTK texture per plane)

### B6: Cache Face Images (0.5 session)
- [ ] In `main_window._on_generation_finished()`, load face images once
- [ ] Pass arrays to both mesh export and 3D preview methods

### B7: Mesh Export in Worker Thread (1 session)
- [ ] Create `ExportWorker(QThread)` class
- [ ] Move all `_export_*_mesh()` calls to worker threads
- [ ] Add progress indication for exports

### B8: Error Handling & Cleanup (1 session)
- [ ] Add `finally` blocks to all processors for temp file cleanup
- [ ] Add structured error types (e.g., `MaskTooSmallError`, `NoFramesError`)
- [ ] Clean up partial output directories on error
- [ ] Add ONNX session release function

### B9: Expanded Tests (1-2 sessions)
- [ ] Add tests for Cylinder, Rings, Slit-scan, Slit-tear processors
- [ ] Add tests for mesh export geometry
- [ ] Add integration test for full generate → preview pipeline
- [ ] Add thread safety test (concurrent VideoSource access)

---

## 6. Implementation Roadmap

### Sprint 1: Critical Fixes (Plan B items B1, B2, B3, B4)
**Goal**: Fix GPU, thread safety, and top performance bottlenecks.  
**Sessions**: 4-5  
**Risk**: Low — targeted changes within existing architecture.  
**Deliverable**: GPU-accelerated 3D preview, thread-safe processing, 10x faster slit-scan.

### Sprint 2: Performance & Reliability (Plan B items B5, B6, B7, B8)
**Goal**: Fix remaining performance issues and reliability gaps.  
**Sessions**: 3-4  
**Risk**: Low-Medium — more files touched but still targeted.  
**Deliverable**: No UI freezes, no resource leaks, comprehensive error handling.

### Sprint 3: Test Coverage (Plan B item B9)
**Goal**: Achieve >80% test coverage for processors and exports.  
**Sessions**: 2  
**Risk**: Very low — only adding tests.  
**Deliverable**: Confidence to proceed with structural refactor.

### Sprint 4-6: Structural Refactor (Plan A phases A4.1-A4.6)
**Goal**: Disentangle modes into isolated modules.  
**Sessions**: 6-8  
**Risk**: Medium-High — large refactor, needs comprehensive tests first.  
**Deliverable**: Mode plugin architecture, each mode independently testable.

### Sprint 7+: Future Considerations
- GPU-accelerated image processing (OpenCL/Metal via PyOpenCL or ctypes)
- Multiprocessing for batch generation
- Rust core for performance-critical paths (only if needed)

---

## 7. Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| GPU config (B1) | VTK may not support Metal on some macOS versions | Fallback to CPU with warning; test on multiple machines |
| Thread-safe VideoSource (B2) | Processors may have subtle dependencies on shared state | Test each processor individually; add integration tests |
| Slit-scan sequential read (B3) | Frame cache may use too much memory for long videos | Limit cache size; evict oldest frames |
| Slit-tear memmap (B4) | Memmap may fail on network drives | Fallback to RAM if memmap fails |
| 3D fill texture LOD (B5) | May reduce visual quality | Make LOD configurable; default to current behavior |
| Mode disentanglement (A4) | High risk of regressions | Comprehensive tests first (Sprint 3); incremental migration |
| Mesh export threading (B7) | VTK/trimesh may not be thread-safe | Test trimesh export in worker thread; fall back to main thread if needed |

---

## 8. Appendix: Detailed Findings

### A8.1: VideoSource Thread Safety Analysis

`VideoSource` wraps `cv2.VideoCapture`. The OpenCV documentation does not guarantee thread safety for `VideoCapture`. In practice:

- `cap.set(CAP_PROP_POS_FRAMES, idx)` + `cap.read()` is a compound operation that must be atomic
- If thread A seeks to frame 100 while thread B is reading frame 50, thread B may get frame 100's data
- The `get_frame_range()` method in `VideoSource` does sequential reads, but if the main thread calls `get_frame()` concurrently, the sequential position is lost

**Recommendation**: Each thread that needs video access should have its own `VideoSource` (and thus its own `VideoCapture`). This is the simplest and safest approach.

### A8.2: VTK macOS Rendering

VTK on macOS can use:
1. **Cocoa + OpenGL** (legacy, OpenGL 4.1 max) — the default for VTK builds
2. **Metal** (via ANGLE or native Metal backend) — newer, requires VTK 9.3+
3. **Software rendering** (Mesa/OSMesa) — fallback, very slow

The current code doesn't configure the OpenGL context, so VTK uses whatever Qt provides. On macOS, Qt 6 defaults to OpenGL 4.1 Core, which should work with VTK — but if the Qt window doesn't get a hardware-accelerated context (e.g., running headless or in a VM), VTK falls back to software.

**Key fix**: Set `QSurfaceFormat` BEFORE creating `QApplication`, and verify the render window is hardware-accelerated.

### A8.3: ONNX Runtime on Apple Silicon

| Package | CoreML EP | Metal EP | Notes |
|---------|-----------|----------|-------|
| `onnxruntime` (pip) | No | No | CPU only |
| `onnxruntime-silicon` | Yes | No | CoreML (ANE/GPU) |
| `onnxruntime` (conda-forge) | Yes | No | May include CoreML |

The current `pyproject.toml` specifies `onnxruntime>=1.16` which installs the CPU-only version on Apple Silicon. Users need to manually install `onnxruntime-silicon` or build from source with CoreML support.

**Key fix**: Add `onnxruntime-silicon` as a platform-specific dependency and log the active provider.

### A8.4: Geometry Duplication Map

The following geometry-building code is duplicated between `preview_3d.py` and `mesh_exporter.py`:

| Geometry | preview_3d.py | mesh_exporter.py | Sync Risk |
|----------|---------------|-------------------|-----------|
| Cuboid faces | `display_cuboid` (lines 474-566) | `export_obj` / `export_gltf` (lines 12-149) | High — UV transforms must match |
| Cylinder surface + caps | `display_cylinder` (lines 1135-1259) | `export_cylinder_obj` / `export_cylinder_gltf` (lines 309-506) | High — UV offset must match |
| Slitscan planar plane | `display_slitscan_planar` (lines 1856-2012) | `_build_planar_plane` (lines 155-236) | High — subdivision must match |
| Slit-tear curtains | `display_slittear` (lines 1261-1373) | `_build_slittear_lines` + export (lines 925-1092) | Medium — subsampling must match |
| Orthogonal planes | `display_orthogonal` (lines 1375-1494) | `export_orthogonal_obj` / `export_orthogonal_gltf` (lines 512-708) | Medium — UV mapping must match |
| Cuboid fill planes | `display_cuboid_fill` (lines 568-764) | `export_cuboid_fill_obj` / `export_cuboid_fill_gltf` (lines 728-919) | High — depth scaling must match |

**Key fix**: Extract all geometry into a shared `geometry.py` module that both preview and export import.

### A8.5: Memory Usage Estimates

| Scenario | Estimated Memory | Current Mitigation | Needed |
|----------|-----------------|-------------------|--------|
| Slice, 1000 frames, 1080p, width=1 | ~6 MB (memmap) | Memmap | OK |
| Cuboid Void, 1000 frames, 500x500 mask | ~3 MB (edges) | Pre-alloc | OK |
| Cuboid Fill, 500 frames, 500x500 mask | ~375 MB (disk) | Disk per frame | OK |
| Cuboid Fill 3D, 100 frames, 500x500 | ~750 MB (textures) | None — all in VRAM | Texture streaming |
| Slit-tear, 1000 frames, 1000 px lines | ~3 MB (strips) + ~3 GB (assembly) | None — RAM assembly | Memmap assembly |
| Rings, 1000 rings, 3072 diameter | ~38 MB (LUT) + ~38 MB (output) | Batched | OK |
| Slitscan planar, 1000 frames, 1080p | ~6 MB (output) | Memmap for large | OK |

### A8.6: Cancellation Granularity

| Processor | Cancel Check Location | Response Time |
|-----------|----------------------|---------------|
| Slice | Per frame | Fast |
| Cuboid Void | Per frame | Fast |
| Cuboid Fill | Per frame | Fast |
| Cylinder | Per frame | Fast |
| Rings | Per frame (Phase 1) + per batch (Phase 2) | Fast |
| Slitscan planar | Per column | Fast |
| Slitscan sweep | Per column | Fast |
| Slitscan oblique | Per batch row (64 rows) | Medium — up to 64 rows delay |
| Slit-tear | Per frame | Fast |

**Key fix**: Add cancel checks inside the oblique batch loop at finer granularity.

---

*End of document*
