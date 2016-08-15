# -*- coding: utf-8 -*-

from lxml import etree


def _serialize(element, is_root_tag=False):
    if is_root_tag:
        # FIXME: Cut off end tag
        return etree.tostring(element)
    else:
        # FIXME: Remove namespaces
        return etree.tostring(element)
