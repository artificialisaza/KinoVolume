"""Printable unfold PDF generator for cuboid and cylinder visualizations.

Generates a cut-and-fold paper model layout with:
- Face images arranged in a cross pattern (cuboid) or strip + circles (cylinder)
- Fold lines (dashed gray) between adjacent faces
- Cut lines (solid black) on the outer perimeter
- Glue tabs on exposed edges
- Metadata: video name, frame range, date, mode
"""

import io
import math
import os
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw

from reportlab.lib.pagesizes import A3, A4, LEGAL, LETTER
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.utils import ImageReader


# Paper sizes in points (72pt = 1 inch)
PAPER_SIZES = {
    "A4": A4,                    # (595.28, 841.89)
    "A3": A3,                    # (841.89, 1190.55)
    "Letter": LETTER,            # (612.0, 792.0)
    "Legal": LEGAL,              # (612.0, 1008.0)
    "Tabloid": (792.0, 1224.0),  # 11 × 17 inches
}

# Margins in points
MARGIN = 15 * mm  # ~15mm margin around all edges
TAB_SIZE = 8 * mm  # Glue tab width


def export_cuboid_pdf(face_images, dimensions, output_path,
                      paper_size="A4", video_name="", frame_range="",
                      scale_mode="fit"):
    """Generate a printable PDF with cuboid faces in a foldable cross layout.

    Layout — four side strips arranged left→right as B, R, T, L (the
    whole figure is horizontally mirrored compared with the geometric
    derivation so that the printed result reads in the natural
    left-to-right print orientation).  F (first frame) sits above T and
    K (last frame) below B.  F and K attach through the wider frame
    edge (mask_w), which matches T and B width.

                                ┌───────────┐
                                │     F     │  (mask_h × mask_w)
        ┌───────────┬───┬───────┴───────┬───┴┐
        │     B     │ R │      T        │ L  │  all num_frames tall
        └───────────┴──┬┴───────┬───────┴────┘
                       │     K  │            (mask_h × mask_w)
                       └────────┘

    Strip order:  B (mask_w) | R (mask_h) | T (mask_w) | L (mask_h)

    Processor face → Unfold transforms:

    | Pos | Processor         | Transform              | Unfold (H × W)  |
    |-----|-------------------|------------------------|-----------------|
    | L   | left  (mh, nf, C) | transpose(flipud)     | (nf, mh)        |
    | T   | top   (nf, mw, C) | as-is                 | (nf, mw)        |
    | R   | right (mh, nf, C) | transpose              | (nf, mh)        |
    | B   | bottom(nf, mw, C) | fliplr                 | (nf, mw)        |
    | F   | front (mh, mw, C) | flipud                 | (mh, mw)        |
    | K   | back  (mh, mw, C) | flipud(fliplr)         | (mh, mw)        |

    Adjacencies:
      F bottom ↔ T top    : top edge of first frame
      L right  ↔ T left   : top-left corner of each frame
      T right  ↔ R left   : top-right corner of each frame
      R right  ↔ B left   : bottom-right corner of each frame
      K top    ↔ B bottom : bottom edge of last frame (reversed)
      B right  ↔ L left   : bottom-left corner of each frame (wrap/glue)
    """
    page_w, page_h = PAPER_SIZES.get(paper_size, A4)
    usable_w = page_w - 2 * MARGIN
    usable_h = page_h - 2 * MARGIN - 12 * mm  # reserve for metadata

    mask_w = dimensions["width"]
    mask_h = dimensions["height"]
    num_frames = dimensions["depth"]

    # --- Prepare face image arrays with correct orientation ---------------
    def _rgb(img):
        if img is not None and img.ndim == 3 and img.shape[2] == 4:
            return img[:, :, :3]
        return img

    front_raw = _rgb(face_images.get("front"))
    back_raw = _rgb(face_images.get("back"))
    top_raw = _rgb(face_images.get("top"))        # (nf, mw, C)
    bottom_raw = _rgb(face_images.get("bottom"))  # (nf, mw, C)
    left_raw = _rgb(face_images.get("left"))      # (mh, nf, C)
    right_raw = _rgb(face_images.get("right"))    # (mh, nf, C)

    # F: first frame, flipped vertically → (mh, mw)
    f_arr = np.flipud(front_raw) if front_raw is not None else None
    # K: last frame, flipud(fliplr) → (mh, mw)
    k_arr = np.flipud(np.fliplr(back_raw)) if back_raw is not None else None
    # L: left edge, transpose(flipud) → (nf, mh)
    l_arr = np.transpose(np.flipud(left_raw), (1, 0, 2)) if left_raw is not None else None
    # T: top edge, as-is → (nf, mw)
    t_arr = top_raw
    # R: right edge, transpose → (nf, mh)
    r_arr = np.transpose(right_raw, (1, 0, 2)) if right_raw is not None else None
    # B: bottom edge, fliplr → (nf, mw)
    b_arr = np.fliplr(bottom_raw) if bottom_raw is not None else None

    # The whole figure is rendered horizontally mirrored so that
    # cut-and-fold paper assembly produces a model whose front face reads
    # in the natural left-to-right orientation (the geometric derivation
    # alone leaves the print mirrored).  Mirroring is implemented by:
    #   1. Flipping every face image left↔right (here);
    #   2. Reversing the strip order to B|R|T|L (below);
    #   3. Mirroring the cut-path / tab positions accordingly.
    # Face adjacencies (where pixels meet across folds) are preserved
    # because both the strip order *and* the image content are mirrored.
    if f_arr is not None:
        f_arr = np.fliplr(f_arr)
    if k_arr is not None:
        k_arr = np.fliplr(k_arr)
    if l_arr is not None:
        l_arr = np.fliplr(l_arr)
    if t_arr is not None:
        t_arr = np.fliplr(t_arr)
    if r_arr is not None:
        r_arr = np.fliplr(r_arr)
    if b_arr is not None:
        b_arr = np.fliplr(b_arr)

    # --- Proportional sizes (pixel-unit space) ---
    l_wu = mask_h       # L strip width
    t_wu = mask_w       # T strip width (wide — F attaches here)
    r_wu = mask_h       # R strip width
    b_wu = mask_w       # B strip width (wide — K attaches here)
    strip_hu = num_frames

    f_wu = mask_w       # F width  (= T width)
    f_hu = mask_h       # F height
    k_wu = mask_w       # K width  (= B width)
    k_hu = mask_h       # K height

    total_wu = l_wu + t_wu + r_wu + b_wu
    total_hu = f_hu + strip_hu + k_hu

    # --- Scaling ---
    if scale_mode == "stretch":
        # Stretch only the temporal (vertical) dimension to fill the page;
        # spatial proportions (F/K, strip widths) stay uniform.
        scale_x = usable_w / total_wu
        # F/K use scale_x so they stay proportional to the strips
        fk_h = (mask_h * scale_x)  # height of F and K at uniform scale
        remaining_h = usable_h - 2 * fk_h
        scale_y_strips = remaining_h / strip_hu if strip_hu else scale_x
        scale_y = scale_y_strips          # for strip_h
        scale_y_fk = scale_x              # for f_h, k_h (uniform)
    else:  # "fit"
        scale = min(usable_w / total_wu, usable_h / total_hu)
        scale_x = scale_y = scale
        scale_y_fk = scale

    # Rendered dimensions
    l_w = l_wu * scale_x
    t_w = t_wu * scale_x
    r_w = r_wu * scale_x
    b_w = b_wu * scale_x
    strip_h = strip_hu * scale_y
    f_w = f_wu * scale_x
    f_h = f_hu * scale_y_fk
    k_w = k_wu * scale_x
    k_h = k_hu * scale_y_fk

    rendered_total_w = l_w + t_w + r_w + b_w
    rendered_total_h = f_h + strip_h + k_h

    # Center on page
    ox = MARGIN + (usable_w - rendered_total_w) / 2
    oy = MARGIN + 10 * mm + (usable_h - rendered_total_h) / 2

    c = pdf_canvas.Canvas(output_path, pagesize=(page_w, page_h))
    c.setTitle("KinoVolume — Cuboid Unfold")

    # --- Positions (PDF y goes up from bottom) ---
    k_y = oy
    strip_y = k_y + k_h
    f_y = strip_y + strip_h

    # Mirrored strip layout — left→right: B | R | T | L
    b_x = ox
    r_x = b_x + b_w
    t_x = r_x + r_w
    l_x = t_x + t_w

    f_x = t_x          # F above T (same width → aligned)
    k_x = b_x          # K below B (same width → aligned)

    # --- Helper to draw a face image ---
    def draw_face(img_array, x, y, w, h):
        if img_array is None:
            return
        pil_img = Image.fromarray(img_array.astype(np.uint8))
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        buf.seek(0)
        c.drawImage(ImageReader(buf), x, y, width=w, height=h)

    draw_face(l_arr, l_x, strip_y, l_w, strip_h)
    draw_face(t_arr, t_x, strip_y, t_w, strip_h)
    draw_face(r_arr, r_x, strip_y, r_w, strip_h)
    draw_face(b_arr, b_x, strip_y, b_w, strip_h)
    draw_face(f_arr, f_x, f_y, f_w, f_h)
    draw_face(k_arr, k_x, k_y, k_w, k_h)

    # --- Fold lines (dashed gray) ---
    c.setStrokeColorRGB(0.5, 0.5, 0.5)
    c.setLineWidth(0.5)
    c.setDash(3, 3)
    c.line(r_x, strip_y, r_x, strip_y + strip_h)             # B–R
    c.line(t_x, strip_y, t_x, strip_y + strip_h)             # R–T
    c.line(l_x, strip_y, l_x, strip_y + strip_h)             # T–L
    c.line(f_x, f_y, f_x + f_w, f_y)                         # F–T
    c.line(k_x, k_y + k_h, k_x + k_w, k_y + k_h)            # K–B

    # --- Cut lines (solid black perimeter) ---
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.8)
    c.setDash()

    # Outline traced clockwise on the mirrored layout (B leftmost, L rightmost).
    path = c.beginPath()
    path.moveTo(f_x, f_y + f_h)                              # F top-left
    path.lineTo(f_x + f_w, f_y + f_h)                        # → F top-right
    path.lineTo(f_x + f_w, f_y)                              # ↓ F right = T top-right
    path.lineTo(l_x + l_w, strip_y + strip_h)                # → strip top to L top-right
    path.lineTo(l_x + l_w, strip_y)                          # ↓ L right side
    path.lineTo(k_x + k_w, strip_y)                          # ← strip bottom to K right (=B right)
    path.lineTo(k_x + k_w, k_y)                              # ↓ K right
    path.lineTo(k_x, k_y)                                    # ← K bottom-left
    path.lineTo(k_x, strip_y)                                # ↑ K left = B left
    path.lineTo(b_x, strip_y)                                # ← strip bottom to B left (leftmost)
    path.lineTo(b_x, strip_y + strip_h)                      # ↑ B left side
    path.lineTo(f_x, strip_y + strip_h)                      # → strip top to F left
    path.lineTo(f_x, f_y + f_h)                              # ↑ close
    c.drawPath(path, stroke=1, fill=0)

    # --- Glue tabs ---
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setFillColorRGB(0.9, 0.9, 0.9)
    c.setLineWidth(0.4)
    tab = TAB_SIZE

    _draw_tab_top(c, f_x, f_y + f_h, f_w, tab * 1.5)              # F top (long — inserts into cube)
    _draw_tab_bottom(c, k_x, k_y, k_w, tab * 1.5)                # K bottom (long — inserts into cube)
    # Wrap-around tab — on L's right edge (rightmost strip), glues to
    # B's left edge (leftmost strip) when assembled.
    _draw_tab_right(c, l_x + l_w, strip_y, strip_h, tab)
    # Closure tabs on L and R (help hold F/K in place)
    _draw_tab_top(c, l_x, strip_y + strip_h, l_w, tab)           # L top
    _draw_tab_bottom(c, l_x, strip_y, l_w, tab)                  # L bottom
    _draw_tab_top(c, r_x, strip_y + strip_h, r_w, tab)           # R top
    _draw_tab_bottom(c, r_x, strip_y, r_w, tab)                  # R bottom

    # --- Metadata ---
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.setFont("Helvetica", 7)
    meta_parts = ["KinoVolume — Cuboid Unfold"]
    if video_name:
        meta_parts.append(f"Video: {video_name}")
    if frame_range:
        meta_parts.append(f"Frames: {frame_range}")
    meta_parts.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.drawString(MARGIN, MARGIN, "  |  ".join(meta_parts))

    c.save()


