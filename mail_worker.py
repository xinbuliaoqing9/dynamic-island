# -*- coding: utf-8 -*-
"""
mail_worker.py — 邮箱验证码监听
通过 IMAP 轮询收件箱，解析最新邮件正文，用正则提取验证码。
支持任意 IMAP 邮箱（QQ/163/Gmail/Outlook/企业邮箱），
凭据使用「授权码」而非登录密码（QQ/163 均需在邮箱网页设置中开启）。

策略：
  - 只看最近 15 分钟内收到的邮件（验证码有时效性）
  - 优先匹配 4-8 位纯数字验证码，其次字母数字混合
  - 同一封邮件只提醒一次（按 Message-ID 去重）
"""
import email
import email.header
import imaplib
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("island.mail")


class MailWorker(QObject):
    codeFound = Signal(str, str, str)   # 验证码, 发件人, 主题
    statusChanged = Signal(str)         # "ok" / 错误信息

    def __init__(self, conf: dict):
        super().__init__()
        self.conf = dict(conf)
        self._thread = None
        self._stop = threading.Event()
        self._seen_ids = set()

    def update_conf(self, conf: dict):
        """配置变更后调用，自动重启轮询"""
        self.conf = dict(conf)
        self.stop()
        self.start()

    def start(self):
        c = self.conf
        if not c.get("host") or not c.get("user") or not c.get("password"):
            log.info("邮箱未配置，验证码监听不启动")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ---------- 后台轮询 ----------

    def _run(self):
        interval = max(8, int(self.conf.get("interval", 15)))
        log.info("邮件监听启动: %s as %s (每%ds)", self.conf["host"], self.conf["user"], interval)
        while not self._stop.is_set():
            ok, msg = self._check_once()
            if ok:
                self.statusChanged.emit("ok")
            else:
                self.statusChanged.emit(msg or "邮件连接失败")
                # 连接失败时降低频率，避免触发邮箱风控
                time.sleep(max(interval, 30))
                continue
            self._stop.wait(interval)

    def _connect(self):
        host = self.conf["host"]
        port = int(self.conf.get("port", 993))
        if port == 143:
            M = imaplib.IMAP4(host, port)
            M.starttls()
        else:
            M = imaplib.IMAP4_SSL(host, port)
        M.login(self.conf["user"], self.conf["password"])
        return M

    def _check_once(self):
        M = None
        try:
            M = self._connect()
            M.select("INBOX", readonly=True)
            # IMAP SEARCH 只支持日期粒度，取最近 1 天再本地按时间过滤
            since = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
            typ, data = M.search(None, f'(SINCE "{since}")')
            if typ != "OK" or not data or not data[0]:
                return True, None
            ids = data[0].split()[-10:]  # 最近 10 封，从新到旧处理
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)

            for mid in reversed(ids):
                if mid.decode() in self._seen_ids:
                    continue
                typ, msg_data = M.fetch(mid, "(RFC822)")
                if typ != "OK":
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                msg_id = (msg.get("Message-ID") or mid.decode()).strip()
                self._seen_ids.add(mid.decode())

                # 解析邮件时间，超过 15 分钟的旧邮件不提示
                try:
                    dt = parsedate_to_datetime(msg.get("Date"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass

                sender = _decode_hdr(msg.get("From", ""))
                subject = _decode_hdr(msg.get("Subject", ""))
                body = _extract_body(msg)
                code = _extract_code(body)
                if code:
                    self.codeFound.emit(code, sender, subject)
                    # 只提示最新一封带验证码的邮件
                    return True, None
            return True, None
        except imaplib.IMAP4.error as e:
            log.warning("IMAP error: %s", e)
            return False, f"登录失败：{e}（请检查授权码）"
        except Exception as e:
            log.warning("mail check failed: %s", e)
            return False, f"邮件连接失败：{e}"
        finally:
            try:
                if M:
                    M.logout()
            except Exception:
                pass


def _decode_hdr(v: str) -> str:
    """解码邮件头部（处理 =?utf-8?B?...?= 编码）"""
    try:
        parts = email.header.decode_header(v or "")
        out = []
        for text, enc in parts:
            if isinstance(text, bytes):
                out.append(text.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(text)
        return "".join(out)
    except Exception:
        return v or ""


def _extract_body(msg) -> str:
    """抽取邮件正文文本（plain 优先，html 去标签兜底）"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body += payload.decode(charset, errors="ignore")
                except Exception:
                    pass
            if body and ctype == "text/plain":
                break
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="ignore")
        except Exception:
            pass
    if "<html" in body.lower():
        body = re.sub(r"<[^>]+>", " ", body)
    return body


# 验证码启发式：
#   1. 常见上下文里的 4-8 位数字（验证码/校验码/code 后面）
#   2. 任意独立的 4-8 位数字
#   3. 字母数字混合码（6-8 位，含数字）
_CTX = re.compile(r"(?:验证码|校验码|确认码|动态码|code|verification)\D{0,20}(\d{4,8})", re.I)
_DIGITS = re.compile(r"(?<![\d])(\d{4,8})(?![\d])")
_ALNUM = re.compile(r"(?<![\w])(?=[A-Z0-9]{6,8}\b)(?=[^a-z]*\d)(?=\w*[A-Z])[A-Z0-9]{6,8}")


def _extract_code(text: str) -> str:
    if not text:
        return ""
    m = _CTX.search(text)
    if m:
        return m.group(1)
    for m in _DIGITS.finditer(text):
        v = m.group(1)
        # 排除年份/金额等干扰
        if v.startswith(("19", "20")) and len(v) == 4:
            continue
        return v
    m = _ALNUM.search(text)
    return m.group(0) if m else ""
