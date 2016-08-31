# -*- coding: utf-8 -*-
"""Publish ROI messages."""

import logging

from lxml import etree
import paho.mqtt.client as mqtt

from . import mqttretainedretriever as retriever
from . import roimachine

LOG = logging.getLogger(__name__)


def _serialize(element, is_root_tag=False):
    END_TAG = b'</ROI:FromPubTransMessages>'
    out = None
    if is_root_tag:
        out = etree.tostring(element, encoding='utf-8')
        # FIXME: Cut off the end tag without using the name.
        out = out.rstrip()
        if out.endswith(END_TAG):
            out = out[:-len(END_TAG)]
    else:
        out = etree.tostring(element, encoding='utf-8')
    return out


class MQTTForwarder:
    """Filter, serialize and publish ROI messages on an MQTT broker.

    We employ a little MQTT-specific trick for publishing the ROI feed: We
    publish the start tag of the root element only if an element with the same
    name is not already available as a retained message on the publishing
    topic. We also do not publish the end tag of the root element. This allows
    the MQTT subscriber to attain a valid XML document no matter when they
    subscribe.

    First we check whether the retained message exists on the topic already.
    Then we start publishing accordingly.
    """

    def __init__(self, config, async_helper, xml_forward_queue,
                 is_mqtt_connected, is_mqtt_disconnected):
        self._async_helper = async_helper
        self._queue = xml_forward_queue
        self._is_mqtt_connected = is_mqtt_connected
        self._is_mqtt_disconnected = is_mqtt_disconnected

        self._host = config['host']
        self._port = config['port']
        self._topic = config['topic']
        self._qos = config['qos']

        self._retriever = retriever.MQTTRetainedRetriever(config)
        self._is_root_start_tag_published = False

        self._client = self._create_client(config)

    def _create_client(self, config):
        client = mqtt.Client(client_id=config['client_id'])
        client.on_connect = self._cb_on_connect
        client.on_disconnect = self._cb_on_disconnect
        return client

    def _signal_connect(self):
        # Order matters in roimanager.py.
        self._is_mqtt_disconnected.clear()
        self._is_mqtt_connected.set()

    def _signal_disconnect(self):
        # Order matters in roimanager.py.
        self._is_mqtt_connected.clear()
        self._is_mqtt_disconnected.set()

    def _cb_on_connect(self, mqtt_client, userdata, flags, rc):
        if rc == 0:
            LOG.info('MQTT connection attempt succeeded.')
            self._signal_connect()
        else:
            LOG.warning('MQTT connection attempt failed: ' +
                        mqtt.connack_string(rc))

    def _cb_on_disconnect(self, mqtt_client, userdata, rc):
        if rc == 0:
            LOG.info('Disconnection succeeded.')
        else:
            LOG.warning('Lost MQTT connection: ' + mqtt.error_string(rc))
        self._signal_disconnect()

    def _check_root_start_tag(self, message):
        if message is not None:
            parser = etree.XMLPullParser(events=('start', ))
            events = parser.read_events()
            parser.feed(message)
            for dummy_action, element in events:
                # First tag must belong to the root element.
                if element.tag == roimachine.ROI_ROOT_NAME:
                    self._is_root_start_tag_published = True
                break
        if self._is_root_start_tag_published:
            LOG.debug('Start tag of the root element has been published as a '
                      'retained message previously.')
        else:
            LOG.warning('Start tag of the root element has not been published '
                        'as a retained message previously.')

    async def _check_retained_message(self):
        message = await self._async_helper.run_in_executor(self._retriever.run)
        self._check_root_start_tag(message)

    async def _publish_root(self):
        while not self._is_root_start_tag_published:
            message = await self._queue.get()
            if message.tag == roimachine.ROI_ROOT_NAME:
                to_be_published = _serialize(message, is_root_tag=True)
                info = self._client.publish(
                    self._topic,
                    payload=to_be_published,
                    qos=self._qos,
                    retain=True)
                await self._async_helper.run_in_executor(info.wait_for_publish)
                self._is_root_start_tag_published = True
            else:
                LOG.warning('Got an element that was not a root element tag '
                            'but the root element has not yet been published. '
                            'Not going to publish the message: ' + _serialize(
                                message, is_root_tag=False))

    async def _keep_publishing(self):
        while True:
            message = await self._queue.get()
            # Let's not publish the root element tags anymore.
            if message.tag != roimachine.ROI_ROOT_NAME:
                to_be_published = _serialize(message, is_root_tag=False)
                self._client.publish(
                    self._topic,
                    payload=to_be_published,
                    qos=self._qos,
                    retain=False)

    async def run(self):
        """Run the MQTTForwarder."""
        await self._check_retained_message()
        self._client.connect_async(self._host, port=self._port)
        self._client.loop_start()
        await self._async_helper.wait_for_event(self._is_mqtt_connected)
        await self._publish_root()
        await self._keep_publishing()
        self._client.disconnect()
        await self._async_helper.wait_for_event(self._is_mqtt_disconnected)
        self._client.loop_stop()
