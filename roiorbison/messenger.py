# -*- coding: utf-8 -*-
"""Prepare ROI messages to be sent to the ROI server."""

import logging

from . import templater

LOG = logging.getLogger(__name__)


def _create_message_id_generator(start=0):
    """Return a generator for unique message IDs."""
    counter = start
    while True:
        yield counter
        counter += 1


class Messenger:
    """Form own ROI messages and queue them to be sent to the ROI server.

    Messenger and its output queue can live for the duration of the
    application.
    """

    def __init__(self, config, output_queue):
        self._output_queue = output_queue

        gen = _create_message_id_generator()

        templates = config['templates']
        self._own_root_start_tag_templater = templater.Templater(
            templates['own_root_start_tag'], gen)
        self._own_root_end_tag_templater = templater.Templater(
            templates['own_root_end_tag'], gen)
        self._resume_subscription_templater = templater.Templater(
            templates['resume_subscription'], gen)
        self._subscribe_templater = templater.Templater(templates['subscribe'],
                                                        gen)
        self._last_processed_templater = templater.Templater(
            templates['last_processed'], gen)

    def _send(self, picked_templater, **kwargs):
        """General sending function."""
        to_be_sent = picked_templater.fill(**kwargs)
        LOG.debug('Sending: ' + to_be_sent.decode('utf-8'))
        self._output_queue.put(to_be_sent)

    def send_own_root_start_tag(self):
        """Send own root start tag."""
        self._send(self._own_root_start_tag_templater)

    def send_own_root_end_tag(self):
        """Send own root end tag."""
        self._send(self._own_root_end_tag_templater)

    def send_resume_subscription(self):
        """Send a subscription resumption element."""
        self._send(self._resume_subscription_templater)

    def send_subscribe(self):
        """Send a subscription element."""
        self._send(self._subscribe_templater)

    def send_last_processed(self, on_message_id, last_processed_message_id):
        """Respond to a request about the last processed message."""
        extra_mapping = {
            'on_message_id': on_message_id,
            'last_processed_message_id': last_processed_message_id,
        }
        self._send(self._last_processed_templater, extra_mapping=extra_mapping)
