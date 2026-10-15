# Lovense BLE protocol

Static protocol notes for Lovense toys, read from the Lovense Remote Android app. There is no `openble-lovense` library yet; when one is added, this manual moves to its `docs/` folder.

This is interoperability documentation of a local app binary. It is not a capture from a live toy.

## Overview

Lovense toys are plain BLE GATT peripherals that take ASCII text commands such as `Vibrate:10;` on one writable characteristic and answer as notifications. There is no app-level authentication or encryption. A toy with an owner-set PIN flags it in its advertisement and needs ordinary OS-level BLE bonding (passkey) first. A smaller set of newer devices also sends binary frames that start with byte `0xAA`.

| Item | Value |
| --- | --- |
| Source artifact | Lovense Remote 8.10.1 (APKPure XAPK), base split `com.lovense.wear.apk` |
| Base APK SHA-256 | `1ffc6e90ac9a23adabacda20558b53e76909f2fc8b879d220a34a70288754020` |
| Code size | 10 dex files, 40,424 classes (JADX 0.7.1 provider via REA 6.4.0) |
| BLE stack | In-house `com.component.dxbluetooth.lib` over Android `BluetoothGatt`; toy layer in `com.component.dxtoy` |
| Native code | Not used for BLE (Unity, Agora, FFmpeg and Vosk libraries only) |

**Method.** I ran static analysis only. REA (`inspect-android-package`, `search-android-classes`, `inspect-android-method`) gave the package identity and method decompilations. A full `jadx` 1.5.6 decompile was used for bulk reading. Nothing was observed at runtime: timings and formats are what the code does, not captured traffic. Names like `i5.b` are obfuscated class names in this build and will change in other versions.

**Evidence key.** "Observed" means the behaviour is read directly from decompiled code, with its class cited. "Inferred" means it was reasoned from code but not proven. Open items are listed at the end.

**Scope.** This manual targets interoperability: talking to toys you own from an open-source client. It does not cover the Lovense cloud, accounts, Wi-Fi provisioning or firmware updates, except where those share the BLE link.

## Discovery and advertising

A scan result counts as a Lovense toy if its advertisement carries a 128-bit service UUID ending in `-BBD5-A6920E4C5653`, or failing that, if its name starts with `lvs` (case-insensitive). Names starting `dfu` or `new` are toys in bootloader/update mode. Observed in `com.component.dxtoy.core.bluetooth.dx.c` (ToyBtDXManager) and `r9.b` (UuidDeviceUtils).

### Identity UUID

The advertised UUID encodes model, firmware and PIN state:

```
XX YY 00 PP - VVVV - 4BD4 - BBD5 - A6920E4C5653
│  │     │     │
│  │     │     └ firmware version, 16-bit hex (e.g. 0023 = 35)
│  │     └ PP = 01: no PIN set,  PP = 11: owner PIN set
│  └ ASCII of 2nd model letter, or 0x30 ('0') if the code is one letter
└ ASCII of 1st model letter
```

- Model code = `chr(XX)` + (`chr(YY)` unless it is `'0'`). Example: `42450001-0023-…` → `BE`, version 35, no PIN.
- Firmware version = `int(VVVV, 16)` (chars 9–13 of the UUID string). The app prefers a version learned from the toy if it has one.
- PIN flag: `r9.b.c()` treats a first group ending `11` as "PIN set". The app uses that to show the lock icon and start the PIN flow.
- From these the app builds a display name `LVS-<code><version>` and a device-type string `<code>:<version>:<MAC without colons>;`. The second is the same shape the toy returns for `DeviceType;`.

### Parsing the advertisement

`r9.b.g()` walks the raw scan record as length/type/value AD structures:

| AD type | Handling |
| --- | --- |
| `0x02`, `0x03` (16-bit UUID lists) | Each 2 bytes read little-endian into a Bluetooth base UUID |
| `0x06`, `0x07` (128-bit UUID lists) | Each 16 bytes read as two **little-endian 64-bit words**, the first taken as the most-significant half |
| anything else | skipped |

Inferred: that 128-bit decode is not the standard full 16-byte reversal. Either toys put the two halves on air in that order, or the parse only works for some firmware and the `LVS-` name fallback covers the rest. A client should try both byte orders and accept whichever one ends in `BBD5-A6920E4C5653`.

### Other advertised services

These UUIDs show up in the app but belong to firmware update or Wi-Fi setup, not toy control:

| UUID | Use |
| --- | --- |
| `6C6F7665-6E73-656F-7461-0001…0004 6471736A` ("lovenseota") | ESP32-C6 OTA service and characteristics |
| `0000FF12/FF14/FF15-0000-1000-8000-00805F9B34FB` | Bluetrum chip OTA |
| `1775244D-…` and `1775FF4F…FF58-6B43-439B-877C-060F2D9BED07` | ESP Wi-Fi provisioning for Wi-Fi-capable toys |
| Nordic DFU | Nordic bootloader (`dfu…` names) |

