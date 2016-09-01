# -*- coding: utf-8 -*-
"""Control all of ROI handling."""

import asyncio
import functools
import logging
import queue

from . import poisonpill
from . import roimachine
from . import util
from . import xmlparser

LOG = logging.getLogger(__name__)


async def _keep_reading(reader, bytes_in_queue):
    """Put each line read from the reader into the queue.

    In case the remote end has closed the connection, return.
    """
    while True:
        line = await reader.read_line()
        if line:
            await bytes_in_queue.put(line)
        else:
            LOG.warning('ROI server has closed TCP connection.')
            return


async def _keep_writing(async_helper, writer, bytes_out_queue):
    """Write the contents of the queue into the writer.

    In case of an exception or the POISON_PILL, log and return.
    """
    while True:
        to_be_sent = await async_helper.run_in_executor(bytes_out_queue.get)
        if to_be_sent is poisonpill.POISON_PILL:
            LOG.debug('Received POISON_PILL.')
            return
        try:
            writer.write(to_be_sent)
            await writer.drain()
        except OSError as ex:
            LOG.warning('ROI TCP writing exception: ' + str(ex))
            return


async def _empty_asyncio_queue(queue_):
    """Empty the queue assuming no one else is putting into the queue."""
    while not queue_.empty():
        await queue_.get()


async def _empty_queue(queue_):
    """Empty the queue assuming no one else is putting into the queue."""
    while not queue_.empty():
        queue_.get()


class ROIManager:
    """Manage ROI protocol and ROI message forwarding."""

    # Size of StreamReader buffer.
    _CONNECTION_READING_BUFFER = 2**16

    def __init__(self, config, async_helper, xml_forward_queue,
                 is_mqtt_connected, is_mqtt_disconnected):
        self._async_helper = async_helper
        self._xml_forward_queue = xml_forward_queue
        self._is_mqtt_connected = is_mqtt_connected
        self._is_mqtt_disconnected = is_mqtt_disconnected

        self._host = config['host']
        self._port = config['port']
        self._reconnect_wait_in_seconds = util.convert_duration_to_seconds(
            config['reconnect_interval'])

        self._bytes_in_queue = asyncio.Queue()
        self._xml_in_queue = queue.Queue()
        self._bytes_out_queue = queue.Queue()

        self._xml_parser = xmlparser.XMLParser(
            self._async_helper, self._bytes_in_queue, self._xml_in_queue,
            self._xml_forward_queue)
        self._roi_machine = roimachine.ROIMachine(config, self._async_helper,
                                                  self._xml_in_queue,
                                                  self._bytes_out_queue)

        self._reader = None
        self._writer = None
        self._mqtt_disconnects_fut = None
        self._parsing_fut = None
        self._reading_fut = None
        self._writing_fut = None
        self._roi_machine_fut = None

    async def _connect(self):
        self._reader, self._writer = await asyncio.open_connection(
            self._host,
            self._port,
            loop=self._async_helper.loop,
            limit=ROIManager._CONNECTION_READING_BUFFER)

    async def _set_futures_up(self):
        self._mqtt_disconnects_fut = self._async_helper.wait_for_event(
            self._is_mqtt_disconnected)
        self._parsing_fut = self._xml_parser.keep_parsing()
        self._reading_fut = _keep_reading(self._reader, self._bytes_in_queue)
        self._writing_fut = _keep_writing(self._async_helper, self._writer,
                                          self._bytes_out_queue)
        self._roi_machine_fut = self._roi_machine.run()

    async def _wait_until_problem(self):
        futures = [
            self._mqtt_disconnects_fut,
            self._parsing_fut,
            self._reading_fut,
            self._writing_fut,
            self._roi_machine_fut,
        ]
        # As long as everything works as expected, none of the futures
        # should get done.
        await self._async_helper.wait_until_first_done(futures, LOG)

    async def _clean_up(self):
        # Clean up in order from the reading end to the writing end.
        self._reading_fut.cancel()
        await self._async_helper.wait_forever(self._reading_fut)
        await self._bytes_in_queue.put(poisonpill.POISON_PILL)
        await self._async_helper.wait_forever(self._parsing_fut)
        await self._async_helper.run_in_executor(
            functools.partial(self._xml_in_queue.put, poisonpill.POISON_PILL))
        await self._async_helper.wait_forever(self._roi_machine_fut)
        await self._async_helper.run_in_executor(
            functools.partial(self._bytes_out_queue.put,
                              poisonpill.POISON_PILL))
        await self._bytes_out_queue.put(poisonpill.POISON_PILL)
        await self._async_helper.wait_forever(self._writing_fut)

        # Empty the queues for reuse.
        await _empty_asyncio_queue(self._bytes_in_queue)
        await _empty_queue(self._xml_in_queue)
        await _empty_queue(self._bytes_out_queue)

        # In CPython 3.5.2 close can be called several times consecutively.
        self._writer.close()

    async def run(self):
        """Run ROIManager."""
        while True:
            try:
                await self._async_helper.wait_for_event(
                    self._is_mqtt_connected)
                await self._connect()
                await self._set_futures_up()
                await self._wait_until_problem()
            except OSError as ex:
                LOG.warning('ROI connection problem: ' + ex)
            await self._clean_up()
            LOG.info('Wait ' + self._reconnect_wait_in_seconds +
                     ' seconds before reconnecting.')
            await asyncio.sleep(self._reconnect_wait_in_seconds)
