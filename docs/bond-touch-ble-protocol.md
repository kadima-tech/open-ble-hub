# Bond Touch BLE protocol

Static protocol notes for Bond Touch bracelets (Impossible Labs), read from the Bond Touch Android app. There is no `openble-bondtouch` library yet; when one is added, this manual moves to its `docs/` folder.

This is interoperability documentation of a local app binary. It is not a capture from a live bracelet.

## Overview

A Bond Touch bracelet is a BLE peripheral with a touch sensor, a vibration motor and one or three RGB LEDs. Bracelets never talk to each other. The phone app records a touch pattern from the wearer's bracelet, sends it through the Bond cloud, and the partner's app plays it back on the partner's bracelet. Everything on the BLE link is local: setting up a bracelet, recording touches, playing patterns, colours, battery and firmware updates.

The app supports five bracelet generations. Four of them (V1, V2, V4, Mini) share one GATT layout, and V3 ("Bond More") has its own. Commands fit in 20 bytes, and the app never asks for a larger MTU. The bracelet asks for a fixed token and an app-chosen 32-bit ID (the AUID); after that, newer firmware also asks the phone to bond at OS level.

| Item | Value |
| --- | --- |
| Source artifact | Bond Touch 11.2.0 (versionCode 490), `com.impossible.bondtouch`, single APK from the APKPure mirror |
| APK SHA-256 | `e0abf27a9d94544fe51125e14262068263e2cb71f56eadedc738956ebb78737e` |
| Code size | 3 dex files, 15,633 classes (jadx 1.5) |
| BLE stack | In-house `com.impossible.bondtouch.bondtouchble` over Android `BluetoothGatt`; Nordic `Android-BLE-Library` only for the separate Bond Heart product |
| Native code | None used for BLE |
| Firmware images bundled | `res/raw/dfu_v120_hwmini.zip`, `dfu_v203_hw4g.zip`, `dfu_v260_hw203.zip`, `dfu_v279_hw2g.zip`, `dfu_v311_hw3g.zip`, `heart_dfu_v102.zip`, `heart_dfu_v103.zip` (Nordic DFU packages) |

**Method.** Static analysis only. REA 6.4.0 (`decode-android-resources`, apktool 3.0.3) gave the package identity, manifest and resources. REA's Android code tools (`inspect-android-package` and others) need a separately supplied `jadx-headless-mcp` 0.7.1 JAR, which was not installed, so the code was read from a full jadx decompile, with apktool smali used to settle two places where jadx's output was ambiguous. Nothing was observed at runtime: timings and formats are what the code does, not captured traffic. Names like `rb0` or `m4223d` are obfuscated in this build and will differ in other versions; the readable class names (`BleBondManagerV2Base`, `WriteFF06Command`, …) are the app's own.

**Evidence key.** "Observed" means the behaviour is read directly from decompiled code, with its class cited. "Inferred" means it was reasoned from code but not proven. Open items are listed at the end.

**Scope.** Talking to a bracelet you own from an open-source client: discovery, setup, touch in, touch out, colours, settings and battery. The Bond cloud (accounts, partner pairing, message relay) is out of scope except where it explains what the app sends over BLE. A short appendix covers the Bond Heart, a different product handled by the same app.

### Product generations

`BleBondTouchDevice` (in `bondtouchble/bluetooth`) lists the generations. The app stores the generation string in preferences as `SAVED_GENERATION`.

| Enum | Saved as | Advertised name (scan filter) | DFU name | Manager class | Target firmware in this app | Bundled image |
| --- | --- | --- | --- | --- | --- | --- |
| `BT1` | `1` | `BOND` | `BOND_DFU` | `v1/BleBondManagerV1` | 1.2.96 | none |
| `BT2` | `2` | `BOND` | `BOND_DFU` | `v2/BleBondManagerV2` | 2.7.9 | `dfu_v279_hw2g` (and `dfu_v260_hw203`, below) |
| `BTM` ("Bond More", 3G) | `3` | `Bond More` | `BOND_M_DFU` | `v3/BleBondManagerV3` | 3.1.1 | `dfu_v311_hw3g` |
| `BT4` | `4` | `BOND 4` | `BOND_4_DFU` | `v4/BleBondManagerV4` | 2.0.3 | `dfu_v203_hw4g` |
| `BT_MINI` | `mini` | `BOND MINI` | `BOND_MINI_DFU` | `mini/BleBondManagerMini` | 1.2.0 | `dfu_v120_hwmini` |

Observed: names in `BondBleConstants.f8599e`/`f8600f`, targets in each manager's `FirmwareVersion` field. Inferred: which name each generation advertises. The app does not decide the generation from the name; it reads an API version byte (see [Generation detection](#generation-detection)). The user-facing brand list in `BrandNamesKt` is "Bond Touch Lite", "Bond Touch", "Bond Heart", "Presence +".

## Discovery and advertising

The app identifies bracelets **by name only**. No scan filter uses a service UUID, and the app never parses manufacturer data.

- **Foreground scan** (`BleBondScanHelper.m4131b`): one `ScanFilter` per name in `["BOND", "Bond More", "BOND 4", "BOND MINI"]`. When a bracelet is already paired, each filter is also pinned to its saved MAC address. Each `ScanResult` is collected as `(scanRecord.deviceName, device)`; the first hit triggers a connect.
- **Companion pairing** (Android 8+): during setup the app calls `CompanionDeviceManager.associate` with two `BluetoothLeDeviceFilter`s, name patterns `BOND(_DFU)?` and `Bond More?` (`p000/rj1`). On Android 11+ the app refuses to scan unless the saved address is an existing association (`BleUtils.m4195a`). Inferred: Android applies these patterns with `find()`, so `BOND 4` and `BOND MINI` also match the first one.
- **Bootloader**: bracelets in DFU mode advertise `BOND_DFU`, `BOND_M_DFU`, `BOND_4_DFU` or `BOND_MINI_DFU`. The DFU screen scans for these for 8 s at `SCAN_MODE_LOW_LATENCY`.

A paired device is recognised among the phone's bonded devices only if its name is in the four-name list (`BleBondClientKt.m4091e`).

## GATT layout