## GATT layout

The app does not hard-code a control UUID for most toys. It picks the channels by characteristic properties after service discovery. Observed in `i5.b` (ToyBleCharacter), methods `a`, `c`, `d`, `h`, `j`.

| Role | Selection rule (generic toys) | Selection rule (pinned model, `k9.b.c.f51075i`) |
| --- | --- | --- |
| Command write (TX) | **Last** characteristic in discovery order, across all services, with `PROPERTY_WRITE` (0x08) | Exactly service `42450001-0023-4bd4-bbd5-a6920e4c5653`, characteristic `42450002-…`. If it shows up more than once, the selection fails |
| Responses (RX) | **Every** characteristic with `PROPERTY_NOTIFY` (0x10) is subscribed | Only `42450003-0023-4bd4-bbd5-a6920e4c5653` |
| CCCD | `0x2902`, written `01 00` (notifications, not indications) | same |

Characteristics that only support write-without-response (0x04) are logged but never picked as the command channel.

Inferred: the pinned UUIDs follow the Lovense identity UUID shape. The same pattern probably holds for other models: service `…0001`, TX `…0002`, RX `…0003`, with the toy's own model and version bytes. A client that copies the app's property-based rule does not need that assumption.

### Write types

Two write paths reach `BleWorker` (`com.component.dxbluetooth.lib.connect.e`):

| Command kind | Queue path | GATT write type | Used for |
| --- | --- | --- | --- |
| Normal text command | `t9.c.b` → `i5.b.o` → op 7 | `WRITE_TYPE_NO_RESPONSE` (1), method `Q` | Almost all ASCII commands (`Vibrate:10;`, `Battery;`, …) |
| "Long" text command | `t9.c.d` → `i5.b.k` → op 6 | `WRITE_TYPE_DEFAULT` (2, with response), method `P` | Commands flagged `isLongCommand` that are not AA frames |
| AA binary frame | `t9.c.c` → `i5.b.q` → op 7 | `WRITE_TYPE_NO_RESPONSE` (1) | `0xAA` frames, hex-decoded first |
| `LVS:` / `FLVS:` / `HLVS:` | hex-decoded → op 7 | `WRITE_TYPE_NO_RESPONSE` (1) | Raw-bytes-in-text commands |

Observed in `com.component.dxtoy.core.commandcore.queue.b.d()` and `t9.c`. Even without response, the library waits for `onCharacteristicWrite`, or 80 ms when `wait_callback` is false, before sending the next write.

All four paths write to the same characteristic, the one chosen by the WRITE-property rule above. Only the with-response path checks that property again before writing.

### Notifications

Incoming values go to `i5.c$b.c()`. If byte 0 is `0xAA`, the payload is handled as a binary frame (logged as hex). Anything else is decoded as UTF-8 text. Both then go to the command dispatcher `t9.a`.

### Generic BLE settings

| Setting | Toy layer value | Library default | Source |
| --- | --- | --- | --- |
| Connect timeout | 10000 ms | 3000 ms | `base/bluetooth/f.j()`, `BleConnectConfigBean` |
| Connect retries | 0 | 2 | same |
| Service discovery timeout | 5000 ms | 3000 ms | same |
| Service discovery retries | 0 | 2 | same |
| `connectGatt` | `autoConnect=false`, `TRANSPORT_LE` |  | `BleWorker` |
| MTU request | none (23-byte ATT MTU, 20-byte payload) |  | only ESP32-C6 OTA requests 517 |
| GATT cache | cleared with hidden `BluetoothGatt.refresh()` on disconnect |  | `BleWorker.E` |

## Connection lifecycle

A toy with its PIN off accepts commands as soon as the notification CCCD write succeeds. Everything after that is the app gathering information. Observed on the app side; toy firmware behaviour is not verified.

