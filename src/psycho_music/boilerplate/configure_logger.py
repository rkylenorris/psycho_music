import loguru
import logging

from functools import lru_cache
from loguru import logger as _base_logger

from .settings import get_app_settings


# Intercept standard logging and redirect to Loguru 
class InterceptHandler(logging.Handler):
    """Redirect standard logging calls into Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _base_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Forward to Loguru, preserving exception info
        _base_logger.opt(
            depth=6,
            exception=record.exc_info
        ).log(level, record.getMessage())


def intercept_stdlib_logging() -> None:
    """
    Route the stdlib `logging` module logs (used by many libraries) into Loguru.
    This avoids split outputs between two logging systems.
    """
    logging.basicConfig(handlers=[InterceptHandler()], level=0)
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = [InterceptHandler()]


# Create base logger from Loguru & load application settings
logger = _base_logger

app_settings = get_app_settings()


# Configure logger with settings from AppSettings
def configure_logging() -> loguru.Logger:
    """configure loguru logger

    Returns:
        loguru.Logger: set up loguru logger
    """

    # Remove all existing sinks
    logger.remove()

    # Console Sink (human-friendly) 
    logger.add(
        app_settings.logging.console_settings.output,
        level=app_settings.logging.console_settings.log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
        format=app_settings.logging.console_settings.format,
    )

    # Rotating File Sink (text)
    logger.add(
        app_settings.logging.flat_file_settings.file_path,
        level=app_settings.logging.flat_file_settings.log_level,
        rotation="7 days",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,  # safe for multiprocessing
        backtrace=True,
        diagnose=False,
    )

    # Rotating Structured JSON Logs 

    logger.add(
        app_settings.logging.json_file_settings.file_path,
        level=app_settings.logging.json_file_settings.log_level,
        rotation="7 days",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
        serialize=True,  # output JSON
    )

    # Route stdlib logging (for libraries) into Loguru
    intercept_stdlib_logging()

    # Bind app_name globally (available in JSON extra) and return logger object
    return logger.bind(
        app_name=app_settings.app_name,
        run_guid=app_settings.logging.run_guid
    )


@lru_cache
def get_logger() -> loguru.Logger:
    return configure_logging()