All Bond UUIDs share one base: `d3c0XXXX-add3-1d4b-000Y-0000b5006bb1`. The fourth group is `0000` for some characteristics and `0001` for others; copy each UUID exactly as written below.

### Services

| Service | Used by | Contents |
| --- | --- | --- |
| `d3c00001-add3-1d4b-0000-0000b5006bb1` | V1, V2, V4, Mini | API version (`ff10`), firmware (`ff03`, V1 only), battery (`ff06`) |
| `d3c00002-add3-1d4b-0001-0000b5006bb1` | V1, V2, V4, Mini | Control: `ffa1`–`ffa8` |
| `d3c00003-add3-1d4b-0000-0000b5006bb1` | V3 only | `ffb1` (commands and events), `ffb2` (touch data), `ffb3` (API version) |
| `0000180a-…` Device Information | V2, V4, Mini, V3 | `2a26` firmware revision string, `2a24` model number string |
| `0000180f-…` Battery | V3 | `2a19` battery level |

### Characteristics

| UUID (short) | Full UUID | Service | Access (as the app uses it) | Purpose |
| --- | --- | --- | --- | --- |
| `ff10` | `d3c0ff10-add3-1d4b-0000-0000b5006bb1` | `…0001` | read | API version byte, picks the generation |
| `ff03` | `d3c0ff03-add3-1d4b-0000-0000b5006bb1` | `…0001` | read | V1 firmware: `[patch, minor]` → `1.minor.patch` |
| `ff06` | `d3c0ff06-add3-1d4b-0000-0000b5006bb1` | `…0001` | read, notify | Battery. V1: `uint16 LE` millivolts. V2/V4/Mini: `[percent, reserved]` |
| `ffa1` | `d3c0ffa1-add3-1d4b-0001-0000b5006bb1` | `…0002` | write | Token. The app always writes the ASCII string `12345678` |
| `ffa2` | `d3c0ffa2-add3-1d4b-0001-0000b5006bb1` | `…0002` | write | AUID, `uint32 LE` |
| `ffa4` | `d3c0ffa4-add3-1d4b-0001-0000b5006bb1` | `…0002` | read, notify | Bracelet state |
| `ffa5` | `d3c0ffa5-add3-1d4b-0001-0000b5006bb1` | `…0002` | notify | Events: touches, taps, paired signal |
| `ffa6` | `d3c0ffa6-add3-1d4b-0001-0000b5006bb1` | `…0002` | write | Command channel (LEDs, motor, config, DFU) |
| `ffa7` | `d3c0ffa7-add3-1d4b-0001-0000b5006bb1` | `…0002` | notify | V1 only: per-command result (app-level ACK) |
| `ffa8` | `d3c0ffa8-add3-1d4b-0001-0000b5006bb1` | `…0002` | notify (encrypted, inferred) | V4/Mini: subscribing triggers OS bonding |
| `ffb1` | `d3c0ffb1-add3-1d4b-0000-0000b5006bb1` | `…0003` | write with response, notify | V3 commands and all V3 events |
| `ffb2` | `d3c0ffb2-add3-1d4b-0000-0000b5006bb1` | `…0003` | write with response, notify | V3 touch patterns in both directions |
| `ffb3` | `d3c0ffb3-add3-1d4b-0000-0000b5006bb1` | `…0003` | read | V3 API version (logged, otherwise unused) |

Observed in `BleBondClientKt`, `BondBleConstants`, `v1/BleBondManagerV1Kt`, `v1/Constants`, `v2/BleBondManagerV2BaseKt`, `v3/Constants`, `v4/BleBondManagerV4Kt`, `mini/BleBondManagerMiniKt`.

CCCD writes use `0x2902` = `01 00` (notifications). Before using a generation, the app checks that every characteristic it needs is present, and raises a connection error if any is missing.

### Byte order

Integers are mostly little-endian. Two exceptions are easy to get wrong:

