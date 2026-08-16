#!/usr/bin/env python3
"""Tests for configureLogging.

Two requirements pull against each other here.

fileConfig defaults to disable_existing_loggers=True, which switches off every
logging.getLogger(__name__) created at import time. That silently dropped all 41
diagnostic calls in the AIInterpret package.

Passing False fixes that, but it also un-silences third-party loggers that the
same side effect had been suppressing. pymongo 4 logs every command *and its
reply* on pymongo.command at DEBUG, and logging.cfg puts the root logger at
DEBUG -- so query results, including user gene lists and job contents, started
being written into application.log at roughly 5000 lines an hour.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_logging_setup
"""
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.LoggingSetup import configureLogging, NOISY_THIRD_PARTY_LOGGERS

CONFIG = """[loggers]
keys=root

[handlers]
keys=consoleHandler

[formatters]
keys=info

[logger_root]
level=DEBUG
handlers=consoleHandler

[handler_consoleHandler]
class=StreamHandler
formatter=info
args=(sys.stdout,)

[formatter_info]
format=%(levelname)s - %(message)s
"""


class ConfigureLoggingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Created before configureLogging runs, which is exactly the case that
        # disable_existing_loggers=True used to break.
        cls.moduleLogger = logging.getLogger("src.classes.AIInterpret.agent")

        handle = tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False)
        handle.write(CONFIG)
        handle.close()
        cls.configPath = handle.name
        configureLogging(cls.configPath)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.configPath)

    def test_module_logger_created_before_config_still_emits(self):
        self.assertFalse(self.moduleLogger.disabled)
        self.assertTrue(self.moduleLogger.isEnabledFor(logging.INFO))

    def test_pymongo_command_logging_is_quiet(self):
        # The specific logger that was writing query replies to disk.
        self.assertFalse(logging.getLogger("pymongo.command").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("pymongo.command").isEnabledFor(logging.INFO))

    def test_every_declared_noisy_logger_is_quieted(self):
        for name in NOISY_THIRD_PARTY_LOGGERS:
            with self.subTest(logger=name):
                self.assertFalse(logging.getLogger(name).isEnabledFor(logging.DEBUG))

    def test_third_party_warnings_still_get_through(self):
        # Quieting must not mean silencing: a genuine pymongo warning is
        # something an operator needs to see.
        self.assertTrue(logging.getLogger("pymongo").isEnabledFor(logging.WARNING))

    def test_root_logger_still_at_debug(self):
        # The application's own verbosity is unchanged; only the noisy
        # third-party trees were lowered.
        self.assertTrue(logging.getLogger().isEnabledFor(logging.DEBUG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
