#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# install.sh — KinoVolume installer for macOS
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/artificialisaza/KinoVolume/main/install.sh | bash
#
# This script downloads KinoVolume from GitHub Releases and installs it
# to /Applications. Using curl (instead of a browser) avoids the
# com.apple.quarantine extended attribute that causes macOS to show
# "damaged, move to Trash" or "malicious software" warnings for
# ad-hoc signed apps.
# ---------------------------------------------------------------------------

set -euo pipefail

REPO="artificialisaza/KinoVolume"
APP_NAME="KinoVolume"
INSTALL_DIR="/Applications"

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}›${NC} $1"; }
ok()    { echo -e "${GREEN}✓${NC} $1"; }
warn()  { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

# ---- Check macOS ----
if [[ "$(uname)" != "Darwin" ]]; then
    error "This installer is for macOS only."
    exit 1
fi

# ---- Determine architecture ----
ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
    PLATFORM="Apple Silicon"
elif [[ "$ARCH" == "x86_64" ]]; then
    PLATFORM="Intel"
else
    error "Unsupported architecture: $ARCH"
    exit 1
fi

info "Detected: macOS on $PLATFORM"

# ---- Determine latest release ----
info "Fetching latest release from GitHub…"
LATEST_TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | python3 -c "import sys, json; print(json.load(sys.stdin).get('tag_name', ''))" 2>/dev/null || echo "")"

if [[ -z "$LATEST_TAG" ]]; then
    # Fallback: use the releases list
    LATEST_TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases" | python3 -c "import sys, json; releases = json.load(sys.stdin); print(releases[0]['tag_name'] if releases else '')" 2>/dev/null || echo "")"
fi

if [[ -z "$LATEST_TAG" ]]; then
    error "Could not determine latest release. Check your internet connection."
    exit 1
fi

info "Latest release: v$LATEST_TAG"

# ---- Find the PKG asset ----
info "Looking for download assets…"
ASSETS_JSON="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/tags/$LATEST_TAG")"

# Try to find a PKG first, then DMG, then ZIP
PKG_URL="$(echo "$ASSETS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset.get('name', '')
    if name.endswith('.pkg'):
        print(asset['browser_download_url'])
        break
" 2>/dev/null || echo "")"

DMG_URL="$(echo "$ASSETS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset.get('name', '')
    if name.endswith('.dmg'):
        print(asset['browser_download_url'])
        break
" 2>/dev/null || echo "")"

ZIP_URL="$(echo "$ASSETS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset.get('name', '')
    if name.endswith('.zip'):
        print(asset['browser_download_url'])
        break
" 2>/dev/null || echo "")"

# ---- Download and install ----
TMPDIR="$(mktemp -d /tmp/kinovolume_install.XXXXXX)"
cleanup() {
    rm -rf "$TMPDIR"
}
trap cleanup EXIT

if [[ -n "$PKG_URL" ]]; then
    # ---- PKG installation (preferred) ----
    info "Found PKG installer. Downloading…"
    PKG_FILE="$TMPDIR/KinoVolume-$LATEST_TAG.pkg"
    curl -fSL -o "$PKG_FILE" "$PKG_URL"
    ok "Downloaded PKG ($(du -h "$PKG_FILE" | cut -f1))"

    info "Installing to $INSTALL_DIR (admin password required)…"
    sudo installer -pkg "$PKG_FILE" -target /
    ok "Installation complete."

elif [[ -n "$DMG_URL" ]]; then
    # ---- DMG installation ----
    info "Found DMG image. Downloading…"
    DMG_FILE="$TMPDIR/KinoVolume-$LATEST_TAG.dmg"
    curl -fSL -o "$DMG_FILE" "$DMG_URL"
    ok "Downloaded DMG ($(du -h "$DMG_FILE" | cut -f1))"

    info "Mounting DMG…"
    MOUNT_POINT="$(hdiutil attach "$DMG_FILE" -nobrowse -quiet | awk '/\/Volumes\// {print $NF}' | head -1)"

    if [[ -z "$MOUNT_POINT" ]]; then
        error "Failed to mount DMG."
        exit 1
    fi

    # Find the .app inside the mounted DMG
    APP_IN_DMG="$(find "$MOUNT_POINT" -maxdepth 1 -name "*.app" -type d | head -1)"

    if [[ -z "$APP_IN_DMG" ]]; then
        error "No .app found in DMG."
        hdiutil detach "$MOUNT_POINT" -quiet
        exit 1
    fi

    info "Copying to $INSTALL_DIR…"
    if [[ -d "$INSTALL_DIR/$APP_NAME.app" ]]; then
        warn "Existing $APP_NAME.app found. Replacing…"
        rm -rf "$INSTALL_DIR/$APP_NAME.app"
    fi
    ditto "$APP_IN_DMG" "$INSTALL_DIR/$APP_NAME.app"

    info "Unmounting DMG…"
    hdiutil detach "$MOUNT_POINT" -quiet

    # Strip quarantine (safety net — curl shouldn't add it, but just in case)
    info "Removing quarantine attributes…"
    xattr -cr "$INSTALL_DIR/$APP_NAME.app" 2>/dev/null || true

    ok "Installation complete."

elif [[ -n "$ZIP_URL" ]]; then
    # ---- ZIP installation ----
    info "Found ZIP archive. Downloading…"
    ZIP_FILE="$TMPDIR/KinoVolume-$LATEST_TAG.zip"
    curl -fSL -o "$ZIP_FILE" "$ZIP_URL"
    ok "Downloaded ZIP ($(du -h "$ZIP_FILE" | cut -f1))"

    info "Extracting…"
    ditto -x -k "$ZIP_FILE" "$TMPDIR/"

    APP_IN_ZIP="$(find "$TMPDIR" -maxdepth 2 -name "*.app" -type d | head -1)"

    if [[ -z "$APP_IN_ZIP" ]]; then
        error "No .app found in ZIP."
        exit 1
    fi

    info "Copying to $INSTALL_DIR…"
    if [[ -d "$INSTALL_DIR/$APP_NAME.app" ]]; then
        warn "Existing $APP_NAME.app found. Replacing…"
        rm -rf "$INSTALL_DIR/$APP_NAME.app"
    fi
    ditto "$APP_IN_ZIP" "$INSTALL_DIR/$APP_NAME.app"

    # Strip quarantine
    info "Removing quarantine attributes…"
    xattr -cr "$INSTALL_DIR/$APP_NAME.app" 2>/dev/null || true

    ok "Installation complete."

else
    error "No suitable download found for release v$LATEST_TAG."
    error "Expected a .pkg, .dmg, or .zip file in the release assets."
    exit 1
fi

# ---- Verify installation ----
if [[ -d "$INSTALL_DIR/$APP_NAME.app" ]]; then
    ok "$APP_NAME is installed at $INSTALL_DIR/$APP_NAME.app"

    # Check for quarantine
    QUARANTINE="$(xattr "$INSTALL_DIR/$APP_NAME.app" 2>/dev/null | grep quarantine || echo "")"
    if [[ -n "$QUARANTINE" ]]; then
        warn "Quarantine attribute detected. Removing…"
        xattr -cr "$INSTALL_DIR/$APP_NAME.app" 2>/dev/null || true
    fi

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  KinoVolume v$LATEST_TAG installed successfully!  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  To launch:"
    echo "    open -a KinoVolume"
    echo ""
    echo "  Or find it in Spotlight / Launchpad / Applications folder."
else
    error "Installation may have failed. $APP_NAME.app not found in $INSTALL_DIR."
    exit 1
fi