| # | Step | App action | Toy response | Timeout / timing | Source |
| --- | --- | --- | --- | --- | --- |
| 1 | Scan | Legacy `startLeScan`, no filters or settings. Windows of 10 s, restarted 500 ms after each stop. A 6th start within 30 s fails `SEARCH_TOO_FAST` | Advertisement (see Discovery) | 10 s window | `n3.f`, `n3.b` |
| 2 | Bond check | PIN flag off but the phone is still bonded → hidden `removeBond()`. If that fails, the app skips the toy | — | — | `business/c.java` (`BtAppBusinessUtils.i`) |
| 3 | Connect | `connectGatt(autoConnect=false, TRANSPORT_LE)` | `STATE_CONNECTED`, status 0 | 10 s, no retry | `base/bluetooth/f.j()`, `BleWorker` |
| 4 | Discover services | Starts 300 ms after connect. No MTU request | Service list | 5 s, no retry | `request/d.java` |
| 5 | Pick channels | TX = last WRITE characteristic; `be` uses `42450002` (see GATT layout) | — | No writable characteristic → `SERVICE_EXCEPTION` | `i5.b.a/h` |
| 6 | Firmware-issue check | Asks the Lovense server whether this toy needs a forced fix. If yes, all commands are blocked locally and an update prompt is shown | — | — | `cp.h` (hook `p9.a.d`) |
| 7 | Enable notifications | For each NOTIFY characteristic (only `42450003` for `be`): `setCharacteristicNotification(true)`, then CCCD `0x2902` = `01 00` | Write success | 30 s request timeout | `i5.b.c/d`, `BleWorker.M` |
| 8 | Connected | CCCD success → state `CONNECT_SUC`. The app's interceptor allows only `DeviceType;` before this point | — | Starts a 10 s DeviceType watchdog | `i5.c`, `w9.a` |
| 9 | Handshake | Sent in parallel by event subscribers, so order is not fixed: `DeviceType;`, `Battery;`, `GetCap;`, `AutoTime;`, plus `GetParts;` and `GetPoint;` on some models | `s:35:0082059AD3BD;`, `85;`, `CAP:…`, `AutoTime:<n>;`, … | No device type after 10 s → `DEVICE_TYPE_ERROR`. DeviceType resent after 1 s if empty | `m7.c`, `k7.a`, `u6.a`, `t5.b`, `x7.a`, `g8.a` |
| 10 | After DeviceType | Server bind check (`POST /toy/checkAndBindV2`; 401/402/403 → app disconnects). May switch to Coded PHY (`setPreferredPhy(4,4,0)`) for long range. A toy known only by name is disconnected after its reply (probe) | — | — | `yp.f`, `dp.b`, `r5.a` |
| 11 | Steady state | Commands through the queue (see Message framing) | Notifications | — | `queue/b.java` |
| 12 | Polling | `Battery;` every 10 s (3 s if a toy reports 0 %), throttled per toy to 3, 10 or 30 s by level. `readRemoteRssi` every 10 s. No keepalive | `NN;` | — | `k7.a`, `toyinfo/rssi/a.java` |
| 13 | Disconnect | Cancel queued requests, `disconnect()`, hidden `refresh()`, `close()` | — | — | `connect/b.e()`, `BleWorker.i/E` |

### DeviceType reply

Format `<code>:<firmware>:<MAC>;`, matching `^\w+:\d+:[A-Za-z0-9]{12};?$`. The code is lower-cased by the app and indexes the device catalogue. The MAC (12 hex digits, no colons) is only compared with the expected one. On a mismatch the app raises an event and asks again.

### Authentication and pairing

| Mechanism | What it is | Needed by a third-party client? |
| --- | --- | --- |
| Toy PIN | Standard BLE SMP bonding with a passkey in the OS dialog. The app never calls `createBond`; it only watches bond state (`BONDING→NONE` = wrong PIN). Managed with `GetPinS;`, `GetPinC;`, `SetPinStatus:<x>;`, `SetPinCode:<x>;`, `SetPinS:<x>;`, `SetPinC:<x>;` | Only if the PIN is on. Let the OS bond, then connect normally |
| Bind | HTTP check of the toy against the user's Lovense account | No. It is app policy, not BLE |
| QCode | Toy sends `$01` + 16 hex digits + `;`. App answers with an XOR transform (see Message framing) | Recommended. What happens without a reply is unknown |
| Wi-Fi management auth | Server-signed ECDSA token inside AA command `0x93` | Only for Wi-Fi slot management |

### Reconnection (app policy)

- Every 2 s while auto-connect is on, the app picks the selected, disconnected toy with the highest priority and the oldest attempt.
- It reconnects by scanning first, then connecting when the toy shows up.
- It retries up to 10 times, waiting `(attempt + 4) × 1 s` between tries (4 s, 5 s, 6 s, …). Each attempt times out after 15 s.
- The counter resets on a successful connection.

## Message framing

The link carries three wire formats on the same TX characteristic. A client tells inbound ones apart by the first byte: `0xAA` means a binary frame, anything else is ASCII text.

### 1. ASCII text commands (all toys)

```
<Name>[:<arg>[:<arg>…]];
```

- UTF-8/ASCII, colon-separated arguments, always ending in `;`. No length prefix, checksum or encryption.
- One command per GATT write. No MTU is negotiated, so keep a command within 20 bytes. The app does no chunking.
- Replies are notifications in the same style, for example `85;` or `s:35:0082059AD3BD;`. Reply tags: for non-motion ("NORMAL") commands the app inserts `,<tag>` before the final `;`. The tag is either one raw byte that cycles 1…127 per toy, skipping `0x00`, `\n`, space, `,`, `:` and `;`, or a fixed string such as `gb` in `GetBatch,gb;`. No tag is added if the result would exceed 20 bytes, or to motion commands. The app strips a matching tag from replies (`y9.h`). Inferred: the firmware echoes the tag. Untagged commands work, since the app itself sends `DeviceType;` and `Battery;` without one.
- Unknown commands come back as `unkown,<Cmd>` (typo as in the code, seen for `GetCap`).

