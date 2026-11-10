"""Keyfolio 入口：配置日志、启动 uvicorn，exe 双击时自动打开浏览器。"""
import logging
import os
import sys
import threading
import webbrowser

from app import paths


def _setup_logging() -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[logging.FileHandler(paths.LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )


_setup_logging()

from app.main import app  # noqa: E402  必须在日志配置之后导入

import uvicorn  # noqa: E402


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        logging.getLogger("keyfolio").warning("无法自动打开浏览器，请手动访问 %s", url)


def main() -> None:
    url = f"http://127.0.0.1:{paths.PORT}"
    if getattr(sys, "frozen", False) or os.environ.get("KEYFOLIO_OPEN") == "1":
        threading.Timer(1.5, _open_browser, [url]).start()
    uvicorn.run(app, host=paths.HOST, port=paths.PORT, log_level="warning")


if __name__ == "__main__":
    main()
