import os
from PIL import Image
import glob

# Ensure output directory for compressed images
os.chdir('/Users/isaza/Documents/GitHub/KinoVolume/docs/images/outputs')

for filepath in glob.glob('*.png'):
    filename = os.path.basename(filepath)
    name, ext = os.path.splitext(filename)
    # create jpg version
    out_path = f"{name}.jpg"
    
    with Image.open(filepath) as img:
        # Convert rgba to rgb
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # calculate new dimensions
        width, height = img.size
        # limit max width or height to 2000 for web view
        max_dim = 2000
        if width > max_dim or height > max_dim:
            if width > height:
                new_width = max_dim
                new_height = int(max_dim * height / width)
            else:
                new_height = max_dim
                new_width = int(max_dim * width / height)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        img.save(out_path, format="JPEG", quality=85)
        print(f"Saved {out_path}")
