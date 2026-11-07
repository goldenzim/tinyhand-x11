#!/usr/bin/env bash
# Install TinyHand for the current user. No root, no build step, no network.
#
#   ./install.sh              install (or refresh) the app for $HOME
#   ./install.sh --autostart  also start it with the session
#   ./install.sh --uninstall  remove the launcher, menu entry and icons (config kept)
#   ./install.sh --purge      same, and delete ~/.config/tinyhand too
#
# Everything is written under $HOME, so it is safe to run as any user on any
# X11 desktop. Re-running is idempotent.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # this script lives in scripts/
LIB="$HOME/.local/lib/tinyhand"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor"
AUTOSTART="$HOME/.config/autostart"
MODE="install"

for arg in "$@"; do
    case "$arg" in
        --autostart)   MODE="install-autostart" ;;
        --uninstall)   MODE="uninstall" ;;
        --purge)       MODE="purge" ;;
        -h|--help)     sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

killing_old() {
    python3 - "$LIB/tinyhand.py" <<'PY' || true
import os, signal, sys
target = sys.argv[1]
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
    except OSError:
        continue
    if len(args) >= 2 and args[1].decode(errors="ignore") == target:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
PY
}

if [ "$MODE" != "install" ] && [ "$MODE" != "install-autostart" ]; then
    killing_old
    rm -f  "$BIN/tinyhand"
    rm -f  "$APPS/tinyhand.desktop" "$AUTOSTART/tinyhand.desktop"
    rm -rf "$LIB"
    for n in 16 24 32 48 64 96 128 192 256 512; do rm -f "$ICONS/${n}x${n}/apps/tinyhand.png"; done
    rm -f "$ICONS/scalable/apps/tinyhand.svg"
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICONS" >/dev/null 2>&1 || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
    rm -f "$HOME/.cache/tinyhand/tinyhand.pid"
    if [ "$MODE" = "purge" ]; then
        rm -rf "$HOME/.config/tinyhand"
        echo "purged: app, launcher, menu entry, icons and config"
    else
        echo "uninstalled (config kept at ~/.config/tinyhand/config.json)"
    fi
    exit 0
fi

echo "== 1. dependencies"
missing=()
if command -v python3 >/dev/null 2>&1; then
    echo "   python3 $(python3 -c 'import sys;print(sys.version.split()[0])')"
else
    echo "   python3 MISSING"
    missing+=("python3")
    echo "   sudo apt install python3"; exit 1
fi
for mod in PyQt5 numpy PIL Xlib; do
    if python3 -c "import $mod" 2>/dev/null; then
        echo "   $mod ok"
    else
        echo "   $mod MISSING"
        missing+=("$mod")
    fi
done
if command -v pw-play >/dev/null 2>&1 || command -v paplay >/dev/null 2>&1; then
    echo "   audio player ok ($(command -v pw-play 2>/dev/null || command -v paplay))"
else
    echo "   no pw-play/paplay: tap sounds will be silent"
fi
if [ "${#missing[@]}" -gt 0 ]; then
    echo
    echo "   Install them first (Debian/Ubuntu):"
    echo "     sudo apt install python3-pyqt5 python3-numpy python3-pil python3-xlib pipewire-bin"
    echo
    echo "   Everything except the sound needs only those five packages."
    echo "   Re-run this script once they are present."
    exit 1
fi

echo "== 2. application files -> $LIB"
if [ "$SRC" != "$LIB" ]; then
    mkdir -p "$LIB"
    for item in tinyhand.py README.md HANDOVER.md LICENSE hands sounds icons scripts tests; do
        [ -e "$SRC/$item" ] && cp -r "$SRC/$item" "$LIB/"
    done
fi
chmod +x "$LIB/scripts/"*.sh 2>/dev/null || true

echo "== 3. launcher -> $BIN/tinyhand"
mkdir -p "$BIN"
cat > "$BIN/tinyhand" <<EOF
#!/usr/bin/env bash
# Run TinyHand. A second launch toggles the running instance instead of starting
# a twin -- an icon that silently does nothing reads as broken.
set -euo pipefail
export DISPLAY="\${DISPLAY:-:0}"
export XAUTHORITY="\${XAUTHORITY:-\$HOME/.Xauthority}"
APP="\$HOME/.local/lib/tinyhand/tinyhand.py"
PIDFILE="\$HOME/.cache/tinyhand/tinyhand.pid"
if [ -f "\$PIDFILE" ]; then
    PID="\$(cat "\$PIDFILE" 2>/dev/null || true)"
    if [ -n "\${PID}" ] && kill -0 "\$PID" 2>/dev/null; then
        kill -USR1 "\$PID"
        exit 0
    fi
    rm -f "\$PIDFILE"
fi
exec python3 "\$APP" "\$@"
EOF
chmod +x "$BIN/tinyhand"

echo "== 4. menu entry"
mkdir -p "$APPS"
cat > "$APPS/tinyhand.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=TinyHand
GenericName=Screen pointer
Comment=A tiny hand on a stick that points at things on your screen
Exec=$BIN/tinyhand
Icon=tinyhand
Terminal=false
Categories=Utility;
StartupNotify=false
Keywords=pointer;presenter;annotate;ink;
EOF
chmod +x "$APPS/tinyhand.desktop"
command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$APPS/tinyhand.desktop" || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "== 5. icon theme"
for n in 16 24 32 48 64 96 128 192 256 512; do
    if [ -f "$LIB/icons/theme/${n}x${n}/apps/tinyhand.png" ]; then
        mkdir -p "$ICONS/${n}x${n}/apps"
        cp "$LIB/icons/theme/${n}x${n}/apps/tinyhand.png" "$ICONS/${n}x${n}/apps/"
    fi
done
[ -f "$LIB/icons/hand-cursor.svg" ] && mkdir -p "$ICONS/scalable/apps" && \
    cp "$LIB/icons/hand-cursor.svg" "$ICONS/scalable/apps/tinyhand.svg"
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICONS" >/dev/null 2>&1 || true

if [ "$MODE" = "install-autostart" ]; then
    echo "== 6. autostart"
    mkdir -p "$AUTOSTART"
    sed 's/^\(Name=\).*/\1TinyHand (autostart)/' "$APPS/tinyhand.desktop" > "$AUTOSTART/tinyhand.desktop"
    sed -i 's/^Exec=.*/Exec='"$BIN"'\/tinyhand/' "$AUTOSTART/tinyhand.desktop"
fi

cat <<EOF

installed for $USER.

  launch        $BIN/tinyhand        (menu: TinyHand)
  pointer on    $BIN/tinyhand --on
  config        ~/.config/tinyhand/config.json
  docs          $LIB/HANDOVER.md  and  $LIB/README.md

ONE THING FIRST: the overlay needs a compositing manager, or it paints as an
opaque black rectangle over the whole desktop. On Xfce:

  xfconf-query -c xfwm4 -p /general/use_compositing -s true

Check the whole thing with:

  $LIB/scripts/verify.sh

It runs the acceptance suite and prints PASS/FAIL for every claim, including the
control test that proves clicks really are swallowed.
EOF
