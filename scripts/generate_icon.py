#!/usr/bin/env python3
"""Generates the application icon.

Draws a simple, on-brand icon (rounded square in the app's accent
gradient, with a stylized hand-skeleton glyph) with QPainter at high
resolution, then uses Pillow to export a proper multi-resolution
Windows .ico (16/32/48/64/128/256px all embedded in one file, which is
what Windows Explorer/taskbar/shortcuts expect) plus a standalone .png
for use elsewhere (About dialog, Linux/macOS, README).

Run once (or whenever the design changes):

    python scripts/generate_icon.py

Requires PySide6 (already a dependency) and Pillow (only needed for
building the .ico -- not a runtime dependency of the app itself, so
it's not in requirements.txt; install it ad hoc with
`pip install Pillow` if regenerating the icon).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

OUTPUT_DIR = PROJECT_ROOT / "assets" / "icon"
SOURCE_SIZE = 1024
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

ACCENT = "#5ec8ff"
VIOLET = "#a78bfa"
BG_DARK = "#0b0d12"


def draw_icon(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    margin = size * 0.04
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = size * 0.22

    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor(ACCENT))
    gradient.setColorAt(1.0, QColor(VIOLET))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, radius, radius)

    # Stylized hand: a rounded palm with four fingers and a thumb, drawn
    # as solid rounded shapes (reads clearly even at 16x16) rather than
    # the thin-stroke line icons used inside the app itself.
    painter.setBrush(QColor(BG_DARK))
    cx, cy = size / 2.0, size / 2.0
    scale = size / 24.0  # design on a 24-unit grid, like the in-app icon set

    palm = QRectF(cx - 3.0 * scale, cy - 1.0 * scale, 6.0 * scale, 7.5 * scale)
    painter.drawRoundedRect(palm, 2.2 * scale, 2.2 * scale)

    finger_w = 1.7 * scale
    finger_specs = [(-3.0, -6.5, 5.5), (-1.0, -7.3, 6.3), (1.0, -6.5, 5.5), (3.0, -5.0, 4.2)]
    for x_off, y_off, length in finger_specs:
        fx = cx + x_off * scale - finger_w / 2.0
        fy = cy + y_off * scale
        painter.drawRoundedRect(QRectF(fx, fy, finger_w, length * scale), finger_w / 2.0, finger_w / 2.0)

    # Thumb, angled off to the side.
    painter.save()
    painter.translate(cx - 4.6 * scale, cy + 1.0 * scale)
    painter.rotate(-38)
    painter.drawRoundedRect(QRectF(-finger_w / 2.0, -4.6 * scale, finger_w, 4.6 * scale), finger_w / 2.0, finger_w / 2.0)
    painter.restore()

    painter.end()
    return pixmap


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 -- must stay alive for QPixmap/QPainter
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source = draw_icon(SOURCE_SIZE)
    png_path = OUTPUT_DIR / "app_icon.png"
    source.save(str(png_path), "PNG")
    print(f"Wrote {png_path}")

    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed -- skipping .ico generation. Run: pip install Pillow", file=sys.stderr)
        print(f"A high-resolution {png_path.name} was still written; you can convert it to .ico separately.")
        return 0

    frames = []
    for s in ICO_SIZES:
        pm = draw_icon(s)
        tmp_path = OUTPUT_DIR / f"_tmp_{s}.png"
        pm.save(str(tmp_path), "PNG")
        frames.append(Image.open(tmp_path).convert("RGBA"))

    ico_path = OUTPUT_DIR / "app_icon.ico"
    frames[-1].save(str(ico_path), format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    for s in ICO_SIZES:
        (OUTPUT_DIR / f"_tmp_{s}.png").unlink(missing_ok=True)

    print(f"Wrote {ico_path} ({', '.join(f'{s}x{s}' for s in ICO_SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
