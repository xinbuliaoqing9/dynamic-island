# -*- coding: utf-8 -*-
"""
stash.py — 文件暂存模块
把拖进来的文件/图片/视频复制到本地暂存目录，支持：
  - 重名自动处理
  - 重启后恢复列表（meta.json 持久化）
  - 从灵动岛把文件拖出去（拖出的是暂存目录里的副本，
    不影响原文件；也可右键打开文件位置）
"""
import json
import logging
import os
import shutil
import time

log = logging.getLogger("island.stash")

_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".ts"}
_AUDIO_EXT = {".mp3", ".flac", ".wav", ".m4a", ".ape", ".ogg"}


class StashManager:
    """暂存区数据管理（无 UI）"""

    def __init__(self, stash_dir: str):
        self.dir = stash_dir
        os.makedirs(self.dir, exist_ok=True)
        self.meta_path = os.path.join(self.dir, "meta.json")
        self.items = []  # [{path, name, size, ts}]
        self._load()

    # ---------- 持久化 ----------

    def _load(self):
        try:
            if os.path.exists(self.meta_path):
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    self.items = json.load(f)
                # 清理已被手动删除的文件
                self.items = [it for it in self.items if os.path.exists(it["path"])]
        except Exception as e:
            log.warning("stash meta load failed: %s", e)
            self.items = []

    def _save(self):
        try:
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=1)
        except Exception as e:
            log.warning("stash meta save failed: %s", e)

    # ---------- 操作 ----------

    def add_paths(self, paths) -> list:
        """复制文件/文件夹进暂存区，返回新增条目"""
        added = []
        for p in paths:
            p = os.path.normpath(str(p))
            try:
                if os.path.isfile(p):
                    dest = self._unique_dest(p)
                    shutil.copy2(p, dest)
                    size = os.path.getsize(dest)
                elif os.path.isdir(p):
                    dest = self._unique_dest_dir(p)
                    shutil.copytree(p, dest)
                    size = self._dir_size(dest)
                else:
                    continue
                item = {
                    "path": dest,
                    "name": os.path.basename(dest),
                    "size": size,
                    "ts": time.time(),
                }
                self.items.append(item)
                added.append(item)
            except Exception as e:
                log.warning("stash add failed %s: %s", p, e)
        if added:
            self._save()
        return added

    def remove(self, item: dict):
        """从暂存区移除（同时删副本文件/文件夹）"""
        try:
            if os.path.isdir(item["path"]):
                shutil.rmtree(item["path"], ignore_errors=True)
            elif os.path.exists(item["path"]):
                os.remove(item["path"])
        except Exception as e:
            log.warning("stash remove failed: %s", e)
        if item in self.items:
            self.items.remove(item)
        self._save()

    def clear(self):
        for it in list(self.items):
            self.remove(it)

    def _unique_dest(self, src: str) -> str:
        base = os.path.basename(src)
        name, ext = os.path.splitext(base)
        dest = os.path.join(self.dir, base)
        i = 1
        while os.path.exists(dest):
            dest = os.path.join(self.dir, f"{name}({i}){ext}")
            i += 1
        return dest

    def _unique_dest_dir(self, src: str) -> str:
        base = os.path.basename(os.path.normpath(src))
        dest = os.path.join(self.dir, base)
        i = 1
        while os.path.exists(dest):
            dest = os.path.join(self.dir, f"{base}({i})")
            i += 1
        return dest

    @staticmethod
    def _dir_size(path: str) -> int:
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    def kind(self, item: dict) -> str:
        if os.path.isdir(item["path"]):
            return "folder"
        ext = os.path.splitext(item["name"])[1].lower()
        if ext in _IMG_EXT:
            return "image"
        if ext in _VIDEO_EXT:
            return "video"
        if ext in _AUDIO_EXT:
            return "audio"
        return "file"
