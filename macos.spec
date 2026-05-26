# macos.spec  — run from the deep_vid_visualizer/ directory:
#   pyinstaller macos.spec

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources/icons',    'resources/icons'),
        ('resources/styles',   'resources/styles'),
        ('resources/models',   'resources/models'),
        ('config.py',          '.'),
    ],
    hiddenimports=[
        'pyvista',
        'pyvistaqt',
        'cv2',
        'numpy',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KinoVolume',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon='resources/icons/KinoVolume.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='KinoVolume',
)

app = BUNDLE(
    coll,
    name='KinoVolume.app',
    icon='resources/icons/KinoVolume.icns',
    bundle_identifier='com.geocinema.kinovolume',
    info_plist={
        'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
        'CFBundleShortVersionString': '0.4',
    },
)

# PyInstaller 6 workaround: BUNDLE(coll) leaves MacOS/ empty on macOS arm64.
# Copy the COLLECT output into the .app bundle manually.
import os, shutil
_app_macos = os.path.join(
    os.path.dirname(os.path.abspath(SPEC)),
    'dist', 'KinoVolume.app', 'Contents', 'MacOS'
)
_collect_dir = os.path.join(
    os.path.dirname(os.path.abspath(SPEC)),
    'dist', 'KinoVolume'
)
if os.path.isdir(_collect_dir) and os.path.isdir(_app_macos):
    for _item in os.listdir(_collect_dir):
        _src = os.path.join(_collect_dir, _item)
        _dst = os.path.join(_app_macos, _item)
        if os.path.lexists(_dst):
            continue

        if os.path.islink(_src):
            os.symlink(os.readlink(_src), _dst)
        elif os.path.isdir(_src):
            shutil.copytree(_src, _dst, symlinks=True)
        else:
            shutil.copy2(_src, _dst, follow_symlinks=False)
