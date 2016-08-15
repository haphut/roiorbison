# -*- coding: utf-8 -*-

import logging
import copy

from lxml import etree

from . import poisonpill


LOG = logging.getLogger(__name__)


def _trim_tree(element):
    """Reduce memory usage of the ElementTree by deleting traversed siblings."""
    parent = element.getparent()
    element.clear()
    while element.getprevious() is not None:
        del parent[0]


class XMLParser:
    def __init__(input_queue, output_queue, forward_queue, run_blocking):
        """Create XMLParser.

        Arguments:
            input_queue: (asyncio.Queue) Queue to read ROI bytes from.
            output_queue: (queue.Queue) Queue towards ROIManager.
            forward_queue: (asyncio.Queue) Queue towards MQTTForwarder.
            run_blocking: (coroutine) Awaitable wrapper for a blocking function.
        """
        self._input_queue = input_queue
        self._output_queue = output_queue
        self._forward_queue = forward_queue
        self._run_blocking = run_blocking

    await def _copy_into_queue(queue, element):
        """Copy an Element into a blocking queue.

        We wish to reduce the memory used by the ElementTree by trimming the
        tree so send independent copies of elements onwards.
        """
        await self._run_blocking(queue.put(copy.deepcopy(element))

    async def _handle_root_start_tag(self):
        """Handle the start tag of the remote root element.

        Put the start tag of the remote root element into both the output and
        forward queues. Also make sure that the main parser for 'end' events
        gets all the bytes read by this function.
        """
        stream_start = b''
        root_start_tag_name = None
        root_parser = etree.XMLPullParser(events=('start', ))
        events = root_parser.read_events()
        while True:
            received = await self._input_queue.get()
            if received is poisonpill.PoisonPill:
                # No matter if we received some bytes as it was not enough to
                # parse into an Element.
                return poisonpill.PoisonPill, None
            stream_start += received
            root_parser.feed(received)
            for unused_action, element in events:
                # First tag must belong to the root element.
                root_start_tag_name = element.tag
                self._copy_into_queue(self._output_queue, element)
                self._copy_into_queue(self._forward_queue, element)
                return stream_start, root_start_tag_name

    async def keep_parsing(self):
        """Parse bytes from input and put Elements to output and forward queues.

        This coroutine completes only in case of a parsing error or if the
        PoisonPill is found from the input queue.
        """
        parser = etree.XMLPullParser(events=('end', ))
        events = parser.read_events()
        try:
            stream_start, root_start_tag_name = self._handle_root_start_tag()
            if stream_start is poisonpill.PoisonPill:
                LOG.debug('Received PoisonPill.')
                return
            parser.feed(stream_start)
            while True:
                for unused_action, element in events:
                    parent = element.getparent()
                    # Only the root element and its children interest us.
                    if parent is None or parent.tag == root_start_tag_name:
                        self._copy_into_queue(self._output_queue, element)
                        self._copy_into_queue(self._forward_queue, element)
                        _trim_tree(element)
                received = await self._input_queue.get()
                if received is poisonpill.PoisonPill:
                    LOG.debug('Received PoisonPill.')
                    return
                parser.feed(received)
        except etree.LxmlError as e:
            LOG.warn(e)