- **V2 config colours and the OUID are big-endian** `uint32` (`BleAppCommandHelperKt.m4224a`), as are the `uint16` breathe timings inside `LOW_BAT_COLOR` and `DISCONNECTED_PARAM`.
- **V1 colours** are an Android ARGB `int` written `uint32 LE`, so on air they read `B G R A`. The app then overwrites the `A` byte (see [V1 commands](#v1-commands-on-ffa6)).

Field formats below follow Android's `FORMAT_UINT8/16/32` (all little-endian) unless marked BE.

## Connection lifecycle

| # | Step | App action | Bracelet response | Source |
| --- | --- | --- | --- | --- |
| 1 | Scan | Name filters as above, optionally pinned to the saved address | Advertisement | `BleBondScanHelper` |
| 2 | Connect | `connectGatt(context, autoConnect=false, cb, TRANSPORT_LE)`. If scanning is impossible (no association, Bluetooth or location off) it falls back to `autoConnect=true` with a 20 min watchdog | `STATE_CONNECTED` | `BleBondClient.m4039c`, `BleConnectionCompat` |
| 3 | Discover | `discoverServices()` immediately; no MTU request, no PHY change | Services | `BleBondClient$gattCallback$1` |
| 4 | Generation | If service `…0003` exists: read `ffb3` → V3. Otherwise read `ff10` → `0x42` BT2, `0x44` BT4, `0x45` Mini, anything else BT1 | API version byte | `onCharacteristicRead`, `p000/rb0` |
| 5 | Manager init | Generation-specific subscribe and read sequence (below) | State, battery | `BleBondManagerV1/V2Base/V3` constructors |
| 6 | Setup handshake | Bracelet asks for the token and then the AUID through its state | State changes | see each generation |
| 7 | Firmware check | Firmware version read and compared with the app's target. Newer or equal → `NO_UPDATE_NEEDED`. Only then does the app go on to bonding and notification setup | — | `FirmwareHelper.m4181a` |
| 8 | OS bonding | V2: ANCS config flag. V4/Mini: subscribe to `ffa8`. V3: `createBond()` | Android pairing prompt | `mo4213S`, `m4243H` |
| 9 | Paired | App saves address and generation, pushes the wearer's touch colour, vibration strength, partner menu and selected partner | — | `BleBondClient$bleBondManagerListener$1.m4067j` |
| 10 | Steady state | Commands through the queue; events by notification | Notifications | `BleCommandHandler` |

**Reconnect policy** (`BleBondClient`, `ReconnectPolicy`): on disconnect with status 133 the app retries up to 5 times, 200 ms apart. Status 5 or 15 (auth or encryption failure) is logged as "stale bond suspected". When the app decides a re-pair is needed, it stops reconnecting on its own (`OnRePairRequired`). The app never requests an MTU (`onMtuChanged` only logs), so every write is at most 20 bytes.

### Setup handshake and the AUID

The bracelet drives setup through its state value. The app's answers are fixed:

- **Token**: the ASCII string `12345678`, written as soon as the bracelet asks (V2 writes it straight after subscribing). There is no per-device secret. Observed in `WriteStringCommand`, `BleBondManagerV2Base.m4238Q` and `BleBondManagerV3` (state `0x82`).
- **AUID**: a random 32-bit integer the app generates once and stores as `SAVED_AUID` (`BleBondPrefs.m4125a`). V1/V2/V4/Mini write it to `ffa2` as `uint32 LE`; V3 sends only its low byte. Inferred: the AUID ties the bracelet to one phone, and a bracelet that already holds a different AUID raises `AUID_ERROR` (event `0x12`), after which the app asks the user to reset or re-pair.

A third-party client can make up its own AUID. Reusing the official app's value (it lives in that app's private preferences) would probably avoid a bracelet reset, but that is unverified.

## V1 (original Bond Touch)

### Init sequence

Observed in the `BleBondManagerV1` constructor and `mo4116r`:

1. Read `ff03` (firmware). Enable notifications on `ff06`, then read `ff06` (battery).
2. On the firmware reply, if no update is needed: check every `ffa*` characteristic, enable notifications on `ffa5`, `ffa4` and `ffa7`, write `12345678` to `ffa1`.
3. After 1 s, request connection priority `BALANCED` (0).

Battery percent = `clamp(mV − 3700, 0, 400) × 100 / 400`.

### `ffa4` state (V1)

`[bondState u8, pairedState u8, charging u8]` (`m4218I`).

| Field | Value | Meaning | App reaction |
| --- | --- | --- | --- |
| `bondState` | `0x83` (131) | Out-of-box state off | — |
| `bondState` | `0x84` (132) | Out-of-box state on | — |
| `pairedState` | `0xF4` (244) | Waiting for AUID | Write AUID `uint32 LE` to `ffa2` |
| `pairedState` | `0xF5` (245) | — | none |
| `pairedState` | `0xF6` (246) | Idle, connected | Resume command queue, mark paired |
| `pairedState` | `0xF7` (247) | Busy (recording or playing) | Pause queue for 30 s |
| `charging` | 0 / 1 | Not charging / charging | — |

### `ffa5` events (V1)

`[eventId u8, counter u8, touchCount u16, touchTimeMs u16]`.

| `eventId` | Name (`AppEvent`) | App reaction |
| --- | --- | --- |
| `0x11` | `AUID_RIGHT` | none |
| `0x12` | `AUID_ERROR` | Flag the bracelet as needing setup |
| `0x13` | `PAIRED_SIGNAL` | Write one byte `0x31` to `ffa6` |
| `0x14` | `SEND_MSG` | Touch recording (below) |

**Recording a touch (V1).** In a `SEND_MSG` event, `touchCount = 1` starts a new message; each event records one press of `touchTimeMs`. `touchCount = 0xFFFF` ends the message and `0xFFFE` means a timeout (also an end). V1 does not report gaps: the app works them out from **phone arrival times** (`next.arrival − next.duration − this.arrival`, negative → 100 ms). Every value is rounded to 50 ms. The result is the standard [touch pattern](#touch-patterns) `[press, gap, press, …]`.

### V1 commands on `ffa6`

A `WriteFF06Command` is `[cmdId u16, seq u16, payload]`. `seq` is a 16-bit counter that wraps at 65 535 and is reset on each connection; it is how replies on `ffa7` are matched to commands.

| `cmdId` | Name | Length | Payload |
| --- | --- | --- | --- |
| `0x0021` (33) | Colour | 16 | `@4 colour u32 LE` (an ARGB int), then byte 7 overwritten with `100`. On air: `B G R 0x64` |
| `0x0025` (37) | Enter DFU | 8 | `@4 0xFFFFFFFF` |
| `0x0026` (38) | Light and vibration step | 16 | `@4 ledId u8, @5 mode u8, @6 phase u8, @7 0x01, @8 level u16, @10 time u16` (the last two are left out of the end step) |
| `0x0027` (39) | Set config key | 16 | `@4 key u32, @8 value u32` |
| `0x0027` (39) | Save config | 8 | `@4 1000 u32` |
| `0x0029` (41) | Reboot | 8 | `@4 0xFFFFFFFF` |
| — | Paired acknowledgement | 1 | the byte `0x31` |

**Setting the touch colour (V1)** (`mo4104f`): `0x0027` with key `1003` and value = the palette RGB, then `0x0027` with key `1006` and value = `ledId`, then save config.

**Playing a pattern (V1)** (`mo4105g`): for each duration in the pattern, a `0x0026` step `(ledId, mode, phase=1, level=100, time)`. `mode` alternates `2, 1, 2, 1, …` starting with the first element. `time = max(ms, 100) × 10 / steps`, halved if `mode == 4`, where `steps` is 30 for red and 100 for every other colour. The pattern ends with a short `0x0026` step `(mode=2, phase=2)`. Inferred: `phase 1` queues a step and `phase 2` runs the queue.

V1 only has 11 fixed colours. The app maps its palette onto LED ids (`BleBondManagerV1` constructor, `BleColorTable`):

| `ledId` | Bracelet RGB (`BleColorTable`) | App colours mapped to it |
| --- | --- | --- |
| 0 | `FF0000` (`steps` 30) | `FF0000` |
| 1 | `00EEF9` | `23E0E8` (also the fallback) |
| 2 | `000FF9` | `106DED` |
| 3 | `BA00F9` | `BE5BFF`, `A502C0` |
| 4 | `F9002D` | `FF44A6` |
| 5 | `07F900` | `03AB55` |
| 6 | `61F900` | `7BBE2F` |
| 7 | `F9F500` | `E8D726` |
| 8 | `F94300` | `FF7931` |
| 9 | `FFFFFF` | `FFFFFF` |
| 10 | `000000` | `000000` |

### `ffa7` command result (V1)

`[result u16, seq u16]`. V1 writes to `ffa6` are not finished when Android reports the write; the queue waits for this notification.

| `result` | Name |
| --- | --- |
| 0 | `ACR_NULL` |
| 1 | `ACR_SUCCESS`: advance the queue and mark the message with `seq` as delivered |
| 2 | `ACR_FAIL` |
| 3 | `ACR_PARAM_ERROR` |
| 4 | `ACR_RES_NULL` |
| 5 | `ACR_RES_UNENOUGH` |
| 6 | `ACR_NUM_OVERFLOW` |
| 7 | `ACR_ROUTING_ERROR` |
| 8 | `ACR_HARDWARD_ERROR` |
| 9 | `ACR_AUTH_ERROR` |
| 10 | `ACR_TIMEOUT` |
| 11 | `ACR_BUSY`: after 10 in a row the app sends `0x0029` reboot |
| 12 | `ACR_MAX` |

Any result other than success makes the app retry the command once, after 3.5 s.

## V2, V4 and Mini

These three share `BleBondManagerV2Base`. The subclasses differ only in the details listed in [Generation differences](#generation-differences).

### Init sequence

Observed in the `BleBondManagerV2Base` constructor:

1. Check that `…0002` has `ffa1`, `ffa2`, `ffa4`, `ffa5` and `ffa6`, that `…0001` has `ff06`, and that DIS has `2a26`.
2. Read `ff06` (battery).
3. Enable notifications on `ff06`, `ffa5` and `ffa4`. When all three CCCD writes succeed (or after 10 s), V2 and Mini request connection priority `BALANCED`; V4 leaves it alone.
4. V2: write the token `12345678` to `ffa1` straight away. V4/Mini: read `ffa4` and let the state drive setup.

### `ffa4` state (V2/V4/Mini)

`[bondState u8, chargingState u8, ledBusy u8, motorBusy u8, touchBusy u8]` (`m4237O`).

| `bondState` | Name (`v2/BondState`) | App reaction |
| --- | --- | --- |
| `0x00` | `NO_STATE` | — |
| `0x82` | `WAITING_TOKEN` | Write `12345678` to `ffa1` |
| `0x83` | `WAITING_AUID` | Write AUID `uint32 LE` to `ffa2` |
| `0x84` | `OOBE` | — |
| `0x85` | `CONNECTED` | Resume the queue. On first entry, read DIS `2a26` (firmware string) |
| `0x86` | `MSG` | Bracelet is recording or playing. Pause the queue for 15 s |
| `0x87` | `FACTORY` | — |
| `0x88` | `QUEUE_EXECUTING` | Bracelet is playing queued commands. The app sets a 5 s watchdog to re-check the state |

`chargingState`: `0` not charging, `1` charging, `2` full, `0xFF` error. `touchBusy = 1` while the wearer is touching; the app uses it for the "touching" UI.

### `ffa5` events (V2/V4/Mini)

`[eventId u8, counter u8, touchMs u32, releaseMs u32, stop u32, (V4) deviceId u8 @14]`, read in each subclass's `mo4210M`. A notification whose first byte is `0x19` and is at least 14 bytes long is instead a **ship-mode report** and is passed up raw.

| `eventId` | `AppEvent` | App reaction |
| --- | --- | --- |
| `0x11` | `AUID_RIGHT` | none |
| `0x12` | `AUID_ERROR` | Flag the bracelet as needing setup |
| `0x13` | `PAIRED_SIGNAL` | Write `31 00 11 22 33 44` (paired acknowledgement) to `ffa6` |
| `0x14` | `SEND_MSG` | One press of a recording (below) |
| `0x15` | `SEND_MSG_TIMEOUT` | Recording ended by timeout |
| `0x16` | `TAP_DETECTED_SIGNAL` | Logged only |
| `0x17` | `NO_ACTION_DOUBLE_TAP_DETECTED` | Double tap. The app can answer with the wearer's colour (see `0x26` presets) |

**Recording a touch (V2/V4).** Each `SEND_MSG` event is one press. `counter = 1` starts a new pattern `[max(touchMs, 50)]`. Later events append `max(releaseMs, 50)` (the gap before this press) and then `max(touchMs, 50)`. `stop == 0xFFFFFFFF` marks the last press, and the pattern is complete. `SEND_MSG_TIMEOUT` with `counter == 0` discards what was collected. On V4, byte 14 is the partner slot (1–3) chosen on the bracelet's menu; any other value means slot 1.

The **Mini** has no pattern: whatever it reports, the app treats every touch as the fixed pattern `[500, 250, 500, 250, 500]`.

### Command frames on `ffa6`

Every command is padded with zeros to **20 bytes**. Byte 1 is always `0x00`.

| Byte 0 | Name | Layout |
| --- | --- | --- |
| `0x25` | Enter DFU | `25 00 11 22 33 44` |
| `0x26` | LED and motor step | see below |
| `0x27` | Config write | `27 00 <property> 01 <value…>` |
| `0x31` | Paired acknowledgement | `31 00 11 22 33 44` |
| `0x32` | Run queue | `32 00 11` after a touch pattern, `32 00 22` after an animation |
| `0x33` | Three-LED frame | see below |
| `0x34` | Wake gesture mode | `34 00 11` on, `34 00 22` off |

Writing `0x32` makes the app pause its own queue for 5 s while the bracelet plays.

#### `0x26` LED and motor step (`LedAndMotorCommand`)

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | `0x26` |
| 1 | 1 | `0x00` |
| 2 | 1 | `queue`: 0 = play now, 1 = append to the queue |
| 3 | 1 | Vibration strength, 0–100 |
| 4 | 2 LE | Vibration time, ms |
| 6 | 1 | LED mode: 1 = solid, 2 = breathe, 4 = off (inferred from use) |
| 7 | 3 | Red, green, blue |
| 10 | 1 | LED brightness (the app always uses 80) |
| 11 | 2 LE | LED fade time, ms |
| 13 | 2 LE | LED hold time, ms |
| 15 | 2 LE | LED sleep time, ms |
| 17 | 2 LE | Total step time, ms (`0xFFFF` = until changed) |
| 19 | 1 | padding |

Presets the app sends (`BleBondManagerV2Base`):

| App action | Bytes 2–18 |
| --- | --- |
| Show colour (`mo4123y`) | queue 0, vib 0/0, mode 1, RGB, 80, 0, 0, 0, `0xFFFF` |
| Clear colour (`mo4106h`) | queue 0, all zero, mode 4 |
| Vibration test with LED (`mo4121w`) | queue 0, vib `strength` for 2000 ms, mode 1, RGB, 80, 0, 0, 0, 2000 |
| Vibration test, motor only (`mo4124z`) | queue 0, vib `strength` for 2000 ms, mode 4 |
| Double-tap answer (`mo4099a`) | queue 0, vib 0, mode 2, own RGB, 80, fade 500, hold 1000, sleep 0, total 2000 |
| Wake-up demo (`mo4107i`) | queue 0, vib 50 for 250 ms (or none), mode 2, RGB, 80, 500, 2000, 250, `0xFFFF` |

#### Playing a touch pattern (V2/V4/Mini)

`mo4105g(pattern, colourA, colourB, strength, slot, flag)`. Durations at even positions in the pattern are presses; odd positions are gaps.

- **One colour** (`colourA == colourB`, an ordinary touch): one `0x26` step per press, with `queue = 1`, `strength`, vibration time = press, mode 2, the colour, brightness 80, fade = 25 % of the press, hold = press − 2 × fade, sleep = the following gap (0 for the last press), total = press + gap. Then `32 00 11`.
- **Two colours** (a "touch meaning" message): `0x33` frames, each 200 ms long during a press, with the colour blended from `colourA` to `colourB` over the whole message, all three LEDs at brightness 80 and motor at `strength`. Each gap becomes one `0x33` frame of all zeros lasting the gap. Then `32 00 22`.

`strength` comes from the user's vibration setting; the app accepts 28, 33, 40, 58, 60, 73, 80, 88 or 100 and uses 80 otherwise (`VibrationHelper$Companion`). On V4 the app then selects the sending partner's slot with config `SELECTED_USER`. The Mini always plays `[500, 250, 500, 250, 500]`.

Before sending, the app maps its UI colours to the bracelet's tuned colours with `ColorMapperHelper.m4206b`: a 40-entry table of UI ARGB to bracelet ARGB, for example `D3007A → D30013` and `FF7C00 → FF2200`. Colours not in the table are sent unchanged.

#### `0x33` three-LED frame

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | `0x33` |
| 1 | 1 | `0x00` |
| 2 | 1 | Motor strength |
| 3 | 3 | Brightness of LED 1, 2, 3 |
| 6 | 3 | LED 1 RGB |
| 9 | 3 | LED 2 RGB |
| 12 | 3 | LED 3 RGB |
| 15 | 2 LE | Frame time, ms |

Animations built from these frames (`BleBondManagerV2Base`):

| Animation | Trigger in the app | Shape |
| --- | --- | --- |
| Rainbow (`mo4111m`) | A partner's "secret" chat notification (throttled to one per 30 s) | 128 frames of 50 ms: a colour wheel across the three LEDs with cosine brightness, motor following a fixed 20-step pattern |
| Background buzz (`mo4101c`) | A partner's ordinary chat notification | Four `0x26` steps of 200 ms, strengths 48, 50, 100, 54, and a 700 ms sleep after the last |
| Arrival (`mo4112n`) | A partner arrives at a saved place | 60 frames of 50 ms in one colour (category colour `FF003C`, `00E1FF` or `FF8800`), motor 10–100 and brightness 20–90 rising and falling every 100 ms |

### Config properties (`0x27`)

Write frame: `27 00 <prop> 01 <value>` (`BleAppCommandHelper.m4223d`). The read parser (`mo4116r`) expects the same header with the value at offset 4, but nothing in this build ever requests a config read.

| Prop | Name | Value | Used by the app |
| --- | --- | --- | --- |
| `0x11` | `OUID` | `u32` BE | — |
| `0x12` | `TOKEN` | `u64` LE | — |
| `0x13` | `MAX_TOUCH_COUNT` | `u8` | — |
| `0x14` | `MIN_TOUCH_DURATION` | `u32` LE, ms | `50` after bonding |
| `0x15` | `MAX_TOUCH_DURATION` | `u32` LE, ms | — |
| `0x16` | `MESSAGE_TIMEOUT` | `u32` LE, ms | — |
| `0x17` | `LOW_BAT_THRESHOLD` | `u8`, % | `10` after bonding |
| `0x18` | `MOTOR_STRENGTH` | `u8` | user vibration setting |
| `0x19` | `BLE_PARAMS` | 6 × `u16` LE: advertising interval, advertising timeout, min and max connection interval, slave latency, supervision timeout | — |
| `0x21` | `LOW_BAT_COLOR` | `enabled u8, breathe u16 BE, sleep u16 BE, repeatSleep u32 BE, colour u32 BE` | `1, 1000, 500, 1171, 0x00FF0000` after bonding |
| `0x22` | `OOBE_COLOR` | colour `u32` BE | — |
| `0x23` | `OOBE_PAIRED_COLOR` | colour `u32` BE | — |
| `0x24` | `DOUBLE_TAP_COLOR` (V2), user-menu entry (V4/Mini) | V2: colour `u32` BE. V4/Mini: `colour u32 BE, entry u32 BE` | see below |
| `0x25` | `TOUCH_COLOR` | colour `u32` BE | the wearer's own colour |
| `0x26` | `TOUCH_WARNING_COLOR` | colour `u32` BE | — |
| `0x27` | `ERROR_COLOR` | colour `u32` BE | — |
| `0x28` | `CHARGING_COLOR` | colour `u32` BE | — |
| `0x29` | `CHARGE_DONE_COLOR` | colour `u32` BE | — |
| `0x30` | `ACCEL_SENSITIVITY` | `u8` | — |
| `0x31` | `DISCONNECTED_PARAM` | `enabled u8, breathe u16 BE, sleep u16 BE, repeatSleep u16 BE, colour u32 BE` | all zero (off) after bonding |
| `0x33` | `ANCS_PARAM` | `u8` 0/1 | see bonding |
| `0x35` | `FACTORY_MODE` | none | — |
| `0x37` | `SELECTED_USER` | `u8` partner slot 1–3 (the read parser takes it from offset 8) | V4 |
| `0xEF` | `RESET_CONFIG` | none | factory reset; the app reconnects 3 s later |

Colours are Android ARGB ints, so on air they are `AA RR GG BB` with `AA` normally `FF`. The low-battery default passes `0x00FF0000`. The `UserMenu` → `0x24` mapping was confirmed in smali, because jadx's output for that branch was garbled.

**Partner menu (V4/Mini).** A V4 bracelet can hold up to three partners and lets the wearer choose who to send to. Each slot `n` (1–3) is set with prop `0x24`: `colour u32 BE, entry u32 BE`, where `entry = n | 0x80` for an active partner (colour = the partner's colour) or `n & 0x7F` for an empty slot (colour `0xFF000000`). Slot 1 is shown only when slot 2 or 3 is active. Setting the wearer's own colour writes `TOUCH_COLOR` and also `0x24` with entry `0x80`.

### Bonding (V2/V4/Mini)

After the firmware string reports no update is needed (`mo4213S`):

- **V2**: if the firmware is older than 2.5.0, skip OS bonding. Otherwise, if the phone is not bonded, write `ANCS_PARAM = 1`; if it is already bonded, write `0`. Inferred: turning ANCS on makes the bracelet request encryption, which starts Android's pairing prompt.
- **V4/Mini**: write `ANCS_PARAM = 0`. If the phone is not bonded, enable notifications on `ffa8`. Inferred: `ffa8` requires encryption, so subscribing starts pairing. A failed CCCD write there is logged as "Bonding attempt FAILED".

When Android reports `BOND_BONDED`, the app writes `LOW_BAT_THRESHOLD`, `LOW_BAT_COLOR`, `MIN_TOUCH_DURATION` and `DISCONNECTED_PARAM` as one batch; V2 also writes `ANCS_PARAM = 0`.

### Generation differences

| | V2 | V4 | Mini |
| --- | --- | --- | --- |
| API version (`ff10`) | `0x42` | `0x44` | `0x45` |
| First action after subscribing | write token | read `ffa4` | read `ffa4` |
| BALANCED priority after subscribing | yes | no | yes |
| Touch recording | pattern | pattern + partner slot (byte 14) | fixed pattern |
| Own colour write | `TOUCH_COLOR` + `DOUBLE_TAP_COLOR` | `TOUCH_COLOR` + `0x24` entry `0x80` | as V4 |
| Partner menu | — | `0x24` slots, `SELECTED_USER` | — |
| OS bonding trigger | `ANCS_PARAM` | `ffa8` CCCD | `ffa8` CCCD |

## V3 (Bond More)

V3 uses service `d3c00003-…`. Every command and event goes over `ffb1`, and touch patterns over `ffb2`. The app writes both with `WRITE_TYPE_DEFAULT` (with response).

### Init sequence

1. Check for `ffb1` and `ffb2`. Enable notifications on `ffb1`.
2. Write `01 30`. Inferred: a hello or firmware-version request, because the next thing the app handles is the `0xAC` firmware reply. The app also sends it right before entering DFU.
3. After 3 s, request connection priority `BALANCED`.
4. On the `0xAC` firmware reply with no update needed: if firmware > 3.0.0, enable notifications on `2a19`. Enable notifications on `ffb2`, then call `createBond()` if the phone is not bonded.

### `ffb1` writes

A write is `[type u8, payload…]` with no padding (`WriteFFB1Command`).

| Bytes | Meaning | Source |
| --- | --- | --- |
| `03 31 32 33 34 35 36 37 38` | Token `12345678` | state `0x82` |
| `07 <auid & 0xFF>` | AUID, low byte only | state `0x83` |
| `01 19`, `01 1B`, `01 41`, `01 42`, `01 49 01`, `01 1C` | Sent once on the first `CONNECTED` state, with a read of `2a19` between `01 49 01` and `01 1C`. `49 01` reads the battery settings (answered by ACK `0x49`). Inferred: the others request the `0xAA`, `0xAB`, `0xAE` and `0xAF` reports, but which byte asks for which is not proven | `BleBondManagerV3` |
| `01 2A` | Enter DFU | `mo4094C` |
| `01 30` | Hello / firmware request (inferred) | constructor |
| `01 31` | Paired acknowledgement | on event `0x13` or state `0x8A` |
| `01 43` / `01 44` | Wake gesture mode on / off | `mo4110l` |
| `01 45 00` + 3 × `[active, R, G, B]` | Set the partner menu. `active`: 0 inactive, 1 active, 2 ignore | `m4247L` |
| `01 45 01` | Read the partner menu | `mo4092A` |
| `01 48 00 <level> <balance> 03` | Vibration test | `mo4124z` |
| `01 48 02 <level> <balance> 03` | Save vibration settings | `mo4097F` |
| `01 4B 00 <led> R G B` | Show colour. `led` 0 = all, 1 = first LED only | `mo4123y`, `mo4114p` (green check, `00FF00`, on LED 1) |
| `01 4B 01` | LED off | `mo4106h` |

For the tutorial, the menu is filled with three fixed colours: `FFFF00`, `007AFF`, `FF2D55`.

### `ffb1` notifications

Byte 0 is the type.

| Type | Layout | Meaning |
| --- | --- | --- |
| `0x02` | `02 <event> [arg]` | Bond event: `0x13` paired signal (app answers `01 31`), `0xB2` double tap, `0xB3` ignored, `0xB4 <slot>` the wearer picked a partner on the bracelet |
| `0x04` | `04 <state>` | State (table below) |
| `0x09` | battery | The app reads `uint16` at offsets 0 and 1 as percent and voltage. That would mix in the type byte, so the real layout is probably `09 <percent> <voltage…>` (open question) |
| `0x0A` | `0A <cmd> <data…>` | ACK of a `01 <cmd>` command (below) |
| `0xA1` | `A1 15 <x> <y> <z>` | Factory: touch position |
| `0xAA` | `AA <4 bytes>` | Lot number: bytes 1–4 reversed, as hex |
| `0xAB` | `AB <4 bytes>` | Device number: bytes 1–4 reversed, as hex |
| `0xAC` | `AC <patch> <minor> <major>` | Firmware version `major.minor.patch` |
| `0xAE` | `AE <u32 LE resets> <u32 LE reason bits>` | Health. The highest set bit of the reason is the nRF51 reset cause: 0 `RESETPIN`, 1 `DOG`, 2 `SREQ`, 3 `LOCKUP`, 16 `OFF`, 17 `LPCOMP`, 18 `DIF` |
| `0xAF` | `AF <u16 LE> <u16 LE> <u16 LE>` | Flash usage: factory, settings and status data |
| `0xB0` | — | ANCS (logged only) |
| `0x01`, `0x03`, `0x05`–`0x07` | — | Ignored by the app |

V3 states (`04 <state>`):

| State | Name in the app log | App reaction |
| --- | --- | --- |
| `0x01` | `BOND_STATE_START` | — |
| `0x82` | `WAITING_TOKEN` | Send `03 "12345678"` |
| `0x83` | `WAITING_AUID` | Send `07 <auid low byte>` |
| `0x84` | `OOBE` | Flag the bracelet as needing setup |
| `0x85` | `CONNECTED` | Resume the queue and send the connect burst (above) |
| `0x86` | `MSG_RECORDING` | Pause the queue for 15 s |
| `0x87` | `MSG_PLAYING` | Pause the queue for 15 s |
| `0x88` | `MENU` | Pause the queue for 15 s; partner menu open on the bracelet |
| `0x89` | `REPLY_MENU` | Pause the queue for 15 s |
| `0x8A` | `WAIT_FOR_ACT_PAIRED` | Send `01 31` |
| `0x8D` | `WAIT_DOUBLE_TAP` | — |
| `0x8E` | `TEST_COLORS` | — |
| `0x8F` | `WAITING_START_AUTHENTICATION` | — |

ACKs (`0A <cmd> …`):

| `cmd` | Data | Meaning |
| --- | --- | --- |
| `0x45` | 3 × `[active, R, G, B]` | Partner menu as the bracelet holds it. If it differs from what the app expects, the app rewrites it |
| `0x48` | `<level> <balance>` | Vibration settings. If they differ from the saved ones, the app rewrites them |
| `0x49` | `<low%> R G B <critical%> R G B` | Battery warning levels and colours |
| `0x4A` | `<sensitivity>` | Accelerometer tap sensitivity |

### Touch patterns on `ffb2`

V3 does not use millisecond lists on the wire. A pattern is a timeline of **samples**: one byte per 50 ms, `0xFF` = not touching, anything else = touching (the app sends `0x35`). Patterns of more than 10 s are squeezed into at most 200 samples by lengthening the sample period (`TouchMessageContent.m4779c`).

**Sending** (`mo4105g`). Each frame is 20 bytes, padded with `0xFF`:

```text
frame 0:  slot  count  packets  R1 G1 B1  R2 G2 B2  flag  FF…
frame n:  up to 20 samples, then FF padding
```

`slot` is the partner slot (1–3), `count` the number of samples, `packets = ceil(count / 20)`, colour 1 and colour 2 the start and end colours, `flag` a boolean the app always sends as 0.

**Receiving.** The bracelet sends the same shape: a header `[slot, frames, packets]`, then `packets` frames of 20 samples. The app joins them, trims leading and trailing `0xFF`, and passes the samples on with the slot.

To convert to the millisecond form used by the other generations: each run of non-`0xFF` samples is a press and each run of `0xFF` a gap, 50 ms per sample.

## Touch patterns

In the app (and in the Bond cloud), a pattern is a list of milliseconds `[press, gap, press, gap, …, press]`, rounded to 50 ms with a minimum of 50 ms. V1, V2 and V4 send and receive this form directly. V3 uses the 50 ms sample form above. The Mini always uses `[500, 250, 500, 250, 500]`.

## Command queue and timing

Every generation sends through one `BleCommandHandler` queue. Its behaviour is worth copying:

| Rule | Value | Source |
| --- | --- | --- |
| GATT operations in flight | 1 | `BleCommandHandler` |
| Next command | after `onCharacteristicWrite`/`Read`/`DescriptorWrite`; V1 `ffa6` writes wait for the `ffa7` result instead | each manager's `mo4100b` |
| Timeout per attempt | 10 s | `BleCommandHandler$startAttempt$1` |
| Retries per command | 1 | `BaseCommand.mo4155b` |
| Retry delay after a negative ACK | 3.5 s | `BleCommandHandler$handleAckRetry$1` |
| Queue limit | 300 commands; the oldest whole message is dropped | `BleCommandHandler` |
| Pause while the bracelet is busy | 15 s (V2/V3 `MSG`), 30 s (V1 `0xF7`), 5 s (after `0x32`) | managers |
| Payload size | ≤ 20 bytes, no MTU request | all |

A message counts as delivered when its last write is acknowledged, and as failed (the app shows it as unsent) if any write in it fails twice.

## Firmware update

The app uses Nordic's DFU library (`no.nordicsemi.android.dfu`), with packages bundled in `res/raw`:

1. Request connection priority `HIGH`.
2. Send the generation's "enter DFU" command (V1 `0x0025`, V2 family `25 00 11 22 33 44`, V3 `01 30` then `01 2A`).
3. Scan for 8 s for `BOND_DFU`, `BOND_M_DFU`, `BOND_4_DFU` or `BOND_MINI_DFU`.
4. `DfuServiceInitiator(address).setForceDfu(true).setNumberOfRetries(3).disableResume().setZip(<res>)`.

`dfu_v260_hw203.zip` is an older legacy package (`dfu_version 0.5`, SoftDevice S130, `ble_bracelet_s130.bin`), used for one V2 hardware revision. Inferred from the file name: hardware 2.0.3. The others are plain application packages; `dfu_v311_hw3g.zip` is an nRF51822 image.

Keep a bracelet's firmware where the official app expects it. Downgrading or cross-flashing has not been tested.

## Implementation notes

A minimal client for a V2/V4/Mini bracelet only needs to subscribe, answer the token and AUID states, then write `0x26` and `0x32` frames.

### Minimal client (pseudocode)

```python
BASE = "d3c0{:04x}-add3-1d4b-{}-0000b5006bb1"
SVC_INFO = BASE.format(0x0001, "0000")
SVC_CTRL = BASE.format(0x0002, "0001")
SVC_V3 = BASE.format(0x0003, "0000")
API, BATT = BASE.format(0xFF10, "0000"), BASE.format(0xFF06, "0000")
TOKEN, AUID, STATE, EVENT, CMD, BONDTRIG = (
    BASE.format(0xFFA0 + n, "0001") for n in (1, 2, 4, 5, 6, 8)
)
NAMES = {"BOND", "Bond More", "BOND 4", "BOND MINI"}


async def connect(dev, auid: int):
    gatt = await dev.connect(transport="le")
    if SVC_V3 in gatt.services:
        return await v3_client(gatt, auid)  # see the V3 section
    api = (await gatt.read(API))[0]  # 0x42 V2, 0x44 V4, 0x45 Mini, else V1
    for c in (BATT, EVENT, STATE):
        await gatt.start_notify(c, on_notify)
    await gatt.read(STATE)  # V2 also writes the token straight away


async def on_state(gatt, data: bytes, auid: int):
    bond, charging, led_busy, motor_busy, touch_busy = data[:5]
    if bond == 0x82:
        await gatt.write(TOKEN, b"12345678")
    elif bond == 0x83:
        await gatt.write(AUID, auid.to_bytes(4, "little"))
    elif bond == 0x85:
        await gatt.read("00002a26-0000-1000-8000-00805f9b34fb")  # firmware


def led_motor(rgb, vib_ms, gap_ms, strength=80, queue=1, mode=2):
    fade = int(vib_ms * 0.25)
    body = bytes([0x26, 0, queue, strength]) + vib_ms.to_bytes(2, "little")
    body += bytes([mode, *rgb, 80])
    for v in (fade, vib_ms - 2 * fade, gap_ms, vib_ms + gap_ms):
        body += (v & 0xFFFF).to_bytes(2, "little")
    return body.ljust(20, b"\0")


async def play(gatt, pattern_ms, rgb):
    presses, gaps = pattern_ms[0::2], pattern_ms[1::2] + [0]
    for press, gap in zip(presses, gaps):
        await gatt.write(CMD, led_motor(rgb, press, gap))  # one at a time
    await gatt.write(CMD, bytes([0x32, 0, 0x11]).ljust(20, b"\0"))
```

The bracelet does not need a keepalive. Leave a colour on with `0x26` and total time `0xFFFF`, and clear it with mode 4.

### Open questions

These need a capture from real hardware or more static work:

- [ ] Which advertised name each generation really uses (the app only matches names, then reads `ff10`).
- [ ] Whether a bracelet set up by the official app accepts a new AUID without a factory reset (`RESET_CONFIG`, `0xEF`).
- [ ] Whether `ffa8` (V4/Mini) and the `ANCS_PARAM` path (V2) really are what starts OS pairing, and what fails without it.
- [ ] The V3 battery notification layout (type `0x09`) and which of `01 19/1B/41/42/1C` requests which report.
- [ ] The meaning of the V1 `0x0026` `mode` values and the time unit (`ms × 10 / steps`).
- [ ] How to request a V2 config read; this build parses replies but never asks.
- [ ] The full content of the `0x19` ship-mode report on `ffa5`.
- [ ] The V3 `ffb2` header `flag` byte and non-`0x35` sample values from the bracelet (perhaps touch position or pressure).

### Evidence

REA 6.4.0 `decode-android-resources` (apktool 3.0.3) on the APK above:

| Claim | REA evidence ID |
| --- | --- |
| Package identity (`com.impossible.bondtouch` 11.2.0 / 490), manifest permissions (`BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`, companion device permissions) | `ev_0e265106841d2ea3dc69e3a2cec178243899f47d45e30be59879cb29c6404a93` |

REA's Android code operations were unavailable (`capability_unavailable`: no `jadx-headless-mcp` JAR), so everything else comes from reading a full jadx decompile, cited by class name in each section. The `UserMenu` → `0x24` mapping and the V3 battery offsets were also checked against apktool smali. Obfuscated names (`rb0`, `m4223d`, `mo4105g`, …) apply to 11.2.0 only.

## Appendix: Bond Heart

The same app also drives **Bond Heart**, a separate product that plays back a partner's heartbeat. It uses Nordic's `Android-BLE-Library` (`heartble/bluetooth/HeartBleManager`) rather than the bracelet code. It is summarised here because it shares the setup ideas.

| Item | Value |
| --- | --- |
| Advertised name | `BondHeart`; `BOND_H_DFU` in bootloader |
| Service | `014f0a00-02cd-4dd4-842d-39fdfabc66f9` |
| `014ffa01-…` | Notify: state, events and ACKs. Write: heartbeat pattern |
| `014ffa02-…` | Write: commands |
| `014ffa03-…` | Read: `[playedCount u32 LE, beatCount u32 LE]`. The app logs whether it requires encryption |
| Battery | `180f`/`2a19`, notify |
| Firmware images | `heart_dfu_v102`, `heart_dfu_v103` (target 1.0.3.10) |

Commands on `fa02`: token `09 37 36 35 34 33 32 31 30` (ASCII `76543210`), AUID `0A <u32 LE>` padded to 9 bytes (the AUID is stored separately as `HEART_SAVED_AUID`), paired signal `07 31`, firmware request `10 33`.

Pattern on `fa01`: `01` then up to 19 bytes, each `(interval_ms − 260) × 255 / 1280`. Inferred: beat-to-beat intervals of 260–1540 ms (about 39–230 BPM).

Notifications on `fa01`: `01 <state>` with states `0x82` `WAITING_TOKEN`, `0x83` `WAITING_AUID`, `0x84` `OOBE`, `0x85` `CONNECTED`; `02 <event>` with events `0x13` paired signal, `0x14` timeout, `0x15` wrong token, `0x16` unsupported message, `0x17` not authorised, `0x18`/`0x19` factory button pressed/released, `0x1A` factory shake; and ACKs `<type> <ackId> …`, inferred to be type `0x0A` as on V3. ACK ids: `1` reset, `2` erase, `3` vibration (`[level]`), `4` LED brightness (`[a, b]`), `5` LED colour (`[R, G, B]`), `0x1C` firmware (`[a, b, c, d]`).
