"""Shared logging configuration.

Every entry point that configures logging goes through configureLogging() so the
two settings below cannot drift apart between the server and the admin tools.
"""
import logging
import logging.config

# Third-party loggers that are far too loud at the root logger's DEBUG level.
# pymongo 4 logs every command *and its reply* on pymongo.command, so a single
# pathway query writes the whole result set -- gene lists, job contents, user
# data -- into application.log. Setting the parent logger is enough; the
# per-component children (command, connection, serverSelection, topology)
# inherit it.
NOISY_THIRD_PARTY_LOGGERS = ("pymongo", "urllib3", "requests", "matplotlib")


def configureLogging(configPath):
    """Apply logging.cfg without switching off the application's own loggers.

    fileConfig defaults to disable_existing_loggers=True, which disables every
    logging.getLogger(__name__) created at import time -- that is, every module
    logger in the codebase. Their records were dropped silently, so the AI
    pipeline in particular ran with no diagnostics at all.

    Passing False fixes that, but it also un-silences third-party loggers that
    were previously disabled by the same side effect, so those are quieted
    explicitly rather than by accident.
    """
    logging.config.fileConfig(configPath, disable_existing_loggers=False)

    for name in NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
