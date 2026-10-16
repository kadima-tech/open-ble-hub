# openble-muse

The Interaxon Muse EEG headband BLE protocol, read from the Muse Android app (55.1), whose protocol library is libmuse, and from public projects (muse-js, muse-lsl, amused, OpenMuse, muse-rs).

- `openble.muse.uuids`: service `0xFE8D` and the `273eXXXX` characteristics, named as the app names them.
- `openble.muse.models`: the model from a serial number, the characteristics each model streams on, default presets and the known preset codes.
- `openble.muse.identify`: matches advertisements and reads the hardware generation from the manufacturer data.
- `openble.muse.commands`: the length-prefixed ASCII commands (`v7`, `s`, `h`, `p21`, `dc001`, …).
- `openble.muse.replies`: reassembles the chunked JSON replies and reads the version and status replies.
- `openble.muse.packets`, `universal`, `ble4`: the three data layouts, selected by the protocol version (`pv`) the headband reports. All three decode to the same `Reading`.
- `openble.muse.link`: `MuseLink` keeps one command in flight, as the app does, and `prepare` runs the app's start-up sequence.

Pure Python 3.11+ with no dependencies and no Bluetooth stack. `MuseLink` takes a `write` coroutine and is fed notifications, so it runs over bleak, a test double, or anything else.

The library is built from static reading of the app and from public work, checked against one live headband: a Muse S on firmware 1.0.1 (`pv` 1) over bleak on macOS. Discovery, the start-up sequence, streaming and halting work on it, and its accelerometer, gyro, DRL/REF and battery packets decode; the tests include those bytes. The Muse S Athena (BLE4) and universal v3 decoders are still checked only against hand-packed bytes. The manual records what the run showed and what is still open, including the BLE4 time-sync message that firmware with `pv` 5 and up may expect.

```
pip install openble-muse
```

## Layouts

| `pv` | Layout | Headbands | Module |
| --- | --- | --- | --- |
| 1–2 | Per-sensor: one characteristic per channel | Muse 2016, Muse 2, Muse S | `packets.decode(uuid, data)` |
| 3 | Universal v3: typed sub-packets on `273e0013` | early Muse S Athena firmware (inferred) | `universal.parse_frame`, `universal.reading` |
| ≥ 4 | BLE4: tagged sub-packets on `273e0013` and `273e0014` | Muse S Athena | `ble4.readings(data)` |

```python
from openble.muse import ble4, commands

commands.encode("s").hex(" ")
# '02 73 0a'

for reading in ble4.readings(notification):
    print(reading.kind, reading.channels, reading.samples)
# eeg ('TP9', 'AF7', 'AF8', 'TP10') ((…), (…), (…), (…))
```

`samples` has one row per time step and one column per channel. EEG is in microvolts, the IMU in g and degrees per second. Optics and PPG stay raw. Where the app and the public projects scale differently, `openble.muse.readings` keeps both constants.

## Stream with bleak

```python
import asyncio

from bleak import BleakClient
from openble.muse import ble4, packets, uuids
from openble.muse.link import MuseLink


async def stream(address: str, seconds: float = 10) -> None:
    async with BleakClient(address) as client:

        async def write(payload: bytes) -> None:
            await client.write_gatt_char(uuids.SERIAL, payload, response=False)

        link = MuseLink(write)
        await client.start_notify(uuids.SERIAL, lambda _, data: link.feed(data))
        session = await link.prepare()  # v7, s, h, p<preset>, s
        print(session.status.name, session.model, session.layout)

        def on_data(char, data: bytearray) -> None:
            if session.layout == "ble4":
                found = ble4.readings(data)
            else:
                found = [packets.decode(char.uuid, data)]
            for reading in found:
                print(reading)

        for uuid in session.subscribe:
            await client.start_notify(uuid, on_data)
        await link.start_streaming()  # dc001
        await asyncio.sleep(seconds)
        await link.halt()  # stop streaming before disconnecting
```

`prepare(preset)` takes a preset code such as `"21"` or `"1045"`. Without one it uses the app's default for the model: `21` for most headbands, and `1021` for the Athena. Public Athena clients use `1041`, `1034` or `1045` instead. A headband in its bootloader raises `BootloaderError`; `link.boot_to_headset()` restarts it, and you then reconnect.

## Protocol notes

[docs/muse-ble-protocol.md](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-muse/docs/muse-ble-protocol.md): models, discovery, the GATT layout, the command channel, the connection lifecycle, the three data layouts and the open questions.

Not affiliated with Interaxon. The name identifies the devices this interoperates with. Not a medical device.

## License

[MIT License](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-muse/LICENSE), copyright 2026 Kadima Tech.
