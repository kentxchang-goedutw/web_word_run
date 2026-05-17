#!/usr/bin/env python3
"""
桌面彈幕 v3 — PyQt6 全桌面版
  · PyQt6 QPainter 直接繪製，無縮小問題
  · ctypes 讓覆蓋層完全穿透滑鼠
  · QFontMetrics 精確量文字寬，不需 update_idletasks
  · 現代 QSS 介面、自訂 ToggleSwitch
作者: 阿剛老師  https://kentxchang.blogspot.tw
授權: CC BY-NC-SA 4.0
"""
import sys, os, json, threading, time, random, re, subprocess, ctypes

# ── 自動安裝依賴 ──────────────────────────────────────────
for _pkg, _mod in [("PyQt6", "PyQt6"), ("requests", "requests")]:
    try:
        __import__(_mod)
    except ImportError:
        print(f"正在安裝 {_pkg}…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", _pkg])

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit,
    QSlider, QScrollArea, QFrame, QVBoxLayout, QHBoxLayout,
    QSizePolicy, QMessageBox, QColorDialog,
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPoint, QRect, QSize,
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QFontMetrics,
    QLinearGradient, QRadialGradient, QPainterPath, QCursor,
)
import requests

# ── 常數 ──────────────────────────────────────────────────
# 打包成 exe 後 __file__ 指向暫存目錄，改用 exe 本身所在目錄
_BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
            else os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(_BASE_DIR, "marquee_settings.json")
FPS      = 30
FRAME_MS = 1000 // FPS
POST_URL_BASE = "https://kentxchang-goedutw.github.io/web_word_run/"
PINK      = "#3b82f6"
PINK_DARK = "#2563eb"
PINK_LIGHT = "#dbeafe"