### 2. AA binary frames (newer toys, selected features)

The app calls these "long commands" or "CmdAA". There is no encryption, only a CRC-8.

```
Request  (app → toy):  AA | CMD | LEN | PAYLOAD[LEN]          | CRC8
Response (toy → app):  AA | CMD | STATUS | LEN | PARAMS[LEN] | CRC8   (total = LEN + 5)
```

- The CRC covers every byte before it, including `0xAA`. Multi-byte fields are little-endian unless stated otherwise.
- At most 248 bytes follow `0xAA`. Sent as write-without-response in one write, with no fragmentation. Each notification must hold a whole frame.
- Replies are matched by the echoed `CMD`, and for `0x30`/`0x70`/`0x8E`/`0x93` also by the echoed sub-command byte. There are no sequence numbers.
- Source: builder `command/code/a.java`, parser `t6.a`, CRC `com.component.dxtoy.utils.b` ("Crc8Utils").

CRC-8 (`poly=0xB1` reflected, `init=0x00`, `refin/refout=true`, `xorout=0x35`; check("123456789") = `0xD4`):

```python
def crc8(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0x8D if c & 1 else c >> 1
    return c ^ 0x35
```

I checked this against the decompiled bit-reversing Java version. Example frames: `AA 8B 00 70` (read pattern status), `AA 8A 01 00 A1` (pattern stop), `AA 93 01 00 05` (Wi-Fi status).

| STATUS | Meaning |
| --- | --- |
| `0x00` | Success |
| `0x01` / `0x02` / `0x03` | Bad command / bad parameter / command not supported |
| `0x04` | CRC error |
| `0x05` | Flash write error |
| `0x20`–`0x22`, `0x2F` | Funscript queue full / needs more data / empty / unknown |
| `0x30` | Queue empty |
| `0x80` | Unknown |

The AA command IDs are in Command reference.

### 3. Raw bytes inside text: `LVS:`, `FLVS:`, `HLVS:`

The prefix, then raw bytes, then `;`, padded with `0xFF` to exactly one 20-byte write (`command/code/y1`, `b0`, `w1`). These are not `0xAA` frames.

### QCode challenge

A toy may send, unprompted, a 20-character notification `$01` + 16 hex digits + `;`. The app answers 200 ms later with a write-without-response (`s7.b`, `r9.a.f`):

```python
def qcode_reply(s: str) -> str:            # s == "$01" + 16 hex + ";"
    a, b, c, d = (int(s[i:i+2], 16) for i in (3, 5, 7, 9))
    rest = s[11:]                         # 8 hex digits + ";"
    sb = lambda x: x - 256 if x > 127 else x            # Java signed byte
    k = sb((c ^ sb((c * d) & 0xFF) ^ sb((c + d) & 0xFF) ^ d) & 0xFF)
    jhex = lambda x: format(x & 0xFFFFFFFF, "x")       # Integer.toHexString
    return ("$01" + jhex(sb(a) ^ k) + jhex(sb(b) ^ k) + "0000" + rest).upper()
```

The app's hex step does not zero-pad, and it sign-extends negative values to `FFFFFFxx`. So the reply length varies. Copy this exactly to match the app; whether the toy accepts a "clean" two-digit form is untested.

## Command reference

Motion commands take a level from 0 (stop) to 20 unless stated. The app refuses out-of-range values before sending. Command constants are in `com.component.dxtoy.core.commandcore.constant.b` (motion) and `…constant.e` (everything else). Builders are in `com.component.dxtoy.command.code`.

### Info and housekeeping

