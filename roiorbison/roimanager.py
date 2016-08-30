# -*- coding: utf-8 -*-

import asyncio
from concurrent import futures
import functools
import logging
import threading

import isodate

from . import poisonpill
from . import roimachine
from . import timeutil


LOG = logging.getLogger(__name__)


async def _run_blocking_until_complete(loop, executor, f):
    future = loop.run_in_executor(executor, f)
    return await future


async def _keep_writing(run_blocking, writer, q):
    while True:
        to_be_sent = await run_blocking(q.get)
        if to_be_sent is poisonpill.PoisonPill:
            LOG.debug('Received PoisonPill.')
            break
        try:
            writer.write(to_be_sent)
            await writer.drain()
        except OSError as e:
            LOG.warn('ROI TCP writing exception: ' + str(e))
            break


async def _keep_reading(reader, q):
    while True:
        line = await reader.read_line()
        if line:
            await q.put(line)
        else:
           break


async def _wait_until_first_done(futures, loop):
    wait = functools.partial(asyncio.wait, loop=loop, timeout=None)
    completed = wait(futures, return_when=futures.FIRST_COMPLETED)
    raised = wait(futures, return_when=futures.FIRST_EXCEPTION)
    done, unused_pending = await wait([completed, raised], return_when=futures.FIRST_COMPLETED)
    if raised in done:
        # FIXME: The message needs work.
        LOG.warn('An awaitable raised an exception but was not supposed to: ' + str(raised))


async def _wait_for_event(run_blocking, event):
    await run_blocking(event.wait)


def _duration_to_seconds(duration):
    return isodate.parse_duration(duration).total_seconds()


async def _empty_queue(queue):
    # FIXME: implement this, consider both queue types
    pass


async def run_roi_protocol(config, loop):
    BYTES_OUT_QUEUE_SIZE = 1
    OTHER_QUEUE_SIZE = 20
    CONNECTION_READING_BUFFER = 2**16

    roi_config = config['roi']
    roi_host = roi_config['host']
    roi_port = roi_config['port']
    reconnect_wait_in_seconds = timeutil.convert_duration_to_seconds(roi_config['reconnect_interval'])

    executor = None
    run_blocking = functools.partial(_run_blocking_until_complete, loop, executor)
    wait_for_event = functools.partial(_wait_for_event, run_blocking)
    wait_forever = functools.partial(asyncio.wait_for, timeout=None, loop=loop)

    bytes_in_queue = asyncio.Queue(OTHER_QUEUE_SIZE)
    xml_in_queue = queue.Queue(OTHER_QUEUE_SIZE)
    bytes_out_queue = queue.Queue(BYTES_OUT_QUEUE_SIZE)
    xml_forward_queue = asyncio.Queue(OTHER_QUEUE_SIZE)

    is_mqtt_connected = threading.Event()
    is_mqtt_disconnected = threading.Event()
    is_mqtt_disconnected.set()

    forwarder = mqttforwarder.MQTTForwarder(config['mqtt'], xml_forward_queue, is_mqtt_connected, is_mqtt_disconnected)
    xml_parser = xmlparser.XMLParser(bytes_in_queue, xml_in_queue,
                                     xml_forward_queue, run_blocking)
    roi_manager = roimachine.ROIMachine(config['roi'], xml_in_queue, bytes_out_queue, run_blocking)

    while True:
        try:
            await wait_for_event(is_mqtt_connected)
            reader, writer = await asyncio.open_connection(host, port, loop=loop, limit=CONNECTION_READING_BUFFER)

            mqtt_disconnected_fut = wait_for_event(is_mqtt_disconnected)
            parsing_fut = xml_parser.keep_parsing()
            reading_fut = _keep_reading(reader, bytes_in_queue)
            writing_fut = _keep_writing(run_blocking, writer, bytes_out_queue)
            roi_manager_fut = roi_manager.run()
            futures = [
                mqtt_disconnected_fut,
                parsing_fut,
                reading_fut,
                writing_fut,
                roi_manager_fut,
            ]
            # As long as everything works as expected, none of the futures
            # should get done.
            await _wait_until_first_done(futures, loop)

        except OSError as e:
            LOG.warn('ROI connection problem: ' + e)

        # Clean up in order from the reading end to the writing end.
        reading_fut.cancel()
        await wait_forever(reading_fut)
        await bytes_in_queue.put(poisonpill.PoisonPill)
        await wait_forever(parsing_fut)
        await xml_in_queue.put(poisonpill.PoisonPill)
        await wait_forever(roi_manager_fut)
        await bytes_out_queue.put(poisonpill.PoisonPill)
        await wait_forever(writing_fut)

        # Empty the queues for reuse.
        await _empty_queue(bytes_in_queue)
        await _empty_queue(xml_in_queue)
        await _empty_queue(bytes_out_queue)

        # In CPython 3.5.2 this can be done several times in a row.
        writer.close()

        await asyncio.sleep(reconnect_wait_in_seconds)