DEFAULT_SETTINGS = {
    "isActive": False,
    "gasUrl": "",
    "minFontSize": 60,
    "maxFontSize": 120,
    "minSpeed": 8,
    "maxSpeed": 15,
    "repeatCount": 3,
    "colors": ["#3b82f6", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"],
}

GAS_CODE = """\
function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("跑馬燈資料");
  if (!sheet) {
    sheet = ss.insertSheet("跑馬燈資料");
    sheet.appendRow(["時間", "內容"]);
    sheet.getRange("1:1").setFontWeight("bold").setBackground("#ffe4e6");
  }
  return sheet;
}

function doGet(e) {
  const sheet = getSheet();
  const data = sheet.getDataRange().getValues();
  data.shift();
  const result = data.map(row => ({ "時間": row[0], "內容": row[1] }));
  const callback = e.parameter.callback;
  const json = JSON.stringify(result);
  if (callback) {
    return ContentService.createTextOutput(callback + "(" + json + ")")
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  return ContentService.createTextOutput(json).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  const sheet = getSheet();
  const params = JSON.parse(e.postData.contents);
  if (params.action === "clear") {
    if (sheet.getLastRow() > 1) {
      sheet.getRange(2, 1, sheet.getLastRow() - 1, 2).clearContent();
    }
    return ContentService.createTextOutput("cleared");
  }
  sheet.appendRow([new Date(), params.content]);
  return ContentService.createTextOutput("success");
}"""

# ── 設定讀寫 ────────────────────────────────────────────
def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        m = DEFAULT_SETTINGS.copy(); m.update(s)
        return m
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

# ── 工具 ────────────────────────────────────────────────
def rand_int(a, b):
    a, b = int(a), int(b)
    if a > b: a, b = b, a
    return random.randint(a, b)

def set_click_through(hwnd):
    """讓視窗完全穿透滑鼠（Windows）"""
    GWL_EXSTYLE   = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    style = ctypes.windll.user32.GetWindowLongW(int(hwnd), GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(
        int(hwnd), GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT)


# ═══════════════════════════════════════════════════════
#  MarqueeItem — 單條跑馬燈資料 + 繪製邏輯
# ═══════════════════════════════════════════════════════
class MarqueeItem:
    def __init__(self, text, settings, sw, sh):
        size     = rand_int(settings["minFontSize"], settings["maxFontSize"])
        color_s  = random.choice(settings["colors"])
        speed_s  = rand_int(settings["minSpeed"], settings["maxSpeed"])

        self.text         = text
        self.font         = QFont("Microsoft JhengHei", size, QFont.Weight.Bold)
        self.color        = QColor(color_s)
        self.speed        = max(1.0, sw / (speed_s * FPS))
        self.repeat_count = int(settings["repeatCount"])
        self.repeats_done = 0
        self.moved        = 0.0

        fm = QFontMetrics(self.font)
        self.text_w  = fm.horizontalAdvance(text)
        self.ascent  = fm.ascent()

        margin  = size + 20
        hi      = max(margin + 1, sh - margin)
        # y = 文字基線
        self.y  = random.randint(margin + self.ascent, hi)
        self.x  = float(sw + 60)
        self.trip_dist = float(sw + 60 + self.text_w)

    def tick(self):
        """回傳 True = 繼續；False = 播完，請移除"""
        self.x     -= self.speed
        self.moved += self.speed
        if self.moved >= self.trip_dist:
            self.repeats_done += 1
            if self.repeats_done >= self.repeat_count:
                return False
            overshoot   = self.moved - self.trip_dist
            self.x     += self.trip_dist   # 彈回右側
            self.moved  = overshoot
        return True

    def draw(self, painter: QPainter):
        painter.setFont(self.font)
        ix, iy = int(self.x), self.y
        # 描邊陰影（四方向各偏移2px，深色半透明）
        shadow = QColor(10, 10, 10, 170)
        painter.setPen(shadow)
        for dx, dy in ((2, 2), (-2, 2), (2, -2), (-2, -2)):
            painter.drawText(ix + dx, iy + dy, self.text)
        # 主文字
        painter.setPen(self.color)
        painter.drawText(ix, iy, self.text)


# ═══════════════════════════════════════════════════════
#  MarqueeOverlay — 全桌面透明覆蓋層
# ═══════════════════════════════════════════════════════
class MarqueeOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.items: list[MarqueeItem] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # 全螢幕覆蓋主螢幕
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def show_overlay(self):
        self.show()
        QApplication.processEvents()          # 確保 winId 已建立
        set_click_through(self.winId())       # 穿透滑鼠
        self._timer.start(FRAME_MS)

    def hide_overlay(self):
        self._timer.stop()
        self.items.clear()
        self.hide()

    def add_text(self, text, settings):
        sw = self.width()
        sh = self.height()
        self.items.append(MarqueeItem(text, settings, sw, sh))

    def clear_items(self):
        self.items.clear()
        self.update()

    def _tick(self):
        self.items = [i for i in self.items if i.tick()]
        self.update()   # 觸發 paintEvent

    def paintEvent(self, event):
        if not self.items:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for item in self.items:
            item.draw(painter)
        painter.end()


# ═══════════════════════════════════════════════════════
#  ToggleSwitch — 自訂開關元件
# ═══════════════════════════════════════════════════════
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(56, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self): return self._checked

    def setChecked(self, v):
        self._checked = bool(v)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        # 軌道
        track = QColor(PINK) if self._checked else QColor("#d1d5db")
        p.setBrush(track)
        p.drawRoundedRect(0, 4, 56, 20, 10, 10)

        # 滑鈕（帶陰影）
        thumb_x = 30 if self._checked else 2
        p.setBrush(QColor(200, 200, 200, 80))
        p.drawEllipse(thumb_x + 2, 4, 24, 24)   # shadow
        p.setBrush(QColor("white"))
        p.drawEllipse(thumb_x, 2, 24, 24)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit(self._checked)


# ═══════════════════════════════════════════════════════
#  FloatingIcon — 可拖曳浮動圓形圖示
# ═══════════════════════════════════════════════════════
class FloatingIcon(QWidget):
    SIZE = 82

    def __init__(self, app_ref):
        super().__init__()
        self._app     = app_ref
        self._active  = False
        self._dragged = False
        self._drag_pos = QPoint()
        self._pulse   = 0.0
        self._pulse_d = 1

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.right() - 110, screen.bottom() - 160)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(60)

        self.show()

    # ── 繪製 ─────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s  = self.SIZE
        cx = cy = s // 2

        # 陰影
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(8, 8, s - 10, s - 10)

        # 漸層外圓
        grad = QRadialGradient(cx, cy - 10, s // 2)
        if self._active:
            grad.setColorAt(0.0, QColor("#93c5fd"))
            grad.setColorAt(1.0, QColor("#1d4ed8"))
        else:
            grad.setColorAt(0.0, QColor("#6b7280"))
            grad.setColorAt(1.0, QColor("#1f2937"))
        p.setBrush(QBrush(grad))
        p.drawEllipse(4, 4, s - 8, s - 8)

        # 高光
        hi = QRadialGradient(cx - 8, cy - 14, 18)
        hi.setColorAt(0.0, QColor(255, 255, 255, 90))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hi))
        p.drawEllipse(cx - 26, cy - 28, 32, 22)

        # 主文字「彈幕」
        p.setPen(QColor("white"))
        danmu_font = QFont("Microsoft JhengHei", 20, QFont.Weight.Bold)
        p.setFont(danmu_font)
        p.drawText(QRect(0, 6, s, s // 2 + 8),
                   Qt.AlignmentFlag.AlignHCenter, "彈幕")

        status_font = QFont("Microsoft JhengHei", 9, QFont.Weight.Bold)
        p.setFont(status_font)
        p.setPen(QColor("#dbeafe") if self._active else QColor("#9ca3af"))
        p.drawText(QRect(0, cy + 14, s, 20),
                   Qt.AlignmentFlag.AlignHCenter,
                   "ON ✨" if self._active else "OFF")

        # active 光環（脈衝）
        if self._active:
            alpha = int(120 + 80 * abs(self._pulse - 0.5) * 2)
            ring_pen = QPen(QColor(236, 72, 153, alpha), 2.5)
            p.setPen(ring_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(3, 3, s - 6, s - 6)

        p.end()

    def _animate(self):
        if self._active:
            self._pulse += self._pulse_d * 0.04
            if self._pulse >= 1.0: self._pulse_d = -1
            elif self._pulse <= 0.0: self._pulse_d = 1
            self.update()

    def update_status(self, active):
        self._active = active
        self.update()

    # ── 拖曳 ─────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._dragged = True

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._dragged:
            self._app.toggle_settings()

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-family: 'Microsoft JhengHei'; font-size: 12px; }")
        menu.addAction("⚙️  設定", self._app.toggle_settings)
        menu.addSeparator()
        menu.addAction("❌  結束程式", self._app.quit)
        menu.exec(event.globalPos())


# ═══════════════════════════════════════════════════════
#  SettingsPanel — 現代設定視窗（QSS 風格）
# ═══════════════════════════════════════════════════════
PANEL_QSS = """
QWidget#panel {
    background: #fff5f7;
}
QScrollArea {
    border: none;
    background: #fff5f7;
}
QWidget#scrollContent {
    background: #fff5f7;
}
QFrame.card {
    background: white;
    border-radius: 14px;
    border: 1px solid #dbeafe;
}
QLabel.sectionTitle {
    color: #3b82f6;
    font-size: 13px;
    font-weight: bold;
    font-family: "Microsoft JhengHei";
}
QLabel.sublabel {
    color: #6b7280;
    font-size: 10px;
    font-family: "Microsoft JhengHei";
}
QLabel.valLabel {
    color: #3b82f6;
    font-size: 11px;
    font-weight: bold;
    font-family: "Arial";
}
QLabel.status {
    color: #3b82f6;
    font-size: 10px;
    font-family: "Microsoft JhengHei";
}
QLineEdit {
    border: 2px solid #dbeafe;
    border-radius: 8px;
    padding: 6px 10px;
    font-family: "Consolas";
    font-size: 11px;
    color: #374151;
    background: white;
}
QLineEdit:focus {
    border-color: #3b82f6;
}
QPushButton#btnPrimary {
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 12px;
    padding: 12px;
    font-size: 14px;
    font-weight: bold;
    font-family: "Microsoft JhengHei";
}
QPushButton#btnPrimary:hover   { background: #2563eb; }
QPushButton#btnPrimary:pressed { background: #1d4ed8; }
QPushButton#btnSecondary {
    background: #f3f4f6;
    color: #4b5563;
    border: none;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 11px;
    font-family: "Microsoft JhengHei";
}
QPushButton#btnSecondary:hover   { background: #e5e7eb; }
QPushButton#btnSecondary:pressed { background: #d1d5db; }
QPushButton#btnDanger {
    background: #fef2f2;
    color: #dc2626;
    border: 1px solid #fecaca;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 11px;
    font-family: "Microsoft JhengHei";
}
QPushButton#btnDanger:hover { background: #fee2e2; }
QSlider::groove:horizontal {
    height: 6px;
    background: #dbeafe;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 20px;
    height: 20px;
    border-radius: 10px;
    background: #3b82f6;
    margin: -7px 0;
}
QSlider::sub-page:horizontal {
    background: #3b82f6;
    border-radius: 3px;
}
"""

class SettingsPanel(QWidget):
    def __init__(self, app_ref):
        super().__init__()
        self._app = app_ref
        self._color_vars = [""] * 5
        self._color_btns = []
        self._help_visible = False
        self._help_widget = None

        self.setObjectName("panel")
        # CustomizeWindowHint + MinimizeButtonHint → 只保留縮小鈕，隱藏關閉鈕
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowTitle("桌面彈幕控制中心 ✨")
        self.setFixedWidth(440)
        self.setStyleSheet(PANEL_QSS)

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(
            (screen.width() - 440) // 2,
            (screen.height() - 740) // 2,
            440, 740)

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # ── 捲動區域 ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root_layout.addWidget(scroll)

        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)

        self._main_layout = QVBoxLayout(content)
        self._main_layout.setContentsMargins(16, 14, 16, 14)
        self._main_layout.setSpacing(10)
        ml = self._main_layout

        def card(title=None):
            f = QFrame()
            f.setProperty("class", "card")
            f.setStyleSheet("QFrame { background: white; border-radius: 14px; "
                            "border: 1px solid #dbeafe; }")
            v = QVBoxLayout(f)
            v.setContentsMargins(14, 10, 14, 12)
            v.setSpacing(4)
            if title:
                lbl = QLabel(title)
                lbl.setProperty("class", "sectionTitle")
                lbl.setStyleSheet("color:#3b82f6;font-size:13px;font-weight:bold;"
                                  "font-family:'Microsoft JhengHei';border:none;")
                v.addWidget(lbl)
            return f, v

        def sublabel(text, parent_layout):
            l = QLabel(text)
            l.setStyleSheet("color:#6b7280;font-size:10px;"
                            "font-family:'Microsoft JhengHei';border:none;")
            parent_layout.addWidget(l)

        def val_label(parent_layout):
            l = QLabel()
            l.setStyleSheet("color:#3b82f6;font-size:11px;font-weight:bold;"
                            "font-family:'Arial';border:none;")
            parent_layout.addWidget(l)
            return l

        def pink_slider(lo, hi, val, on_change):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(int(val))
            sl.valueChanged.connect(on_change)
            return sl

        # ── 標題 ─────────────────────────────────────────
        title = QLabel("桌面彈幕控制中心 ✨")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("color:#3b82f6;font-size:18px;font-weight:bold;"
                            "font-family:'Microsoft JhengHei';padding:6px 0;border:none;")
        ml.addWidget(title)

        # ── 啟用開關 ──────────────────────────────────────
        tog_frame = QFrame()
        tog_frame.setStyleSheet("background:#2563eb;border-radius:14px;")
        tog_row = QHBoxLayout(tog_frame)
        tog_row.setContentsMargins(14, 8, 14, 8)
        tog_lbl = QLabel("啟用桌面彈幕")
        tog_lbl.setStyleSheet("color:white;font-size:13px;font-weight:bold;"
                              "font-family:'Microsoft JhengHei';border:none;")
        self._toggle = ToggleSwitch(self._app.settings.get("isActive", False))
        tog_row.addWidget(tog_lbl)
        tog_row.addStretch()
        tog_row.addWidget(self._toggle)
        ml.addWidget(tog_frame)

        # ── GAS 網址 ──────────────────────────────────────
        gas_f, gas_v = card("🌐  GAS Web App 網址")
        self._url_edit = QLineEdit(self._app.settings.get("gasUrl", ""))
        self._url_edit.setPlaceholderText("貼上 GAS 網址（含 /exec）…")
        self._url_edit.setFixedHeight(34)
        gas_v.addWidget(self._url_edit)

        btn_row_w = QWidget(); btn_row_w.setStyleSheet("border:none;")
        btn_row = QHBoxLayout(btn_row_w)
        btn_row.setContentsMargins(0, 4, 0, 0); btn_row.setSpacing(6)

        post_btn = QPushButton("開啟訪客發文網址 ✨"); post_btn.setObjectName("btnSecondary")
        post_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        post_btn.clicked.connect(self._open_post)
        btn_row.addWidget(post_btn)

        help_btn = QPushButton("❓"); help_btn.setObjectName("btnSecondary")
        help_btn.setFixedWidth(36); help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        help_btn.clicked.connect(self._toggle_help)
        btn_row.addWidget(help_btn)
        gas_v.addWidget(btn_row_w)

        # 說明折疊
        self._help_widget = QWidget(); self._help_widget.setVisible(False)
        self._help_widget.setStyleSheet(
            "background:#fff0f6;border-radius:10px;border:none;")
        hv = QVBoxLayout(self._help_widget)
        hv.setContentsMargins(10, 8, 10, 8)
        help_text = QLabel(
            "如何設定 GAS：\n"
            "1. 建立 Google Apps Script 專案\n"
            "2. 貼入程式碼並存檔\n"
            "3. 點擊「部署」>「新部署」\n"
            "4. 類型選「網頁應用程式」\n"
            "5. 「誰有權存取」選「任何人」\n"
            "6. 部署後複製網址貼回上方"
        )
        help_text.setStyleSheet(
            "color:#4b5563;font-size:10px;font-family:'Microsoft JhengHei';border:none;")
        hv.addWidget(help_text)

        self._copy_btn = QPushButton("📋 複製 GAS 程式碼")
        self._copy_btn.setObjectName("btnSecondary")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self._copy_gas)
        hv.addWidget(self._copy_btn)
        gas_v.addWidget(self._help_widget)
        ml.addWidget(gas_f)

        # ══ 儲存 + 清空（二欄，GAS 下方、字體設定上方）═════
        action_row_w = QWidget(); action_row_w.setStyleSheet("border:none;")
        action_row = QHBoxLayout(action_row_w)
        action_row.setContentsMargins(0, 0, 0, 0); action_row.setSpacing(8)

        self._save_btn = QPushButton("儲存並套用 ✨")
        self._save_btn.setObjectName("btnPrimary")
        self._save_btn.setFixedHeight(46)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._save)
        action_row.addWidget(self._save_btn, 3)   # 佔 3/4 寬

        self._clear_btn = QPushButton("清空\n雲端資料")
        self._clear_btn.setObjectName("btnDanger")
        self._clear_btn.setFixedHeight(46)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._clear_cloud)
        action_row.addWidget(self._clear_btn, 1)   # 佔 1/4 寬

        ml.addWidget(action_row_w)

        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._status_lbl.setStyleSheet(
            "color:#3b82f6;font-size:10px;font-family:'Microsoft JhengHei';border:none;")
        ml.addWidget(self._status_lbl)

        # ── 文字大小 ──────────────────────────────────────
        s = self._app.settings
        font_f, font_v = card("📏  文字大小 (px)")
        self._font_lbl = val_label(font_v)
        self._min_font_sl = pink_slider(20, 350, s["minFontSize"], self._upd_font)
        self._max_font_sl = pink_slider(20, 350, s["maxFontSize"], self._upd_font)
        sublabel("最小字體", font_v); font_v.addWidget(self._min_font_sl)
        sublabel("最大字體", font_v); font_v.addWidget(self._max_font_sl)
        self._upd_font()
        ml.addWidget(font_f)

        # ── 速度 ──────────────────────────────────────────
        speed_f, speed_v = card("⚡  顯示速度（秒，數字越小越快）")
        self._speed_lbl = val_label(speed_v)
        self._min_speed_sl = pink_slider(2, 40, s["minSpeed"], self._upd_speed)
        self._max_speed_sl = pink_slider(2, 40, s["maxSpeed"], self._upd_speed)
        sublabel("最快速度", speed_v); speed_v.addWidget(self._min_speed_sl)
        sublabel("最慢速度", speed_v); speed_v.addWidget(self._max_speed_sl)
        self._upd_speed()
        ml.addWidget(speed_f)

        # ── 重複次數 ──────────────────────────────────────
        rep_f, rep_v = card("🔄  每條文字重複次數")
        self._rep_lbl = val_label(rep_v)
        self._rep_sl = pink_slider(1, 10, s["repeatCount"], self._upd_rep)
        rep_v.addWidget(self._rep_sl)
        self._upd_rep()
        ml.addWidget(rep_f)

        # ── 調色盤 ────────────────────────────────────────
        col_f, col_v = card("🎨  隨機調色盤（點色塊更換）")
        col_row_w = QWidget(); col_row_w.setStyleSheet("border:none;")
        col_row = QHBoxLayout(col_row_w)
        col_row.setContentsMargins(0, 4, 0, 0); col_row.setSpacing(8)

        colors = (s["colors"] + ["#cccccc"] * 5)[:5]
        self._color_vars = list(colors)
        self._color_btns = []

        for i in range(5):
            btn = QPushButton()
            btn.setFixedSize(44, 44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._set_color_btn(btn, colors[i])
            btn.clicked.connect(lambda _, idx=i: self._pick_color(idx))
            col_row.addWidget(btn)
            self._color_btns.append(btn)

        col_row.addStretch()
        col_v.addWidget(col_row_w)
        ml.addWidget(col_f)

        # ── 頁尾 ──────────────────────────────────────────
        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#dbeafe;border:none;")
        ml.addWidget(sep)
        foot = QLabel("Made by 阿剛老師  ·  CC BY-NC-SA 4.0")
        foot.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        foot.setStyleSheet("color:#9ca3af;font-size:9px;"
                           "font-family:'Microsoft JhengHei';border:none;")
        ml.addWidget(foot)
        ml.addStretch()

    # ── 介面更新 ─────────────────────────────────────────
    def _upd_font(self):
        self._font_lbl.setText(
            f"{self._min_font_sl.value()} ~ {self._max_font_sl.value()} px")

    def _upd_speed(self):
        self._speed_lbl.setText(
            f"{self._min_speed_sl.value()} ~ {self._max_speed_sl.value()} 秒")

    def _upd_rep(self):
        self._rep_lbl.setText(f"{self._rep_sl.value()} 次")

    @staticmethod
    def _set_color_btn(btn, color):
        btn.setStyleSheet(
            f"QPushButton {{ background:{color}; border-radius:8px; border:2px solid #e5e7eb; }}"
            f"QPushButton:hover {{ border-color:#3b82f6; }}")

    # ── 動作 ─────────────────────────────────────────────
    def _open_post(self):
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "請先輸入 GAS 網址"); return
        import webbrowser
        webbrowser.open(f"{POST_URL_BASE}?gasurl={url}")

    def _toggle_help(self):
        self._help_visible = not self._help_visible
        self._help_widget.setVisible(self._help_visible)

    def _copy_gas(self):
        QApplication.clipboard().setText(GAS_CODE)
        old = self._copy_btn.text()
        self._copy_btn.setText("✅ 已複製！")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText(old))

    def _save(self):
        url = self._url_edit.text().strip()
        if url and "/exec" not in url:
            QMessageBox.warning(self, "網址格式警告",
                                "GAS 網址格式可能有誤\n（正確格式應包含 /exec）")
            return
        self._app.apply_settings({
            "isActive":    self._toggle.isChecked(),
            "gasUrl":      url,
            "minFontSize": self._min_font_sl.value(),
            "maxFontSize": self._max_font_sl.value(),
            "minSpeed":    self._min_speed_sl.value(),
            "maxSpeed":    self._max_speed_sl.value(),
            "repeatCount": self._rep_sl.value(),
            "colors":      list(self._color_vars),
        })
        self._status_lbl.setText("✅ 已儲存並套用！ ✨")
        QTimer.singleShot(3000, lambda: self._status_lbl.setText(""))

    def _pick_color(self, idx):
        cur = QColor(self._color_vars[idx])
        col = QColorDialog.getColor(cur, self, "選擇顏色")
        if col.isValid():
            self._color_vars[idx] = col.name()
            self._set_color_btn(self._color_btns[idx], col.name())

    def _clear_cloud(self):
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "請先輸入 GAS 網址"); return
        if QMessageBox.question(self, "確認", "確定要清空雲端試算表的資料嗎？") \
                != QMessageBox.StandardButton.Yes:
            return
        self._status_lbl.setText("⏳ 清空中…")
        self._app.toast.show_msg("⏳ 正在清空雲端資料…", duration_ms=8000)

        def _do():
            try:
                requests.post(url, json={"action": "clear"}, timeout=10)
                self._app.fetcher.reset_count()
                QTimer.singleShot(0, lambda: self._status_lbl.setText("✅ 雲端已清空"))
                QTimer.singleShot(0, lambda: self._app.toast.show_msg("✅ 雲端資料已清空"))
            except Exception as e:
                msg = f"❌ 清空失敗：{e}"
                QTimer.singleShot(0, lambda: self._status_lbl.setText(msg))
                QTimer.singleShot(0, lambda: self._app.toast.show_msg(msg))

        threading.Thread(target=_do, daemon=True).start()

    def load_settings(self, s):
        """面板已開啟時同步最新設定"""
        self._toggle.setChecked(s.get("isActive", False))
        self._url_edit.setText(s.get("gasUrl", ""))
        self._min_font_sl.setValue(s.get("minFontSize", 60))
        self._max_font_sl.setValue(s.get("maxFontSize", 120))
        self._min_speed_sl.setValue(s.get("minSpeed", 8))
        self._max_speed_sl.setValue(s.get("maxSpeed", 15))
        self._rep_sl.setValue(s.get("repeatCount", 3))
        for i, c in enumerate((s.get("colors", []) + ["#ccc"] * 5)[:5]):
            self._color_vars[i] = c
            self._set_color_btn(self._color_btns[i], c)


