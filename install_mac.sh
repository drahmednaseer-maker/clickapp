#!/bin/bash
# ============================================================
#  RetryClicker — macOS Setup
#  Compatible with macOS Tahoe (26) / Sequoia (15) / Sonoma (14)
#
#  Two modes:
#    ./install_mac.sh          → run from source (python3 retry_clicker.py)
#    ./install_mac.sh --build  → build a self-contained RetryClicker.app + DMG
# ============================================================

set -e
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_MODE=0
[[ "$1" == "--build" ]] && BUILD_MODE=1

echo ""
echo -e "${BOLD}======================================${RESET}"
echo -e "${BOLD}  RetryClicker — macOS Installer${RESET}"
echo -e "${BOLD}======================================${RESET}"
echo ""

# ── 1. Python 3 ───────────────────────────────────────────────────────────
echo -e "${BOLD}[1/5] Checking Python 3...${RESET}"
if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}Python 3 not found.${RESET}"
    echo "  Install from https://www.python.org/downloads/ or:"
    echo "      brew install python"
    exit 1
fi
echo -e "  ${GREEN}Found: $(python3 --version)${RESET}"

# ── 2. Homebrew ───────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[2/5] Checking Homebrew...${RESET}"
if command -v brew &>/dev/null; then
    echo -e "  ${GREEN}Homebrew found: $(which brew)${RESET}"
else
    echo -e "  ${YELLOW}Homebrew not found — installing...${RESET}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# ── 3. Tesseract OCR ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[3/5] Checking Tesseract OCR...${RESET}"
if command -v tesseract &>/dev/null; then
    echo -e "  ${GREEN}Tesseract: $(tesseract --version | head -1)${RESET}"
else
    echo "  Installing Tesseract..."
    brew install tesseract
    echo -e "  ${GREEN}Tesseract installed.${RESET}"
fi

# ── 4. Python packages ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[4/5] Installing Python packages...${RESET}"
PKGS="mss pyautogui pillow pytesseract opencv-python"
[[ $BUILD_MODE -eq 1 ]] && PKGS="$PKGS pyinstaller"
pip3 install --quiet --upgrade $PKGS
echo -e "  ${GREEN}All packages installed.${RESET}"

# ── 5. Permissions reminder ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}[5/5] macOS Permissions${RESET}"
echo ""
echo -e "  ${YELLOW}Grant these before running RetryClicker:${RESET}"
echo ""
echo -e "  ${BOLD}Screen Recording${RESET}"
echo "    System Settings > Privacy & Security > Screen Recording"
if [[ $BUILD_MODE -eq 1 ]]; then
    echo "    → Enable for RetryClicker.app"
else
    echo "    → Enable for Terminal (or your Python launcher)"
fi
echo ""
echo -e "  ${BOLD}Accessibility${RESET}"
echo "    System Settings > Privacy & Security > Accessibility"
if [[ $BUILD_MODE -eq 1 ]]; then
    echo "    → Enable for RetryClicker.app"
else
    echo "    → Enable for Terminal (or your Python launcher)"
fi
echo ""

open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture" 2>/dev/null || true

# ── Build app if requested ────────────────────────────────────────────────
if [[ $BUILD_MODE -eq 1 ]]; then
    echo ""
    echo -e "${BOLD}Building RetryClicker.app...${RESET}"
    cd "$SCRIPT_DIR"
    bash build_mac_app.sh
else
    echo ""
    echo -e "${GREEN}${BOLD}Setup complete!${RESET}"
    echo ""
    echo "  Run directly:       ${BOLD}./run_mac.command${RESET}"
    echo "  Or build a .app:    ${BOLD}./install_mac.sh --build${RESET}"
    echo ""
fi
