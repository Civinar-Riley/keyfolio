"""路径解析：开发态、Docker、PyInstaller exe 三种运行形态统一。"""
import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller exe：exe 所在目录
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()

DATA_DIR = Path(os.environ.get("KEYFOLIO_DATA_DIR") or (BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "data.db"
LOG_PATH = DATA_DIR / "app.log"

if getattr(sys, "frozen", False):
    STATIC_DIR = Path(getattr(sys, "_MEIPASS")) / "app" / "static"
else:
    STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = os.environ.get("KEYFOLIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("KEYFOLIO_PORT", "3000"))