# ═══════════════════════════════════════════════════════
#  ToastNotice — 螢幕右下角小提示浮層
# ═══════════════════════════════════════════════════════
class ToastNotice(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        self._lbl = QLabel("")
        self._lbl.setStyleSheet(
            "color:white; font-size:12px; font-family:'Microsoft JhengHei';"
            "font-weight:bold; border:none;")
        layout.addWidget(self._lbl)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(40, 40, 40, 210))
        p.drawRoundedRect(self.rect(), 10, 10)
        p.end()

    def show_msg(self, msg, duration_ms=3000):
        self._lbl.setText(msg)
        self.adjustSize()
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.right() - self.width() - 20,
                  screen.bottom() - self.height() - 80)
        self.show()
        self._hide_timer.start(duration_ms)


# ═══════════════════════════════════════════════════════
#  GASFetchThread — 背景執行緒定期抓取 GAS 資料
# ═══════════════════════════════════════════════════════
class GASFetchThread(QThread):
    new_text = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._settings = None
        self._running  = False
        self._count    = 0
        self._lock     = threading.Lock()

    def configure(self, settings):
        with self._lock:
            self._settings = settings

    def reset_count(self):
        with self._lock:
            self._count = 0

    def stop_fetch(self):
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            with self._lock:
                s = self._settings
            if s and s.get("gasUrl"):
                self._fetch(s)
            # 分段 sleep，允許快速停止
            for _ in range(30):
                if not self._running: break
                time.sleep(0.1)

    def _fetch(self, s):
        url = s["gasUrl"]
        url = f"{url}{'&' if '?' in url else '?'}t={int(time.time()*1000)}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            self._process(resp.text)
        except Exception as e:
            print(f"[GAS] {e}")

    def _process(self, text):
        try:
            data = json.loads(text)
        except Exception:
            m = re.match(r'^[^(]+\((.*)\)$', text, re.DOTALL)
            if not m: return
            try: data = json.loads(m.group(1))
            except Exception: return

        if not isinstance(data, list): return
        with self._lock: last = self._count

        if len(data) > last:
            for item in data[last:]:
                c = item.get("內容", "")
                if c: self.new_text.emit(str(c))
            with self._lock: self._count = len(data)
        elif len(data) < last:
            with self._lock: self._count = len(data)