| Command | Arguments | Reply | Notes |
| --- | --- | --- | --- |
| `DeviceType;` | — | `<code>:<fw>:<MAC12>;` | Identity. See Connection lifecycle |
| `Battery;` | — | `<percent>;` e.g. `85;`; sometimes `s<n>;` | Meaning of the `s` form is unknown |
| `GetCap;` | — | Binary, see below; `unkown,GetCap` if unsupported | Newer firmware only |
| `GetBatch,gb;` | — | `<batch>,gb;` | Production batch string |
| `DeviceInfo;` | — | `info:<a>:<b>:…;` |  |
| `GetParts;` | — | `Parts:<n>;` | Only some models |
| `PowerOff;` | — | `POWEROFF…` | Turns the toy off |
| `CN:<name>;` | 1–12 chars `[0-9A-Za-z_ ]`; must not contain `dfu`, `new`, `lvs` | `OK…,cn;` | Rename the BLE name |
| `RstName;` | — | `OK…,rn;` | Restore the default name |
| `GetTx;` / `SetTx:<0..100>;` |  | `Tx:<n>;` | Radio TX power |
| `SilentM:<0\|1>;` |  | `OK,sm;` | Silent mode |
| `AutoTime;` / `AutoTime:<0..36000>;` |  | `AutoTime:<n>;` | Auto power-off time |
| `AutoSwith:<On\|Off>:<On\|Off>;` / `GetAS;` |  | `AutoSwith:<a>:<b>;` | Spelling as in firmware |
| `Light:on;` / `Light:off;` / `GetLight;` |  | `Light:<1\|0>;` | Status LED |
| `ALight:On;` / `ALight:Off;` / `GetAlight;` |  | `ALight:<1\|0>;` | Ambient light |
| `GetPinS;` `GetPinC;` `SetPinStatus:<x>;` `SetPinCode:<6 digits>;` `SetPinS:<x>;` `SetPinC:<x>;` |  |  | PIN management (newer firmware uses `SetPinCode`) |
| `DFU;` | — | — | Reboots into the bootloader. Do not send casually |

`GetCap` reply layout: bytes 0–3 = `CAP:`. Byte 4 = feature bits (b0 program, b1 feedback, b2 long commands, b3 PIN, b4 rename, b5 LED, b6 silent update). Byte 8 = channel count. Bytes 9 to n−2 = one ASCII function letter per channel (`v r s p t f d o q m b c`; `z` = colour). Bytes 5–7 are unknown. Source `u6.a`, `ToyLvsInfoBean.parseLvsData`.

### Motion control

These are sent untagged and without response, with the queue's dedup applied (see Implementation notes). Send level 0 to stop.

| Command | Range | Function letter | Notes |
| --- | --- | --- | --- |
| `Vibrate:<n>;` | 0–20 | `v` | All motors |
| `Vibrate1:<n>;` `Vibrate2:<n>;` `Vibrate3:<n>;` | 0–20 | `v1` `v2` `v3` | Per motor. Some models swap 1 and 2 (server config) |
| `Rotate:<n>;` | 0–20 | `r` |  |
| `Rotate:True:<n>;` / `Rotate:False:<n>;` | 0–20 | `rl` / `rr` | Rotate with explicit direction |
| `RotateChange;` | — |  | Reverse direction. Never deduplicated |
| `Air:Level:<n>;` | **0–3** | `p` | Air pump |
| `Air:In:<n>;` / `Air:Out:<n>;` | 1–3 | `p` |  |
| `Thrusting:<n>;` | 0–20 | `t` |  |
| `suck:<n>;` | 0–20 | `s` | Lowercase. Some models get `Vibrate:` instead |
| `Finger:<n>;` | 0–20 | `f` |  |
| `Depth:<n>;` | **0–3** | `d` | App maps UI 0–20 → 0 / 1–7 / 8–14 / 15+ |
| `Slap:<n>;` | 0–20 | `o` | Used for "oscillate" |
| `Bumping:<n>;` | 0–20 | `q` |  |
| `Squirt:<n>;` | 0–20 | `m` |  |
| `FSetSite:<n>;` or `SetPoint:<n>;` | 0–100 | `pos` | Stroke position. `SetPoint` on Solace Pro "pos2" firmware |
| `SetStroke:<min>:<max>;` | min 0–80, max 20–100, max−min ≥ 20 |  | Reply `OK,ss;` |
| `GetStroke;` / `GetSite;` / `GetPoint;` |  |  | `stroke:a,b;` / `site:a:b;` / `point:…` |
| `VibAir:<n>;` | 0–3 |  |  |
| `VibRotate:<n>;` | 0–20 |  |  |
| `AVibrate:<lvl>:<t>;` (`AVibrate1`, `AVibrate2`, `ARotate`, `AAirLevel` 0–3, `ASquirt`) | level as above, t 0–300 |  | Timed variants. Unit of `t` not stated (seconds inferred) |
| `AirLoop:<a>:<b>;` / `AirNLoop:<a>:<b>;` | 10–7510 each | `p` | Unit not stated (ms inferred) |

### Combined (multi-channel) commands

The app tries these in order: `LVS:`, then `Mply:`, then `Multiply:`, then single commands (`f9.a`). Which ones a toy takes comes from `GetCap` (LVS) or the server config (`supportMultiply`).

| Command | Format | Notes |
| --- | --- | --- |
| `Mply:<v1>:…:<vN>;` | One value per function group, N ≤ 5. `-1` = leave unchanged | Air (`p`) groups 0–3, others 0–20 |
| `Multiply:<v1>:…;` | Same, N ≤ 3 | Older variant |
| `LVS:` + bytes + `;` | One byte per channel in `GetCap` order, padded with `0xFF` to 20 bytes. Rotate is sign-magnitude (bit 7 = direction). All `0x00`/`0xFF` = stop | Max 15 channel bytes |
| `FLVS:` / `HLVS:` + bytes + `;` | Values ×5, max 14 bytes | Only `ba`/`be` toys with a special app build; FLVS for fw ≤ 67, else HLVS |

