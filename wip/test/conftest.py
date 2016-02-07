from contextlib import contextmanager

import pytest
from eliot import MemoryLogger, _output
from eliot.testing import UnflushedTracebacks


@pytest.fixture
def validate_logging():
    @contextmanager
    def _make_validator(logger=None):
        logger = MemoryLogger()
        try:
            yield logger
        finally:
            logger.validate()
            if logger.tracebackMessages:
                UnflushedTracebacks(logger.tracebackMessages)
    return _make_validator


@pytest.fixture
def capture_logging(monkeypatch, validate_logging):
    @contextmanager
    def _monkeypatch_default_logger():
        with validate_logging() as logger:
            monkeypatch.setattr(_output, '_DEFAULT_LOGGER', logger)
            yield logger
    return _monkeypatch_default_logger
