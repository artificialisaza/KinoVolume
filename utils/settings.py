import os
import json

SETTINGS_FILE = os.path.expanduser("~/.kinovolume_settings.json")

def save_last_output_dir(path):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"output_dir": path}, f)
    except Exception:
        pass

def load_last_output_dir():
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
            return data.get("output_dir", "")
    except Exception:
        return ""
