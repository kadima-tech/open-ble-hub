"""Bond Touch bracelet BLE protocol, read statically from the Bond Touch app.

``uuids`` names the GATT layout and ``identify`` matches advertisements and
picks the generation. ``v1``, ``v2`` (V2, V4 and Mini) and ``v3`` (Bond More)
parse what each generation sends and build what it takes. ``patterns`` holds
the millisecond touch patterns they share, and ``link`` answers the setup
handshake and sends commands over any transport. Nothing here imports a
Bluetooth stack. See docs/bond-touch-ble-protocol.md.
"""