### Patterns and storage (text)

| Command | Arguments | Reply |
| --- | --- | --- |
| `Preset:<0..10>;` | Built-in pattern number, 0 = stop | — |
| `Pat:<n>;` | 0–20 | — |
| `SetPat:<a>:<b>;` / `GetPat,gp;` | a 1–3, b 0–20 | `OK…,sp;` / `<n>,gp;` |
| `GetPatten;` / `GetPatten:<0..9>;` |  | `P:<names>;` / pattern data |
| `Pl<idx>:<a>/<b>:<digits>;` | idx 0–9, up to 500 digits 0–9 | Upload a stored pattern. Length handling over 20 bytes is unresolved |
| `Ps:<0..9>:<digits>;` / `Remove:<0..9>;` / `Pattern:Clear;` |  | `Remove` replies `…b,rp;` |
| `Space:All;` / `Space:Free;` / `Space:Clear;` |  | `<n>b,sa;` / `,sf;` / `,sc;` |

### Sensors and feedback (text)

| Command | Arguments | Reply |
| --- | --- | --- |
| `Contact:<sub>[:<arg>];` | sub 1–10 (1 set mode, 2 get mode, 3 clear, 4 auto-calibrate, 5 get sensor, 6 sensitivity, 7 vibration mode, 8 manual calibrate) | `Contact:<sub>:<v>;` or `OK,ct<sub>;` |
| `Pressure:<sub>[:<arg>];` | sub 1–5 | `Pressure:2:…` or `OK,ps<n>;` |
| `TouchMode:…;`, `SetTouchL/V:…;` |  | Feedback then arrives as AA `0x70` frames |

Other constants found but not traced in detail: wash/squirt (`WashMode`, `WashTime 5..15`, `SquirtT 1..20`, unsolicited `LowLiquid;`, `LoadFail;`), LED colour (`GetColor`, `SetColor`, `LRGB`, `SetBnsG`), heat (`Heat`, `HeatS`), alarm (`AI`, `AIW`, …), `Notify:On/Off` (unsolicited `Evt:`), `TravelLock`, `Level:<1..5>;`, `GetLevel,gl;`, `SetLevel:<1..5>:<0..20>;`. Unsolicited toy messages include `BLOCKED`, `RtL:`, `CurVib:`, `M:S`.

Not present in this build: `Status:`, `Sync`, `Function:`, `Name:`, `Test`, or ID-prefixed commands.

### AA binary commands

| ID | Name | Direction | Payload |
| --- | --- | --- | --- |
| `0x30` | LIGHT\_RGB | both | `sub` first: 1 set colour DB, 2 get colour DB, 3 set app light level, 4 get app light level, 5/6 set/get live-reward level, 7–9 reset. Set level: `03, nLevels, nLeds, {index, led[nLeds], mode, freq}*` |
| `0x70` | FEEDBACK\_EVT | toy → app | `sub`: 1 notify on, 2 touch mode, 3 auto-calibrate point state (two 20-bit bitmaps), 5 calibrate max difference, 7 pressure, 8 contact |
| `0x80`–`0x82` | WRITE\_PATTERN\_{JUST, CLEAR, CLEAR\_RUN}\_20 | app → toy | 3-byte points: `idx[7:0], idx[15:8], (idx[17:16]<<6) \| (value & 0x3F)` |
| `0x85`–`0x87` | WRITE\_PATTERN\_…\_100 | app → toy | 4-byte points: `idx` u24 LE, `value` u8 0–100 |
| `0x90`–`0x92` | WRITE\_PATTERN\_…\_100\_2 | app → toy | As `_100`, for Solace Pro "pos2" firmware |
| (write ack) |  | toy → app | Frame bytes 5–6 = free space u16 LE; 7–9 = time index (18 bits LE) |
| `0x8A` | PLAY\_PATTERN\_ACTION | app → toy | 1 byte: 0 stop, 1 pause, 2 play, 3 playing end |
| `0x8B` | READ\_PATTERN\_STATUS | both | Empty request; reply like the write ack |
| `0x8C` | SET\_PATTERN\_SPEED | ? | No builder found |
| `0x8D` | SET\_PATTERN\_PROGRAM | app → toy | `slot u8, total u16 LE, {start, end, speed, times}*` |
| `0x8E` | PATTERN\_PROGRAM\_CONTROL | both | `op [, arg]`: 1 free space, 2 revert, 3 play, 4 pause, 5 continue, 6 stop, 7 get pattern IDs, 8 delete |
| `0x93` | Wi-Fi management | both | `sub`: 0 status, 1 challenge, 5 device ID, 7 switch state, 8 MQTT status work without auth. 2 list slots, 3 switch slot, 4 delete slot, 6 enable Wi-Fi need a server-signed token |

