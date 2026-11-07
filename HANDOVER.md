# HANDOVER — build TinyHand on another machine

**Audience:** an agent or a person installing this on a Linux desktop that is not the box it was
written on. Written to be followed top to bottom with no context from the original session.

**Expected time:** 5 minutes, most of it waiting for `apt`.

---

## 0. Read this line before anything else

**TinyHand is an X11 application. If the session is Wayland, stop.**

```sh
echo "$XDG_SESSION_TYPE  DISPLAY=$DISPLAY  WAYLAND=$WAYLAND_DISPLAY"
```

- `x11` → go on. This will work.
- `wayland` → the interesting half cannot be built. A Wayland client cannot consume input aimed
  at other applications, cannot hide the cursor globally, and cannot stack above arbitrary
  windows outside `wlr-layer-shell`. Do not spend time hunting a workaround; report back with
  that finding and stop. (An XWayland session is still X11 for the purposes of this app, but the
  compositor in charge is the Wayland one — the transparency note in §4 then applies differently:
  XWayland is usually composited, so the overlay *will* blend.)
- empty `DISPLAY` from a script or ssh → the commands below need the user's session environment:
  `export DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority`, or read them out of
  `tr '\0' '\n' < /proc/$(pgrep -f xfce4-session | head -1)/environ | grep -E 'DISPLAY|XAUTHORITY'`
  (substitute the session manager that is actually running).

## 1. What this is