def export_cylinder_pdf(face_images, dimensions, output_path,
                        paper_size="A4", video_name="", frame_range="",
                        scale_mode="fit"):
    """Generate a printable PDF for a cylinder: unrolled surface + two caps.

    Layout — caps are placed to the right of the surface rectangle,
    stacked vertically, so the figure uses maximum page area:

        ┌─────────────────────────┬───┐
        │                         │ ○ │  Cap Front
        │   SURFACE (rectangle)   ├───┤
        │                         │ ○ │  Cap Back
        └─────────────────────────┴───┘

    Caps are circular images (white outside the circle) with petal-shaped glue
    tabs around the circumference.
    """
    page_w, page_h = PAPER_SIZES.get(paper_size, A4)
    usable_w = page_w - 2 * MARGIN
    usable_h = page_h - 2 * MARGIN - 12 * mm

    surface_img = face_images.get("surface")
    cap_front = face_images.get("cap_front")
    cap_back = face_images.get("cap_back")

    if surface_img is None:
        return

    s_h, s_w = surface_img.shape[:2]
    cap_diam = cap_front.shape[0] if cap_front is not None else 0
    has_caps = cap_diam > 0 and (cap_front is not None or cap_back is not None)

    gap = 5 * mm
    petal_tab = TAB_SIZE * 0.8  # petal protrusion from circle

    if has_caps:
        # Vertical space for two stacked caps: each cap circle + petals on
        # outer edges + petals between the two caps (must not overlap).
        # cap_gap = gap between circle edges, big enough for two petal tabs.
        cap_gap = gap + 2 * petal_tab

        if scale_mode == "stretch":
            # Spatial uniform, temporal stretches
            scale_x = (usable_w - gap - 2 * petal_tab) / (s_w + cap_diam)
            cd_pts = cap_diam * scale_x
            caps_stack_h = 2 * cd_pts + cap_gap + 2 * petal_tab  # outer petals
            scale_y = usable_h / s_h
            sw = s_w * scale_x
            sh = s_h * scale_y
        else:
            # Fit: uniform scale, constrained by tightest axis
            # Horizontal: usable_w = s_w*s + gap + cap_diam*s + 2*petal_tab
            sx_budget = (usable_w - gap - 2 * petal_tab) / (s_w + cap_diam)
            # Vertical (surface): usable_h / s_h
            sy_surf = usable_h / s_h
            # Vertical (caps): usable_h = 2*cap_diam*s + cap_gap + 2*petal_tab
            sy_caps = (usable_h - cap_gap - 2 * petal_tab) / (2 * cap_diam) if cap_diam else 999
            scale_fit = min(sx_budget, sy_surf, sy_caps)
            scale_x = scale_y = scale_fit
            sw = s_w * scale_x
            sh = s_h * scale_y
            cd_pts = cap_diam * scale_x
            caps_stack_h = 2 * cd_pts + cap_gap + 2 * petal_tab

        cap_col_w = cd_pts + 2 * petal_tab
        total_rendered_w = sw + gap + cap_col_w
        total_rendered_h = max(sh, caps_stack_h)
    else:
        if scale_mode == "stretch":
            scale_x = usable_w / s_w
            scale_y = usable_h / s_h
        else:
            scale_x = scale_y = min(usable_w / s_w, usable_h / s_h)
        sw = s_w * scale_x
        sh = s_h * scale_y
        total_rendered_w = sw
        total_rendered_h = sh

    c = pdf_canvas.Canvas(output_path, pagesize=(page_w, page_h))
    c.setTitle("KinoVolume — Cylinder Unfold")

    # Center the whole layout on the page
    ox = MARGIN + (usable_w - total_rendered_w) / 2
    oy = MARGIN + 10 * mm + (usable_h - total_rendered_h) / 2

    # Surface position (left side, vertically centered)
    sx = ox
    sy = oy + (total_rendered_h - sh) / 2

    pil_surf = Image.fromarray(surface_img.astype(np.uint8))
    buf = io.BytesIO()
    pil_surf.save(buf, format="PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), sx, sy, width=sw, height=sh)

    # Cut line around surface
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.8)
    c.rect(sx, sy, sw, sh, stroke=1, fill=0)

    # Glue tab on the right edge (for wrapping the cylinder)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setFillColorRGB(0.9, 0.9, 0.9)
    _draw_tab_right(c, sx + sw, sy, sh, TAB_SIZE)

    # --- Caps (to the right of the surface) ---
    if has_caps:
        cap_col_x = sx + sw + gap + petal_tab  # left edge of cap column
        cap_gap = gap + 2 * petal_tab  # room for petals between caps
        # Stack caps vertically, centered with surface
        cap_base_y = sy + (sh - (2 * cd_pts + cap_gap)) / 2

        for i, (cap_img, label) in enumerate([
            (cap_front, "Front Cap"),
            (cap_back, "Back Cap"),
        ]):
            if cap_img is None:
                continue

            if i == 0:
                cap_y = cap_base_y + cd_pts + cap_gap  # upper
            else:
                cap_y = cap_base_y  # lower

            cap_x = cap_col_x

            _draw_circular_cap(c, cap_img, cap_x, cap_y, cd_pts)

            c.setStrokeColorRGB(0, 0, 0)
            c.setLineWidth(0.8)
            cx = cap_x + cd_pts / 2
            cy = cap_y + cd_pts / 2
            c.circle(cx, cy, cd_pts / 2, stroke=1, fill=0)

            _draw_petal_tabs(c, cx, cy, cd_pts / 2, n_petals=8,
                             tab_size=petal_tab)

            c.setFont("Helvetica", 6)
            c.setFillColorRGB(0.4, 0.4, 0.4)
            c.drawCentredString(cx, cap_y - 8, label)

    # --- Metadata ---
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.setFont("Helvetica", 7)
    meta_parts = ["KinoVolume — Cylinder Unfold"]
    if video_name:
        meta_parts.append(f"Video: {video_name}")
    if frame_range:
        meta_parts.append(f"Frames: {frame_range}")
    meta_parts.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.drawString(MARGIN, MARGIN, "  |  ".join(meta_parts))

    c.save()


