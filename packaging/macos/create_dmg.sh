#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: create_dmg.sh [APP_PATH] [OUTPUT_DMG]

Creates a compressed macOS DMG with:
- the app bundle
- an Applications symlink for drag-and-drop install
- Finder icon layout (best effort)

Defaults:
- APP_PATH:   dist/KinoVolume.app
- OUTPUT_DMG: dist/<app-name>-v<version>.dmg
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEFAULT_APP="$PROJECT_ROOT/dist/KinoVolume.app"

APP_PATH="${1:-$DEFAULT_APP}"
if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found: $APP_PATH"
  exit 1
fi

APP_PATH="$(cd "$(dirname "$APP_PATH")" && pwd)/$(basename "$APP_PATH")"
APP_NAME="$(basename "$APP_PATH")"
APP_STEM="${APP_NAME%.app}"

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_PATH/Contents/Info.plist" 2>/dev/null || true)"
if [[ -z "$VERSION" ]]; then
  VERSION="0.0"
fi

VOL_NAME="$APP_STEM Installer"
OUT_DIR="$PROJECT_ROOT/dist"
OUT_DMG="$OUT_DIR/${APP_STEM// /-}-v${VERSION}.dmg"

if [[ -n "${2:-}" ]]; then
  if [[ "${2}" = /* ]]; then
    OUT_DMG="${2}"
  else
    OUT_DMG="$PROJECT_ROOT/${2}"
  fi
fi

mkdir -p "$(dirname "$OUT_DMG")"

WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.dmg_build.XXXXXX")"
STAGE_DIR="$WORK_DIR/stage"
RW_DMG="$WORK_DIR/temp_rw.dmg"
MOUNT_POINT=""

cleanup() {
  if [[ -n "$MOUNT_POINT" ]] && mount | grep -Fq "on $MOUNT_POINT "; then
    hdiutil detach "$MOUNT_POINT" -quiet || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$STAGE_DIR"
ditto "$APP_PATH" "$STAGE_DIR/$APP_NAME"
ln -s /Applications "$STAGE_DIR/Applications"

hdiutil create -volname "$VOL_NAME" -srcfolder "$STAGE_DIR" -ov -format UDRW "$RW_DMG" >/dev/null

ATTACH_OUTPUT="$(hdiutil attach "$RW_DMG" -readwrite -noverify -noautoopen)"
MOUNT_POINT="$(echo "$ATTACH_OUTPUT" | awk '/\/Volumes\// {print substr($0, index($0, "/Volumes/")); exit}')"
if [[ -z "$MOUNT_POINT" ]]; then
  echo "Failed to determine DMG mount point."
  exit 1
fi

# Best effort: customize Finder window for drag-and-drop install UX.
if osascript <<EOF >/dev/null 2>&1
tell application "Finder"
  tell disk "$VOL_NAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set bounds of container window to {140, 120, 760, 460}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 128
    set text size of viewOptions to 13
    set position of item "$APP_NAME" to {170, 180}
    set position of item "Applications" to {450, 180}
    close
    open
    update without registering applications
    delay 1
  end tell
end tell
EOF
then
  :
else
  echo "Warning: could not apply Finder layout (permissions/headless). Continuing."
fi

sync
hdiutil detach "$MOUNT_POINT" -quiet
MOUNT_POINT=""

# UDZO is zlib-compressed and lossless.
hdiutil convert "$RW_DMG" -ov -format UDZO -imagekey zlib-level=9 -o "$OUT_DMG" >/dev/null

echo "Created DMG: $OUT_DMG"
du -sh "$OUT_DMG"
