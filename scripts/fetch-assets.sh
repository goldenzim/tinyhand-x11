#!/usr/bin/env bash
# Fetch the upstream art (hands, tap sounds, icons) and prepare it for TinyHand.
#
# The hand PNGs are 1024x1536 with huge transparent margins (~2 MB each). They are
# trimmed to their alpha bounding box and resampled to 900 px tall, which takes the
# set from ~63 MB to ~5.5 MB. That is safe ONLY because the app measures every
# sprite from its alpha channel at load time, so the geometry is re-derived from
# whatever image it is given -- no per-file metadata to invalidate.
#
# Upstream: https://github.com/nilbuild/tinyhand (MIT), pinned below.
set -euo pipefail

COMMIT="${TINYHAND_COMMIT:-c5fb36b7c4d7c87480958872a724b30a52427a47}"
RAW="https://raw.githubusercontent.com/nilbuild/tinyhand/${COMMIT}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

HANDS="lavender glove coral plush robot pink blue mint lemon black chrome holo fuzzy
       wood marble terrazzo glass jelly pastel pixel lowpoly knit skeleton astro space
       monster water lava grass cactus choco cloud mech neon leaf cookie"
SOUNDS="boop click pop squeak thock wood"

mkdir -p "$APP_DIR/hands" "$APP_DIR/sounds" "$APP_DIR/icons"

fetch() { # $1 = repo path, $2 = dest
    curl -fsSL "${RAW}/$1" -o "$2" || { echo "FAILED: $1" >&2; exit 1; }
}

echo "-- hands"
for h in $HANDS; do
    fetch "assets/hand_${h}.png" "$WORK/hand_${h}.png"
    echo "   hand_${h}.png"
done

echo "-- sounds"
for s in $SOUNDS; do
    fetch "assets/sounds/tap_${s}.wav" "$APP_DIR/sounds/tap_${s}.wav"
done

echo "-- icons"
fetch "assets/menubar_on.png"  "$APP_DIR/icons/menubar_on.png"
fetch "assets/menubar_off.png" "$APP_DIR/icons/menubar_off.png"
fetch "assets/icon/hand-cursor.svg" "$APP_DIR/icons/hand-cursor.svg"

echo "-- trimming sprites (alpha bbox, 900 px tall)"
python3 - "$WORK" "$APP_DIR/hands" <<'PY'
import glob, os, sys
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for path in sorted(glob.glob(os.path.join(src, "hand_*.png"))):
    im = Image.open(path).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box is None:
        sys.exit(f"{path}: fully transparent, cannot trim")
    im = im.crop(box)
    w, h = im.size
    if h > 900:
        im = im.resize((max(1, round(w * 900 / h)), 900), Image.LANCZOS)
    im.save(os.path.join(dst, os.path.basename(path)), optimize=True)
print(f"   {len(glob.glob(os.path.join(dst, '*.png')))} hands written")
PY

echo "-- icon theme PNGs"
if command -v inkscape >/dev/null 2>&1; then
    for n in 16 24 32 48 64 96 128 192 256 512; do
        mkdir -p "$APP_DIR/icons/theme/${n}x${n}/apps"
        inkscape "$APP_DIR/icons/hand-cursor.svg" \
            --export-filename="$APP_DIR/icons/theme/${n}x${n}/apps/tinyhand.png" \
            --export-width="$n" --export-background-opacity=0 >/dev/null 2>&1
    done
    echo "   rendered with inkscape"
else
    echo "   inkscape not installed: keeping the PNGs already in icons/theme/"
fi

echo
echo "assets ready:"
du -sh "$APP_DIR/hands" "$APP_DIR/sounds" "$APP_DIR/icons"
