#!/usr/bin/env python3
"""X11 facts that bash cannot get at cleanly, for verify.sh.

    _xcheck.py session        -> key=value lines: display, server, compositor, xtest
    _xcheck.py hotkey h       -> whether Ctrl+Alt+H can be grabbed (free / taken)
    _xcheck.py measure DIR    -> measured sprite geometry for every hand in DIR
"""
import sys


def session():
    from Xlib import display
    from Xlib.error import DisplayError
    try:
        d = display.Display()
    except DisplayError as exc:
        print("display=none")
        print(f"error={exc}")
        return 1
    root = d.screen().root
    # Detecting "is anything compositing" honestly: _NET_WM_CM_S0 is owned by the
    # compositing manager, BUT xfwm4 holds that atom even when its compositor is
    # switched off -- so on Xfce the selection says nothing and the xfconf key is
    # the truth. Anywhere else, fall back to the selection owner.
    atom = d.get_atom("_NET_WM_CM_S0")
    owner = d.get_selection_owner(atom)
    state = "yes" if owner else "no"
    how = "cm_selection"
    import shutil
    import subprocess
    if shutil.which("xfconf-query") and shutil.which("xfwm4"):
        try:
            out = subprocess.run(
                ["xfconf-query", "-c", "xfwm4", "-p", "/general/use_compositing"],
                capture_output=True, text=True, timeout=5, env={**__import__("os").environ}).stdout.strip()
            if out in ("true", "false"):
                state = "yes" if out == "true" else "no"
                how = "xfwm4 xfconf key"
        except Exception:
            pass
    print(f"display={d.get_display_name()}")
    print(f"screen={d.screen().width_in_pixels}x{d.screen().height_in_pixels}")
    print(f"compositor={state}")
    print(f"compositor_source={how}")
    print(f"cm_selection_owner={'yes' if owner else 'no'}")
    print(f"xtest={'yes' if d.has_extension('XTEST') else 'no'}")
    print(f"xfixes={'yes' if d.has_extension('XFIXES') else 'no'}")
    d.close()
    return 0


def hotkey(name):
    """Try to grab Ctrl+Alt+<name>. Free => we can have it. Taken => something else owns it."""
    from Xlib import X, XK, display
    d = display.Display()
    root = d.screen().root
    errors = []
    d.set_error_handler(lambda err, req: errors.append(err.__class__.__name__) or 0)
    code = d.keysym_to_keycode(XK.string_to_keysym(name))
    mods = X.ControlMask | X.Mod1Mask
    for extra in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
        try:
            root.grab_key(code, mods | extra, True, X.GrabModeAsync, X.GrabModeAsync)
        except Exception as exc:
            errors.append(str(exc))
    d.sync()
    for extra in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
        try:
            root.ungrab_key(code, mods | extra)
        except Exception:
            pass
    d.sync()
    d.close()
    if errors:
        print(f"hotkey_ctrl_alt_{name}=taken ({errors[0]})")
        return 1
    print(f"hotkey_ctrl_alt_{name}=free")
    return 0


def measure(hand_dir):
    """Import the app's own measurer so a broken sprite set shows up here, not at runtime."""
    sys.path.insert(0, hand_dir.rsplit("/hands", 1)[0])
    import glob
    import os
    from PyQt5 import QtGui                      # noqa: F401  (QImage needs no QApplication)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "th", os.path.join(hand_dir.rsplit("/hands", 1)[0], "tinyhand.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.argv = ["tinyhand.py", "--help"]          # keep argparse quiet if it runs
    spec.loader.exec_module(mod)
    bad = 0
    names = sorted(glob.glob(os.path.join(hand_dir, "*.png")))
    for path in names:
        name = os.path.basename(path)[len("hand_"):-len(".png")]
        try:
            a = mod.HandAsset(name)
        except Exception as exc:
            print(f"   FAIL {name}: {exc}")
            bad += 1
            continue
        # tip == 0 is normal: the sprite was trimmed to its alpha bounding box, so the
        # fingertip is the first row of the image. What must hold is the ORDER.
        sane = 0.0 <= a.tip < a.wrist < a.rod_end <= 1.0 and a.aspect > 0
        if not sane:
            print(f"   FAIL {name}: implausible geometry "
                  f"tip={a.tip:.3f} wrist={a.wrist:.3f} rodEnd={a.rod_end:.3f}")
            bad += 1
        else:
            print(f"   ok   {name:10s} aspect={a.aspect:.3f} tip={a.tip:.3f} "
                  f"wrist={a.wrist:.3f} rodEnd={a.rod_end:.3f}")
    print(f"measured={len(names) - bad}/{len(names)}")
    return 1 if bad else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "session"
    if cmd == "session":
        sys.exit(session())
    if cmd == "hotkey":
        sys.exit(hotkey(sys.argv[2]))
    if cmd == "measure":
        sys.exit(measure(sys.argv[2]))
    sys.exit(f"unknown command {cmd}")
