# -*- coding: utf-8 -*-

import asyncio
import logging

from lxml import etree
from automaton import machines
from automaton import runners

import messenger
import poisonpill


LOG = logging.getLogger(__name__)


class ROIMachine:
    """Manage ROI protocol.

    The same ROIMachine object is meant to be used over several TCP connections.
    ROIMachine keeps track of whether it should attempt to resume an existing
    subscription or create a new subscription.
    """
    # Expected element names from the server in one place.
    _ROOT_NAME = '{http://www.pubtrans.com/ROI/3.0}FromPubTransMessages'
    _LAST_PROCESSED_NAME = 'LastProcessedMessageRequest'
    _SUBSCRIPTION_RESUME_RESPONSE_NAME = 'SubscriptionResumeResponse'
    _SUBSCRIPTION_RESPONSE_NAME = 'SubscriptionResponse'
    _SUBSCRIPTION_ERROR_REPORT_NAME = 'SubscriptionErrorReport'
    _SUBSCRIPTION_ERROR_RESPONSE_NAME = 'SubscriptionErrorResponse'

    _ROI_STATE_SPACE = [
        {
            'name': 'ready_to_start',
            'next_states': {
                'start': 'own_root_tag',
            },
        },
        {
            'name': 'own_root_tag',
            'next_states': {
                'sent_own_root_start_tag': 'remote_root_tag',
            },
        },
        {
            'name': 'remote_root_tag',
            'next_states': {
                'got_remote_root_start_tag': 'subscription_branching',
                'got_unexpected_element': 'closing',
                'got_poison_pill': 'closing',
            },
        },
        {
            'name': 'subscription_branching',
            'next_states': {
                'chose_to_resume': 'resuming_attempt',
                'chose_to_subscribe': 'subscribing_attempt',
            },
        },
        {
            'name': 'resuming_attempt',
            'next_states': {
                'sent_resuming_element': 'resuming_response',
            },
        },
        {
            'name': 'subscribing_attempt',
            'next_states': {
                'sent_subscribing_element': 'subscribing_response',
            },
        },
        {
            'name': 'resuming_response',
            'next_states': {
                'got_last_processed_request': 'last_processed',
                'got_resuming_ok': 'listening',
                'got_too_old_but_perhaps_resuming_ok': 'resuming_response',
                'got_resuming_failed': 'closing',
                'got_unexpected_element': 'closing',
                'got_poison_pill': 'closing',
            },
        },
        {
            'name': 'subscribing_response',
            'next_states': {
                'got_last_processed_request': 'last_processed',
                'got_subscribing_ok': 'listening',
                'got_subscribing_failed': 'closing',
                'got_unexpected_element': 'closing',
                'got_poison_pill': 'closing',
            },
        },
        {
            'name': 'last_processed',
            'next_states': {
                'sent_lp_response_return_listening': 'listening',
                'sent_lp_response_return_subscribing': 'subscribing_response',
                'sent_lp_response_return_resuming': 'resuming_response',
            },
        },
        {
            'name': 'listening',
            'next_states': {
                'got_last_processed_request': 'last_processed',
                'got_remote_root_end_tag': 'closing',
                'got_other_element': 'listening',
                'got_poison_pill': 'closing',
            },
        },
        {
            'name': 'closing',
            'next_states': {
                'sent_own_root_end_tag': 'closed'
            },
        },
        {
            'name': 'closed',
            'is_terminal': True,
        },
    ]

    def __init__(self, config, input_queue, output_queue, run_blocking):
        self._input_queue = input_queue
        self._messenger = messenger.Messenger(config, output_queue)
        self._run_blocking = run_blocking
        self._machine = self._create_machine()

    # The functions named _react_in_* are reactions triggered by state machine
    # transitions. In ROIMachine, each such reaction corresponds with exactly
    # one state. They contain the code that should be run when in the new state.

    def _react_in_own_root_tag(self, unused_old_state, unused_new_state, unused_event):
        self._messenger.send_own_root_start_tag()
        return 'sent_own_root_start_tag'

    def _react_in_remote_root_tag(self, unused_old_state, unused_new_state, unused_event):
        received = self._input_queue.get()
        if received is poisonpill.PoisonPill:
            LOG.debug('Received PoisonPill.')
            return 'got_poison_pill'
        if received.tag == ROIMachine._ROOT_NAME:
            LOG.debug('Received: ' + received)
            return 'got_remote_root_start_tag'
        else:
            return 'got_unexpected_element'

    def _react_in_subscription_branching(self, unused_old_state, unused_new_state, unused_event):
        if self._should_resume:
            return 'chose_to_resume'
        else:
            return 'chose_to_subscribe'

    def _react_in_resuming_attempt(self, unused_old_state, unused_new_state, unused_event):
        self._messenger.send_resume_subscription()
        return 'sent_resuming_element'

    def _react_in_subscribing_attempt(self, unused_old_state, unused_new_state, unused_event):
        self._messenger.send_subscribe()
        return 'sent_resuming_element'

    # FIXME: Unknown when SubscriptionErrorReport or SubscriptionErrorResponse
    #        might lead to a successful resuming. We might cut off successful
    #        subscriptions.
    def _react_in_resuming_response(self, unused_old_state, unused_new_state, unused_event):
        received = self._input_queue.get()
        if received is poisonpill.PoisonPill:
            LOG.debug('Received PoisonPill.')
            return 'got_poison_pill'
        tag = received.tag
        if tag == ROIMachine._SUBSCRIPTION_RESUME_RESPONSE_NAME:
            LOG.info('Received: ' + received)
            return 'got_resuming_ok'
        if tag == ROIMachine._LAST_PROCESSED_NAME:
            self._on_message_id = received.get('MessageId')
            LOG.debug('Received: ' + received)
            return 'got_last_processed_request'
        if tag == ROIMachine._SUBSCRIPTION_ERROR_REPORT_NAME:
            LOG.warn('Received: ' + received)
            # "The SynchronisedUpToUtcDateTime is no longer in the production
            # plan's active interval. The Production Plan will be recovered from
            # the earliest possible time instead."
            if received.get('Code') == '122':
                return 'got_too_old_but_perhaps_resuming_ok'
            else:
                self._should_resume = False
                return 'got_resuming_failed'
        if tag == ROIMachine._SUBSCRIPTION_ERROR_RESPONSE_NAME:
            LOG.warn('Received: ' + received)
            self._should_resume = False
            return 'got_resuming_failed'
        LOG.warn('Received: ' + received)
        return 'got_unexpected_element'

    def _react_in_subscribing_response(self, unused_old_state, unused_new_state, unused_event):
        received = self._input_queue.get()
        if received is poisonpill.PoisonPill:
            LOG.debug('Received PoisonPill.')
            return 'got_poison_pill'
        tag = received.tag
        if tag == ROIMachine._SUBSCRIPTION_RESPONSE_NAME:
            self._should_resume = True
            LOG.info('Received: ' + received)
            return 'got_subscribing_ok'
        if tag == ROIMachine._LAST_PROCESSED_NAME:
            self._on_message_id = received.get('MessageId')
            LOG.debug('Received: ' + received)
            return 'got_last_processed_request'
        if tag == ROIMachine._SUBSCRIPTION_ERROR_REPORT_NAME or tag == ROIMachine._SUBSCRIPTION_ERROR_RESPONSE_NAME:
            self._should_resume = True
            LOG.warn('Received: ' + received)
            return 'got_subscribing_failed'
        self._should_resume = True
        LOG.warn('Received: ' + received)
        return 'got_unexpected_element'

    def _react_in_last_processed(self, old_state, unused_new_state, unused_event):
        self._messenger.send_last_processed(self._on_message_id, self._on_message_id)
        if old_state == 'listening':
            return 'sent_lp_response_return_listening'
        if old_state == 'resuming_response':
            return 'sent_lp_response_return_resuming'
        return 'sent_lp_response_return_subscribing'

    def _react_in_listening(self, unused_old_state, unused_new_state, unused_event):
        received = self._input_queue.get()
        if received is poisonpill.PoisonPill:
            LOG.debug('Received PoisonPill.')
            return 'got_poison_pill'
        tag = received.tag
        if tag == ROIMachine._LAST_PROCESSED_NAME:
            self._on_message_id = received.get('MessageId')
            LOG.debug('Received: ' + received)
            return 'got_last_processed_request'
        if tag == ROIMachine._REMOTE_ROOT_START_TAG_NAME:
            LOG.warn('Received: ' + received)
            return 'got_remote_root_end_tag'
        LOG.debug('Received: ' + received)
        return 'got_other_element'

    def _react_in_closing(self, unused_old_state, unused_new_state, unused_event):
        self._messenger.send_own_root_end_tag()
        return 'sent_own_root_end_tag'

    def _create_machine(self):
        m = machines.FiniteMachine.build(ROIMachine._ROI_STATE_SPACE)
        m.default_start_state = 'ready_to_start'
        m.add_reaction('listening', 'sent_lp_response_return_listening', self._react_in_listening)
        m.add_reaction('resuming_response', 'sent_lp_response_return_resuming', self._react_in_resuming_response)
        m.add_reaction('subscribing_response', 'sent_lp_response_return_subscribing', self._react_in_subscribing_response)
        m.add_reaction('last_processed', 'got_last_processed_request', self._react_in_last_processed)
        m.add_reaction('listening', 'got_other_element', self._react_in_listening)
        m.add_reaction('closing', 'got_remote_root_end_tag', self._react_in_closing)
        m.add_reaction('remote_root_tag', 'sent_own_root_start_tag', self._react_in_remote_root_tag)
        m.add_reaction('own_root_tag', 'start', self._react_in_own_root_tag)
        m.add_reaction('subscription_branching', 'got_remote_root_start_tag', self._react_in_subscription_branching)
        m.add_reaction('closing', 'got_unexpected_element', self._react_in_closing)
        m.add_reaction('resuming_response', 'sent_resuming_element', self._react_in_resuming_response)
        m.add_reaction('closing', 'got_resuming_failed', self._react_in_closing)
        m.add_reaction('listening', 'got_resuming_ok', self._react_in_listening)
        m.add_reaction('resuming_response', 'got_too_old_but_perhaps_resuming_ok', self._react_in_resuming_response)
        m.add_reaction('subscribing_response', 'sent_subscribing_element', self._react_in_subscribing_response)
        m.add_reaction('closing', 'got_subscribing_failed', self._react_in_closing)
        m.add_reaction('listening', 'got_subscribing_ok', self._react_in_listening)
        m.add_reaction('resuming_attempt', 'chose_to_resume', self._react_in_resuming_attempt)
        m.add_reaction('subscribing_attempt', 'chose_to_subscribe', self._react_in_subscribing_attempt)
        m.freeze()
        LOG.debug('ROI state machine:\n' + m.pformat())
        return m

    async def run(self):
        runner = runners.FiniteRunner(self._machine)
        await self._run_blocking(runner.run('start'))


if __name__ == "__main__":
    from unittest.mock import MagicMock
    loop = asyncio.get_event_loop()
    config = MagicMock()
    input_queue = MagicMock()
    output_queue = MagicMock()
    logging.basicConfig(level=logging.DEBUG)
    r = ROIMachine(config, input_queue, output_queue, print)
