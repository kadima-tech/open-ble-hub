# openble-bondtouch

The Bond Touch bracelet BLE protocol (Impossible Labs), read from the Bond Touch Android app (11.2.0).

- `openble.bondtouch.uuids`: the Bond services and characteristics, spelled out one by one because their fourth group differs, and the advertised names.
- `openble.bondtouch.identify`: matches advertisements, picks the generation from the GATT table and the `ff10` API version byte, and lists what each generation needs.
- `openble.bondtouch.v2`: V2, V4 and Mini. The `ffa4` state, `ffa5` events and touch recording, the 20-byte `ffa6` frames (`0x26` LED and motor steps, `0x33` three-LED frames, run queue) and the `0x27` config properties.
- `openble.bondtouch.v1`: the original Bond Touch. Its `[cmdId, seq, payload]` commands, `ffa7` results, 11 fixed LED colours, and gaps worked out from arrival times.
- `openble.bondtouch.v3`: Bond More. The `ffb1` commands and reports, and the `ffb2` touch frames of 50 ms samples.
- `openble.bondtouch.patterns`: the `[press, gap, …, press]` millisecond patterns every generation shares, and the conversion to V3 samples.
- `openble.bondtouch.link`: `BraceletLink` answers the token, AUID and paired-signal requests, collects touches, and sends commands one at a time with the app's pauses. On V1 it also waits for each result.

Pure Python 3.11+ with no dependencies and no Bluetooth stack. `BraceletLink` takes a `write(uuid, payload)` coroutine and is fed notifications, so it runs over bleak, a test double, or anything else.

Everything here comes from static reading of the app, checked against one live bracelet: a V2 (`Bond002`, firmware 2.6.4) over bleak on macOS. Setup (including taking over from the official app with a double-tap), colours, played patterns with vibration, and received touches work on it. V1, V3, V4 and Mini have not been run yet. The manual records what that run showed and the questions still open.

```
pip install openble-bondtouch
```

## Build frames

```python
from openble.bondtouch import v2, v3
from openble.bondtouch.identify import generation_of
from openble.bondtouch.patterns import to_samples

generation_of(b"\x44")
# 'v4'

v2.show_colour((0x23, 0xE0, 0xE8)).hex(" ")
# '26 00 00 00 00 00 01 23 e0 e8 50 00 00 00 00 00 00 ff ff 00'

v2.play_touch([400, 200, 300], (0xFF, 0, 0))  # two 0x26 steps, then 32 00 11
v3.touch_frames(to_samples([400, 200, 300]), (0xFF, 0, 0), slot=1)
```

## Drive a bracelet with bleak

```python
import asyncio

from bleak import BleakClient
from openble.bondtouch.link import BraceletLink, detect_generation, notify_uuids


async def touch(address: str, auid: int) -> None:
    async with BleakClient(address) as client:

        async def read(uuid: str) -> bytes:
            return bytes(await client.read_gatt_char(uuid))

        async def write(uuid: str, payload: bytes) -> None:
            # A V2 on 2.6.4 offers ffa6 without response only.
            char = client.services.get_characteristic(uuid)
            response = "write" in char.properties
            await client.write_gatt_char(uuid, payload, response=response)

        services = [service.uuid for service in client.services]
        generation = await detect_generation(read, services)
        link = BraceletLink(write, generation, auid, read=read)
        for uuid in notify_uuids(generation):
            await client.start_notify(uuid, lambda c, data, u=uuid: link.feed(u, data))
        await link.start()
        await link.wait_connected()
        await link.play([400, 200, 400], (0xFF, 0x44, 0xA6))
        message = await link.touches.get()  # the wearer's next touch
        print(message.pattern, message.slot)
        await link.close()
```

Pick any 32-bit AUID and keep it. A bracelet set up with another AUID, for example by the official app, reports `AUID_ERROR` (and `link.needs_setup`), goes to its out-of-box state and flashes. The app then asks the wearer to double-tap it to continue, which the link answers.

Newer firmware also asks for OS-level bonding after setup. The app triggers it by writing `v2.ancs(True)` on V2, by subscribing to `uuids.BOND_TRIGGER` on V4 and Mini, and with `createBond()` on V3 (`client.pair()` in bleak). Once bonded it writes `v2.after_bonding(generation)`.

## Choices the manual leaves open

Where the app's code did not settle a detail, this library picks one and says so in the docstring:

- `v2.play_blend` blends the colour at the start of each 200 ms frame.
- `patterns.to_samples` squeezes patterns longer than 10 s by rounding run boundaries to the nearest sample.
- `BraceletLink.clear_colour` on V1 sends colour black.
- `BraceletLink` sends V1 command `seq` from 0 after each connection.

## Protocol notes

[docs/bond-touch-ble-protocol.md](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-bondtouch/docs/bond-touch-ble-protocol.md): discovery, the GATT layout, the connection lifecycle, each generation's state, events and commands, firmware updates and the open questions.

Not affiliated with Impossible Labs. The name identifies the devices this interoperates with.

## License

[MIT License](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-bondtouch/LICENSE), copyright 2026 Kadima Tech.
