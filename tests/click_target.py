#!/usr/bin/env python3
"""Click-target probe: a plain window that reports every click it gets.
Used to prove the TinyHand overlay really swallows clicks meant for apps below."""
import sys
from PyQt5 import QtCore, QtWidgets

n = 0
app = QtWidgets.QApplication(sys.argv)
w = QtWidgets.QWidget()
w.setWindowTitle("click-target")
w.setGeometry(200, 200, 600, 400)
w.setStyleSheet("background:#2244aa;color:white;font:24px sans-serif")
lab = QtWidgets.QLabel("clicks: 0", w)
lab.move(20, 20)
w.show()


def on_press(e):
    global n
    n += 1
    lab.setText(f"clicks: {n}")
    print(f"TARGET GOT CLICK {n}", flush=True)


w.mousePressEvent = on_press
QtCore.QTimer.singleShot(9000, app.quit)
app.exec_()
print(f"TARGET TOTAL {n}", flush=True)
