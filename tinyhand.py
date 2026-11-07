#!/usr/bin/env python3
"""TinyHand for Linux/X11.

A tiny hand on a stick that points at things on your screen. Port of
nilbuild/tinyhand (MIT) from AppKit to X11 + PyQt5.

    tinyhand            # tray icon, hand off; Ctrl+Alt+H toggles
    tinyhand --on       # start with the hand already out

MIT licence. Original: https://github.com/nilbuild/tinyhand
"""
import argparse
import json
import math
import os
import signal
import subprocess
import sys
import threading

import numpy as np
from PIL import Image

from PyQt5 import QtCore, QtGui, QtWidgets

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HAND_DIR = os.path.join(APP_DIR, "hands")
SOUND_DIR = os.path.join(APP_DIR, "sounds")
ICON_DIR = os.path.join(APP_DIR, "icons")
CONFIG_PATH = os.path.expanduser("~/.config/tinyhand/config.json")
PID_DIR = os.path.expanduser("~/.cache/tinyhand")
PIDFILE = os.path.join(PID_DIR, "tinyhand.pid")
DEBUG = bool(os.environ.get("TINYHAND_DEBUG"))


def log(msg):
    if DEBUG:
        print(f"[tinyhand] {msg}", flush=True)

# id, title, ink colour (from PointerStyle.swift)
STYLES = [
    ("lavender", "Lavender toy", "#8754F2"), ("glove", "Cursor glove", "#8754F2"),
    ("coral", "Coral vinyl", "#F0323C"), ("plush", "Plush", "#2F86F0"),
    ("robot", "Robot", "#16A87A"), ("pink", "Bubblegum", "#EE4F98"),
    ("blue", "Sky", "#2F86F0"), ("mint", "Mint", "#16A87A"),
    ("lemon", "Lemon", "#F2B705"), ("black", "Midnight", "#1D1D21"),
    ("chrome", "Chrome", "#6B7380"), ("holo", "Holo", "#8754F2"),
    ("fuzzy", "Fuzzy", "#8754F2"), ("wood", "Wood", "#9A5E2C"),
    ("marble", "Marble", "#6B7380"), ("terrazzo", "Terrazzo", "#F0561D"),
    ("glass", "Glass", "#1597E5"), ("jelly", "Jelly", "#A33FE6"),
    ("pastel", "Pastel", "#EE4F98"), ("pixel", "Pixel", "#1D1D21"),
    ("lowpoly", "Low poly", "#8754F2"), ("knit", "Knit", "#8754F2"),
    ("skeleton", "Skeleton", "#9A5E2C"), ("astro", "Astronaut", "#2F86F0"),
    ("space", "Space", "#F0323C"), ("monster", "Monster", "#3E9E2E"),
    ("water", "Water", "#1597E5"), ("lava", "Lava", "#F0561D"),
    ("grass", "Grass", "#3E9E2E"), ("cactus", "Cactus", "#3E9E2E"),
    ("choco", "Chocolate", "#9A5E2C"), ("cloud", "Cloud", "#2F86F0"),
    ("mech", "Mech", "#F0561D"), ("neon", "Neon", "#E0309A"),
    ("leaf", "Leaf", "#3E9E2E"), ("cookie", "Gingerbread", "#9A5E2C"),
    ("laser", "Laser dot", "#F0323C"),
]
STYLE_TITLE = {s[0]: s[1] for s in STYLES}
STYLE_INK = {s[0]: s[2] for s in STYLES}

INK_CHOICES = [("match", "Match the pointer", None), ("red", "Red", "#F0323C"),
               ("orange", "Orange", "#FF8A00"), ("yellow", "Yellow", "#FFCC00"),
               ("green", "Green", "#30C25A"), ("blue", "Blue", "#0A84FF"),
               ("purple", "Purple", "#8754F2"), ("white", "White", "#FFFFFF"),
               ("black", "Black", "#1D1D21")]

DEFAULTS = {
    "style": "lavender",
    "pointerSize": 0.13,          # fraction of screen height (upstream default)
    "showShadow": True,
    "soundHands": True,
    "soundLaser": False,
    "tapSound": "thock",
    "inkChoice": "match",
    "pinned": ["lavender", "glove", "coral", "plush", "robot", "laser"],
    "interactKey": "ctrl",
    "startActive": False,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass
    cfg["pointerSize"] = min(0.20, max(0.08, float(cfg["pointerSize"])))
    if cfg["style"] not in STYLE_TITLE:
        cfg["style"] = DEFAULTS["style"]
    cfg["pinned"] = [s for s in cfg["pinned"] if s in STYLE_TITLE][:8] or list(DEFAULTS["pinned"])
    cfg.pop("startActive", None)          # runtime only, never persisted
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, CONFIG_PATH)


