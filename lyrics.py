# -*- coding: utf-8 -*-
"""
lyrics.py — 歌词获取模块
双源策略：
  1. 网易云音乐公开接口（无需登录）
  2. QQ 音乐接口（兜底，需要 Referer 头）
输入：歌名 + 歌手名（来自系统媒体会话）
输出：解析后的 LRC 时间轴列表 [(秒, 歌词文本), ...]
"""
import base64
import logging
import re

import requests

log = logging.getLogger("island.lyrics")

# LRC 时间标签，如 [01:23.45] 或 [01:23]
_TIME_TAG = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# 过滤掉纯元数据行
_META_LINE = re.compile(r"^\[(ti|ar|al|by|offset|kana?):", re.I)

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}


def _parse_lrc(lrc_text: str):
    """把 LRC 文本解析为 [(秒, 文本), ...] 并按时间排序"""
    lines = []
    if not lrc_text:
        return lines
    for raw in lrc_text.splitlines():
        raw = raw.strip()
        if not raw or _META_LINE.match(raw):
            continue
        text = _TIME_TAG.sub("", raw).strip()
        if not text or text in ("纯音乐，请欣赏",):
            continue
        for m in _TIME_TAG.finditer(raw):
            sec = int(m.group(1)) * 60 + int(m.group(2))
            if m.group(3):
                sec += int(m.group(3).ljust(3, "0")) / 1000.0
            lines.append((sec, text))
    lines.sort(key=lambda x: x[0])
    return lines


def _netease_lrc(title: str, artist: str):
    """网易云：搜索歌曲 -> 拿 id -> 拉歌词"""
    try:
        r = requests.post(
            "http://music.163.com/api/search/pc",
            data={"s": f"{title} {artist}".strip(), "type": 1, "limit": 5, "offset": 0},
            headers=_UA, timeout=6,
        )
        songs = r.json().get("result", {}).get("songs") or []
        if not songs:
            return None
        # 用歌名匹配度最高的第一条
        sid = songs[0]["id"]
        r2 = requests.get(
            "http://music.163.com/api/song/lyric",
            params={"id": sid, "lv": 1, "kv": 1, "tv": -1},
            headers=_UA, timeout=6,
        )
        lrc = (r2.json().get("lrc") or {}).get("lyric")
        return _parse_lrc(lrc) if lrc else None
    except Exception as e:
        log.debug("netease lyric failed: %s", e)
        return None


def _qq_lrc(title: str, artist: str):
    """QQ 音乐兜底源"""
    try:
        s = requests.get(
            "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
            params={"w": f"{title} {artist}".strip(), "format": "json", "n": 3},
            headers={**_UA, "Referer": "https://y.qq.com/"}, timeout=6,
        )
        lst = s.json().get("data", {}).get("song", {}).get("list") or []
        if not lst:
            return None
        mid = lst[0]["songmid"]
        r2 = requests.get(
            "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
            params={"songmid": mid, "g_tk": 5381, "format": "json"},
            headers={**_UA, "Referer": "https://y.qq.com/"}, timeout=6,
        )
        b64 = r2.json().get("lyric")
        if not b64:
            return None
        lrc = base64.b64decode(b64).decode("utf-8", errors="ignore")
        return _parse_lrc(lrc)
    except Exception as e:
        log.debug("qq lyric failed: %s", e)
        return None


def fetch_lrc(title: str, artist: str):
    """对外入口：返回 [(秒, 文本)] 或 None。先网易云后 QQ。"""
    if not title:
        return None
    for fn in (_netease_lrc, _qq_lrc):
        lines = fn(title, artist or "")
        if lines:
            log.info("歌词获取成功 via %s: %s - %s (%d行)", fn.__name__, title, artist, len(lines))
            return lines
    return None


def current_line(lrc_lines, pos: float):
    """根据当前播放进度返回 (当前行文本, 下一行文本)"""
    if not lrc_lines:
        return "", ""
    cur, nxt = "", ""
    for sec, text in lrc_lines:
        if sec <= pos + 0.3:
            cur = text
        else:
            nxt = text
            break
    return cur, nxt
