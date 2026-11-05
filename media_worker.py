# -*- coding: utf-8 -*-
"""
media_worker.py — 系统媒体会话监听
通过 Windows 的 GlobalSystemMediaTransportControls（SMTC）读取
当前正在播放的音乐：歌名、歌手、专辑封面、进度、播放状态，
并提供 播放/暂停/上一首/下一首 控制。
网易云、QQ音乐、Spotify、浏览器网页播放等全部通用。

实现方式：后台线程跑 asyncio 事件循环，每秒轮询一次，
通过 Qt 信号跨线程把数据发给 UI。
"""
import asyncio
import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

log = logging.getLogger("island.media")


class MediaWatcher(QObject):
    """跨线程媒体监听器"""

    # info: {title, artist, album, cover_path, status}
    mediaChanged = Signal(dict)
    # pos(秒), dur(秒), 是否播放中
    positionChanged = Signal(float, float, bool)
    # 播放器名称（来源应用）
    sourceChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._loop = None
        self._last_key = None          # (title, artist) 用于判断切歌
        self._last_pos_emit = 0.0
        self._est_pos = 0.0            # 本地估算的播放进度（秒）
        self._est_ts = time.time()
        self._ready = threading.Event()

    # ---------- 对 UI 暴露的方法 ----------

    def start(self):
        self._thread.start()
        # 最多等 5 秒让事件循环就绪
        self._ready.wait(5)

    def control(self, action: str):
        """播放控制：play / pause / toggle / prev / next"""
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self._async_control(action), self._loop)

    # ---------- 后台线程内部 ----------

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            log.error("media loop crashed: %s", e)

    async def _main(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )
        self._mgr = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        self._ready.set()
        log.info("SMTC manager ready")
        empty_polls = 0
        last_count = -1
        while True:
            try:
                count = len(list(self._mgr.get_sessions()))
                if count != last_count:
                    log.info("SMTC sessions: %d", count)
                    last_count = count
                if count == 0:
                    empty_polls += 1
                    # 已知坑：部分 Windows 构建上，音乐开始播放之前
                    # 请求的 Manager 不会刷新会话列表，空转 20 秒后重建
                    if empty_polls % 20 == 0:
                        log.info("no sessions for a while, re-request manager")
                        self._mgr = await (
                            GlobalSystemMediaTransportControlsSessionManager
                            .request_async())
                else:
                    empty_polls = 0
                await self._poll()
            except Exception as e:
                log.debug("poll error: %s", e)
            await asyncio.sleep(1)

    def _pick_session(self):
        """挑一个有内容的媒体会话（优先音乐类）"""
        sessions = list(self._mgr.get_sessions())
        if not sessions:
            return None, None
        # 优先选正在 Playing 的
        best = None
        for s in sessions:
            try:
                pb = s.get_playback_info()
                if pb.playback_status == 4:  # PLAYING
                    best = s
                    break
            except Exception:
                continue
        if best is None:
            best = sessions[0]
        return best, best.source_app_user_model_id if best else None

    async def _poll(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )

        session, app_id = self._pick_session()
        if session is None:
            if self._last_key != ("", ""):
                self._last_key = ("", "")
                self.mediaChanged.emit({"title": "", "artist": "", "album": "",
                                        "cover_path": "", "status": "none"})
            return

        if app_id:
            self.sourceChanged.emit(str(app_id))

        props = await session.try_get_media_properties_async()
        title, artist, album = props.title, props.artist, props.album_title
        pb = session.get_playback_info()
        playing = pb.playback_status == Status.PLAYING

        # 封面：只在切歌时保存一次
        key = (title, artist)
        cover_path = ""
        if self._last_key != key:
            try:
                stream = await props.thumbnail.open_read_async()
                size = stream.size
                from winrt.windows.storage.streams import DataReader
                reader = DataReader(stream)
                await reader.load_async(size)
                # winrt 4.x: read_bytes 需要传入预分配的 bytearray
                buf = bytearray(size)
                reader.read_bytes(buf)
                data = bytes(buf)
                if data:
                    import os
                    cover_path = os.path.join(_cover_dir(), "cover.png")
                    with open(cover_path, "wb") as f:
                        f.write(data)
            except Exception as e:
                log.debug("cover error: %s", e)

            # 切歌：重置本地进度估算器
            self._est_pos = 0.0
            self._est_ts = time.time()
            self._last_key = key
            self.mediaChanged.emit({
                "title": title, "artist": artist, "album": album,
                "cover_path": cover_path,
                "status": "playing" if playing else "paused",
            })

        # 进度：SMTC 的 position 只在事件时刷新，播放中要按流逝时间补偿。
        # 部分播放器（如网易云音乐）不上报时间轴（dur=0），
        # 此时用本地时钟估算播放进度，保证歌词能滚动。
        tl = session.get_timeline_properties()
        pos = tl.position.total_seconds()
        dur = tl.end_time.total_seconds() if tl.end_time else 0.0
        now = time.time()
        if dur > 0.5:
            if playing:
                since = now - tl.last_updated_time.timestamp()
                if 0 < since < 30:
                    pos += since
            self._est_pos = pos          # 有真实进度时同步估算器
            self._est_ts = now
            use_pos = pos
        else:
            if playing:
                self._est_pos += now - self._est_ts
                self._est_ts = now
                use_pos = self._est_pos
            else:
                self._est_ts = now       # 暂停：冻结估算进度
                use_pos = self._est_pos

        if now - self._last_pos_emit >= 0.9:
            self._last_pos_emit = now
            self.positionChanged.emit(use_pos, dur, playing)

    async def _async_control(self, action: str):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
        )
        session, _ = self._pick_session()
        if session is None:
            return
        try:
            pb = session.get_playback_info()
            if action == "play":
                await session.try_play_async()
            elif action == "pause":
                await session.try_pause_async()
            elif action == "toggle":
                if pb.playback_status == Status.PLAYING:
                    await session.try_pause_async()
                else:
                    await session.try_play_async()
            elif action == "prev":
                await session.try_skip_previous_async()
            elif action == "next":
                await session.try_skip_next_async()
        except Exception as e:
            log.debug("control error: %s", e)


def _cover_dir():
    import os
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")
    os.makedirs(d, exist_ok=True)
    return d