Source: IDs in `r6.f`; builders in `n6.b`, `o6.b`, `p6.f`, `business/longc/aalightrgb/a.java`; parsers in `t6.a`, `p6.c`, `solacepro/pattern/b.java`, `hq.d`. AA support is gated by `GetCap` bit 2 or the server config `supportLanPattern`.

## Device catalogue

The model code (the letters before the first `:` of `DeviceType;`) is the key for everything model-specific. The full code → product → capabilities table is not in Java code. It is an encrypted JSON config the app bundles and refreshes from Lovense. The code confirms only the pairs below.

### Code-confirmed models

| Code | Product | Notes | Source |
| --- | --- | --- | --- |
| `s` | Lush (generations 1–6 via ToyCode suffixes) |  | `com.wear.ext.j1`, `k9.b` |
| `b` | Max |  | `j1.MAX` |
| `w` | Domi |  | `j1.DOMI` |
| `q` | Tenera |  | `j1.TENERA` |
| `ba` | Solace Pro | Binary command handler (`toytype/z15`, `toytype/solacepro`) | `j1.SOLACE_PRO` |
| `be` | Internal name "B12A"; retail name not confirmed | Pinned to service `42450001-…`; Wi-Fi provisioning stack | `j1.B12A`, `k9.b.c.f51075i` |
| `ca` | Mission 2 |  | `j1.MISSION2` |
| `wd` | Spinel |  | `j1.SPINEL` |
| `qb` | Fizz |  | `j1.FIZZ` |
| `kd` | Valor |  | `j1.VALOR` |
| `f` / `fs` | Sex Machine / Mini Sex Machine |  | `j1.XMACHINE`, `MINI_XMACHINE` |

Other model codes in the `ToyCode` class (`k9.b`), not mapped to a product in code: `a an c cb cd ce d ea eb ec ed ef eg ei el fz ga h j l n o p pd qa r sc sd se sp t ta u v x z za`. Some codes have several generations (for example `o_010100/02/03`, `ed_010100/020200/02020D`). Product names the app knows: ambi, calor, diamo, dolce, domi, edge, exomoon, ferri, flexer, gemini, gravity, gush, hush, hyphy, lapis, lovense(mini)sexmachine, lush, max, mission, nora, osci, ridge, solace, solacepro, tenera, vulse (`rg.z0`, `rg.c0`).

### Capability schema

Each config entry (`ToyConfigToyItemBean`, `m9.a`) carries:

| Field | Meaning |
| --- | --- |
| `symbol[]` | Model codes this entry matches, case-insensitive |
| `type`, `showName`, `fullName` | Product names |
| `func[]` | Function letters (table below) |
| `motorKeys` / `motorValues` | Per-function `{minv, maxv}` range, which can differ by firmware version (`fversionDiff`) |
| `supportMultiply` | `"Mply"` or `"Multiply"`: which combined command the model takes |
| `supportLEDColor`, `supportLanPattern`, `pinCodeSupport`, `program` | Feature flags |

Function letters and their built-in default max levels, used when the config gives no range (`OldToyBean.TOY_OPERATION`):

| Letter | Function | Default max |
| --- | --- | --- |
| `v`, `v1`–`v3` | Vibrate (main, motor 1–3) | 20 |
| `r` | Rotate | 20 |
| `p` | Air pump | 3 |
| `s` | Suction | 20 |
| `t` | Thrusting | 20 |
| `f` | Fingering | 20 |
| `d` | Depth | 20 |
| `pos` | Stroke position | 100 |
| `o` | Oscillate / slap | 20 |
| `q` | Bumping | 20 |
| `m` | Squirt | 20 |

### Where the full table lives

- Bundled: `assets/ToyConfigV3Res.txt` (plus V2 and Dev copies) in `game_asset_pack.apk`. Each file starts `DTX$` and is decrypted only by native `libdxp.so` (`P._dtxDecrypt`, called from `x3.a`).
- Refreshed from the server: `POST {apiBase}/app/toy/config/lastUpdateV3` with body `{appType, platform:"android", appVersion, dataVersion}`. The response holds `data.info`, the same encrypted string (`n9.a`, `j9.b` ToyConfigManager).

I did not decrypt the config. Until someone does, an open-source library can build its own table from the device-type replies of real toys, or send `GetCap;` (see Command reference).

## Implementation notes

A minimal client only has to scan, connect, subscribe, send `DeviceType;`, then stream motion commands no faster than one per 100 ms per toy.

### Minimal client (pseudocode)

