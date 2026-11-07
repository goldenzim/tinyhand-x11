#!/usr/bin/env bash
# TinyHand acceptance suite. Every claim the README makes, tested here.
#
#   ./scripts/verify.sh
#
# Prints PASS / FAIL / SKIP per check and exits non-zero if anything failed.
# It moves the mouse pointer and, briefly, covers the screen with the overlay --
# that is the app doing its job, not a fault. Everything is put back at the end.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$APP_DIR/tinyhand.py"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

WORK="$(mktemp -d)"
SAVED="$(xdotool getmouselocation --shell 2>/dev/null | tr '\n' ' ' || true)"
FAILED=0
SKIPPED=0

pass() { printf '  PASS  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; FAILED=$((FAILED + 1)); }
skip() { printf '  SKIP  %s\n' "$*"; SKIPPED=$((SKIPPED + 1)); }
head_() { printf '\n== %s\n' "$*"; }

stop_app() {
    python3 - <<'PY' 2>/dev/null || true
import os, signal
# match on the basename: the launcher runs the INSTALLED copy of the app, which is not
# always the same path this suite was started from (tarball vs ~/.local/lib).
# only OUR instances: another account's pointer on another display is not this suite's
# to stop, and counting it makes check 7 report 2 forever on a shared box.
me = os.getuid()
def mine(pid):
    try:
        return os.stat(f"/proc/{pid}").st_uid == me
    except OSError:
        return False
for pid in os.listdir("/proc"):
    if not pid.isdigit() or not mine(pid):
        continue
    try:
        args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
    except OSError:
        continue
    if len(args) >= 2 and os.path.basename(args[1].decode(errors="ignore")) == "tinyhand.py":
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
PY
    sleep 0.6
}

instance_count() {
    python3 - <<'PY'
import os
me = os.getuid()
n = 0
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        if os.stat(f"/proc/{pid}").st_uid != me:
            continue
        args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
    except OSError:
        continue
    if len(args) >= 2 and os.path.basename(args[1].decode(errors="ignore")) == "tinyhand.py":
        n += 1
print(n)
PY
}

start_app() {
    TINYHAND_DEBUG=1 python3 "$APP" --on >"$WORK/app.log" 2>&1 &
    APP_PID=$!
    sleep 2.5
    kill -0 "$APP_PID" 2>/dev/null
}

cleanup() {
    stop_app
    [ -n "${SAVED}" ] && eval "$SAVED" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

printf 'TinyHand acceptance suite\napp: %s\n' "$APP"

# ---------------------------------------------------------------- 1. platform
head_ "1. platform (X11 only -- this is not a Wayland app)"
SESSION="$("$APP_DIR/scripts/_xcheck.py" session 2>&1)"
echo "$SESSION" | sed 's/^/    /'
if echo "$SESSION" | grep -q '^display=' && ! echo "$SESSION" | grep -q '^display=none'; then
    pass "an X server is reachable"
else
    fail "no X server (set DISPLAY / XAUTHORITY; Wayland is unsupported)"
fi
XTEST="$(echo "$SESSION" | sed -n 's/^xtest=//p')"
if echo "$SESSION" | grep -q '^compositor=yes'; then
    pass "a compositing manager is running (per-pixel alpha will blend)"
else
    fail "nothing is compositing -- the overlay will paint as a black rectangle.
        Xfce:  xfconf-query -c xfwm4 -p /general/use_compositing -s true"
fi

# ---------------------------------------------------------------- 2. packages
head_ "2. dependencies"
for mod in PyQt5 numpy PIL Xlib; do
    if python3 -c "import $mod" 2>/dev/null; then pass "python3 -c 'import $mod'"; else fail "missing python module: $mod (apt install python3-${mod,,})"; fi
done
if command -v pw-play >/dev/null 2>&1 || command -v paplay >/dev/null 2>&1; then
    pass "an audio player for tap sounds"
else
    skip "no pw-play/paplay -- taps will be silent"
fi
for tool in xdotool scrot; do
    command -v "$tool" >/dev/null 2>&1 && pass "$tool present" || skip "$tool missing (needed for the pointer and screenshot checks)"
done

# ---------------------------------------------------------------- 3. assets
head_ "3. hand sprites (measured from alpha, exactly as the app does at load)"
HANDS=$(ls "$APP_DIR/hands"/hand_*.png 2>/dev/null | wc -l)
[ "$HANDS" -ge 36 ] && pass "$HANDS hand sprites present" || fail "only $HANDS hand sprites (expected 36): run scripts/fetch-assets.sh"
SOUNDS=$(ls "$APP_DIR/sounds"/*.wav 2>/dev/null | wc -l)
[ "$SOUNDS" -ge 6 ] && pass "$SOUNDS tap sounds present" || fail "only $SOUNDS tap sounds: run scripts/fetch-assets.sh"
MEASURED="$("$APP_DIR/scripts/_xcheck.py" measure "$APP_DIR/hands" 2>&1)"
echo "$MEASURED" | grep -E '^   (ok|FAIL)' | sed 's/^/  /' | head -40
if echo "$MEASURED" | grep -q '^measured='; then
    RATIO="$(echo "$MEASURED" | sed -n 's/^measured=//p')"
    if [ "${RATIO%%/*}" = "${RATIO##*/}" ]; then pass "every sprite measures ($RATIO)"; else fail "sprite geometry: $RATIO"; fi
else
    fail "could not measure sprites: $(echo "$MEASURED" | tail -2)"
fi

# ---------------------------------------------------------------- 4. hotkeys
head_ "4. global hotkeys (grab, not steal -- released immediately)"
if "$APP_DIR/scripts/_xcheck.py" hotkey h; then
    pass "Ctrl+Alt+H is free to grab"
else
    skip "Ctrl+Alt+H is already owned by another client; the tray and launcher still toggle"
fi
if "$APP_DIR/scripts/_xcheck.py" hotkey x; then
    pass "Ctrl+Alt+X is free to grab"
else
    skip "Ctrl+Alt+X is already owned by another client"
fi

# ---------------------------------------------------------------- 5. clicks
head_ "5. clicks are swallowed -- control run first, or the test proves nothing"
if command -v xdotool >/dev/null 2>&1; then
    stop_app
    python3 "$APP_DIR/tests/click_target.py" >"$WORK/target_a.log" 2>&1 &
    TARGET_PID=$!
    sleep 1.5
    xdotool mousemove 500 400
    sleep 0.3
    xdotool click 1
    sleep 0.2
    xdotool click 1
    sleep 7.5
    CONTROL="$(grep -c 'TARGET GOT CLICK' "$WORK/target_a.log" 2>/dev/null | head -1)"
    CONTROL="${CONTROL:-0}"
    kill "$TARGET_PID" 2>/dev/null
    if [ "$CONTROL" -ge 2 ]; then
        pass "control: $CONTROL/2 clicks reached the target with no overlay"
    else
        fail "control: only $CONTROL/2 clicks reached the target (test bed is broken, results below are meaningless)"
    fi

    python3 "$APP_DIR/tests/click_target.py" >"$WORK/target_b.log" 2>&1 &
    TARGET_PID=$!
    sleep 1.5
    start_app || fail "overlay did not start (see $WORK/app.log)"
    xdotool mousemove 500 400
    sleep 0.4
    xdotool click 1
    sleep 0.4
    xdotool keydown ctrl
    sleep 0.2
    xdotool click 1
    sleep 0.4
    xdotool keyup ctrl
    sleep 1.0
    stop_app
    sleep 6.0
    EATEN="$(grep -c 'tap at' "$WORK/app.log" 2>/dev/null | head -1)"; EATEN="${EATEN:-0}"
    REACHED="$(grep -c 'TARGET GOT CLICK' "$WORK/target_b.log" 2>/dev/null | head -1)"; REACHED="${REACHED:-0}"
    kill "$TARGET_PID" 2>/dev/null
    [ "$EATEN" -ge 1 ] && pass "overlay swallowed $EATEN click(s)" || fail "overlay logged no swallowed click"
    [ "$REACHED" -eq 1 ] && pass "Ctrl+click reached the target exactly once (click-for-real works)" \
                          || fail "Ctrl+click reached the target $REACHED times (expected exactly 1)"
else
    skip "xdotool missing -- cannot run the click-swallowing proof"
fi

# ---------------------------------------------------------------- 6. pixels
head_ "6. it actually draws (pixel diff with the pointer parked)"
if command -v scrot >/dev/null 2>&1 && [ "$XTEST" = "yes" ]; then
    stop_app
    xdotool mousemove 900 700
    sleep 0.5
    scrot -o "$WORK/off.png"
    start_app || true
    xdotool mousemove 900 700
    sleep 1.2
    scrot -o "$WORK/on.png"
    stop_app
    DIFF="$(python3 - "$WORK/off.png" "$WORK/on.png" <<'PY'
import sys
from PIL import Image, ImageChops
a = Image.open(sys.argv[1]).convert("RGB")
b = Image.open(sys.argv[2]).convert("RGB")
box = (300, 200, 1800, 1200)            # around the parked pointer
d = ImageChops.difference(a.crop(box), b.crop(box)).convert("L")
changed = sum(1 for v in d.getdata() if v > 24)
bbox = d.point(lambda v: 255 if v > 24 else 0).getbbox()
print(f"{changed} {bbox}")
PY
)"
    CHANGED="${DIFF%% *}"
    BBOX="${DIFF#* }"
    if [ "${CHANGED:-0}" -gt 3000 ]; then
        pass "$CHANGED pixels changed when the hand appeared (diff region $BBOX)"
    else
        fail "only ${CHANGED:-0} pixels changed: the hand did not draw (check the compositor)"
        cp "$WORK/on.png" "/tmp/tinyhand-verify-on.png" 2>/dev/null && echo "        screenshot kept: /tmp/tinyhand-verify-on.png"
    fi
else
    skip "scrot or XTEST missing -- cannot diff the screen"
fi

# ---------------------------------------------------------------- 7. launcher
head_ "7. launcher is idempotent (a second click must not start a second copy)"
stop_app
if [ -x "$HOME/.local/bin/tinyhand" ]; then
    ( setsid "$HOME/.local/bin/tinyhand" >/dev/null 2>&1 & )   # execs the app: must detach
    sleep 2.5
    FIRST="$(instance_count)"
    timeout 10 "$HOME/.local/bin/tinyhand" >/dev/null 2>&1 || true   # exits at once: signal only
    sleep 1.5
    SECOND="$(instance_count)"
    stop_app
    if [ "$FIRST" = "1" ] && [ "$SECOND" = "1" ]; then
        pass "one process after a cold launch and after a second launch (it toggled, as designed)"
    else
        fail "process count cold=$FIRST, after second launch=$SECOND (expected 1 and 1)"
    fi
else
    skip "$HOME/.local/bin/tinyhand not installed -- run scripts/install.sh"
fi

# ---------------------------------------------------------------- summary
head_ "summary"
if [ "$FAILED" -eq 0 ]; then
    printf '  %s\n' "ALL CHECKS PASSED${SKIPPED:+ (${SKIPPED} skipped)}"
    exit 0
fi
printf '  %s\n' "$FAILED check(s) failed, $SKIPPED skipped"
exit 1
