# -*- coding: utf-8 -*-
"""Templater class."""

import string


def _get_file_content(filename):
    with open(filename, 'rt', encoding='utf-8') as handle:
        return handle.read()


class Templater:
    """Fills out ROI messages from a template file.

    The given message_id_generator should be shared across all Templaters in
    use so that the message IDs stay unique.
    """

    def __init__(self, config, message_id_generator):
        self._generator = message_id_generator
        self._template = string.Template(_get_file_content(config['filename']))
        self._mapping = config['mapping']

    def fill(self, extra_mapping=None):
        """Fill out the template.

        The dict extra_mapping overrides the config given in the initialization
        of the Templater. 'message_id' cannot be overridden.
        """
        if extra_mapping is None:
            extra_mapping = {}
        # Generate a message_id regardless whether the Template requires it.
        # This can leave holes in the sent message_id ranges. As only
        # uniqueness is required, that is okay.
        message_id_mapping = {'message_id': next(self._generator)}
        merged_mapping = {
            **self._mapping,
            **extra_mapping,
            **message_id_mapping,
        }
        return self._template.substitute(merged_mapping).encode('utf-8')
