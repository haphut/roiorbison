#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main module."""

import asyncio
import logging
import logging.config
import threading

from . import cmdline
from . import mqttforwarder
from . import roimanager
from . import util


def main():
    """Main function."""
    args = cmdline.parse_cmdline()
    config = args.config

    logging.config.dictConfig(config['logging'])
    logger = logging.getLogger(__name__)

    loop = asyncio.get_event_loop()
    async_helper = util.AsyncHelper(loop, executor=None)

    xml_forward_queue = asyncio.Queue()

    # Create separate events for getting connected and disconnected so both can
    # be waited for normally. Not very pretty.
    is_mqtt_connected = threading.Event()
    is_mqtt_disconnected = threading.Event()
    is_mqtt_disconnected.set()

    mqtt_forwarder = mqttforwarder.MQTTForwarder(
        config['mqtt'], async_helper, xml_forward_queue, is_mqtt_connected,
        is_mqtt_disconnected)
    roi_manager = roimanager.ROIManager(config['roi'], async_helper,
                                        xml_forward_queue, is_mqtt_connected,
                                        is_mqtt_disconnected)

    futures = [mqtt_forwarder.run(), roi_manager.run()]
    loop.run_until_complete(
        async_helper.wait_until_first_done(futures, logger))


if __name__ == '__main__':
    main()
