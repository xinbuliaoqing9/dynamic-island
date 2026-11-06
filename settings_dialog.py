# -*- coding: utf-8 -*-
"""
settings_dialog.py — 功能管理面板
每个功能有独立开关：
  [x] 音乐歌词显示      [x] 音乐控制按钮
  [x] 文件暂存          [x] 邮箱验证码
外加邮箱 IMAP 配置、开机自启。
所有配置持久化到 config.json，改动即时生效。
"""
import json
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

CONFIG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.dirname(os.path.abspath(__file__))),
    "DynamicIsland", "config.json",
)

DEFAULT_CONF = {
    "features": {
        "music": True,        # 音乐信息 + 歌词
        "controls": True,     # 播放控制按钮
        "stash": True,        # 文件暂存
        "mail": False,        # 邮箱验证码（默认关，需配置邮箱）
    },
    "imap": {
        "host": "",           # 旧单账户字段（保留兼容，新配置走 accounts）
        "port": 993,
        "user": "",           # 邮箱完整地址
        "password": "",       # 授权码（不是登录密码）
        "interval": 15,       # 轮询间隔（秒）
        "accounts": [],       # 多邮箱账户：[{host,port,user,password}, ...]
    },
    "ui": {
        "y": 12,              # 距屏幕顶部像素
    },
}


def load_conf() -> dict:
    conf = json.loads(json.dumps(DEFAULT_CONF))  # 深拷贝默认值
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k in conf and isinstance(conf[k], dict):
                    conf[k].update(v)
                else:
                    conf[k] = v
    except Exception:
        pass
    return conf


def save_conf(conf: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)


