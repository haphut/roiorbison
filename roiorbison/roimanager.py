# -*- coding: utf-8 -*-
"""Control all of ROI handling."""

import asyncio
import logging
import queue

from . import poisonpill
from . import roimachine
from . import util
from . import xmlparser

LOG = logging.getLogger(__name__)

# Size for TCP StreamReader buffer.
CONNECTION_READING_BUFFER = 2**16


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

    In case of an exception or the PoisonPill, log and return.
    """
    while True:
        to_be_sent = await async_helper.run_in_executor(bytes_out_queue.get)
        if to_be_sent is poisonpill.PoisonPill:
            LOG.debug('Received PoisonPill.')
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


async def run_roi(config, async_helper, xml_forward_queue, is_mqtt_connected,
                  is_mqtt_disconnected):
    """Run ROI protocol and ROI message forwarding."""
    host = config['host']
    port = config['port']
    reconnect_wait_in_seconds = util.convert_duration_to_seconds(config[
        'reconnect_interval'])

    bytes_in_queue = asyncio.Queue()
    xml_in_queue = queue.Queue()
    bytes_out_queue = queue.Queue()

    xml_parser = xmlparser.XMLParser(async_helper, bytes_in_queue,
                                     xml_in_queue, xml_forward_queue)
    roi_machine = roimachine.ROIMachine(config, async_helper, xml_in_queue,
                                        bytes_out_queue)

    while True:
        try:
            await async_helper.wait_for_event(is_mqtt_connected)
            reader, writer = await asyncio.open_connection(
                host,
                port,
                loop=async_helper.loop,
                limit=CONNECTION_READING_BUFFER)

            mqtt_disconnected_fut = async_helper.wait_for_event(
                is_mqtt_disconnected)
            parsing_fut = xml_parser.keep_parsing()
            reading_fut = _keep_reading(reader, bytes_in_queue)
            writing_fut = _keep_writing(async_helper, writer, bytes_out_queue)
            roi_machine_fut = roi_machine.run()
            futures = [
                mqtt_disconnected_fut,
                parsing_fut,
                reading_fut,
                writing_fut,
                roi_machine_fut,
            ]
            # As long as everything works as expected, none of the futures
            # should get done.
            await async_helper.wait_until_first_done(futures, LOG)

        except OSError as ex:
            LOG.warning('ROI connection problem: ' + ex)

        # Clean up in order from the reading end to the writing end.
        reading_fut.cancel()
        await async_helper.wait_forever(reading_fut)
        await bytes_in_queue.put(poisonpill.PoisonPill)
        await async_helper.wait_forever(parsing_fut)
        await xml_in_queue.put(poisonpill.PoisonPill)
        await async_helper.wait_forever(roi_machine_fut)
        await bytes_out_queue.put(poisonpill.PoisonPill)
        await async_helper.wait_forever(writing_fut)

        # Empty the queues for reuse.
        await _empty_asyncio_queue(bytes_in_queue)
        await _empty_queue(xml_in_queue)
        await _empty_queue(bytes_out_queue)

        # In CPython 3.5.2 close can be called several times consecutively.
        writer.close()

        LOG.info('Wait ' + reconnect_wait_in_seconds +
                 ' seconds before reconnecting.')
        await asyncio.sleep(reconnect_wait_in_seconds)
