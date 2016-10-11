# -*- coding: utf-8 -*-
"""Figure out ROI protocol state."""

import logging

from automaton import machines
from automaton import runners

from . import messenger
from . import poisonpill

LOG = logging.getLogger(__name__)

# Expected element names from the server in one place.
ROI_ROOT_NAME = '{http://www.pubtrans.com/ROI/3.0}FromPubTransMessages'
ROI_LAST_PROCESSED_NAME = 'LastProcessedMessageRequest'
ROI_SUBSCRIPTION_RESUME_RESPONSE_NAME = 'SubscriptionResumeResponse'
ROI_SUBSCRIPTION_RESPONSE_NAME = 'SubscriptionResponse'
ROI_SUBSCRIPTION_ERROR_REPORT_NAME = 'SubscriptionErrorReport'
ROI_SUBSCRIPTION_ERROR_RESPONSE_NAME = 'SubscriptionErrorResponse'


class ROIMachine:
    """Choose how to respond to the ROI server.

    The same ROIMachine object is meant to be used over several TCP
    connections. ROIMachine keeps track of whether it should attempt to resume
    an existing subscription or create a new subscription.
    """

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
                'got_remote_root_start_tag': 'subscription_choice',
                'got_unexpected_element': 'closing',
                'got_poison_pill': 'closing',
            },
        },
        {
            'name': 'subscription_choice',
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

    def __init__(self, config, async_helper, input_queue, output_queue):
        self._async_helper = async_helper
        self._input_queue = input_queue
        self._messenger = messenger.Messenger(config, output_queue)
        self._should_resume = True
        self._on_message_id = None
        self._machine = self._create_machine()

    # The functions named _react_in_* are reactions triggered by state machine
    # transitions. In ROIMachine, each such reaction corresponds with exactly
    # one state. They contain the code that should be run when in the new
    # state.

    def _react_in_own_root_tag(self, dummy_old_state, dummy_new_state,
                               dummy_event):
        self._messenger.send_own_root_start_tag()
        return 'sent_own_root_start_tag'

    def _react_in_remote_root_tag(self, dummy_old_state, dummy_new_state,
                                  dummy_event):
        received = self._input_queue.get()
        if received is poisonpill.POISON_PILL:
            LOG.debug('Received POISON_PILL.')
            return 'got_poison_pill'
        if received.tag == ROI_ROOT_NAME:
            LOG.debug('Received: ' + str(received))
            return 'got_remote_root_start_tag'
        else:
            return 'got_unexpected_element'

    def _react_in_subscription_choice(self, dummy_old_state, dummy_new_state,
                                      dummy_event):
        if self._should_resume:
            return 'chose_to_resume'
        else:
            return 'chose_to_subscribe'

    def _react_in_resuming_attempt(self, dummy_old_state, dummy_new_state,
                                   dummy_event):
        self._messenger.send_resume_subscription()
        return 'sent_resuming_element'

    def _react_in_subscribing_attempt(self, dummy_old_state, dummy_new_state,
                                      dummy_event):
        self._messenger.send_subscribe()
        return 'sent_resuming_element'

    # FIXME: Unknown when SubscriptionErrorReport or SubscriptionErrorResponse
    #        might lead to a successful resuming. We might cut off successful
    #        subscriptions.
    def _react_in_resuming_response(self, dummy_old_state, dummy_new_state,
                                    dummy_event):
        received = self._input_queue.get()
        if received is poisonpill.POISON_PILL:
            LOG.debug('Received POISON_PILL.')
            return 'got_poison_pill'
        tag = received.tag
        if tag == ROI_SUBSCRIPTION_RESUME_RESPONSE_NAME:
            LOG.info('Received: ' + str(received))
            return 'got_resuming_ok'
        if tag == ROI_LAST_PROCESSED_NAME:
            self._on_message_id = received.get('MessageId')
            LOG.debug('Received: ' + str(received))
            return 'got_last_processed_request'
        if tag == ROI_SUBSCRIPTION_ERROR_REPORT_NAME:
            LOG.warning('Received: ' + str(received))
            # "The SynchronisedUpToUtcDateTime is no longer in the production
            # plan's active interval. The Production Plan will be recovered
            # from the earliest possible time instead."
            if received.get('Code') == '122':
                return 'got_too_old_but_perhaps_resuming_ok'
            else:
                self._should_resume = False
                return 'got_resuming_failed'
        if tag == ROI_SUBSCRIPTION_ERROR_RESPONSE_NAME:
            LOG.warning('Received: ' + str(received))
            self._should_resume = False
            return 'got_resuming_failed'
        LOG.warning('Received: ' + str(received))
        return 'got_unexpected_element'

    def _react_in_subscribing_response(self, dummy_old_state, dummy_new_state,
                                       dummy_event):
        received = self._input_queue.get()
        if received is poisonpill.POISON_PILL:
            LOG.debug('Received POISON_PILL.')
            return 'got_poison_pill'
        tag = received.tag
        if tag == ROI_SUBSCRIPTION_RESPONSE_NAME:
            self._should_resume = True
            LOG.info('Received: ' + str(received))
            return 'got_subscribing_ok'
        if tag == ROI_LAST_PROCESSED_NAME:
            self._on_message_id = received.get('MessageId')
            LOG.debug('Received: ' + str(received))
            return 'got_last_processed_request'
        if (tag == ROI_SUBSCRIPTION_ERROR_REPORT_NAME or
                tag == ROI_SUBSCRIPTION_ERROR_RESPONSE_NAME):
            self._should_resume = True
            LOG.warning('Received: ' + str(received))
            return 'got_subscribing_failed'
        self._should_resume = True
        LOG.warning('Received: ' + str(received))
        return 'got_unexpected_element'

    def _react_in_last_processed(self, old_state, dummy_new_state,
                                 dummy_event):
        self._messenger.send_last_processed(self._on_message_id,
                                            self._on_message_id)
        if old_state == 'listening':
            return 'sent_lp_response_return_listening'
        if old_state == 'resuming_response':
            return 'sent_lp_response_return_resuming'
        return 'sent_lp_response_return_subscribing'

    def _react_in_listening(self, dummy_old_state, dummy_new_state,
                            dummy_event):
        received = self._input_queue.get()
        if received is poisonpill.POISON_PILL:
            LOG.debug('Received POISON_PILL.')
            return 'got_poison_pill'
        tag = received.tag
        if tag == ROI_LAST_PROCESSED_NAME:
            self._on_message_id = received.get('MessageId')
            LOG.debug('Received: ' + str(received))
            return 'got_last_processed_request'
        if tag == ROI_ROOT_NAME:
            LOG.warning('Received: ' + str(received))
            return 'got_remote_root_end_tag'
        LOG.debug('Received: ' + str(received))
        return 'got_other_element'

    def _react_in_closing(self, dummy_old_state, dummy_new_state, dummy_event):
        self._messenger.send_own_root_end_tag()
        return 'sent_own_root_end_tag'

    def _create_machine(self):
        m = machines.FiniteMachine.build(ROIMachine._ROI_STATE_SPACE)
        m.default_start_state = 'ready_to_start'
        m.add_reaction('listening', 'sent_lp_response_return_listening',
                       self._react_in_listening)
        m.add_reaction('resuming_response', 'sent_lp_response_return_resuming',
                       self._react_in_resuming_response)
        m.add_reaction('subscribing_response',
                       'sent_lp_response_return_subscribing',
                       self._react_in_subscribing_response)
        m.add_reaction('last_processed', 'got_last_processed_request',
                       self._react_in_last_processed)
        m.add_reaction('listening', 'got_other_element',
                       self._react_in_listening)
        m.add_reaction('closing', 'got_remote_root_end_tag',
                       self._react_in_closing)
        m.add_reaction('remote_root_tag', 'sent_own_root_start_tag',
                       self._react_in_remote_root_tag)
        m.add_reaction('own_root_tag', 'start', self._react_in_own_root_tag)
        m.add_reaction('subscription_choice', 'got_remote_root_start_tag',
                       self._react_in_subscription_choice)
        m.add_reaction('closing', 'got_unexpected_element',
                       self._react_in_closing)
        m.add_reaction('resuming_response', 'sent_resuming_element',
                       self._react_in_resuming_response)
        m.add_reaction('closing', 'got_resuming_failed',
                       self._react_in_closing)
        m.add_reaction('listening', 'got_resuming_ok',
                       self._react_in_listening)
        m.add_reaction('resuming_response',
                       'got_too_old_but_perhaps_resuming_ok',
                       self._react_in_resuming_response)
        m.add_reaction('subscribing_response', 'sent_subscribing_element',
                       self._react_in_subscribing_response)
        m.add_reaction('closing', 'got_subscribing_failed',
                       self._react_in_closing)
        m.add_reaction('listening', 'got_subscribing_ok',
                       self._react_in_listening)
        m.add_reaction('resuming_attempt', 'chose_to_resume',
                       self._react_in_resuming_attempt)
        m.add_reaction('subscribing_attempt', 'chose_to_subscribe',
                       self._react_in_subscribing_attempt)
        m.freeze()
        LOG.debug('ROI state machine:\n' + m.pformat())
        return m

    async def run(self):
        """Run the ROI state machine."""
        runner = runners.FiniteRunner(self._machine)
        await self._async_helper.run_in_executor(runner.run, 'start')
