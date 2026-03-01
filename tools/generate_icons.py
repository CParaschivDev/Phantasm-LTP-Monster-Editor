"""
Generate logo.png and multi-size icon.ico from assets/logo.svg.
Tries to use PySide6's QSvgRenderer first, falls back to cairosvg if available.
Requires PySide6 and Pillow for best results.
Run: python tools/generate_icons.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, 'assets')
SVG = os.path.join(ASSETS, 'logo.svg')
OUT_PNG = os.path.join(ASSETS, 'logo.png')
OUT_ICO = os.path.join(ASSETS, 'icon.ico')

sizes = [256, 128, 64, 48, 32, 16]

os.makedirs(ASSETS, exist_ok=True)

def from_qt():
    try:
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtGui import QPixmap, QPainter
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    except Exception as e:
        print('PySide6 not available or missing SVG support:', e)
        return False
    if not os.path.exists(SVG):
        print('SVG not found:', SVG)
        return False
    try:
        # ensure a QGuiApplication exists before creating QPixmap
        app = QApplication.instance() or QApplication([])
        rend = QSvgRenderer(SVG)
        big = sizes[0]
        pix = QPixmap(big, big)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        rend.render(p)
        p.end()
        # save largest PNG
        pix.save(OUT_PNG)
        # use Pillow to write ICO with multiple sizes if available
        try:
            from PIL import Image
            img = Image.open(OUT_PNG)
            img.save(OUT_ICO, sizes=[(s,s) for s in sizes])
            print('Wrote', OUT_PNG, OUT_ICO)
            return True
        except Exception as e:
            print('Pillow not available or failed; trying QPixmap save for ico:', e)
            if pix.save(OUT_ICO):
                print('Wrote', OUT_PNG, OUT_ICO)
                return True
            return False
    except Exception as e:
        print('Failed to render via Qt:', e)
        return False


def from_cairosvg():
    try:
        import cairosvg
    except Exception as e:
        print('cairosvg not available:', e)
        return False
    if not os.path.exists(SVG):
        print('SVG not found:', SVG)
        return False
    try:
        cairosvg.svg2png(url=SVG, write_to=OUT_PNG, output_width=256, output_height=256)
        try:
            from PIL import Image
            img = Image.open(OUT_PNG)
            img.save(OUT_ICO, sizes=[(s,s) for s in sizes])
            print('Wrote', OUT_PNG, OUT_ICO)
            return True
        except Exception as e:
            print('Pillow missing; ICO not created:', e)
            return True
    except Exception as e:
        print('cairosvg render failed:', e)
        return False

if __name__ == '__main__':
    ok = from_qt()
    if not ok:
        ok = from_cairosvg()
    if not ok:
        print('Failed to generate icons. Install PySide6 (with QtSvg) and Pillow, or cairosvg + cairo.')
    sys.exit(0 if ok else 2)
