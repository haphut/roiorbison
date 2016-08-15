# -*- coding: utf-8 -*-
"""Setup logging facilities."""

import logging.config
import time


class UTCFormatter(logging.Formatter):
    """Use UTC time instead of local time."""
    converter = time.gmtime


def set_logging(config):
    """Set logging up based on given dict."""
    logging.config.dictConfig(config)
