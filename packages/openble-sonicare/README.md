# openble-sonicare

The Philips Sonicare toothbrush GATT map, read from the Sonicare app's bytecode.

- `openble.sonicare.uuids`: the `477ea600-…` service and characteristic ids, each with the name and value kind the app uses.
- `openble.sonicare.identify`: matches advertisements to a Sonicare handle (`toothbrush`) or the second plugin family (`toothbrush-condor`).

Pure Python 3.11+ with no dependencies. Most byte layouts, and the SACP writes, are still open. The protocol manual records what is known and what is not.

```
pip install openble-sonicare
```

```python
from openble.sonicare.identify import classify
from openble.sonicare.uuids import CBT_CHARS, cbt, cbt_suffix

classify("Philips Sonicare", [cbt("0001")])
# (['toothbrush'], ['service 477ea600-…0001', 'name Philips Sonicare'])

CBT_CHARS[cbt_suffix(cbt("4050"))]
# ('handle time', 'int')
```

## Protocol notes

[docs/sonicare-toothbrush-protocol.md](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-sonicare/docs/sonicare-toothbrush-protocol.md): discovery, connect, bonding and the GATT catalog.

Not affiliated with Philips. The names identify the devices this interoperates with.

## License

[MIT License](https://github.com/kadima-tech/open-ble-hub/blob/main/packages/openble-sonicare/LICENSE), copyright 2026 Kadima Tech.
