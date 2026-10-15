# openble-lifesense

The Lifesense A2/A3 Bluetooth weight-scale protocol, as spoken by the Philips DL8780 and other scales built on the Lifesense SDK.

- `openble.lifesense.packets`: parsers for the weight (8A21, 8A24) and body-composition (8A22) packets.
- `openble.lifesense.link`: the 8A81 command frames, and the pair and sync handshake that makes the scale send a weigh.
- `openble.lifesense.identify`: matches advertisements and GATT tables to a scale.
- `openble.lifesense.uuids`: service and characteristic ids.

Pure Python 3.11+ with no dependencies and no Bluetooth stack. The handshake takes a `write` coroutine and a queue of indications, so it runs over bleak, a test double, or anything else.

```
pip install openble-lifesense
```

## Parse a weigh

```python
from openble.lifesense.packets import parse_a3_append, parse_a3_weight

weight = parse_a3_weight(
    bytes.fromhex("1f 16 26 00 fe 89 50 91 1f 00 00 00 00 17 13 00 ff 01 19 00")
)
weight["weight_kg"], weight["impedance"], weight["date"]
# ('97.5', '488.7', '2026-10-13 19:50:33')

append = parse_a3_append(
    bytes.fromhex("6d 89 50 91 1f 01 fc f0 32 f2 79 f1 26 f0 00 00 00 00 00 00")
)
append["body_fat_ratio"]
# '25.2'
```

`parse_scale_notification(short, data, family=..., previous=...)` picks the parser the Lifesense dispatcher would use for a characteristic. `identify.protocol_digit(service_uuids)` gives the `family`.

## Pair and sync with bleak

The scale sends a `0xA0` password when it is in pairing mode (hold the unit button for 3 s) and a `0xA1` random when it is already paired. `run_scale_handshake` answers either one. It stores the password and broadcast id in a `ScaleStore` JSON file, and it needs that same file for every later sync.

```python
import asyncio
from pathlib import Path

from bleak import BleakClient
from openble.lifesense.link import ScaleStore, run_scale_handshake
from openble.lifesense.packets import parse_a3_weight
from openble.lifesense.uuids import sig


async def weigh(address: str) -> None:
    commands: asyncio.Queue[bytes] = asyncio.Queue()
    async with BleakClient(address) as client:
        await client.start_notify(
            sig("8a24"), lambda _, data: print(parse_a3_weight(bytes(data)))
        )
        await client.start_notify(
            sig("8a82"), lambda _, data: commands.put_nowait(bytes(data))
        )

        async def write(payload: bytes) -> None:
            await client.write_gatt_char(sig("8a81"), payload, response=True)

        await run_scale_handshake(
            write=write,
            queue=commands,
            store=ScaleStore(Path("scale.json")),
            device_key=address,
            user_number=1,
            user_name="User",
            password_override=None,
            listen_seconds=60,
            log=lambda kind, **payload: print(payload.get("message", "")),
        )
```

`apps/ble-probe` and `apps/bathroom-hub` in the [repository](https://github.com/kadima-tech/open-ble-hub) are complete clients built this way.

## Protocol notes

- [docs/lifesense-scale-protocol.md](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-lifesense/docs/lifesense-scale-protocol.md): the static manual, read from the Philips Health app's bytecode.
- [docs/dl8780-connection-handoff.md](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-lifesense/docs/dl8780-connection-handoff.md): what worked against a live DL8780, including the HCI capture the sync sequence follows.

Not affiliated with Philips or Lifesense. The names identify the devices this interoperates with.

## License

[MIT License](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-lifesense/LICENSE), copyright 2026 Kadima Tech.
