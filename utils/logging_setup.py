import io
import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
    # Force UTF-8 so Unicode characters (arrows, accents) don't crash on Windows terminals
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[logging.StreamHandler(utf8_stdout)],
    )
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
