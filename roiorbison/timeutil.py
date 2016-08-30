# -*- coding: utf-8 -*-
"""Time utilities."""

import isodate


def convert_duration_to_seconds(duration):
    """Convert ISO 8601 duration to float seconds."""
    return isodate.parse_duration(duration).total_seconds()
