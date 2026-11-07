# TinyHand for Linux/X11

A tiny hand on a stick that points at things on your screen. Port of
[nilbuild/tinyhand](https://github.com/nilbuild/tinyhand) (macOS, MIT) to X11 + PyQt5.

While the pointer is on, a hand tracks your mouse and **swallows your clicks**: click and it
taps, drag and it draws. Hold `Ctrl` and click to click *for real*.

## Install

Already installed on this box:

| | |
|---|---|
| Code | `~/.local/lib/tinyhand/tinyhand.py` |
| Launcher | `~/.local/bin/tinyhand` |
| Menu entry | `~/.local/share/applications/tinyhand.desktop` |

Dependencies: `python3-pyqt5`, `python3-numpy`, `python3-pil`, `python3-xlib`, `pipewire`
(for `pw-play` sounds). No pip, no venv, no build step.

```sh
xfconf-query -c xfwm4 -p /general/use_compositing -s true   # REQUIRED: see below
tinyhand                                                    # or Whisker -> TinyHand
```

**A compositing manager must be running**, or the transparent overlay paints as a black
rectangle over the whole desktop. `xfwm4` compositing is enough; `picom` is not needed. On
ian-linux it is off by default and this app does not turn it on for you.

## Use

| | |
|---|---|
| `Ctrl+Alt+H`, tray click, or `tinyhand` again | on / off |
| Click | the hand taps; nothing underneath is clicked |
| Drag | draw ink |
| `Ctrl+Alt+X` | clear the ink |
| Wheel click (middle button) | clear the ink, any time the pointer is on |
| `Esc` | clear everything and turn the pointer off |
| `Ctrl` + click | click for real, on the app underneath |
| pointer near the bottom, or the first 3 s | hand-picker toolbar (centre of screen) |

Right-click the tray icon for all 36 hands plus a laser dot, the settings dialog, and quit.

## Change things

`~/.config/tinyhand/config.json` — `pointerSize` is the hand length as a fraction of screen
height (0.08–0.20, default 0.13; the slider in Settings does the same thing). `style` is a hand
id, `pinned` is the toolbar's contents, `interactKey` is `ctrl` / `alt` / `shift` / `off`.

**Adding a hand:** drop a hand-on-a-stick PNG (transparent background, hand at the top, rod
running to the bottom) into `hands/` as `hand_<id>.png`, then add the id to `STYLES` in
`tinyhand.py`. Geometry is measured from the alpha channel at load, so no other metadata is
needed in the file.

## Wayland

Not supported, and not supportable: a client cannot consume input aimed at other clients,
hide the cursor globally, or float above arbitrary windows outside `wlr-layer-shell`.

## Licence

MIT. The port, launcher and settings UI are local; the hand PNGs, tap sounds and icons are the
upstream assets. Upstream copyright © 2026 Kamran Ahmed — see `LICENSE`.

**Unofficial.** This is a port, not a release of the upstream project: it is not affiliated with,
sponsored by or endorsed by Kamran Ahmed or TinyHand, and the name is used only to say what it is
a port of. `LICENSE` must travel with any copy or derivative of this tree.
