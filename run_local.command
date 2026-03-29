#!/bin/bash
# ──────────────────────────────────────────────────
# BRRRR Dashboard - Double-click to launch locally
# ──────────────────────────────────────────────────
cd "$(dirname "$0")"

echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║    BRRRR Deal Scanner Dashboard       ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""

if command -v python3 &>/dev/null; then PY=python3
elif command -v python &>/dev/null; then PY=python
else
    echo "[ERROR] Python not found. Install from https://python.org"
    read -p "Press Enter to close..."
    exit 1
fi

echo "Using: $($PY --version)"

# Install deps
$PY -m pip install flask requests google-genai --quiet 2>/dev/null

echo ""
echo "  Dashboard starting at: http://127.0.0.1:5000"
echo "  Press Ctrl+C to stop"
echo ""

# Open browser after a short delay
(sleep 2 && open http://127.0.0.1:5000 2>/dev/null) &

$PY app.py
