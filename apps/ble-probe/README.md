# BLE probe

A diagnostic client for the devices the openble libraries cover. It scans, connects, reads the characteristics the protocol manuals name, and subscribes to their notifications. Scale packets are parsed with [openble-lifesense](../../packages/openble-lifesense). Toothbrush values whose byte layout is still open are printed as hex.

```
make venv
source .venv/bin/activate
python -m ble_probe scan
python -m ble_probe brush
python -m ble_probe scale
python -m ble_probe watch
```

`scale` answers the Lifesense A3 exchange on characteristic 8A81. A scale that is already paired sends a random (`0xA1`) and expects the password from the original pair. This DL8780 has already sent that password; it is in `.philips-scale.json`. Hold the measurement-unit button for 3 seconds so the scale enters pairing and sends `0xA0` when a new pair is required. The client stores the password and broadcast id in `.philips-scale.json`. Later connections answer the random with that password, write the stored broadcast id and the clock, and wait for the scale's `0xC0` before writing the profile and `0x22`. The scale then keeps the link and sends the weigh on 8A24 and 8A22. Use `watch` for this. If another app pairs the scale, pair it again from the Mac. What has and has not worked on the live scale is in [dl8780-connection-handoff.md](../../packages/openble-lifesense/docs/dl8780-connection-handoff.md). Sonicare SACP writes are still unsent. On macOS, Core Bluetooth shows its own pairing dialog when a read needs encryption.

`watch` keeps a scan running and connects at the first advertisement from the scale. It subscribes to the scale indications, answers an A3 password with the pairing queue or a random with the XOR and the clock, and leaves the link up until the scale drops it or the link has been quiet for `--idle-seconds` (default 180). It then scans again. Ctrl-C stops it. The Bluetooth symbol on the scale lights when the scale accepts that connection, and it flashes while a measurement is sent.

On macOS the device address printed by `scan` is a UUID. Pass it back with `--address` when more than one match is in range. `--out readings.jsonl` appends a JSON line per read and notification. `--seconds` is how long to keep listening after subscribe (60s for the scale, 25s for the brush).

Allow Bluetooth for the terminal in System Settings → Privacy & Security → Bluetooth. For a first pair, hold the scale's unit button for 3 seconds, then step on barefoot when the client says the handshake was sent. `--password` accepts 8 hex digits copied from an earlier pair. `--user-number` and `--user-name` are the slot written during that new pair (defaults `1` and `User`). `--age`, `--height-cm`, and `--sex` fill the Lifesense user-info frame (age 18..100, height 100..204 cm, sex `male` or `female`). The scale stores that height in metres after dividing the centimetres by 100. Leave all three off and the client sends the empty 15-byte frame.

`make scan`, `make scale` and `make watch` run the same commands inside `.venv` from the repository root; pass options with `ARGS`, for example `make watch ARGS="--out readings.jsonl"`.

## License

[MIT-0](LICENSE).
