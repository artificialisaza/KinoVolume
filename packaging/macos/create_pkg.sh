#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# create_pkg.sh — Creates a macOS PKG installer from KinoVolume.app
#
# Why a PKG? On macOS 26 (Tahoe), ad-hoc signed apps downloaded from the web
# show "damaged, move to Trash" because the browser applies a quarantine
# extended attribute that Gatekeeper rejects for ad-hoc signatures.
#
# A PKG installer solves this because:
# 1. Installer.app copies files to /Applications WITHOUT propagating quarantine
# 2. The postinstall script explicitly strips any quarantine xattr
# 3. The PKG itself only shows "unidentified developer" (bypassable via
#    right-click → Open), NOT "damaged"
#
# Usage: create_pkg.sh [APP_PATH] [OUTPUT_PKG]
# ---------------------------------------------------------------------------

usage() {
  cat <<'EOF'
Usage: create_pkg.sh [APP_PATH] [OUTPUT_PKG]

Creates a PKG installer that installs the app to /Applications and
strips quarantine attributes via a postinstall script.

Defaults:
- APP_PATH:    dist/KinoVolume.app
- OUTPUT_PKG:  dist/KinoVolume-v<version>.pkg
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

BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist" 2>/dev/null || echo "com.geocinema.kinovolume")"

OUT_DIR="$PROJECT_ROOT/dist"
OUT_PKG="$OUT_DIR/${APP_STEM// /-}-v${VERSION}.pkg"

if [[ -n "${2:-}" ]]; then
  if [[ "${2}" = /* ]]; then
    OUT_PKG="${2}"
  else
    OUT_PKG="$PROJECT_ROOT/${2}"
  fi
fi

mkdir -p "$(dirname "$OUT_PKG")"

# pkgbuild/productbuild need a writable TMPDIR. The system TemporaryItems
# folder may have permission issues on some macOS installations.
CUSTOM_TMP="$PROJECT_ROOT/.pkg_tmp"
mkdir -p "$CUSTOM_TMP"
export TMPDIR="$CUSTOM_TMP/"

WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.pkg_build.XXXXXX")"
STAGE_ROOT="$WORK_DIR/root"
SCRIPTS_DIR="$WORK_DIR/scripts"

cleanup() {
  rm -rf "$WORK_DIR" "$CUSTOM_TMP"
}
trap cleanup EXIT

echo "=== Creating PKG installer ==="
echo "  App:        $APP_PATH"
echo "  Version:    $VERSION"
echo "  Bundle ID:  $BUNDLE_ID"
echo "  Output:     $OUT_PKG"
echo ""

# ---- Stage the app into /Applications structure ----
echo "  Staging app bundle …"
mkdir -p "$STAGE_ROOT/Applications"
ditto "$APP_PATH" "$STAGE_ROOT/Applications/$APP_NAME"

# ---- Create postinstall script ----
# This runs after the app is copied to /Applications.
# It strips all extended attributes (including com.apple.quarantine)
# from the installed app, preventing the "damaged, move to Trash" error.
echo "  Creating postinstall script …"
mkdir -p "$SCRIPTS_DIR"
cat > "$SCRIPTS_DIR/postinstall" <<'POSTINSTALL'
#!/usr/bin/env bash
# postinstall — runs after KinoVolume.app is installed to /Applications
#
# Strips all extended attributes (especially com.apple.quarantine) from
# the installed app. This prevents macOS Gatekeeper from showing
# "damaged, move to Trash" for ad-hoc signed apps.

set -e

APP_PATH="/Applications/KinoVolume.app"

if [[ ! -d "$APP_PATH" ]]; then
    echo "Warning: $APP_PATH not found after installation."
    exit 0
fi

# Remove all extended attributes recursively (including quarantine)
echo "Removing quarantine attributes from $APP_PATH …"
xattr -cr "$APP_PATH" 2>/dev/null || true

# Verify the app bundle is intact
if [[ -x "$APP_PATH/Contents/MacOS/KinoVolume" ]]; then
    echo "KinoVolume installed successfully."
else
    echo "Warning: Main executable not found in $APP_PATH"
fi

exit 0
POSTINSTALL
chmod 755 "$SCRIPTS_DIR/postinstall"

# ---- Build the PKG ----
echo "  Building PKG with pkgbuild …"
pkgbuild \
    --root "$STAGE_ROOT" \
    --scripts "$SCRIPTS_DIR" \
    --identifier "$BUNDLE_ID" \
    --version "$VERSION" \
    --install-location "/" \
    "$OUT_PKG"

echo ""
echo "  ✓ PKG installer created: $OUT_PKG"
du -sh "$OUT_PKG"
echo ""
echo "  Distribution instructions:"
echo "    Users download the .pkg, double-click to open Installer,"
echo "    follow prompts (admin password required), and the app is"
echo "    installed to /Applications with quarantine stripped."
echo "    If macOS says 'unidentified developer' on the PKG itself,"
echo "    right-click → Open, or System Settings → Privacy & Security."