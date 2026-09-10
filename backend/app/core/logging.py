"""
Centralised application logging configuration.

Produces structured, timestamped logs to stdout (captured by any deployment
platform's log aggregator) sufficient to diagnose validation failures, OCR
issues, LLM/API failures and unexpected exceptions during evaluation.
"""
import logging
import sys

from app.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    root.handlers = [handler]

    # Quiet down noisy third-party loggers unless we're in DEBUG.
    if settings.LOG_LEVEL.upper() != "DEBUG":
        for noisy in ("httpx", "httpcore", "PIL", "pdfminer", "multipart"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