# ═══════════════════════════════════════════════════════
#  App — 主協調器
# ═══════════════════════════════════════════════════════
class App:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.settings = load_settings()

        self.overlay = MarqueeOverlay()
        self.icon    = FloatingIcon(self)
        self.panel   = SettingsPanel(self)
        self.panel.hide()
        self.toast   = ToastNotice()

        self.fetcher = GASFetchThread()
        self.fetcher.new_text.connect(self._on_text)
        self.fetcher.configure(self.settings)

        if self.settings["isActive"]:
            self.overlay.show_overlay()
            self.fetcher.start()
        self.icon.update_status(self.settings["isActive"])

        # 啟動時自動清空雲端資料
        QTimer.singleShot(800, self._auto_clear_on_start)

    def _auto_clear_on_start(self):
        url = self.settings.get("gasUrl", "").strip()
        if not url:
            return
        self.toast.show_msg("⏳ 正在清空雲端資料…", duration_ms=8000)

        def _do():
            try:
                requests.post(url, json={"action": "clear"}, timeout=10)
                self.fetcher.reset_count()
                QTimer.singleShot(0, lambda: self.toast.show_msg("✅ 雲端資料已清空"))
                # 同步到面板狀態列（若已開啟）
                if self.panel.isVisible():
                    QTimer.singleShot(0, lambda: self.panel._status_lbl.setText("✅ 雲端資料已清空"))
            except Exception as e:
                QTimer.singleShot(0, lambda: self.toast.show_msg(f"❌ 清空失敗：{e}"))

        threading.Thread(target=_do, daemon=True).start()

    def _on_text(self, text):
        if self.settings["isActive"]:
            self.overlay.add_text(text, self.settings)

    def toggle_settings(self):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.load_settings(self.settings)
            self.panel.show()
            self.panel.raise_()

    def apply_settings(self, new_settings):
        self.settings = new_settings
        save_settings(self.settings)
        self.fetcher.configure(self.settings)

        if self.settings["isActive"]:
            self.overlay.show_overlay()
            if not self.fetcher.isRunning():
                self.fetcher.start()
        else:
            self.fetcher.stop_fetch()
            self.overlay.hide_overlay()

        self.icon.update_status(self.settings["isActive"])

    def quit(self):
        self.fetcher.stop_fetch()
        self.fetcher.wait(1000)
        self.qapp.quit()


# ── 入口 ───────────────────────────────────────────────
def main():
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("桌面彈幕")

    app = App(qapp)
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