# ---------------------------------------------------------------------------
# Circular cap helpers
# ---------------------------------------------------------------------------

def _draw_circular_cap(c, cap_array, x, y, size):
    """Draw a cap image clipped to a circle (white outside)."""
    pil_img = Image.fromarray(cap_array.astype(np.uint8)).convert("RGBA")
    w, h = pil_img.size

    # Create circular mask
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([0, 0, w - 1, h - 1], fill=255)

    # Composite onto white background
    bg = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    bg.paste(pil_img, (0, 0), mask)
    result = bg.convert("RGB")

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    buf.seek(0)
    c.drawImage(ImageReader(buf), x, y, width=size, height=size)


def _draw_petal_tabs(c, cx, cy, radius, n_petals=8, tab_size=6 * mm):
    """Draw petal-shaped glue tabs around a circle for folding/gluing."""
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setFillColorRGB(0.92, 0.92, 0.92)
    c.setLineWidth(0.4)

    angle_step = 2 * math.pi / n_petals
    half_arc = angle_step * 0.4  # petal spans 80% of the sector

    for i in range(n_petals):
        theta = i * angle_step
        # Start and end points on the circle
        a1 = theta - half_arc
        a2 = theta + half_arc

        x1 = cx + radius * math.cos(a1)
        y1 = cy + radius * math.sin(a1)
        x2 = cx + radius * math.cos(a2)
        y2 = cy + radius * math.sin(a2)

        # Outer point of the petal
        ox = cx + (radius + tab_size) * math.cos(theta)
        oy = cy + (radius + tab_size) * math.sin(theta)

        path = c.beginPath()
        path.moveTo(x1, y1)
        path.lineTo(ox, oy)
        path.lineTo(x2, y2)
        c.drawPath(path, stroke=1, fill=1)


