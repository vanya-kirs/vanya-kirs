import logging
import logging.handlers
import os


def setup_logging(enable_listener_file: bool = False) -> None:
    """Configure application-wide logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    if enable_listener_file:
        _add_listener_file_handler()


def _add_listener_file_handler() -> None:
    """Add a rotating file handler for the listener process."""
    log_dir = os.environ.get("LOG_DIR", "/tmp/tgparser_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "listener.log")

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    listener_logger = logging.getLogger("app.listener")
    listener_logger.addHandler(handler)
    listener_logger.info("Listener file logging initialized: %s", log_path)


def setup_parser_file_logging() -> None:
    """Add a rotating file handler for the parser and parse tasks."""
    log_dir = os.environ.get("LOG_DIR", "/tmp/tgparser_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "parser.log")

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    for name in ("app.parser", "app.tasks.parse"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)

    logging.getLogger("app.parser").info(
        "Parser file logging initialized: %s", log_path
    )
