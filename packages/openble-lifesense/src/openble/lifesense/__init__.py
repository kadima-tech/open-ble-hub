"""Lifesense A2/A3 weight-scale protocol, as used by the Philips DL8780.

``packets`` parses weight and body-composition packets. ``link`` builds the
8A81 command frames and runs the pair and sync handshake over any transport.
``identify`` matches advertisements. Nothing here imports a Bluetooth stack.
"""