# ---------------------------------------------------------------------------
# Tab drawing helpers
# ---------------------------------------------------------------------------

def _draw_tab_top(c, x, y, width, tab_h):
    """Draw a trapezoidal glue tab above the edge from (x,y) to (x+width,y)."""
    inset = tab_h * 0.4
    path = c.beginPath()
    path.moveTo(x, y)
    path.lineTo(x + inset, y + tab_h)
    path.lineTo(x + width - inset, y + tab_h)
    path.lineTo(x + width, y)
    c.drawPath(path, stroke=1, fill=1)


def _draw_tab_bottom(c, x, y, width, tab_h):
    """Draw a trapezoidal glue tab below the edge from (x,y) to (x+width,y)."""
    inset = tab_h * 0.4
    path = c.beginPath()
    path.moveTo(x, y)
    path.lineTo(x + inset, y - tab_h)
    path.lineTo(x + width - inset, y - tab_h)
    path.lineTo(x + width, y)
    c.drawPath(path, stroke=1, fill=1)


def _draw_tab_left(c, x, y, height, tab_w):
    """Draw a trapezoidal glue tab to the left of edge from (x,y) to (x,y+height)."""
    inset = tab_w * 0.4
    path = c.beginPath()
    path.moveTo(x, y)
    path.lineTo(x - tab_w, y + inset)
    path.lineTo(x - tab_w, y + height - inset)
    path.lineTo(x, y + height)
    c.drawPath(path, stroke=1, fill=1)


def _draw_tab_right(c, x, y, height, tab_w):
    """Draw a trapezoidal glue tab to the right of edge from (x,y) to (x,y+height)."""
    inset = tab_w * 0.4
    path = c.beginPath()
    path.moveTo(x, y)
    path.lineTo(x + tab_w, y + inset)
    path.lineTo(x + tab_w, y + height - inset)
    path.lineTo(x, y + height)
    c.drawPath(path, stroke=1, fill=1)
