#!/bin/bash
# ============================================================
#  RetryClicker — macOS App Builder
#  Builds a fully-packaged RetryClicker.app + optional .dmg
#  Compatible with macOS Tahoe (26) / Sequoia (15) / Sonoma (14)
#
#  Usage:
#    chmod +x build_mac_app.sh
#    ./build_mac_app.sh
#
#  Optional — sign + notarise:
#    SIGN_ID="Developer ID Application: Your Name (TEAMID)" \
#    APPLE_ID="you@example.com" \
#    APP_PASSWORD="xxxx-xxxx-xxxx-xxxx" \
#    TEAM_ID="XXXXXXXXXX" \
#    ./build_mac_app.sh
# ============================================================

set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
RESET="\033[0m"

APP_NAME="RetryClicker"
BUNDLE_ID="com.retryclicker.app"
VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
APP_PATH="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/${APP_NAME}_${VERSION}.dmg"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   RetryClicker — macOS App Builder   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"
echo ""

# ── Step 1: Check Python & pip ────────────────────────────────────────────
echo -e "${BOLD}[1/7] Checking Python 3...${RESET}"
if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}Python 3 not found. Install from https://www.python.org${RESET}"
    exit 1
fi
PY_VER=$(python3 --version)
echo -e "  ${GREEN}Found: $PY_VER${RESET}"

# ── Step 2: Check / install Homebrew deps ─────────────────────────────────
echo ""
echo -e "${BOLD}[2/7] Checking Homebrew dependencies...${RESET}"
if ! command -v brew &>/dev/null; then
    echo -e "  ${YELLOW}Homebrew not found — installing...${RESET}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Tesseract
if command -v tesseract &>/dev/null; then
    echo -e "  ${GREEN}Tesseract: $(tesseract --version | head -1)${RESET}"
else
    echo "  Installing Tesseract via Homebrew..."
    brew install tesseract
fi

# Python-tk for tkinter (Homebrew python@3.x ships it separately)
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if ! python3 -c "import tkinter" &>/dev/null 2>&1; then
    echo "  Installing python-tk..."
    brew install "python-tk@3.$PY_MINOR" 2>/dev/null || brew install python-tk
fi
echo -e "  ${GREEN}tkinter OK${RESET}"

# ── Step 3: Install Python packages ───────────────────────────────────────
echo ""
echo -e "${BOLD}[3/7] Installing Python packages...${RESET}"
pip3 install --quiet --upgrade \
    mss pyautogui pillow pytesseract opencv-python pyinstaller

echo -e "  ${GREEN}All packages installed.${RESET}"

# ── Step 4: Generate app icon (if no .icns present) ───────────────────────
echo ""
echo -e "${BOLD}[4/7] Preparing app icon...${RESET}"
cd "$SCRIPT_DIR"
if [ ! -f "AppIcon.icns" ]; then
    echo "  Generating placeholder icon..."
    # Create a simple 1024×1024 PNG via Python + Pillow, then convert
    python3 - <<'PYEOF'
from PIL import Image, ImageDraw, ImageFont
import os

size = 1024
img = Image.new("RGBA", (size, size), (13, 15, 24, 255))
draw = ImageDraw.Draw(img)

