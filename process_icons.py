"""One-shot script to process temp icons into resources/icons/ for the dark theme."""
from PIL import Image, ImageDraw
import numpy as np
import os

icons_dir = "resources/icons"
temp_dir = "temp"
os.makedirs(icons_dir, exist_ok=True)


def tint_icon(src_path, dst_name, color=(224, 224, 224), rotate=0, flip_h=False):
    img = Image.open(src_path).convert("RGBA")
    if flip_h:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    arr = np.array(img, dtype=np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    luminosity = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    icon_alpha = np.clip((1.0 - luminosity) * (a / 255.0), 0, 1)
    out = np.zeros_like(arr)
    out[:, :, 0] = color[0]
    out[:, :, 1] = color[1]
    out[:, :, 2] = color[2]
    out[:, :, 3] = (icon_alpha * 255).clip(0, 255).astype(np.uint8)
    result = Image.fromarray(out.astype(np.uint8), "RGBA")
    if rotate:
        result = result.rotate(rotate, expand=True)
    result = result.resize((32, 32), Image.LANCZOS)
    dst = os.path.join(icons_dir, dst_name)
    result.save(dst)
    print(f"  saved {dst}")


# Camera icon
tint_icon(f"{temp_dir}/camera.png", "camera.png")

# Zoom icons (replace old magnifying-glass with +/-)
tint_icon(f"{temp_dir}/plus.png", "zoom-in.png")
tint_icon(f"{temp_dir}/minus.png", "zoom-out.png")

# Rotation icons
tint_icon(f"{temp_dir}/rotate-right.png", "rotate-cw.png")
tint_icon(f"{temp_dir}/rotate-right.png", "rotate-ccw.png", flip_h=True)

# Directional arrow icons (right=0, up=90, left=180, down=-90 / 270)
tint_icon(f"{temp_dir}/right-arrow.png", "arrow-right.png", rotate=0)
tint_icon(f"{temp_dir}/right-arrow.png", "arrow-left.png", rotate=180)
tint_icon(f"{temp_dir}/right-arrow.png", "arrow-up.png", rotate=90)
tint_icon(f"{temp_dir}/right-arrow.png", "arrow-down.png", rotate=270)

# Background-color icon: circle outline + small filled square in centre
bg_img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
draw = ImageDraw.Draw(bg_img)
draw.ellipse([2, 2, 29, 29], outline=(224, 224, 224, 255), width=2)
draw.rectangle([12, 12, 19, 19], fill=(224, 224, 224, 200))
bg_img.save(os.path.join(icons_dir, "bg-color.png"))
print("  saved resources/icons/bg-color.png")

print("Done!")

# Info icon
tint_icon(f"{temp_dir}/info.png", "info.png")