class SettingsDialog(QDialog):
    """功能管理面板：功能开关 + 邮箱配置"""

    def __init__(self, conf: dict, parent=None):
        super().__init__(parent)
        self.conf = conf
        self.setWindowTitle("灵动岛 · 功能管理")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        tabs = QTabWidget()
        tabs.addTab(self._build_features_tab(), "功能开关")
        tabs.addTab(self._build_mail_tab(), "邮箱配置")
        tabs.addTab(self._build_help_tab(), "帮助")

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(btns)

    # ---------- Tab 1：功能开关 ----------

    def _build_features_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = self.conf["features"]

        self.cb_music = QCheckBox("🎵 音乐信息 / 歌词显示")
        self.cb_music.setChecked(f["music"])
        self.cb_controls = QCheckBox("⏯ 音乐控制按钮（播放/暂停/切歌）")
        self.cb_controls.setChecked(f["controls"])
        self.cb_stash = QCheckBox("📁 文件暂存（拖入暂存、拖出使用）")
        self.cb_stash.setChecked(f["stash"])
        self.cb_mail = QCheckBox("📧 邮箱验证码提醒（需在「邮箱配置」填写授权码）")
        self.cb_mail.setChecked(f["mail"])

        for cb, tip in [
            (self.cb_music, "读取系统正在播放的歌曲，显示封面、歌名、滚动歌词"),
            (self.cb_controls, "在灵动岛上直接控制播放"),
            (self.cb_stash, "把文件/图片/视频拖到灵动岛上暂存，随时拖出去"),
            (self.cb_mail, "通过 IMAP 监听收件箱，自动提取验证码"),
        ]:
            cb.setToolTip(tip)
            lay.addWidget(cb)

        hint = QLabel("关闭的功能不会在灵动岛上显示对应区域，\n后台也不再消耗资源。")
        hint.setStyleSheet("color:#888; font-size:12px;")
        lay.addWidget(hint)
        lay.addStretch()
        return w

    # ---------- Tab 2：邮箱配置（支持多邮箱） ----------

    def _build_mail_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        tip = QLabel("可同时监听多个邮箱（如 QQ + 163），每个邮箱各填一行：")
        tip.setStyleSheet("color:#555; font-size:12px;")
        lay.addWidget(tip)

        # 兼容旧配置：无 accounts 时把旧单账户字段填入第一行
        imap = self.conf["imap"]
        rows = list(imap.get("accounts") or [])
        if not rows and imap.get("host"):
            rows = [{"host": imap.get("host", ""),
                     "port": imap.get("port", 993),
                     "user": imap.get("user", ""),
                     "password": imap.get("password", "")}]

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(
            ["备注", "IMAP服务器", "端口", "邮箱账号", "授权码"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setColumnWidth(0, 70)
        self.tbl.setColumnWidth(1, 130)
        self.tbl.setColumnWidth(2, 55)
        self.tbl.setColumnWidth(3, 170)
        for r in rows:
            self._add_row(r)
        lay.addWidget(self.tbl)

        btns = QHBoxLayout()
        btn_add = QPushButton("＋ 添加邮箱")
        btn_add.clicked.connect(lambda: self._add_row(
            {"name": "", "host": "imap.qq.com", "port": 993,
             "user": "", "password": ""}))
        btn_del = QPushButton("－ 删除选中行")
        btn_del.clicked.connect(self._del_row)
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addStretch()
        lay.addLayout(btns)

        form = QHBoxLayout()
        form.addWidget(QLabel("轮询间隔(秒)"))
        self.ed_interval = QLineEdit(str(imap.get("interval", 15)))
        self.ed_interval.setMaximumWidth(70)
        form.addWidget(self.ed_interval)
        form.addStretch()
        lay.addLayout(form)
        return w

    def _add_row(self, acct: dict):
        r = self.tbl.rowCount()
        self.tbl.insertRow(r)
        vals = [acct.get("name", ""), acct.get("host", ""),
                str(acct.get("port", 993)), acct.get("user", ""),
                acct.get("password", "")]
        for c, v in enumerate(vals):
            self.tbl.setItem(r, c, QTableWidgetItem(v))

    def _del_row(self):
        rows = {i.row() for i in self.tbl.selectedIndexes()}
        for r in sorted(rows, reverse=True):
            self.tbl.removeRow(r)

    # ---------- Tab 3：帮助 ----------

    def _build_help_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        txt = QLabel(
            "【常见邮箱授权码获取方法】\n\n"
            "· 支持同时监听多个邮箱：在「邮箱配置」页点「＋ 添加邮箱」，\n"
            "   QQ 和 163 各填一行即可，哪个先收到就提醒哪个\n\n"
            "· QQ邮箱：网页版 → 设置 → 账户 → 开启 IMAP/SMTP 服务 → 生成授权码\n"
            "   IMAP服务器填 imap.qq.com，端口 993\n\n"
            "· 163邮箱：网页版 → 设置 → POP3/IMAP/SMTP → 开启并获取授权码\n"
            "   IMAP服务器填 imap.163.com，端口 993\n\n"
            "· Outlook：imap-mail.outlook.com（用账号密码即可）\n\n"
            "【★ 音乐不显示？先开播放器的 SMTC 开关！】\n\n"
            "灵动岛通过 Windows 系统媒体接口(SMTC) 读歌名/封面/歌词，\n"
            "播放器必须把这个开关打开：\n\n"
            "· 网易云音乐：设置 → 系统 → 开启「SMTC」→ 完全退出后重开\n"
            "· QQ音乐：设置 → 系统 → 打开「SMTC」→ 重启QQ音乐\n"
            "· 酷狗音乐：设置 → 打开「支持系统播放控件」\n"
            "· Spotify / Apple Music / Edge浏览器：默认开启无需设置\n\n"
            "自测方法：播放音乐时按键盘音量键，音量条旁出现歌曲卡片\n"
            "即 SMTC 已生效；没出现就是播放器没开（或版本太旧，先升级）。\n\n"
            "【使用技巧】\n"
            "· 拖文件到灵动岛 = 暂存；从岛上按住文件拖出 = 取出\n"
            "· 暂存是复制一份，拖出后岛上副本仍在，可反复取用\n"
            "· 文件夹、任意后缀文件都能暂存\n"
            "· 右键文件缩略图：打开 / 打开位置 / 移除\n"
            "· 鼠标放到验证码上即自动复制\n"
            "· 右键灵动岛空白处或托盘图标：功能管理 / 退出"
        )
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(txt)
        lay.addStretch()
        return w

    # ---------- 保存 ----------

    def _on_save(self):
        self.conf["features"]["music"] = self.cb_music.isChecked()
        self.conf["features"]["controls"] = self.cb_controls.isChecked()
        self.conf["features"]["stash"] = self.cb_stash.isChecked()
        self.conf["features"]["mail"] = self.cb_mail.isChecked()

        imap = self.conf["imap"]
        # 读取表格里的所有邮箱账户
        accounts = []
        for r in range(self.tbl.rowCount()):
            def cell(rr, cc):
                it = self.tbl.item(rr, cc)
                return (it.text().strip() if it else "")
            acct = {
                "name": cell(r, 0),
                "host": cell(r, 1),
                "port": 993,
                "user": cell(r, 3),
                "password": cell(r, 4),
            }
            try:
                acct["port"] = int(cell(r, 2) or "993")
            except ValueError:
                pass
            if acct["host"] and acct["user"]:
                accounts.append(acct)
        imap["accounts"] = accounts
        # 同步旧单账户字段 = 第一个账户（兼容旧版本读取）
        if accounts:
            imap["host"] = accounts[0]["host"]
            imap["port"] = accounts[0]["port"]
            imap["user"] = accounts[0]["user"]
            imap["password"] = accounts[0]["password"]
        try:
            imap["interval"] = max(8, int(self.ed_interval.text().strip() or "15"))
        except ValueError:
            imap["interval"] = 15

        # 校验：勾了邮箱功能但没配邮箱 → 提示但不强制
        if self.conf["features"]["mail"] and not accounts:
            QMessageBox.warning(self, "邮箱未配置完整",
                                "已勾选验证码功能，但还没有添加邮箱账户。\n"
                                "功能会开启，但在配置好之前不会收到提醒。")
        save_conf(self.conf)
        self.accept()
