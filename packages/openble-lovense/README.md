# openble-lovense

The Lovense toy BLE protocol, read from the Lovense Remote Android app (8.10.1).

- `openble.lovense.identify`: decodes the advertised identity UUID (model and PIN flag) and matches advertisements to a toy.
- `openble.lovense.commands`: the ASCII text commands (`Vibrate:10;`, `Mply:…;`, `LVS:…`), with the ranges the app enforces and the reply tags.
- `openble.lovense.replies`: parsers for `DeviceType;`, `Battery;` and `GetCap;`, and the answer to the `$01` QCode challenge.
- `openble.lovense.frames`: the `0xAA` binary frames and their CRC-8.
- `openble.lovense.link`: picks the TX and RX characteristics the way the app does, and `ToyLink` paces writes, routes notifications and answers QCode.
- `openble.lovense.models`: the model codes and function letters the app's code confirms.

Pure Python 3.11+ with no dependencies and no Bluetooth stack. `ToyLink` takes a `write` coroutine and is fed notifications, so it runs over bleak, a test double, or anything else.

Everything here comes from static reading of the app, checked against one live toy: a Lovense Max on firmware 223 over bleak on macOS. Discovery, channel selection, `DeviceType;`, `Battery;`, `GetCap;`, reply tags, `Vibrate:` and `LVS:` work on it. It answers `Mply:` and `0xAA` frames with `unkown,`; `replies.unknown_command` reads that reply. The manual records what that run showed and the questions still open.

```
pip install openble-lovense
```

## Build commands and check frames

```python
from openble.lovense import commands, frames
from openble.lovense.identify import parse_identity

parse_identity("42450001-0023-4bd4-bbd5-a6920e4c5653")
# Identity(model='be', uuid_version=35, pin_set=False)

commands.vibrate(10), commands.mply([20, -1, 5]), commands.motion("p", 3)
# (b'Vibrate:10;', b'Mply:20:-1:5;', b'Air:Level:3;')

frames.play_pattern_action(frames.PATTERN_STOP).hex(" ")
# 'aa 8a 01 00 a1'
```

## Drive a toy with bleak

```python
import asyncio

from bleak import BleakClient
from openble.lovense import commands
from openble.lovense.link import ToyLink, pick_channels


async def buzz(address: str) -> None:
    async with BleakClient(address) as client:
        channels = pick_channels(
            (service.uuid, char.uuid, char.properties)
            for service in client.services
            for char in service.characteristics
        )

        async def write(payload: bytes) -> None:
            await client.write_gatt_char(channels.tx, payload, response=False)

        link = ToyLink(write)
        for uuid in channels.rx:
            await client.start_notify(uuid, lambda _, data: link.feed(data))

        print(
            await link.device_type()
        )  # DeviceType(model='b', firmware=223, mac='D6111451517F')
        print(await link.battery())
        await link.move(commands.vibrate(10))
        await asyncio.sleep(2)
        await link.stop(["v"])  # levels persist, so stop before disconnecting
        await link.close()
```

A toy whose owner set a PIN needs ordinary OS-level bonding first; let the operating system show its passkey dialog. A `be` toy (model from `identify.identity_of`) uses fixed channels: pass `model="be"` to `pick_channels`.

## Protocol notes

[docs/lovense-ble-protocol.md](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-lovense/docs/lovense-ble-protocol.md): discovery, the GATT layout, the connection lifecycle, both wire formats, the command reference and the open questions.

Not affiliated with Lovense. The name identifies the devices this interoperates with.

## License

[MIT License](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-lovense/LICENSE), copyright 2026 Kadima Tech.
