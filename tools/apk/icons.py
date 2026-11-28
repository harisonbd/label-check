"""v2.45.1: app icon and start screen for the Android app, made from icon-512.png (the web app icon).
Called by build.sh on the GitHub runner (Pillow in a small venv). Usage: python3 icons.py <icon-512.png> <android res folder>
- adaptive icon (Android 8+): the full icon as foreground layer (108 dp; the tag sits inside the visible middle),
  background colour = the icon's corner colour
- old icons (ic_launcher.png, ic_launcher_round.png, 48 dp)
- every splash.png the Capacitor template has: the icon in the middle of the dark app background
"""
import os, sys
from PIL import Image, ImageDraw

DENS = {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}
BG = (18, 20, 23)                         # #121417, the app's dark background


def main(icon_path, res):
    icon = Image.open(icon_path).convert('RGBA')
    corner = icon.getpixel((4, 4))[:3]
    for d, k in DENS.items():
        folder = os.path.join(res, 'mipmap-' + d)
        os.makedirs(folder, exist_ok=True)
        icon.resize((round(108 * k),) * 2, Image.LANCZOS).save(os.path.join(folder, 'ic_launcher_foreground.png'))
        s = round(48 * k)
        sq = icon.resize((s, s), Image.LANCZOS)
        sq.save(os.path.join(folder, 'ic_launcher.png'))
        mask = Image.new('L', (s * 4, s * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, s * 4 - 1, s * 4 - 1), fill=255)
        rnd = Image.new('RGBA', (s, s), (0, 0, 0, 0))
        rnd.paste(sq, (0, 0), mask.resize((s, s), Image.LANCZOS))
        rnd.save(os.path.join(folder, 'ic_launcher_round.png'))
    any_dir = os.path.join(res, 'mipmap-anydpi-v26')
    os.makedirs(any_dir, exist_ok=True)
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
           '    <background android:drawable="@color/ic_launcher_background"/>\n'
           '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n</adaptive-icon>\n')
    for n in ('ic_launcher.xml', 'ic_launcher_round.xml'):
        open(os.path.join(any_dir, n), 'w').write(xml)
    values = os.path.join(res, 'values')
    os.makedirs(values, exist_ok=True)
    open(os.path.join(values, 'ic_launcher_background.xml'), 'w').write(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#%02X%02X%02X</color>\n</resources>\n' % corner)
    n = 0
    for dirpath, _, files in os.walk(res):
        for f in files:
            if f != 'splash.png':
                continue
            p = os.path.join(dirpath, f)
            w, h = Image.open(p).size
            m = min(w, h) // 3
            out = Image.new('RGB', (w, h), BG)
            ic = icon.resize((m, m), Image.LANCZOS)
            rm = Image.new('L', (m * 4, m * 4), 0)                       # rounded corners, like an app icon
            ImageDraw.Draw(rm).rounded_rectangle((0, 0, m * 4 - 1, m * 4 - 1), radius=m * 4 // 5, fill=255)
            out.paste(ic, ((w - m) // 2, (h - m) // 2), rm.resize((m, m), Image.LANCZOS))
            out.save(p)
            n += 1
    print('icons done; corner colour #%02X%02X%02X; splash images: %d' % (corner + (n,)))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
