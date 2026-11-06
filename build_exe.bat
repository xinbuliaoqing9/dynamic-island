@echo off
rem ============================================================
rem  一键打包脚本：把灵动岛打包成免安装的 exe
rem  使用前提：本机已安装 Python 3.11+ 并执行过
rem            pip install -r requirements.txt pyinstaller
rem  产物：dist\DynamicIsland\DynamicIsland.exe （整个 dist\DynamicIsland 文件夹）
rem ============================================================
cd /d "%~dp0"
python -m PyInstaller --noconfirm ^
  --name DynamicIsland ^
  --windowed ^
  --icon icon.ico ^
  --distpath dist2 ^
  --workpath build2 ^
  --hidden-import winrt.windows.media.control ^
  --hidden-import winrt.windows.storage.streams ^
  --collect-submodules winrt ^
  main.py
echo.
echo 打包完成！可分发文件在 dist2\DynamicIsland\ 目录，压缩后即可发给别人。
pause
