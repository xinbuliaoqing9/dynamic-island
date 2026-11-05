# 桌面灵动岛 (Desktop Dynamic Island)

Windows 桌面顶部的悬浮「灵动岛」：**文件暂存中转 + 音乐歌词显示 + 邮箱验证码提醒**，每个功能都带独立开关。

![平台](https://img.shields.io/badge/Windows-10%2F11-blue) ![Python](https://img.shields.io/badge/Python-3.11%2B-green)

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 📁 文件暂存 | 把文件/图片/视频**拖到岛上暂存**，随时**按住拖出**取用（副本方式，不动原文件），重启不丢失 |
| 🎵 音乐歌词 | 自动读取系统正在播放的歌曲（网易云/QQ音乐/Spotify/浏览器均支持）：封面、歌名、歌手、**滚动歌词**、进度条 |
| ⏯ 播放控制 | 岛上直接 播放/暂停/上一首/下一首 |
| 📧 验证码提醒 | 通过 IMAP 监听邮箱收件箱，收到验证码邮件自动提取并显示，**点击即复制** |
| 🎛 功能管理 | 每个功能可单独开关；邮箱在管理面板配置 |

## 🚀 快速开始

### 方式一：下载打包好的 exe（推荐普通用户）

到 [Releases](../../releases) 下载 `DynamicIsland.zip`，解压后双击 `DynamicIsland.exe` 即可，**无需安装 Python**。

### 方式二：源码运行（开发者）

```bash
pip install -r requirements.txt
python main.py
```

### 自己打包 exe

```bash
pip install pyinstaller
build_exe.bat    # 产物在 dist/DynamicIsland/
```

## 📧 邮箱验证码配置

验证码功能默认关闭，需要在 **托盘图标右键 → 功能管理 → 邮箱配置** 中填写：

| 邮箱 | IMAP 服务器 | 端口 | 密码说明 |
|------|-------------|------|----------|
| QQ 邮箱 | imap.qq.com | 993 | 网页版设置→账户→开启IMAP→生成**授权码** |
| 163 邮箱 | imap.163.com | 993 | 设置→POP3/IMAP/SMTP→开启→**授权码** |
| Outlook | imap-mail.outlook.com | 993 | 账号密码 |

> ⚠️ 授权码不是邮箱登录密码。配置只保存在本机 `config.json`，不会上传。

## 🖱 使用技巧

- 把文件拖到岛上 = 暂存；从岛上按住文件拖出 = 取用
- 右键文件缩略图：打开 / 打开位置 / 移除 / 清空
- 按住胶囊空白处可上下拖动位置
- 鼠标移开会自动收起，悬停自动展开
- 托盘图标右键：功能管理 / 退出

## 📁 项目结构

```
dynamic-island/
├── main.py            # 主程序：悬浮岛 UI 与交互
├── media_worker.py    # Windows 系统媒体会话监听（SMTC）
├── lyrics.py          # 歌词获取（网易云 + QQ 双源 LRC 解析）
├── mail_worker.py     # IMAP 邮箱轮询 + 验证码提取
├── stash.py           # 文件暂存管理
├── settings_dialog.py # 功能管理面板
└── build_exe.bat      # PyInstaller 打包脚本
```

## ⚠️ 已知限制

- 歌词来自公开接口模糊匹配，冷门歌曲可能匹配失败
- 邮箱验证码轮询间隔建议 ≥15 秒，过于频繁可能触发邮箱风控
- 需要 Windows 10 1703+ 才有系统媒体接口（SMTC）

## License

MIT
