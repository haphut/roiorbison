# -*- coding: utf-8 -*-
"""Templater class."""

import string

from pkg_resources import resource_string


class Templater:
    """Fills out ROI messages from a template file.

    The given message_id_generator should be shared across all Templaters in
    use so that the message IDs stay unique.
    """

    def __init__(self, config, message_id_generator):
        self._generator = message_id_generator
        self._template = string.Template(resource_string(
            __name__, config['filename']).decode('utf-8'))
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
