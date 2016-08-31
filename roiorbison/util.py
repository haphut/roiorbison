# -*- coding: utf-8 -*-
"""Utilities."""

import asyncio
import concurrent.futures
import functools

import isodate


def convert_duration_to_seconds(duration):
    """Convert ISO 8601 duration to float seconds."""
    return isodate.parse_duration(duration).total_seconds()


class AsyncHelper:
    """Collect asyncio helpers that require the same loop and executor."""

    def __init__(self, loop, executor=None):
        self.loop = loop
        self.executor = executor

    async def wait_until_first_done(self, futures, logger):
        """Wait until the first future completes or raises an exception.

        We do not expect any future to raise an exception, so log a warning if
        that happens.
        """
        wait = functools.partial(asyncio.wait, loop=self.loop, timeout=None)
        completed = wait(
            futures, return_when=concurrent.futures.FIRST_COMPLETED)
        raised = wait(futures, return_when=concurrent.futures.FIRST_EXCEPTION)
        done, dummy_pending = await wait(
            [completed, raised],
            return_when=concurrent.futures.FIRST_COMPLETED)
        if raised in done:
            logger.warning(
                'An awaitable raised an exception but was not supposed to: ' +
                str(raised))

    async def run_in_executor(self, func, *args):
        """Use asyncio.run_in_executor() easily."""
        return await self.loop.run_in_executor(self.executor, func, *args)

    async def wait_for_event(self, event, *args, **kwargs):
        """Use threading.Event.wait() with asyncio."""
        return await self.run_in_executor(event.wait, *args, **kwargs)

    async def wait_forever(self, future):
        """Wait for a future until it is done."""
        return await asyncio.wait_for(future, timeout=None, loop=self.loop)
