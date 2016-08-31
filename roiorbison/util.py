# -*- coding: utf-8 -*-
"""Utilities."""

import asyncio
import concurrent.futures
import functools

import isodate


def convert_duration_to_seconds(duration):
    """Convert ISO 8601 duration to float seconds."""
    return isodate.parse_duration(duration).total_seconds()


async def wait_until_first_done(futures, loop, logger):
    """Wait until the first future completes or raises an exception.

    We do not expect any future to raise an exception, so log a warning if that
    happens.
    """
    wait = functools.partial(asyncio.wait, loop=loop, timeout=None)
    completed = wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
    raised = wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
    done, dummy_pending = await wait(
        [completed, raised], return_when=concurrent.futures.FIRST_COMPLETED)
    if raised in done:
        logger.warning(
            'An awaitable raised an exception but was not supposed to: ' + str(
                raised))


async def run_in_executor(loop, executor, func, *args):
    """Wrap asyncio.run_in_executor() for use with functools.partial()."""
    return await loop.run_in_executor(executor, func, *args)
