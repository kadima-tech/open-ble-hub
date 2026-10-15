"""Lovense toy BLE protocol, read statically from the Lovense Remote app.

``identify`` reads the identity UUID and matches advertisements. ``commands``
builds the ASCII text commands, ``replies`` parses what the toy answers,
``frames`` builds and checks the 0xAA binary frames with their CRC-8, and
``link`` picks the GATT channels and paces writes over any transport.
Nothing here imports a Bluetooth stack. See docs/lovense-ble-protocol.md.
"""
