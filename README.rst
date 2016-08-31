**********
roiorbison
**********

roiorbison listens to a NOPTIS ROI XML feed and publishes nearly all received messages as such on an MQTT broker.


Description
-----------

The `ROI feed <http://transmodel-cen.eu/?page_id=351>`_ contains real-time public transit data, e.g. vehicle locations and arrival time predictions.

The ROI protocol consists of a conceptually potentially infinite XML conversation over a TCP connection.
The client starts the dialogue by sending the start tag of the client root element.
The server responds with the start tag of the server root element.
The child elements of the two root elements act as messages.
If all goes without trouble, the interaction continues indefinitely.

roiorbison reacts to the inevitable trouble by automatically reconnecting and resuming the ROI subscription.
roiorbison also publishes the messages from the ROI server to the given MQTT topic on the given MQTT broker.

To ease the parsing of the ROI-over-MQTT feed, roiorbison employs an MQTT-specific trick:
The start tag of the root element from the ROI server is published as a retained message to the MQTT topic.
All other XML elements are published as normal MQTT messages.
The retained message will get sent to the MQTT subscribers before the other messages in the MQTT topic.
The retained message will also get sent even when an MQTT client subscribes to the topic after the publication of the retained message.
Thus no matter when an MQTT client subscribes to the ROI topic, they will see a valid XML document.
The end tag of the root element is never published to ease parsing as well.


Dependencies
------------

roiorbison requires Python 3.5 and several libraries from PyPI.
lxml `requires <http://lxml.de/installation.html#requirements>`_ libxml2 and libxslt to be installed on the system, as well.


Install
-------

.. code-block:: sh

  git clone https://github.com/hsldevcom/roiorbison
  cd roiorbison
  pip install -r requirements/prod.txt
  cp config.yaml.template config.yaml
  # Change endpoints, credentials etc.
  vim config.yaml


Run
---

.. code-block:: sh

  python3 roiorbison/roiorbison.py


Develop
-------

Install development dependencies:

.. code-block:: sh

  pip-sync requirements/dev.txt

Upgrade dependencies:

.. code-block:: sh

  ./upgrade_dependencies.sh
  pip-sync requirements/dev.txt


License
-------

roiorbison is dual-licensed under AGPLv3 and EUPL v1.2.
Take your pick.