A presentation pointer: a hand on a stick swings up from below the screen, follows the mouse,
and **swallows clicks** — click and it taps, drag and it draws ink. `Ctrl` + click passes a click
through to the app underneath. It is a port of [nilbuild/tinyhand](https://github.com/nilbuild/tinyhand)
(macOS, MIT) to X11 + PyQt5; the upstream art is reused under the same licence.

You are installing:

```
tinyhand.py          939 lines: overlay window, pose maths, toolbar, tray, hotkeys, settings
hands/               36 sprite PNGs, trimmed to alpha, 900 px tall      (5.5 MB)
sounds/              6 tap WAVs                                         (72 KB)
icons/               tray glyphs, upstream SVG, pre-rendered theme PNGs (176 KB)
tests/click_target.py    a window that counts clicks -- the control half of the click proof
scripts/install.sh       install for the current $HOME (no root, idempotent)
scripts/verify.sh        the acceptance suite (§3) -- run this before believing anything
scripts/fetch-assets.sh  rebuild hands/ and sounds/ from upstream, pinned commit
scripts/_xcheck.py       X11 facts for the suite: session, compositor, hotkey, sprite geometry
README.md                user-facing: controls, config keys, how to add a hand
LICENSE                  MIT, © 2026 Kamran Ahmed (upstream)
```

## 2. Install

```sh
sudo apt install python3-pyqt5 python3-numpy python3-pil python3-xlib pipewire-bin
./scripts/install.sh                 # add --autostart to start it with the session
```

`install.sh` checks the dependencies first and refuses with the exact apt line if any are
missing; if it succeeds it writes, all under `$HOME` and never as root:

| | |
|---|---|
| `~/.local/lib/tinyhand/` | the app and its assets |
| `~/.local/bin/tinyhand` | launcher (a second run toggles the running instance) |
| `~/.local/share/applications/tinyhand.desktop` | menu entry |
| `~/.local/share/icons/hicolor/*/apps/tinyhand.png` | icon at ten sizes |
| `~/.config/tinyhand/config.json` | created on first run |

Re-running is safe. `./scripts/install.sh --uninstall` removes everything but the config;
`--purge` takes the config too.

There is **no build step**: no pip, no venv, no compiler, no network at install time.

## 3. The compositor gate — do this before judging the app

**If nothing is compositing, the overlay paints as an opaque black rectangle over the entire
desktop.** That is not a bug in the paint code and no amount of looking at pixels will fix it.

| Desktop | What to do |
|---|---|
| Xfce | `xfconf-query -c xfwm4 -p /general/use_compositing -s true` (Settings → Window Manager Tweaks → Compositor) |
| anything else, no compositor | run `picom &` for the session |
| GNOME / KDE (default) | usually already compositing — check §4 before assuming |

Ask before making it permanent: on a machine used for games, compositing is a performance
decision its owner made deliberately. Toggling it for a test and putting it back is fine.

## 4. Acceptance suite

```sh
./scripts/verify.sh
```

Seven groups, each printing `PASS` / `FAIL` / `SKIP`, exit code 0 only if nothing failed. It
moves the mouse pointer and briefly covers the screen — that is the app working.

Expected on a healthy X11 machine:

```
== 1. platform           PASS an X server is reachable
                         PASS a compositing manager is running
== 2. dependencies       PASS python3 -c 'import PyQt5'   (x4)   PASS audio player
== 3. hand sprites       PASS 36 hand sprites present
                         PASS 6 tap sounds present
                         ok   <36 lines of measured geometry>
                         PASS every sprite measures (36/36)
== 4. global hotkeys     PASS Ctrl+Alt+H is free to grab
                         PASS Ctrl+Alt+X is free to grab
== 5. clicks             PASS control: 2/2 clicks reached the target with no overlay
                         PASS overlay swallowed 1 click(s)
                         PASS Ctrl+click reached the target exactly once
== 6. it actually draws  PASS ~16000 pixels changed when the hand appeared
== 7. launcher           PASS one process after a cold launch and after a second launch
   ALL CHECKS PASSED
```

How to read the failures:

| Check | What a FAIL means |
|---|---|
| `an X server is reachable` | wrong `DISPLAY`/`XAUTHORITY`, or a Wayland session (§0) |
| `a compositing manager is running` | §3 — the only "failure" that is a configuration choice |
| sprite measure `36/36` | `hands/` incomplete or corrupt → `./scripts/fetch-assets.sh` |
| `control: 2/2` | the test bed is broken (xdotool/pointer); **ignore the click results below it** |
| `overlay swallowed` | clicks are reaching apps while the hand is up — the core promise |
| `Ctrl+click reached the target exactly once` | 0 = pass-through broke; 2 = the click is being double-delivered |
| `pixels changed` | the overlay drew nothing: check compositing first, then `/tmp/tinyhand-verify-on.png` |
| launcher `1 and 1` | two copies running, or the toggle signal did not land |

**Never report "it works" without §5's control run passing.** A click test that cannot fail
proves nothing, which is the whole reason the target window exists.

## 5. Decisions already made — do not re-litigate these quietly

If one has to change, say so explicitly and say why.

1. **X11 only.** Wayland is out of scope by nature (§0), not by effort.
2. **The overlay is a topmost override-redirect window, not a root-window grab.** A full-screen
   window already receives every press, so clicks are swallowed for free. Do not add
   `XGrabButton`/`XGrabPointer`: while held it makes every other X client unclickable, and a
   crash under a grab is a desktop that ignores the mouse.
3. **Panels are excluded by geometry**, not by XFixes input shapes: the overlay covers
   `screen.availableGeometry()`, so the panel stays live and its cursor is the real one.
4. **"Click for real" is hide + XTEST replay** of a complete click, re-shown after 140 ms. A
   swallowed press cannot be un-swallowed, and synthesising a second press while the physical
   one is down delivers two presses. Verified 1:1.
5. **Sprite geometry is measured from alpha at load**, so any hand PNG works. Nothing has
   per-asset metadata; keep it that way.
6. **Default hand size is 13% of screen height**, the upstream default (range 8–20%). Not a
   taste call — do not "improve" it.
7. **The picker toolbar is anchored to the centre of the screen.** Centring it on the cursor
   makes its own buttons unclickable.
8. **Assets are pinned** to upstream commit `c5fb36b7c4d7c87480958872a724b30a52427a47`; they are
   trimmed to their alpha bounding box and resampled to 900 px. Safe only because of (5).

## 6. Known limits

- Menus and popups can end up underneath the hand (upstream detects open menus and steps aside;
  that detection was not ported). `Ctrl`+click or toggle off.
- `Esc` is grabbed globally while the pointer is on, so applications do not see `Esc` during a
  session.
- The middle (wheel) button clears the ink, the same action as `Ctrl`+Alt+X; the other extra
  buttons are swallowed and do nothing. Only the first mouse button taps and draws.
- Multi-monitor code is written against the union of all screens but has only been run on one.
- No updater, no launch-at-login beyond `--autostart`, no GUI for importing a custom hand
  (drop a PNG in `hands/` and add its id to `STYLES`).

## 7. Rebuilding the art (optional, needs network)

```sh
./scripts/fetch-assets.sh          # pins the upstream commit, trims, resamples, renders icons
```

36 hands download at ~63 MB and land as ~5.5 MB. Geometry is re-derived at load time, so a
re-fetch cannot invalidate anything.

## 8. Reporting back

Send: session type and compositor state, the `verify.sh` summary line, the hand size if it was
changed, and anything that failed with the check's name and its output. If a check failed, say
which one — "it doesn't work" costs a round trip.

Background and the full X11/AppKit primitive map (why each decision above was made) live in
`~/docs/TINYHAND.md` on ian-linux and in the `linux-desktop-overlay-apps` skill.