# --------------------------------------------------------------------- X11 bits
class X11:
    """The two things Qt will not do for us: global hotkeys and synthetic clicks."""

    def __init__(self):
        from Xlib import X, display
        self.X = X
        self.d = display.Display()
        self.root = self.d.screen().root
        self.grabs = []
        self.xtest = self.d.has_extension("XTEST")
        self.problems = []
        self.d.set_error_handler(self._on_error)

    def _on_error(self, err, _req):
        self.problems.append(f"{err.__class__.__name__}")
        return 0

    def _variants(self, mods):
        from Xlib import X
        out = []
        for extra in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
            out.append(mods | extra)
        return out

    def grab(self, keysym_name, mods, action):
        from Xlib import X, XK
        code = self.d.keysym_to_keycode(XK.string_to_keysym(keysym_name))
        if not code:
            self.problems.append(f"no keycode for {keysym_name}")
            return
        ok = True
        before = len(self.problems)
        for m in self._variants(mods):
            try:
                self.root.grab_key(code, m, True, X.GrabModeAsync, X.GrabModeAsync)
                self.grabs.append((code, m))
            except Exception as exc:                      # BadAccess: someone else owns it
                ok = False
                self.problems.append(f"{keysym_name}+{m:#x}: {exc}")
        self.d.sync()
        if len(self.problems) > before:                  # BadAccess: another client owns it
            ok = False
            log(f"grab {keysym_name} refused: {self.problems[-1]}")
        if ok:
            self.bindings = getattr(self, "bindings", {})
            for m in self._variants(mods):
                self.bindings[(code, m)] = action

    def ungrab(self, keysym_name, mods):
        from Xlib import XK
        code = self.d.keysym_to_keycode(XK.string_to_keysym(keysym_name))
        for m in self._variants(mods):
            try:
                self.root.ungrab_key(code, m)
            except Exception:
                pass
            self.bindings.pop((code, m), None)
            self.grabs = [g for g in self.grabs if g != (code, m)]
        self.d.sync()

    def poll(self):
        """Drain pending key presses, return the list of actions they map to."""
        acts = []
        while self.d.pending_events():
            ev = self.d.next_event()
            kind = ev.__class__.__name__
            if kind == "KeyPress":
                code = getattr(ev, "detail", None)
                state = getattr(ev, "state", 0) & 0xFF
                act = getattr(self, "bindings", {}).get((code, state))
                if act:
                    acts.append(act)
        return acts

    def click(self, x, y):
        """Replay a complete left click at absolute coordinates."""
        if not self.xtest:
            return False
        from Xlib.ext import xtest
        from Xlib import X
        xtest.fake_input(self.d, X.MotionNotify, x=int(x), y=int(y))
        xtest.fake_input(self.d, X.ButtonPress, 1)
        xtest.fake_input(self.d, X.ButtonRelease, 1)
        self.d.sync()
        return True

    def close(self):
        try:
            self.d.close()
        except Exception:
            pass


