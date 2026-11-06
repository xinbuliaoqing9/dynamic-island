# -*- coding: utf-8 -*-
"""
main.py — 桌面灵动岛 主程序（v2 轮播版）

设计：
  · 单胶囊轮播 UI：音乐 / 暂存区 / 验证码 共用同一个胶囊，
    事件驱动平滑淡入切换 —— 放歌时显示音乐，拖文件进来自动切到
    暂存区，收到验证码自动切到验证码。
  · QQ 式吸顶：无内容且 3 秒无触碰自动滑出屏幕隐藏，
    鼠标碰到屏幕顶部自动滑回。
  · 验证码：鼠标放上去即复制。
  · 固定窗口尺寸（不再 hover 变高变矮），消除重排卡顿。
"""
import logging
import math
import os
import sys
import threading
import time

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QPoint, QObject, QSize, QFileInfo,
    QMimeData, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QPainter, QPixmap, QDrag, QBrush,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QProgressBar,
    QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
    QFileIconProvider,
)
from PySide6.QtGui import QLinearGradient, QPen

from lyrics import current_line, fetch_lrc
from mail_worker import MailWorker
from media_worker import MediaWatcher
from settings_dialog import CONFIG_PATH, SettingsDialog, load_conf, save_conf
from stash import StashManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("island.main")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)
STASH_DIR = os.path.join(RUNTIME_DIR, "stash")

WIN_W, WIN_H = 414, 102         # 长度缩短1/3、高度加宽一半后的尺寸
# 隐藏时露出屏幕顶部的像素。窗口自身有 6px 布局边距，胶囊内又有 6px
# 光晕边距，胶囊主体从窗口顶部 12px 处才开始——所以至少要露 12px
# 以上才能看到边线。取 20px = 可见约 8px 的霓虹描边（QQ 同款效果）。
HIDE_PEEK = 20

MODE_MUSIC, MODE_STASH, MODE_CODE, MODE_IDLE = 0, 1, 2, 3