```python
SUFFIX = "-bbd5-a6920e4c5653"

def is_lovense(adv):
    return any(str(u).lower().endswith(SUFFIX) for u in adv.uuids_both_byte_orders()) \
        or (adv.name or "").lower().startswith("lvs")

async def connect(dev):
    gatt = await dev.connect(transport="le", timeout=10)
    services = await gatt.discover(timeout=5)
    chars = [c for s in services for c in s.characteristics]
    if dev.model_hint == "be":
        tx = find(chars, "42450002-0023-4bd4-bbd5-a6920e4c5653")
        rx = [find(chars, "42450003-0023-4bd4-bbd5-a6920e4c5653")]
    else:
        tx = [c for c in chars if c.props & WRITE][-1]          # last writable
        rx = [c for c in chars if c.props & NOTIFY]
    for c in rx:
        await gatt.start_notify(c, on_notify)                   # CCCD 0x2902 = 01 00
    await send(tx, "DeviceType;")                               # expect "<code>:<fw>:<mac>;" within 10 s

def on_notify(data: bytes):
    if data[:1] == b"\xAA":
        handle_aa(data)                                         # check crc8(data[:-1]) == data[-1]
    else:
        text = data.decode("utf-8", "replace")
        if text.startswith("$01") and text.endswith(";") and len(text) == 20:
            schedule(0.2, write_no_rsp, tx, qcode_reply(text).encode())
        else:
            handle_text(text)

async def send(tx, cmd: str):
    await gatt.write(tx, cmd.encode(), response=False)          # app default for normal commands
```

### Timing and flow control (app behaviour worth copying)

| Rule | Value | Source |
| --- | --- | --- |
| Minimum gap between commands to one toy | 100 ms | `ToyCommandBean.sendIntervalTime`, `y9.e` |
| Gap between GATT operations | 10 ms, one in flight per device | `connect/b.java` |
| Drop a repeat of the identical motion command | within 1000 ms | `y9.c` |
| Merge combined commands | `-1`/`0xFF` slots take the older value before it is dropped | `y9.b` |
| Retries on a write error | up to 3, re-queued at the front | `y9.f` |
| Stop commands (all zero) | always resent on failure | `z9.a` |
| Queue size | 100, drop oldest | `queue/a.java` |
| Battery poll | 10 s (3 s at 0 %) | `k7.a` |

The toy needs no keepalive. Motion levels persist until changed, so a client should send a stop (`Vibrate:0;`, or the right zero command) before it disconnects.

### Open questions

These need a capture from real hardware or more static work:

- [ ] Does firmware reject writes on an unencrypted link when the PIN is on?
- [ ] What happens if a QCode challenge goes unanswered, and does a zero-padded reply work?
- [ ] On air, are the 128-bit identity UUID halves swapped, as the app's parser assumes?
- [ ] Does firmware echo the `,<tag>` byte, and does it accept any tag value?
- [ ] How are payloads over 20 bytes (`Pl…` patterns, large AA frames) carried with no MTU request?
- [ ] What do the `s<n>;` battery reply and `GetCap` bytes 5–7 mean?
- [ ] Time units of the `A*` timed commands and `AirLoop`.
- [ ] The full model code → product → range table (encrypted `ToyConfigV3Res.txt`, decrypted by native `libdxp.so`).
- [ ] Payload of AA `0x8C` and of `0x70` subcommands 7 and 8.

### Evidence

REA 6.4.0 with the JADX headless provider 0.7.1, on the base APK above.

| Claim | REA evidence ID |
| --- | --- |
| Package identity and manifest | `ev_f444335c1f8ba026fd024ac9adda9d6e037c759bf938290e7af83c22935a0e1b` |
| Scan record → identity UUID (`r9.b.f`) | `ev_f593d09646517a73438359cbe5f2ca73900bad7a7f651158b089ee938795bd26` |
| AD structure parser (`r9.b.g`) | `ev_db88eb3acf52397ebbc3340c024c79e976624a259d94a7bd44945b7c893ca7c6` |
| Write-channel selection (`i5.b.h`) | `ev_4dda9a22a4f4d41f3d4e9b422aefcc51bd42b4cf7315a569afdfb17541e7742c` |
| Characteristic inventory (`i5.b.a`) | `ev_0cbdc1385b5c53ea7dbb5012e290e4ad5db48a353a5b29abdc5c60a1c2d03982` |
| Write with response (`BleWorker.P`) | `ev_9620c97a523ee92de12c23600f4cfbdd0f2c772bc71183b2a02be24dfc2bbb7e` |
| Notification enable (`BleWorker.M`) | `ev_037a1222de0401316ede4f8dbee30179473543ed44b44498eb03f7e4f29159d5` |

Everything else comes from reading the full jadx 1.5.6 decompile, cited by class name in each section. Obfuscated names (`i5.b`, `r9.b`, …) apply to 8.10.1 only.