# ---------------------------------------------------------------- the hand asset
class HandAsset:
    """Sprite geometry measured from the alpha channel -- port of HandAsset.measure()."""

    def __init__(self, name):
        path = os.path.join(HAND_DIR, f"hand_{name}.png")
        im = Image.open(path).convert("RGBA")
        self.img = QtGui.QImage(path)
        a = np.array(im.getchannel("A"))
        h, w = a.shape
        rows = (a > 128).sum(axis=1)

        nz = np.nonzero(rows)[0]
        if nz.size == 0:
            raise ValueError(f"{path}: fully transparent")
        top = int(nz[0])
        search_end = min(h, top + int(0.45 * h))
        max_w = int(rows[top:search_end].max())
        if max_w <= 0:
            raise ValueError(f"{path}: cannot measure")

        fist = next((y for y in range(top, h) if rows[y] > 0.6 * max_w), top)
        wrist = next((y for y in range(fist, h) if rows[y] < 0.35 * max_w), min(h - 1, fist + 1))
        rod_w = int(rows[min(h - 1, wrist + h // 50)])
        last_row = int(nz[-1])
        handle = None
        for y in range(min(h - 1, wrist + h // 33), h):
            if rows[y] > 1.8 * rod_w:
                handle = y
                break
        rod_end = handle if handle is not None else last_row

        band = a[top:wrist, :]
        xs = np.nonzero((band > 128).any(axis=0))[0]
        min_x, max_x = int(xs[0]), int(xs[-1])

        def centre(y):
            cx = np.nonzero(a[min(h - 1, y), :] > 128)[0]
            return 0.5 if cx.size == 0 else (cx[0] + cx[-1]) / 2.0 / w

        fh = float(h)
        self.w, self.h = w, h
        self.aspect = w / fh
        self.hand_top = max(0.0, top - 0.004 * fh) / fh
        self.tip = top / fh
        self.wrist = wrist / fh
        self.rod_end = rod_end / fh
        self.tip_x = centre(min(h - 1, top + h // 200))
        self.rod_x = centre((wrist + rod_end) // 2)
        self.hand_min_x = min_x / float(w)
        self.hand_max_x = max_x / float(w)

        rgba = np.array(im)
        rgba[..., 0:3] = 0
        self.shadow = QtGui.QImage(rgba.data, w, h, 4 * w,
                                   QtGui.QImage.Format_RGBA8888).copy()

        # toolbar thumbnail: square crop of the hand region
        hand_h = (self.wrist - self.hand_top) * h
        side = int(max((self.hand_max_x - self.hand_min_x) * w, hand_h) * 1.06)
        cx = (self.hand_min_x + self.hand_max_x) / 2 * w
        cy = (self.hand_top + self.wrist) / 2 * h
        rect = QtCore.QRect(int(cx - side / 2), int(cy - side / 2), side, side)
        rect = rect.intersected(QtCore.QRect(0, 0, w, h))
        self.thumb = self.img.copy(rect).scaled(
            56, 56, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

    def src_rod(self):
        return QtCore.QRectF(0, self.wrist * self.h, self.w, (self.rod_end - self.wrist) * self.h)

    def src_hand(self):
        return QtCore.QRectF(0, self.hand_top * self.h, self.w, (self.wrist - self.hand_top) * self.h)


class Assets:
    def __init__(self):
        self.cache = {}
        self.order = []

    def get(self, name):
        if name in self.cache:
            self.order.remove(name)
            self.order.append(name)
            return self.cache[name]
        try:
            asset = HandAsset(name)
        except Exception:
            return None
        self.cache[name] = asset
        self.order.append(name)
        while len(self.order) > 3:
            self.cache.pop(self.order.pop(0), None)
        return asset


# ---------------------------------------------------------------- pose constants
GRIP_LEAN, GRIP_DEPTH, GRIP_FOLLOW = 0.30, 0.12, 0.08
MIN_ROD, LIFT = 0.05, 0.06


class Overlay(QtWidgets.QWidget):
    def __init__(self, app):
        super().__init__(None)
        self.app = app
        self.assets = app.assets
        self.cfg = app.cfg
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint
                            | QtCore.Qt.X11BypassWindowManagerHint
                            | QtCore.Qt.WindowStaysOnTopHint
                            | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.BlankCursor)

        self.origin = QtCore.QPoint(0, 0)
        self.rebuild_geometry()

        self.asset = None
        self.load_style(self.cfg["style"])

        self.cursor = QtCore.QPointF(0, 0)
        self.gx = None
        self.press = 0.0
        self.held = False
        self.ink = []
        self.reveal_until = QtCore.QDateTime.currentDateTime().addSecs(3)
        self.toolbar_rects = []
        self.active = False

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(8)

    # ---- geometry: everything except the panels/docks
    def rebuild_geometry(self):
        union = None
        for scr in QtWidgets.QApplication.screens():
            r = scr.availableGeometry()
            union = r if union is None else union.united(r)
        if union is None:
            union = QtWidgets.QApplication.primaryScreen().geometry()
        self.origin = union.topLeft()
        self.setGeometry(union)

    def screen_for(self, gpos):
        scr = QtWidgets.QApplication.screenAt(gpos) or QtWidgets.QApplication.primaryScreen()
        return scr.availableGeometry()

    def load_style(self, style):
        self.cfg["style"] = style
        self.asset = self.assets.get(style) if style != "laser" else None
        if style != "laser" and self.asset is None:
            self.cfg["style"] = style = "laser"
        self.setWindowTitle("tinyhand")
        self.update()

    def ink_colour(self):
        choice = dict((c[0], c[2]) for c in INK_CHOICES).get(self.cfg["inkChoice"])
        return QtGui.QColor(choice or STYLE_INK.get(self.cfg["style"], "#8754F2"))

    # ---- input
    def mouseMoveEvent(self, e):
        self.cursor = QtCore.QPointF(e.pos())
        if self.held and self.ink:
            self.ink[-1].append(QtCore.QPointF(e.pos()))

    def mousePressEvent(self, e):
        pos = QtCore.QPointF(e.pos())
        self.cursor = pos
        for rect, action in self.toolbar_rects:
            if rect.contains(pos.toPoint()):
                log(f"toolbar hit at {pos.x():.0f},{pos.y():.0f}")
                action()
                return
        if self.mod_held(e.modifiers()) and self.app.x11 and self.app.x11.xtest:
            g = pos.toPoint() + self.origin
            self.hide()                                    # let the click land on the app below
            log(f"native click at {g.x()},{g.y()}")
            self.app.x11.click(g.x(), g.y())
            QtCore.QTimer.singleShot(140, self._reshow)
            return
        if e.button() == QtCore.Qt.MiddleButton:           # wheel click: erase the ink
            self.held = False
            if self.ink:
                log(f"wheel click: cleared {len(self.ink)} stroke(s)")
                self.clear_ink()
            return
        self.held = True
        self.press = 1.0
        self.ink.append([pos])
        self.app.play_tap()
        log(f"tap at {pos.x():.0f},{pos.y():.0f} (swallowed, nothing underneath)")

    def _reshow(self):
        if self.active:
            self.show()
            self.raise_()

    def mouseReleaseEvent(self, e):
        self.held = False

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.app.deactivate()

    def mod_held(self, mods):
        want = self.cfg["interactKey"]
        if want == "ctrl":
            return bool(mods & QtCore.Qt.ControlModifier)
        if want == "alt":
            return bool(mods & QtCore.Qt.AltModifier)
        if want == "shift":
            return bool(mods & QtCore.Qt.ShiftModifier)
        return False

    # ---- per frame
    def tick(self):
        gpos = QtGui.QCursor.pos()
        self.cursor = QtCore.QPointF(gpos - self.origin)
        if self.cfg.get("_dirty"):
            self.cfg.pop("_dirty")
            self.rebuild_geometry()
        self.update()

    # ---- port of ArmView.aim()
    def pose(self, screen_rect):
        c = self.cursor
        W, H = screen_rect.width(), screen_rect.height()
        target_x = min(max(c.x() + GRIP_LEAN * W, W * 0.15), W * 1.05)
        self.gx = target_x if self.gx is None else self.gx + (target_x - self.gx) * GRIP_FOLLOW
        if not self.held:
            self.press += (0 - self.press) * 0.18
        grip = QtCore.QPointF(self.gx, screen_rect.bottom() + GRIP_DEPTH * H - self.origin.y())
        a = self.asset
        dx = c.x() - grip.x()
        dy = c.y() - grip.y()
        reach = math.hypot(dx, dy)
        hand_pts = self.cfg["pointerSize"] * H * (1 - 0.06 * self.press)
        s = hand_pts / (a.wrist - a.hand_top)
        width_pts = s * a.aspect
        hand_tip_pts = (a.wrist - a.tip) * s
        tip_off_x = (a.tip_x - a.rod_x) * width_pts
        along = math.sqrt(max(0.0, reach * reach - tip_off_x * tip_off_x))
        rod_len = max(MIN_ROD * H, along - hand_tip_pts)
        tip_angle = math.atan2(rod_len + hand_tip_pts, tip_off_x)
        rotation = math.atan2(-dy, dx) - tip_angle
        lift = LIFT * H * (1 - 0.8 * self.press)
        return grip, rotation, rod_len, hand_pts, width_pts, lift

    def draw_sprite(self, p, img, grip, rotation, rod_len, hand_pts, width_pts):
        a = self.asset
        p.save()
        p.translate(grip)
        p.rotate(-math.degrees(rotation))
        p.save()
        p.translate(0, -rod_len)
        p.drawImage(QtCore.QRectF(-width_pts / 2, 0, width_pts, rod_len), img, a.src_rod())
        p.restore()
        p.save()
        p.translate(0, -(rod_len + hand_pts))
        p.drawImage(QtCore.QRectF(-width_pts / 2, 0, width_pts, hand_pts), img, a.src_hand())
        p.restore()
        p.restore()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        screen_rect = self.screen_for(QtGui.QCursor.pos())

        if self.ink:
            pen = QtGui.QPen(self.ink_colour())
            pen.setWidthF(max(3.0, screen_rect.height() * 0.0055))
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            p.setPen(pen)
            for stroke in self.ink:
                if len(stroke) == 1:
                    p.drawPoint(stroke[0])
                for i in range(1, len(stroke)):
                    p.drawLine(stroke[i - 1], stroke[i])

        if self.cfg["style"] == "laser":
            self.draw_laser(p, screen_rect)
        elif self.asset is not None:
            grip, rotation, rod_len, hand_pts, width_pts, lift = self.pose(screen_rect)
            if self.cfg["showShadow"]:
                p.setOpacity(0.30 + 0.04 * self.press)
                self.draw_sprite(p, self.asset.shadow,
                                 QtCore.QPointF(grip.x() + lift * 0.6, grip.y() + lift),
                                 rotation, rod_len, hand_pts, width_pts)
                p.setOpacity(1.0)
            self.draw_sprite(p, self.asset.img, grip, rotation, rod_len, hand_pts, width_pts)

        self.draw_toolbar(p, screen_rect)
        p.end()

    def draw_laser(self, p, screen_rect):
        r = max(4.0, screen_rect.height() * 0.0038 * self.cfg["pointerSize"] / 0.13) * (1 + 0.2 * self.press)
        c = self.cursor
        grad = QtGui.QRadialGradient(c, r * 3.2)
        grad.setColorAt(0.0, QtGui.QColor(255, 60, 60, 200))
        grad.setColorAt(0.45, QtGui.QColor(255, 60, 60, 70))
        grad.setColorAt(1.0, QtGui.QColor(255, 60, 60, 0))
        p.setBrush(QtGui.QBrush(grad))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(c, r * 3.2, r * 3.2)
        p.setBrush(QtGui.QColor(255, 40, 40))
        p.drawEllipse(c, r, r)
        p.setBrush(QtGui.QColor(255, 220, 210, 240))
        p.drawEllipse(c, r * 0.45, r * 0.45)

    # ---- toolbar
    def draw_toolbar(self, p, screen_rect):
        if not self.cfg.get("showToolbar", True):
            self.toolbar_rects = []
            return
        c = self.cursor
        bottom = screen_rect.bottom() - self.origin.y()
        cx = screen_rect.center().x() - self.origin.x()
        reveal = (QtCore.QDateTime.currentDateTime() < self.reveal_until
                  or bottom - c.y() < 90)
        if not reveal:
            self.toolbar_rects = []
            return

        pins = self.cfg["pinned"]
        thumb = 40
        gap = 6
        pad = 8
        n = len(pins) + 2                      # + sound + exit
        w = pad * 2 + n * thumb + (n - 1) * gap
        h = thumb + pad * 2
        left = min(max(cx - w / 2, 12), self.width() - w - 12)
        self.toolbar_bar = QtCore.QRectF(left, bottom - h - 46, w, h)
        top = bottom - h - 46
        bar = QtCore.QRectF(left, top, w, h)

        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(20, 20, 24, 225))
        p.drawRoundedRect(bar, 14, 14)

        rects = []
        x = left + pad
        y = top + pad
        for style in pins:
            r = QtCore.QRectF(x, y, thumb, thumb)
            active = style == self.cfg["style"]
            p.setBrush(QtGui.QColor(255, 255, 255, 55 if active else 18))
            p.drawRoundedRect(r, 9, 9)
            if style == "laser":
                p.setBrush(QtGui.QColor(240, 50, 50))
                p.drawEllipse(r.center(), 7, 7)
            else:
                asset = self.assets.get(style)
                if asset is not None:
                    p.drawPixmap(int(r.center().x() - asset.thumb.width() / 2),
                                 int(r.center().y() - asset.thumb.height() / 2),
                                 QtGui.QPixmap.fromImage(asset.thumb))
            rects.append((r, (lambda s=style: self.pick(s))))
            x += thumb + gap

        sound_on = self.cfg["soundLaser"] if self.cfg["style"] == "laser" else self.cfg["soundHands"]
        r = QtCore.QRectF(x, y, thumb, thumb)
        p.setBrush(QtGui.QColor(255, 255, 255, 18))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QtGui.QPen(QtGui.QColor(235, 235, 240)))
        f = p.font()
        f.setPointSizeF(13)
        p.setFont(f)
        p.drawText(r, QtCore.Qt.AlignCenter, "\U0001F50A" if sound_on else "\U0001F507")
        p.setPen(QtCore.Qt.NoPen)
        rects.append((r, self.toggle_sound))
        x += thumb + gap

        r = QtCore.QRectF(x, y, thumb, thumb)
        p.setBrush(QtGui.QColor(255, 255, 255, 18))
        p.drawRoundedRect(r, 9, 9)
        p.setPen(QtGui.QPen(QtGui.QColor(240, 120, 120)))
        p.drawText(r, QtCore.Qt.AlignCenter, "\u2715")
        p.setPen(QtCore.Qt.NoPen)
        rects.append((r, self.app.deactivate))
        self.toolbar_rects = rects

    def pick(self, style):
        log(f"pick {style}")
        self.load_style(style)
        self.app.set_style(style)
        self.reveal_until = QtCore.QDateTime.currentDateTime().addSecs(3)

    def toggle_sound(self):
        key = "soundLaser" if self.cfg["style"] == "laser" else "soundHands"
        self.cfg[key] = not self.cfg[key]
        self.app.save()
        self.reveal_until = QtCore.QDateTime.currentDateTime().addSecs(3)

    def clear_ink(self):
        self.ink = []


# --------------------------------------------------------------------- settings
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cfg = app.cfg
        self.setWindowTitle("TinyHand settings")
        self.setMinimumWidth(420)
        lay = QtWidgets.QFormLayout(self)

        self.size = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size.setRange(8, 20)
        self.size.setValue(int(round(self.cfg["pointerSize"] * 100)))
        self.size_label = QtWidgets.QLabel()
        self.size.valueChanged.connect(self.on_size)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.size)
        row.addWidget(self.size_label)
        lay.addRow("Hand size", row)
        self.on_size(self.size.value())

        self.shadow = QtWidgets.QCheckBox("Drop shadow")
        self.shadow.setChecked(self.cfg["showShadow"])
        self.shadow.toggled.connect(self.set_cfg("showShadow"))
        lay.addRow(self.shadow)

        self.tap = QtWidgets.QComboBox()
        for name in ("boop", "click", "pop", "squeak", "thock", "wood"):
            self.tap.addItem(name, name)
        self.tap.setCurrentText(self.cfg["tapSound"])
        self.tap.currentIndexChanged.connect(self.set_cfg("tapSound", self.tap.currentData))
        lay.addRow("Tap sound", self.tap)

        self.ink = QtWidgets.QComboBox()
        for key, title, _c in INK_CHOICES:
            self.ink.addItem(title, key)
        self.ink.setCurrentIndex([c[0] for c in INK_CHOICES].index(self.cfg["inkChoice"]))
        self.ink.currentIndexChanged.connect(self.set_cfg("inkChoice", self.ink.currentData))
        lay.addRow("Ink colour", self.ink)

        self.interact = QtWidgets.QComboBox()
        for key, title in (("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("off", "Off")):
            self.interact.addItem(f"Hold {title} to click for real" if key != "off" else "Off",
                                  key)
        self.interact.setCurrentIndex(["ctrl", "alt", "shift", "off"].index(self.cfg["interactKey"]))
        self.interact.currentIndexChanged.connect(self.set_cfg("interactKey", self.interact.currentData))
        lay.addRow("Pass-through click", self.interact)

        pins = QtWidgets.QGroupBox("Toolbar hands (up to 8)")
        grid = QtWidgets.QGridLayout(pins)
        self.pin_boxes = {}
        for i, (key, title, _c) in enumerate(STYLES):
            cb = QtWidgets.QCheckBox(title)
            cb.setChecked(key in self.cfg["pinned"])
            cb.toggled.connect(self.on_pin)
            self.pin_boxes[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        inner = QtWidgets.QScrollArea()
        inner.setWidget(pins)
        inner.setWidgetResizable(True)
        inner.setMinimumHeight(190)
        lay.addRow(inner)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addRow(close)

    def on_size(self, v):
        self.cfg["pointerSize"] = v / 100.0
        self.size_label.setText(f"{v}% of the screen height")
        self.app.save()

    def set_cfg(self, key, getter=None):
        def handler(*_a):
            if getter is not None:
                self.cfg[key] = getter()
            else:
                self.cfg[key] = self.shadow.isChecked()
            self.app.save()
        return handler

    def on_pin(self, *_a):
        chosen = [k for k, cb in self.pin_boxes.items() if cb.isChecked()]
        if len(chosen) > 8:
            for key in chosen[8:]:
                self.pin_boxes[key].blockSignals(True)
                self.pin_boxes[key].setChecked(False)
                self.pin_boxes[key].blockSignals(False)
            chosen = chosen[:8]
        self.cfg["pinned"] = chosen or ["lavender", "laser"]
        self.app.save()


# -------------------------------------------------------------------- the app
class TinyHand(QtWidgets.QApplication):
    HOTKEYS = {"toggle": ("h", 0), "clear": ("x", 0)}       # + Ctrl+Alt masks

    def __init__(self, argv, cfg):
        super().__init__(argv)
        self.cfg = cfg
        self.assets = Assets()
        self.setQuitOnLastWindowClosed(False)
        self.x11 = None
        try:
            self.x11 = X11()
        except Exception as exc:
            print(f"x11 unavailable: {exc}", file=sys.stderr)

        self.overlay = Overlay(self)
        self.settings = None

        self.tray = QtWidgets.QSystemTrayIcon(self.make_tray_icon(False), self)
        self.tray.setToolTip("TinyHand")
        self.tray_menu = self.build_menu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        self.hotkey_timer = QtCore.QTimer(self)
        self.hotkey_timer.timeout.connect(self.poll_hotkeys)
        self.hotkey_timer.start(30)

        # signal control, so ~/.local/bin/tinyhand can toggle a running instance
        os.makedirs(PID_DIR, exist_ok=True)
        with open(PIDFILE, "w") as fh:
            fh.write(str(os.getpid()))
        self.pending = []
        signal.signal(signal.SIGUSR1, lambda *_a: self.pending.append("toggle"))
        signal.signal(signal.SIGUSR2, lambda *_a: self.pending.append("clear"))
        signal.signal(signal.SIGTERM, lambda *_a: self.pending.append("quit"))
        signal.signal(signal.SIGINT, lambda *_a: self.pending.append("quit"))
        self.sig_timer = QtCore.QTimer(self)
        self.sig_timer.timeout.connect(self.drain_signals)
        self.sig_timer.start(120)

        from Xlib import X
        self.masks_ctrl_alt = X.ControlMask | X.Mod1Mask
        self.install_hotkeys()

        if cfg.get("_startActive"):
            QtCore.QTimer.singleShot(300, self.activate)

    def drain_signals(self):
        while self.pending:
            act = self.pending.pop(0)
            log(f"signal {act}")
            if act == "toggle":
                self.toggle()
            elif act == "clear":
                self.overlay.clear_ink()
            elif act == "quit":
                self.quit_app()
                return

    # ---- hotkeys
    def install_hotkeys(self):
        if not self.x11:
            return
        from Xlib import X
        self.x11.grab("h", X.ControlMask | X.Mod1Mask, "toggle")
        self.x11.grab("x", X.ControlMask | X.Mod1Mask, "clear")

    def poll_hotkeys(self):
        if not self.x11:
            return
        for act in self.x11.poll():
            log(f"hotkey {act}")
            if act == "toggle":
                self.toggle()
            elif act == "clear":
                self.overlay.clear_ink()
            elif act == "quit":
                self.quit_app()
                return
            elif act == "escape":
                self.deactivate()

    def grab_escape(self, on):
        if not self.x11:
            return
        if on:
            self.x11.grab("Escape", 0, "escape")
        else:
            self.x11.ungrab("Escape", 0)

    # ---- tray
    def make_tray_icon(self, on):
        path = os.path.join(ICON_DIR, "menubar_on.png" if on else "menubar_off.png")
        icon = QtGui.QIcon(path)
        if icon.isNull():
            pm = QtGui.QPixmap(22, 22)
            pm.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setBrush(QtGui.QColor("#8754F2" if on else "#777777"))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(4, 4, 14, 14)
            p.end()
            icon = QtGui.QIcon(pm)
        return icon

    def build_menu(self):
        m = QtWidgets.QMenu()
        self.act_toggle = m.addAction("Turn pointer on")
        self.act_toggle.triggered.connect(self.toggle)
        styles = m.addMenu("Hand")
        for key, title, _c in STYLES:
            a = styles.addAction(title)
            a.setCheckable(True)
            a.setChecked(key == self.cfg["style"])
            a.triggered.connect(lambda _c=False, k=key: self.pick_from_menu(k))
            setattr(self, f"_style_act_{key}", a)
        m.addSeparator()
        self.act_sound = m.addAction("Tap sounds")
        self.act_sound.setCheckable(True)
        self.act_sound.setChecked(self.cfg["soundHands"])
        self.act_sound.triggered.connect(self.toggle_sound_menu)
        s = m.addAction("Settings\u2026")
        s.triggered.connect(self.open_settings)
        q = m.addAction("Quit")
        q.triggered.connect(self.quit_app)
        return m

    def pick_from_menu(self, key):
        self.cfg["style"] = key
        self.overlay.load_style(key)
        self.save()
        for k, _t, _c in STYLES:
            getattr(self, f"_style_act_{k}").setChecked(k == key)
        if self.overlay.active:
            self.overlay.reveal_until = QtCore.QDateTime.currentDateTime().addSecs(3)

    def set_style(self, key):
        self.cfg["style"] = key
        getattr(self, f"_style_act_{key}", None) and getattr(self, f"_style_act_{key}").setChecked(True)
        self.save()

    def toggle_sound_menu(self, checked):
        self.cfg["soundHands"] = checked
        self.cfg["soundLaser"] = checked
        self.save()

    def on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.toggle()

    def open_settings(self):
        if self.settings is None:
            self.settings = SettingsDialog(self)
        self.settings.show()
        self.settings.raise_()

    # ---- lifecycle
    def toggle(self):
        self.deactivate() if self.overlay.active else self.activate()

    def activate(self):
        if self.overlay.active:
            return
        log("activate")
        self.overlay.active = True
        self.overlay.rebuild_geometry()
        self.overlay.gx = None
        self.overlay.reveal_until = QtCore.QDateTime.currentDateTime().addSecs(3)
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.activateWindow()
        self.grab_escape(True)
        self.act_toggle.setText("Turn pointer off")
        self.tray.setIcon(self.make_tray_icon(True))

    def deactivate(self):
        if not self.overlay.active:
            return
        log("deactivate")
        self.overlay.active = False
        self.overlay.clear_ink()
        self.overlay.hide()
        self.grab_escape(False)
        self.act_toggle.setText("Turn pointer on")
        self.tray.setIcon(self.make_tray_icon(False))

    def quit_app(self):
        self.deactivate()
        try:
            os.unlink(PIDFILE)
        except OSError:
            pass
        if self.x11:
            self.x11.close()
        self.tray.hide()
        self.quit()

    # ---- misc
    def play_tap(self):
        sound_on = self.cfg["soundLaser"] if self.cfg["style"] == "laser" else self.cfg["soundHands"]
        if not sound_on:
            return
        path = os.path.join(SOUND_DIR, f"tap_{self.cfg['tapSound']}.wav")
        if not os.path.exists(path):
            return
        threading.Thread(target=subprocess.run,
                         args=(["pw-play", path],),
                         kwargs={"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL},
                         daemon=True).start()

    def save(self):
        save_config({k: v for k, v in self.cfg.items() if not k.startswith("_")})
        self.overlay.update()
        if self.settings is not None:
            self.settings.size.blockSignals(True)
            self.settings.size.setValue(int(round(self.cfg["pointerSize"] * 100)))
            self.settings.size.blockSignals(False)


def live_instance():
    """PID of a running instance, or None. Never returns our own pid."""
    try:
        with open(PIDFILE) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def main():
    ap = argparse.ArgumentParser(description="A tiny hand on a stick that points at things.")
    ap.add_argument("--on", action="store_true", help="start with the pointer already on")
    args = ap.parse_args()
    cfg = load_config()
    cfg["_startActive"] = args.on
    app = TinyHand(sys.argv[:1], cfg)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