# Gradient-like background circle
for r in range(size//2, 0, -1):
    ratio = r / (size//2)
    col = (
        int(12 + ratio * 112),
        int(15 + ratio * 99),
        int(24 + ratio * 239),
        255
    )
    draw.ellipse([size//2-r, size//2-r, size//2+r, size//2+r], fill=col)

# "RC" text
try:
    font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 420)
except Exception:
    font = ImageFont.load_default()

text = "RC"
bbox = draw.textbbox((0, 0), text, font=font)
tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
draw.text(((size-tw)//2 - bbox[0], (size-th)//2 - bbox[1] - 20),
          text, fill=(167, 139, 250, 255), font=font)

# Save as PNG first
img.save("/tmp/AppIcon_1024.png")
print("  Icon PNG created")
PYEOF

    # Build .icns from PNG using iconutil
    mkdir -p /tmp/AppIcon.iconset
    for RES in 16 32 64 128 256 512 1024; do
        sips -z $RES $RES /tmp/AppIcon_1024.png \
             --out "/tmp/AppIcon.iconset/icon_${RES}x${RES}.png" &>/dev/null
        if [ $RES -le 512 ]; then
            R2=$((RES*2))
            sips -z $R2 $R2 /tmp/AppIcon_1024.png \
                 --out "/tmp/AppIcon.iconset/icon_${RES}x${RES}@2x.png" &>/dev/null
        fi
    done
    iconutil -c icns /tmp/AppIcon.iconset -o "$SCRIPT_DIR/AppIcon.icns"
    echo -e "  ${GREEN}AppIcon.icns created.${RESET}"
else
    echo -e "  ${GREEN}AppIcon.icns found.${RESET}"
fi

# ── Step 5: PyInstaller build ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}[5/7] Building .app with PyInstaller...${RESET}"
cd "$SCRIPT_DIR"

# Clean previous build
rm -rf build dist __pycache__

pyinstaller RetryClicker.spec --noconfirm 2>&1 | grep -E "(INFO|WARNING|ERROR|Building)" || true

if [ ! -d "$APP_PATH" ]; then
    echo -e "  ${RED}Build failed — $APP_PATH not found.${RESET}"
    exit 1
fi
echo -e "  ${GREEN}Build complete: $APP_PATH${RESET}"

# ── Step 6: Code signing ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[6/7] Code signing...${RESET}"
if [ -n "$SIGN_ID" ]; then
    echo "  Signing with: $SIGN_ID"
    codesign --force --deep --options runtime \
             --entitlements "$SCRIPT_DIR/entitlements.plist" \
             --sign "$SIGN_ID" "$APP_PATH"
    echo -e "  ${GREEN}Signed.${RESET}"

    # Notarise if credentials provided
    if [ -n "$APPLE_ID" ] && [ -n "$APP_PASSWORD" ] && [ -n "$TEAM_ID" ]; then
        echo "  Creating ZIP for notarization..."
        ditto -c -k --keepParent "$APP_PATH" /tmp/RetryClicker_notarize.zip
        echo "  Submitting to Apple notary service..."
        xcrun notarytool submit /tmp/RetryClicker_notarize.zip \
            --apple-id "$APPLE_ID" \
            --password "$APP_PASSWORD" \
            --team-id "$TEAM_ID" \
            --wait
        echo "  Stapling notarization ticket..."
        xcrun stapler staple "$APP_PATH"
        echo -e "  ${GREEN}Notarized & stapled.${RESET}"
    else
        echo -e "  ${YELLOW}Skipping notarization (set APPLE_ID, APP_PASSWORD, TEAM_ID to enable).${RESET}"
    fi
else
    # Ad-hoc sign — allows running locally without a Developer account
    echo "  No SIGN_ID set — applying ad-hoc signature (local use only)..."
    codesign --force --deep --options runtime \
             --entitlements "$SCRIPT_DIR/entitlements.plist" \
             --sign - "$APP_PATH"
    echo -e "  ${GREEN}Ad-hoc signed.${RESET}"
fi

# ── Step 7: Build DMG ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[7/7] Creating DMG installer...${RESET}"

# Use create-dmg if available, otherwise plain hdiutil
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "RetryClicker" \
        --background "/System/Library/Desktop Pictures/Solid Colors/Space Gray Pro.png" \
        --window-pos 200 120 \
        --window-size 660 400 \
        --icon-size 128 \
        --icon "RetryClicker.app" 170 180 \
        --hide-extension "RetryClicker.app" \
        --app-drop-link 490 180 \
        "$DMG_PATH" \
        "$DIST_DIR/" 2>/dev/null || true
else
    # Fallback: plain hdiutil
    hdiutil create -volname "RetryClicker" -srcfolder "$APP_PATH" \
            -ov -format UDZO "$DMG_PATH"
fi

if [ -f "$DMG_PATH" ]; then
    echo -e "  ${GREEN}DMG created: $DMG_PATH${RESET}"
else
    echo -e "  ${YELLOW}DMG creation skipped (app still available in dist/).${RESET}"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║  RetryClicker.app built successfully!         ║${RESET}"
echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  ${BOLD}App:${RESET} $APP_PATH"
[ -f "$DMG_PATH" ] && echo -e "  ${BOLD}DMG:${RESET} $DMG_PATH"
echo ""
echo -e "  ${YELLOW}${BOLD}IMPORTANT — Grant these permissions before first use:${RESET}"
echo ""
echo -e "  ${BOLD}Screen Recording${RESET}"
echo "    System Settings > Privacy & Security > Screen Recording"
echo "    → Enable for RetryClicker"
echo ""
echo -e "  ${BOLD}Accessibility${RESET}"
echo "    System Settings > Privacy & Security > Accessibility"
echo "    → Enable for RetryClicker"
echo ""
echo "  Opening Privacy & Security now..."
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture" 2>/dev/null || true
echo ""
