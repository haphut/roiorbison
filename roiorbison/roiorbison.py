#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import logging.config

import cmdline
import log


def main():
    # Format logging from a file.
    # Create event loop
    # Create queues?
    # Start MQTT connection
    # When mqtt subscription and retain check is finished,
    # Start ROI TCP connection while True -loop
    args = cmdline.parse_cmdline()
    config = args.config

    log.set_logging(config['logging'])
    LOG = logging.getLogger(__name__)

    loop = asyncio.get_event_loop()

    #mqtt_forwarder = MQTTForwarder(config['mqtt'])


if __name__ == "__main__":
    main()
