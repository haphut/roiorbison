# -*- coding: utf-8 -*-
"""Connect and try to retrieve a retained message from an MQTT topic."""

import logging
import threading

import paho.mqtt.client as mqtt

from . import util

LOG = logging.getLogger(__name__)
PAHO_LOG = logging.getLogger("paho.mqtt.client")


class MQTTRetainedRetriever:
    """Connect and try to retrieve a retained message from an MQTT topic."""

    _LOG_MATCH = {
        mqtt.MQTT_LOG_DEBUG: logging.DEBUG,
        mqtt.MQTT_LOG_INFO: logging.INFO,
        mqtt.MQTT_LOG_NOTICE: logging.INFO,
        mqtt.MQTT_LOG_WARNING: logging.WARNING,
        mqtt.MQTT_LOG_ERR: logging.ERROR,
    }

    def __init__(self, config):
        self._retained_message = None
        self._is_message_handled = False
        self._is_retrieval_done = threading.Event()
        self._timer = None

        self._host = config['host']
        self._port = config['port']
        self._topic = config['topic']
        self._qos = config['qos']
        self._client = self._create_client(config)

        self._wait_in_seconds = util.convert_duration_to_seconds(config[
            'retained_message_wait_duration'])

    def _create_client(self, config):
        """Create an MQTT client with all the proper settings."""
        client_id = config.get('client_id', None)
        client = mqtt.Client(
            client_id=client_id, transport=config['transport'])
        client.on_connect = self._cb_on_connect
        client.on_subscribe = self._cb_on_subscribe
        client.on_message = self._cb_on_message
        client.on_unsubscribe = self._cb_on_unsubscribe
        client.on_disconnect = self._cb_on_disconnect
        client.on_log = self._cb_on_log
        tls_path = config.get('ca_certs_path', None)
        if tls_path is not None:
            client.tls_set(tls_path)
        username = config.get('username', None)
        password = config.get('password', None)
        if username is not None and password is not None:
            client.username_pw_set(username, password=password)
        return client

    def _cb_on_connect(self, mqtt_client, userdata, flags, rc):
        LOG.debug("_cb_on_connect")
        if rc == 0:
            LOG.info('MQTT connection attempt succeeded.')
            self._client.subscribe(self._topic, self._qos)
        else:
            LOG.info('MQTT connection attempt failed: ' +
                        mqtt.connack_string(rc))

    def _cb_on_subscribe(self, client, userdata, mid, granted_qos):
        LOG.debug("_cb_on_subscribe")
        if len(granted_qos) != 1:
            LOG.error('Only one topic was subscribed to but granted_qos has '
                      'value: ' + str(granted_qos))
        got_qos = granted_qos[0]
        if got_qos != self._qos:
            LOG.warning('Granted QoS for the subscription was ' + str(got_qos)
                        + '. Expected QoS ' + str(self._qos) + '.')
        if not self._is_message_handled:
            self._timer = threading.Timer(self._wait_in_seconds,
                                          self._client.unsubscribe, [self._topic])
            self._timer.start()

    def _cb_on_message(self, client, userdata, message):
        LOG.debug("_cb_on_message")
        if self._timer is not None:
            self._timer.cancel()
        if message.topic == self._topic and message.retain:
            if message.qos != self._qos:
                LOG.warning('Retained message QoS was ' + str(message.qos) +
                            '. Expected QoS ' + str(self._qos) + '.')
            self._retained_message = message.payload
        self._is_message_handled = True
        self._client.unsubscribe([self._topic])

    def _cb_on_unsubscribe(self, client, userdata, mid):
        LOG.debug("_cb_on_unsubscribe")
        self._client.disconnect()

    def _cb_on_disconnect(self, client, userdata, rc):
        LOG.debug("_cb_on_disconnect")
        if rc == 0:
            LOG.info('MQTT disconnection succeeded.')
            # We should make sure that the connection is disconnected before
            # reusing the client ID elsewhere. That is why the Event is set
            # this late.
            self._is_retrieval_done.set()
        else:
            LOG.warning('Lost MQTT connection: ' + mqtt.error_string(rc))

    def _cb_on_log(self, mqtt_client, userdata, level, buf):
        log_level = MQTTRetainedRetriever._LOG_MATCH[level]
        PAHO_LOG.log(log_level, buf)

    def run(self):
        """Connect, subscribe, wait for a message and return the message.

        This function blocks so it should be run in a separate thread.
        """
        LOG.info("Connecting to host %s port %s", self._host, self._port)
        self._client.connect_async(self._host, port=self._port)
        self._client.loop_forever()
        self._is_retrieval_done.wait()
        return self._retained_message
