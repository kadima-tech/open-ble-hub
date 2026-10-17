"""Bathroom Hub: Philips DL8780 to Google Health bridge for a Raspberry Pi."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bathroom-hub")
except PackageNotFoundError:
    __version__ = "0+unknown"
