import sys

from loguru import logger

from app.core.config import settings


def _safe_console_sink(message) -> None:
    text = str(message)
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(
        encoding,
        errors="replace",
    )
    sys.stdout.write(safe_text)


logger.remove()
logger.add(
    sink=_safe_console_sink,
    level=settings.log_level,
    serialize=False,
    backtrace=False,
    diagnose=settings.debug,
)
