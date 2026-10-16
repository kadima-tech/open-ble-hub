"""Interaxon Muse headband BLE protocol, read from the Muse app and public work.

``uuids`` names the GATT characteristics, ``models`` maps a serial number to
a model and its characteristics, ``identify`` matches advertisements,
``commands`` frames the ASCII commands and ``replies`` reassembles and reads
the JSON answers. The data layouts are ``packets`` (per-sensor, ``pv`` 1-2),
``universal`` (``pv`` 3) and ``ble4`` (``pv`` >= 4). ``link`` runs the
start-up sequence over any transport. Nothing here imports a Bluetooth stack.
See docs/muse-ble-protocol.md.
"""