def _elide(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


class NeonPill(QWidget):
    """自绘霓虹胶囊：深空渐变底 + 流动彩色描边 + 柔光晕"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(66)           # 15fps 边框流动，几乎不耗资源

    def _tick(self):
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.045) % 1.0
        self.update()

    def _hue(self, offset):
        # 青蓝→紫→粉 区间往复，避免跑到黄绿色系
        t = 0.5 + 0.35 * math.sin(2 * math.pi * ((self._phase + offset) % 1.0))
        return QColor.fromHsvF(t, 0.72, 1.0, 1.0)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        m = 6                            # 留给光晕的空间
        rect = self.rect().adjusted(m, m, -m, -m)
        radius = (h - 2 * m) / 2

        # 1. 外圈柔光晕（两层低透明描边）
        for i, alpha in ((4, 28), (2, 55)):
            glow = QColor(self._hue(0.0))
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, i))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-i, -i, i, i), radius + i, radius + i)

        # 2. 深空渐变底
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, QColor(14, 22, 48))
        bg.setColorAt(0.55, QColor(24, 22, 62))
        bg.setColorAt(1.0, QColor(40, 20, 74))
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, radius, radius)

        # 3. 流动霓虹描边（双色渐变随时间流转）
        border = QLinearGradient(0, 0, w, h)
        border.setColorAt(0.0, self._hue(0.00))
        border.setColorAt(0.5, self._hue(0.12))
        border.setColorAt(1.0, self._hue(0.24))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border, 1.6))
        p.drawRoundedRect(rect, radius, radius)
        p.end()


class CoverLabel(QLabel):
    """旋转封面控件：固定画布内绕中心旋转绘制，杜绝 transformed()
    输出画布尺寸随角度变化导致的颤动"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pm = None
        self._angle = 0.0

    def set_cover(self, pm):
        self._pm = pm if (pm and not pm.isNull()) else None
        self.update()

    def set_angle(self, a: float):
        self._angle = a
        self.update()

    def paintEvent(self, ev):
        if self._pm is None:
            super().paintEvent(ev)          # 无封面时画 🎵 文本
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        c = self.rect().center()
        p.translate(c)
        p.rotate(self._angle)
        p.drawPixmap(-self._pm.width() // 2, -self._pm.height() // 2, self._pm)
        p.end()


# ---------------- 歌词异步获取 ----------------

class _BridgeHost(QObject):
    lrcReady = Signal(list)


# ---------------- 暂存缩略图条（横向，支持拖出） ----------------

class StashStrip(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(False)
        self.setFixedHeight(76)
        self.setIconSize(QSize(40, 40))
        self.setGridSize(QSize(52, 74))      # 固定单元格，防止缩略图溢出被裁切
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setDragEnabled(True)
        self.setHorizontalScrollMode(QListWidget.ScrollPerPixel)
        self.setStyleSheet(
            "QListWidget{background:transparent;border:none;}"
            "QListWidget::item{border-radius:8px;}"
            "QListWidget::item:selected{background:#3a3a4a;}"
        )
        self._provider = QFileIconProvider()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def refresh(self, items, kind_of):
        self.clear()
        for it in items:
            try:
                icon = None
                if kind_of(it) == "image":
                    pm = QPixmap(it["path"])
                    if not pm.isNull():
                        icon = QIcon(pm.scaled(40, 40, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
                if icon is None:
                    # PySide6 6.12 移除了 icon(QUrl)，必须用 QFileInfo
                    icon = self._provider.icon(QFileInfo(it["path"]))
                li = QListWidgetItem(icon, "")
                li.setData(Qt.UserRole, it["path"])
                li.setToolTip(f"{it['name']} · 按住拖出去即可使用\n右键更多操作")
                self.addItem(li)
            except Exception as e:
                # 单个条目出错不影响整个暂存区渲染
                log.warning("stash item render failed %s: %s",
                            it.get("name"), e)

    def startDrag(self, actions):
        item = self.currentItem()
        if not item:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(item.data(Qt.UserRole))])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    def _menu(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.UserRole)
        win = self.window()
        m = QMenu(self)
        m.addAction("打开", lambda: os.startfile(path))
        m.addAction("打开所在位置", lambda: os.startfile(os.path.dirname(path)))
        m.addSeparator()
        m.addAction("移除该文件", lambda: win.stash_remove_item(path))
        m.addAction("清空暂存区", lambda: win.stash_clear_all())
        m.exec(self.mapToGlobal(pos))


# ---------------- 带淡入切换的堆叠容器 ----------------

class FadeStack(QStackedWidget):
    def switch(self, idx: int):
        if idx == self.currentIndex():
            return
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(0.15)
        self.setGraphicsEffect(eff)
        self.setCurrentIndex(idx)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.15)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        # 动画结束必须立刻移除效果：一是省资源，
        # 二是避免与子控件的 DropShadow 效果嵌套导致渲染空白
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)


# ---------------- 主窗口 ----------------

class IslandWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.conf = load_conf()
        self.setWindowTitle("灵动岛")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFixedSize(WIN_W, WIN_H)

        # ---------- 状态 ----------
        self.stash = StashManager(STASH_DIR)
        self.media = MediaWatcher()
        self.mail = MailWorker(self.conf["imap"])
        self.lrc_bridge = _BridgeHost()
        self.lrc_bridge.lrcReady.connect(self._on_lrc_ready)
        self.lrc = []
        self.lrc_key = ""
        self.cur_title = ""
        self.cur_playing = False
        self.code_text = ""
        self.code_time = 0.0
        self.override_until = 0.0      # 临时模式（stash/code）截止时间
        self.override_mode = None
        self._last_active = time.time()
        self._hidden = False
        self._settings_open = False
        self._pos_anim = None
        self._cover_angle = 0.0        # 旋转封面当前角度
        self._cover_orig = None        # 圆形蒙版后的原始封面

        self._build_ui()
        self._build_tray()
        self._connect()

        # 吸顶定位：y 强制钳制在顶部区域(0~60px)，x 记忆上次的水平位置
        self.conf.setdefault("ui", {})
        fixed_y = max(0, min(self.conf["ui"].get("y", 12), 24))
        if fixed_y != self.conf["ui"].get("y"):
            self.conf["ui"]["y"] = fixed_y
            save_conf(self.conf)
        self._place(dur=0)

        # 自动隐藏巡检：每 500ms 检查一次
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._tick_idle)
        self._idle_timer.start(500)

        # 封面旋转计时器（约 10 秒一圈，播放中才转）
        self._rot_timer = QTimer(self)
        self._rot_timer.timeout.connect(self._rotate_tick)
        self._rot_timer.start(33)

        self.media.start()
        self.apply_features()
        self.stack.setCurrentIndex(self._default_mode())

    # ================= UI 构建 =================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        self.pill = NeonPill()
        root.addWidget(self.pill)
        pill_l = QHBoxLayout(self.pill)
        pill_l.setContentsMargins(16, 10, 16, 10)
        pill_l.setSpacing(10)

        self.stack = FadeStack()
        pill_l.addWidget(self.stack, 1)

        self._build_music_page()
        self._build_stash_page()
        self._build_code_page()
        self._build_idle_page()

        self.setStyleSheet("""
            QLabel { color:#f0f6ff; }
            QToolButton { color:#dff6ff; border:none;
                          background:rgba(122,162,255,0.13);
                          font-size:14px; border-radius:16px; }
            QToolButton:hover { background:rgba(122,162,255,0.40); }
            #playBtn { color:#fff; font-weight:800;
                       background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                         stop:0 #5ad0f0, stop:1 #b06aff); }
            #playBtn:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                         stop:0 #8ee1ff, stop:1 #cd9bff); }
            QProgressBar { background:rgba(255,255,255,0.10);
                           border:none; border-radius:2px; }
            QProgressBar::chunk { border-radius:2px;
                       background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                         stop:0 #5ad0f0, stop:1 #b06aff); }
        """)

    def _build_music_page(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.cover = CoverLabel()
        self.cover.setText("🎵")
        self.cover.setFixedSize(60, 60)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(
            "border-radius:14px;background:#2a2a35;font-size:26px;")

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.title = QLabel("正在等待音乐…")
        self.title.setStyleSheet("font-weight:700;font-size:14px;color:#ffffff;")
        # 注意：不要给 title 加 DropShadow 效果——它会与 FadeStack 的
        # 透明度效果嵌套，导致歌名渲染成空白
        self.sub = QLabel("把文件拖到岛上即可暂存")
        self.sub.setStyleSheet("color:#99a;font-size:12px;")
        text_box.addWidget(self.title)
        text_box.addWidget(self.sub)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(64)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar{background:#333344;border:none;border-radius:2px;}"
            "QProgressBar::chunk{background:#5ad0f0;border-radius:2px;}")

        self.btn_prev = QToolButton(text="⏮")
        self.btn_play = QToolButton(text="▶", objectName="playBtn")
        self.btn_next = QToolButton(text="⏭")
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            b.setFixedSize(32, 32)
            b.setCursor(Qt.PointingHandCursor)

        lay.addWidget(self.cover)
        lay.addLayout(text_box, 1)
        lay.addWidget(self.progress)
        lay.addWidget(self.btn_prev)
        lay.addWidget(self.btn_play)
        lay.addWidget(self.btn_next)
        self.stack.addWidget(w)     # index MODE_MUSIC

    def _build_stash_page(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.stash_title = QLabel("📁 暂存区")
        self.stash_title.setStyleSheet("font-weight:600;font-size:13px;color:#fff;")
        self.stash_strip = StashStrip()
        self.stash_hint = QLabel("按住缩略图拖出去即取用")
        self.stash_hint.setStyleSheet("color:#9fc6ff;font-size:11px;")
        lay.addWidget(self.stash_title)
        lay.addWidget(self.stash_strip, 1)
        lay.addWidget(self.stash_hint)
        self.stack.addWidget(w)     # index MODE_STASH

    def _build_code_page(self):
        w = QWidget(objectName="codePage")
        # 渐变提示底色
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        icon = QLabel("📧")
        icon.setStyleSheet("font-size:22px;")
        self.code_label = QLabel("——")
        self.code_label.setStyleSheet(
            "color:#8dffb0;font-size:26px;font-weight:800;letter-spacing:3px;")
        _cg = QGraphicsDropShadowEffect(self)
        _cg.setBlurRadius(18); _cg.setColor(QColor(90, 255, 140, 200))
        _cg.setOffset(0, 0)
        self.code_label.setGraphicsEffect(_cg)
        self.code_from = QLabel("")
        self.code_from.setStyleSheet("color:#889;font-size:11px;")
        self.code_tip = QLabel("悬停即复制")
        self.code_tip.setStyleSheet("color:#5ad0f0;font-size:11px;")
        lay.addWidget(icon)
        lay.addWidget(self.code_label)
        lay.addWidget(self.code_from, 1)
        lay.addWidget(self.code_tip)
        self.stack.addWidget(w)     # index MODE_CODE
        w.setMouseTracking(True)
        w.installEventFilter(self)

    def _build_idle_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.idle_label = QLabel("✨ 把文件拖进来暂存 · 播放音乐显示歌词 ✨")
        self.idle_label.setAlignment(Qt.AlignCenter)
        self.idle_label.setStyleSheet("color:#9fc6ff;font-size:13px;")
        lay.addWidget(self.idle_label)
        self.stack.addWidget(w)     # index MODE_IDLE

    def _build_tray(self):
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#12121a"))
        p.setPen(QColor("#5ad0f0"))
        p.drawRoundedRect(2, 2, 28, 28, 12, 12)
        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        p.drawText(pm.rect(), Qt.AlignCenter, "岛")
        p.end()
        self.tray = QSystemTrayIcon(QIcon(pm), self)
        menu = QMenu()
        menu.addAction("功能管理", self.open_settings)
        menu.addAction("显示/隐藏", self._toggle_visible)
        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("灵动岛")
        self.tray.activated.connect(
            lambda r: self.open_settings() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    # ================= 信号接线 =================

    def _connect(self):
        self.media.mediaChanged.connect(self._on_media)
        self.media.positionChanged.connect(self._on_position)
        self.mail.codeFound.connect(self._on_code)
        self.btn_prev.clicked.connect(lambda: self.media.control("prev"))
        self.btn_next.clicked.connect(lambda: self.media.control("next"))
        self.btn_play.clicked.connect(lambda: self.media.control("toggle"))

    # ================= 模式（轮播）逻辑 =================

    def _default_mode(self) -> int:
        if self.cur_title:
            return MODE_MUSIC
        if self.stash.items:
            return MODE_STASH
        return MODE_IDLE

    def _enter_mode(self, mode: int, instant=False, temp_ms=0):
        """切到指定模式；temp_ms>0 表示临时模式，到期自动回默认"""
        if temp_ms:
            self.override_mode = mode
            self.override_until = time.time() + temp_ms / 1000
        else:
            self.override_mode = None
            self.override_until = 0
        if instant:
            self.stack.setCurrentIndex(mode)
        else:
            self.stack.switch(mode)

    def _on_media(self, info: dict):
        title = info.get("title", "")
        self.cur_playing = info.get("status") == "playing"
        if not title:
            self.cur_title = ""
            self.title.setText("正在等待音乐…")
            self.sub.setText("把文件拖到岛上即可暂存")
            self.cover.setText("🎵")
            self.cover.setPixmap(QPixmap())
            self._cover_orig = None
            self.progress.setValue(0)
        else:
            self.cur_title = title
            self.title.setText(_elide(title, 14))
            self.sub.setText(_elide(info.get("artist", ""), 20))
            cp = info.get("cover_path", "")
            pm = QPixmap(cp) if cp and os.path.exists(cp) else QPixmap()
            if not pm.isNull():
                self.cover.setText("")
                # 圆形蒙版 + 从 0 度开始旋转（黑胶唱片效果）
                self._cover_angle = 0.0
                self._cover_orig = self._circle_cover(pm, 60)
                self.cover.set_cover(self._cover_orig)
            else:
                self.cover.setText("🎵")
                self._cover_orig = None
                self.cover.set_cover(None)
            self.btn_play.setText("⏸" if self.cur_playing else "▶")
            # 切歌 → 异步拉歌词
            key = (title, info.get("artist", ""))
            if self.lrc_key != key:
                self.lrc_key = key
                self.lrc = []
                threading.Thread(target=self._fetch_lrc_bg,
                                 args=(title, info.get("artist", "")),
                                 daemon=True).start()
        if self._hidden and self.cur_playing:
            self._unhide()
        # 无临时模式时回到默认（比如从 idle 切到 music）
        if time.time() > self.override_until:
            self._enter_mode(self._default_mode(),
                             instant=(self.stack.currentIndex() == MODE_IDLE
                                      and not self.cur_title))

    def _circle_cover(self, pm: QPixmap, d: int) -> QPixmap:
        """把封面裁成圆形（黑胶唱片效果的基础图）"""
        src = pm.scaled(d, d, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
        out = QPixmap(d, d)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(src))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, d, d)
        p.end()
        return out

    def _rotate_tick(self):
        """播放中匀速旋转封面（约 10 秒一圈），暂停时定格"""
        if self._cover_orig is None or not self.cur_playing:
            return
        self._cover_angle = (self._cover_angle + 1.2) % 360   # 33ms×1.2°≈10s/圈
        self.cover.set_angle(self._cover_angle)

    def _fetch_lrc_bg(self, title, artist):
        lines = fetch_lrc(title, artist)
        self.lrc_bridge.lrcReady.emit(lines or [])

    def _on_lrc_ready(self, lines):
        self.lrc = lines

    def _on_position(self, pos, dur, playing):
        self.cur_playing = playing
        self.btn_play.setText("⏸" if playing else "▶")
        if dur > 0:                       # 有真实总时长才显示进度条
            self.progress.show()
            v = int(pos / dur * 1000)
            if self.progress.value() != v:
                self.progress.setValue(v)
        else:
            self.progress.hide()          # 播放器不报时间轴(如网易云)时隐藏
        if self.lrc and self.stack.currentIndex() == MODE_MUSIC:
            cur, _ = current_line(self.lrc, pos)
            if cur:
                self.sub.setText("♪ " + _elide(cur, 20))    # 副行显示当前歌词

    # ================= 邮件 =================

    def _on_code(self, code, sender, subject):
        self.code_text = code
        self.code_time = time.time()
        self.code_label.setText(code)
        self.code_from.setText(f"来自 {_elide(sender, 16)} · {subject}")
        self._enter_mode(MODE_CODE, temp_ms=30000)   # 展示 30 秒
        self._unhide()
        QApplication.beep()
        self.tray.showMessage("收到验证码", f"{code}（悬停即复制）",
                              QSystemTrayIcon.Information, 3000)

    def eventFilter(self, obj, ev):
        """验证码页：悬停即复制"""
        if obj.objectName() == "codePage":
            t = ev.type()
            if t in (ev.Type.Enter, ev.Type.MouseButtonPress):
                if self.code_text:
                    QApplication.clipboard().setText(self.code_text)
                    self.code_tip.setText("✓ 已复制")
                    self.code_tip.setStyleSheet(
                        "color:#7be08a;font-size:12px;font-weight:700;")
                    QTimer.singleShot(1500, self._reset_code_tip)
            elif t == ev.Type.Leave:
                self._reset_code_tip()
        return super().eventFilter(obj, ev)

    def _reset_code_tip(self):
        self.code_tip.setText("悬停即复制")
        self.code_tip.setStyleSheet("color:#5ad0f0;font-size:11px;")

    # ================= 暂存 =================

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._enter_mode(MODE_STASH, temp_ms=8000)

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return
        added = self.stash.add_paths(paths)
        self.stash_strip.refresh(self.stash.items, self.stash.kind)
        self._enter_mode(MODE_STASH, temp_ms=10000)
        self._unhide()
        self.tray.showMessage("灵动岛", f"已暂存 {len(added)} 个文件",
                              QSystemTrayIcon.Information, 2000)

    def stash_remove_item(self, path):
        for it in list(self.stash.items):
            if it["path"] == path:
                self.stash.remove(it)
        self.stash_strip.refresh(self.stash.items, self.stash.kind)

    def stash_clear_all(self):
        self.stash.clear()
        self.stash_strip.refresh(self.stash.items, self.stash.kind)

    # ================= QQ 式吸顶隐藏 =================

    def _has_content(self) -> bool:
        """决定是否保持显示：放歌中 或 最近 2 分钟内收到过验证码。
        暂存区有文件不阻止隐藏（悬停屏幕顶部即可唤回取文件）。"""
        if self.cur_playing:
            return True
        if self.code_text and time.time() - self.code_time < 120:
            return True
        return False

    def _tick_idle(self):
        """每 500ms 用全局光标坐标判断（唯一判据，不依赖任何鼠标事件，
        无边框半透明窗口常会丢失 leave 事件导致 underMouse 永远为 True）"""
        try:
            from PySide6.QtGui import QCursor
            cursor_in = self.frameGeometry().contains(QCursor.pos())
            now = time.time()
            if self._hidden:
                if cursor_in:                 # 鼠标碰到顶部感应条 → 唤回
                    self._unhide()
                return
            if self._settings_open:
                # 防御：设置面板已不存在却没复位时自动恢复，避免永久卡住
                dlg = getattr(self, "_settings_dlg", None)
                if dlg is None or not dlg.isVisible():
                    self._settings_open = False
                else:
                    return
            if cursor_in or self._has_content():
                self._last_active = now
                return
            if now - self._last_active >= 3.0:
                log.info("idle 3s -> auto hide (cursor_in=%s content=%s)",
                         cursor_in, self._has_content())
                self._hide_slide()
        except Exception:
            log.exception("tick idle error")

    def _hide_slide(self):
        """平滑滑出屏幕，只留 6px 感应条"""
        self._hidden = True
        self._animate_y(-WIN_H + HIDE_PEEK)

    def _unhide(self):
        self._last_active = time.time()
        if not self._hidden:
            return
        self._hidden = False
        self._animate_y(self.conf["ui"]["y"])

    def _toggle_visible(self):
        if self._hidden:
            self._unhide()
        else:
            self._hide_slide()

    def _animate_y(self, target_y):
        # 注意：不能用 DeleteWhenStopped，否则动画播完 C++ 对象被销毁，
        # 下次再动这个引用会 RuntimeError，导致隐藏/唤回机制整体瘫痪
        anim = getattr(self, "_pos_anim", None)
        if anim is not None:
            try:
                if anim.state() == QPropertyAnimation.Running:
                    anim.stop()
            except RuntimeError:
                pass                          # 旧对象已被回收，忽略即可
        anim = QPropertyAnimation(self, b"pos", self)   # parent=self 常驻
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setEndValue(QPoint(self.x(), target_y))
        anim.start()
        self._pos_anim = anim

    def _place(self, dur=200):
        """放置/回弹到吸顶位置：y 钳制在顶部区域，x = 记忆值或屏幕居中"""
        screen = self.screen().availableGeometry()
        y = max(0, min(self.conf["ui"].get("y", 12), 24))
        self.conf["ui"]["y"] = y
        x = self.conf["ui"].get("x")
        if x is None:
            x = screen.x() + (screen.width() - WIN_W) // 2
        # 水平方向限制在屏幕范围内
        x = max(screen.x() - WIN_W + 120, min(x, screen.right() - 120))
        if dur <= 0:
            self.move(x, y)
        else:
            self._animate_y_pos(QPoint(x, y))

    def _animate_y_pos(self, end_pos, dur=200):
        """通用位置动画（parent=self 常驻，不用 DeleteWhenStopped）"""
        anim = getattr(self, "_pos_anim", None)
        if anim is not None:
            try:
                if anim.state() == QPropertyAnimation.Running:
                    anim.stop()
            except RuntimeError:
                pass
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(dur)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setEndValue(end_pos)
        anim.start()
        self._pos_anim = anim

    # ================= 鼠标交互 =================

    def enterEvent(self, e):
        self._unhide()
        # 注意：这里不再刷新 _last_active，计时完全由 _tick_idle 的
        # 全局光标判定驱动，避免系统误发 enter/leave 事件干扰倒计时

    def mousePressEvent(self, e):
        self._last_active = time.time()
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        self._last_active = time.time()
        if hasattr(self, "_drag_pos") and self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if hasattr(self, "_drag_pos"):
            self._drag_pos = None
            # 松手后吸附到钳制后的顶部位置（0~24px 内可微调，怎么拖都吸顶）
            self.conf["ui"]["y"] = max(0, min(self.y(), 24))
            self.conf["ui"]["x"] = self.x()
            save_conf(self.conf)
            self._place(dur=250)

    def leaveEvent(self, e):
        # 鼠标离开时结束临时模式，回到默认显示（不参与隐藏计时）
        if time.time() > self.override_until:
            self._enter_mode(self._default_mode())

    # ================= 功能开关 / 设置 =================

    def apply_features(self):
        f = self.conf["features"]
        music_on = f["music"]
        for wdg in (self.cover, self.btn_prev, self.btn_next, self.btn_play,
                    self.progress):
            wdg.setVisible(music_on)
        if not music_on:
            self.cur_title = ""
        if f["mail"]:
            self.mail.update_conf(self.conf["imap"])
        else:
            self.mail.stop()
        self.stash_strip.setVisible(f["stash"])

    def open_settings(self):
        """功能管理：屏幕居中 + 置顶，并临时取消灵动岛顶层，避免遮挡"""
        self._settings_open = True
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.show()                       # 让出顶层

        dlg = SettingsDialog(self.conf)
        self._settings_dlg = dlg
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
        dlg.adjustSize()
        scr = QApplication.primaryScreen().availableGeometry()
        dlg.move(scr.center() - dlg.rect().center())
        dlg.exec()

        self._settings_open = False
        try:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            self.show()
            self._unhide()
            self.apply_features()
        except Exception:
            log.exception("restore after settings failed")

    def closeEvent(self, e):
        self.mail.stop()
        super().closeEvent(e)


def _setup_logging():
    """输出到控制台 + 文件，方便排查线上问题"""
    fh = logging.FileHandler(os.path.join(RUNTIME_DIR, "island.log"),
                             encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)


def main():
    _setup_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = IslandWindow()
    win.show()
    log.info("config: %s", CONFIG_PATH)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
