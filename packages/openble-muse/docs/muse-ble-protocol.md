# Muse BLE protocol

Protocol notes for Interaxon Muse EEG headbands. They combine a static reading of the official Muse Android app, which embeds Interaxon's protocol library (libmuse), with existing open-source work. The `openble-muse` library in this package implements them; see [Library choices](#library-choices) for where it picks between the app and public work.

This is interoperability documentation. One live headband has since been checked against it; see [Live check](#live-check). Everything else is still static.

### Live check

On 2026-10-16 the `openble-muse` library drove a Muse S over bleak on macOS, with no Muse app running, using `prepare()` with the default preset and 10 s of streaming.

| Item | Seen |
| --- | --- |
| Advertisement | name `MuseS-36C4`; manufacturer data under company ID `0x0030`, `01 05 00 00 00 00 00 00`. Byte 1 is `5` = `aster`, read the way bleak hands it over (company ID stripped) |
| GATT | `273e0001` (notify, write-without-response) and `273e0002`–`273e0012`: 18 characteristics, one of the counts the app accepts |
| `v7` reply | `{"ap":"headset","sp":"Aster_revD","tp":"consumer","hw":"00.8","bn":7,"fi":"9623a79","fw":"1.0.1","bl":"0.0.28","pv":1,"rc":0}`. `pv` 1 to `v7`. `fi` is not in the app's key list |
| `s` reply | `sn` `5008-…` → `MU_04`; `bp` 25; `ps` 81, then 33 after `p21`; `hs`, `ts` present; no `ln`, `ms` |
| Sequence | `v7` → `s` → `h` → `p21` → `s` → `dc001` (one send) → data; `h` at the end. Every command answered `{"rc":0}` |
| Data, 10 s | 214 notifications on each of `0003`–`0006` (4 EEG channels, 21.4/s × 12 = 256 Hz); 172 each on `0009` and `000a` (52 Hz); 47 on `0008`; 1 on `000b`. No counter gaps. `p21` sent nothing on the PPG or thermistor characteristics |
| Accelerometer | about 1 g at rest with `raw / 16384`, e.g. `(0.381, 0.089, −0.936)` |
| Battery packet | `[0]`/512 = 30 % while `bp` said 25; `[1]`×2.2 = 3100 mV; `[2]` and `[3]` were 0 |
| EEG | raw values spanned 0–4095 with a mean near 1300: the electrodes were railing, so this run does not settle the EEG scale or offset |

`ps` is the preset code read as hexadecimal and sent as a JSON integer: 33 = `0x21`, 81 = `0x51`.

## Overview

Muse headbands from Muse 2016 onward are BLE GATT peripherals with one vendor service, `0xFE8D`. The host controls the headband with short ASCII commands such as `s\n`, sent length-prefixed on one characteristic. The headband answers on the same characteristic with JSON objects that always carry a return code `rc`. There is no app-level authentication or encryption, and the app never bonds.

The version reply's protocol version (`pv`) selects one of three data layouts. The app accepts `pv` 1–7.

| `pv` | Layout | Headbands | Characteristics |
| --- | --- | --- | --- |
| 1–2 | **Per-sensor**: one notify characteristic per channel; 20-byte packets with a big-endian 16-bit counter and big-endian samples | Muse 2016, Muse 2, Muse S | `273e0002`–`273e0012` |
| 3 | **Universal v3**: one characteristic carries timestamped frames of typed sub-packets, packed little-endian | early `MS-03` (Muse S Athena) firmware (inferred) | `273e0013` |
| ≥ 4 | **BLE4**: a newer framing with 14-bit EEG, 20-bit optics and a frame counter. Version 5 and up add a time-sync characteristic | current Muse S Athena firmware; this is what the open-source Athena projects decode | `273e0013`, `273e0014`, `273e0015` |

## Sources

| Item | Value |
| --- | --- |
| App | Muse for Android 55.1 (`com.interaxon.muse`, versionCode 829). APKPure XAPK, SHA-256 `081a8c8bc3ba8ce72d8d3aee54ca333127e54406784ea3834300444375fcf157` |
| Base APK | `com.interaxon.muse.apk`, SHA-256 `09abde429bbf2ca56246ddf8d5f50a300712bc6760c41b5cb8507d73f2c68a2a`. Contains the Java BLE glue `com.choosemuse.libmuse.*` |
| Native split | `config.arm64_v8a.apk`, SHA-256 `27656aeb8e519efbabe03d0fd31a0298c74f9ebe4662e211dffc94f4d6a03494` |
| Protocol library | `lib/arm64-v8a/libdorothy.so`, SHA-256 `39a5278e6de2e2f7d373d75650f0eae2837718a2bb554ba1e4f396234e98a64d`. It embeds libmuse (namespace `interaxon::nevis`). Not stripped (C++ symbols present), no DWARF, built without optimisation |
| Internal code names | `nevis` (BLE connector and Muse 2016), `blackcomb` (Muse 2), `aster` (Muse S), `athena` (Muse S Athena), `glasses` (`GL-01`) |

**Prior public work** (cited as "Public" below):

| Project | Covers |
| --- | --- |
| [urish/muse-js](https://github.com/urish/muse-js) | Per-sensor protocol: UUIDs, command framing, `v1`/`s`/`h`/`d`/`p21`/`p20`/`p50`, JSON reply reassembly, EEG/IMU/PPG/telemetry decoding |
| [alexandrebarachant/muse-lsl](https://github.com/alexandrebarachant/muse-lsl) | Sample rates, IMU scale factors, Athena default preset `p1041` and EEG scale `1450/16383` |
| [nexon33/amused](https://github.com/nexon33/amused) (amused-py) | First open Athena implementation: start-up sequence, `p1034`/`p1035`, tag table, 14-bit/20-bit LSB-first packing, IMU scaling |
| [DominiqueMakowski/OpenMuse](https://github.com/DominiqueMakowski/OpenMuse) | Athena presets and their sensor sets, sensor specifications |
| [eugenehp/muse-rs](https://github.com/eugenehp/muse-rs) | Both firmware families: framing, start-up sequences, Athena packet header, tag table, scaling, battery |

**Method.** The app was analysed statically.

- REA 6.4.0 (`npx rea-agents@6.4.0`) with the Hopper 6.6.0 provider produced the pseudocode evidence listed at the end.
- Most of the reading used the symbol table and an annotated arm64 disassembly (Capstone 5.0.7 + pyelftools) that resolves strings, GOT and PLT references.
- JADX 1.5 decompiled the Java glue and the libmuse enums (`CharacteristicId`, `MuseModel`, `MusePreset`, `MuseDataPacketType`).

Nothing was observed at runtime. Each section names the libmuse function it was read from.

**Evidence key.**

- **Observed:** read directly from the app's code, with the function cited.
- **Inferred:** reasoned from code but not proven.
- **Public:** taken from the projects above.

Where the app and public work disagree, both are given.

**Scope.** Talking to headbands you own from an open-source client. Out of scope: the 2014 Muse (`MU-01`, classic Bluetooth); the app's signal-processing algorithms; cloud features; firmware update; and the contents of the optional licence blob.

## Models

The app picks the model from the first character of the headband's serial number (`sn` in the status reply). Observed in `interaxon::bridge::get_model_from_serial_number`. Product names are the common public names. Where no public mapping was found, the row says so.

| `MuseModel` | Product | Serial starts with | Capability set | Default preset |
| --- | --- | --- | --- | --- |
| `MU_01` | Muse 2014 | `1` | classic BT (not covered) | `14` |
| `MU_02` | Muse 2016 | `2` | `nevis` | `21` |
| `MU_03` | Muse 2 | `4`, second char ≤ `2` | `blackcomb` | `21` |
| `MU_06` | later Muse 2 hardware (inferred from the capability set) | `4`, second char > `2` | `blackcomb` | `21` |
| `MU_04` | Muse S | `5` | `aster` | `21` |
| `MU_05` | later Muse S hardware (inferred) | `6` | `aster` | `21` |
| `MS_03` | Muse S Athena (Public: amused calls it "Gen 3, MS_03") | `7` | `athena` | `1021` |
| `GL_01` | internal "glasses" device | `3` | `glasses` | — |
| `AMHL_01` | internal, product unknown | `9` | `blackcomb` | — |

Default presets come from `interaxon::cmd::get_default_preset`. Any other first character throws "unknown muse model from serial number".

## Discovery and advertising

Observed in `MuseManagerAndroid` and `LeDevice.getInfo`.

- **Scan filter:** service UUID `0000FE8D-0000-1000-8000-00805F9B34FB`, scan mode `SCAN_MODE_LOW_LATENCY`.
- **Name:** headbands advertise `Muse-XXXX`. A name starting `Muse` is treated as a headband.
- **Manufacturer data:** the app takes the first manufacturer-specific AD entry, whatever its company ID. Byte 1 is a hardware generation: `5` = `aster`, `6` = `letto` (product unknown), `7` = `athena`.
- **Fallback name:** if the OS reports no name, the app builds `Muse-` + the last four hex digits of the MAC (`MuseS-` when byte 1 is 5, 6 or 7). After connecting, the `hn` field of the status reply wins.

## GATT layout

One primary service, `0xFE8D`. Every characteristic UUID has the form `273eXXXX-4c4d-454d-96be-f03bac821358`. The mapping below is observed in `CharacteristicMapperImpl::CharacteristicMapperImpl()`, with names from the Java `CharacteristicId` enum. The muse-js names for the same UUIDs agree (Public).

| UUID suffix | `CharacteristicId` | Role | Format |
| --- | --- | --- | --- |
| `0001` | `SERIAL` | Commands (write) and JSON replies (notify) | `[len][ASCII]` |
| `0002` | `SIGNAL_AUX_LEFT` | EEG, left auxiliary | 12 × u12 |
| `0003` | `SIGNAL_TP9` | EEG, left ear | 12 × u12 |
| `0004` | `SIGNAL_FP1` | EEG, left forehead (AF7) | 12 × u12 |
| `0005` | `SIGNAL_FP2` | EEG, right forehead (AF8) | 12 × u12 |
| `0006` | `SIGNAL_TP10` | EEG, right ear | 12 × u12 |
| `0007` | `SIGNAL_AUX_RIGHT` | EEG, right auxiliary (muse-js "AUX", the 5th channel) | 12 × u12 |
| `0008` | `DRL_REF` | DRL and REF electrodes | 12 × u12 |
| `0009` | `GYRO` | Gyroscope | 9 × s16 |
| `000a` | `ACCELEROMETER` | Accelerometer | 9 × s16 |
| `000b` | `BATTERY` | Battery / telemetry | 4 × u16 |
| `000c` | `MAGNETOMETER` | Magnetometer (glasses) | 9 × s16 |
| `000d` | `PRESSURE` | Pressure (glasses) | 2 × u32 |
| `000e` | `ULTRA_VIOLET` | UV (glasses) | 4 × u16 |
| `000f` | `PPG_AMBIENT` | PPG ambient | 6 × u24 |
| `0010` | `PPG_IR` | PPG infrared | 6 × u24 |
| `0011` | `PPG_RED` | PPG red | 6 × u24 |
| `0012` | `THERMISTOR` | Skin thermistor | 12 × u12 |
| `0013` | `UNIVERSAL` | Multiplexed stream (`pv` ≥ 3) | see [Universal v3](#universal-v3-stream-pv-3) and [BLE4](#ble4-stream-pv--4) |
| `0014` | `MUSE_DEBUG` | Athena; subscribed with `0013` (muse-rs also reads data frames here) | BLE4 frames (Public) |
| `0015` | `TIME_SYNC` | Athena time sync, only when `pv` ≥ 5 | see [Time sync](#time-sync) |

**Which characteristics each model uses.** Observed in `DeviceCapability::get_characteristics(model, pv)` and its initialisers. `SERIAL` is always present as well.

| Capability set | Data characteristics |
| --- | --- |
| `nevis` (`MU_02`) | `0002`–`0008`, `000b`, `000a`, `0009` |
| `blackcomb` (`MU_03`, `MU_06`, `AMHL_01`) | `nevis` + `000f`, `0010`, `0011` |
| `aster` (`MU_04`, `MU_05`) | `blackcomb` + `0012` |
| `athena` (`MS_03`) | `0013`, `0014`, `0015`. `0015` is dropped when `pv` < 5 |
| `glasses` (`GL_01`) | `0002`–`0008`, `000b`, `000a`, `0009`, `000c`, `000d`, `000e` |

### Android GATT handling

Observed in `LeDevice`:

1. `connectGatt(autoConnect = false)`, then `requestConnectionPriority(HIGH)`, then a reflective `BluetoothGatt.refresh()` to clear the service cache.
2. On connect, `requestMtu(512)` with a 5 s watchdog and one retry. `discoverServices()` runs only after the MTU callback.
3. Characteristics are mapped by UUID. The connection is dropped unless the number of mapped characteristics is 1 (bootloader: `SERIAL` only), 2, 3, 4, 11, 14, 17 or 18.
4. Writes use `WRITE_TYPE_NO_RESPONSE` when the characteristic supports it, otherwise write-with-response.
5. Subscriptions: `setCharacteristicNotification`, then write the first descriptor (the CCCD). The value is `02 00` (indications) if the characteristic only indicates, otherwise `01 00` (notifications). `00 00` stops them.
6. `isPaired()` returns `false`, so no bonding happens.

## Command channel

### Framing

Observed in `nevis::ConnectorImpl::send`; muse-js and muse-rs use the same framing (Public).

```
byte 0       : n = number of command bytes that follow, including the '\n' (n & 0x1F, n ≤ 19)
bytes 1..n   : ASCII command, always terminated with '\n' (cmd::nevis::_::suffix)
```

`s` is sent as `02 73 0a`. Anything longer than 19 bytes raises "Detected payload larger than 19 bytes".

- Commands that start with `L` or `Q` are fire-and-forget: the app expects no reply.
- For every other command, the app marks a reply as pending and sends nothing else until it arrives.

### Replies

Observed in `ConnectorImpl::did_receive_value_for_characteristic_deferred`. A reply can span several notifications on `273e0001`:

```
byte 0       : n = number of valid payload bytes (byte0 & 0x1F)
bytes 1..n   : the next n characters of the reply (the rest of the notification is padding)
```

Append each chunk to a buffer. When the buffer parses as JSON (`ConnectorImpl::is_valid_json`), that is one complete reply; clear the buffer. muse-js instead accumulates until it sees `}` (Public). Every reply carries an integer `rc`; `0` means success. A reply with no `rc` is an error ("a serial command response from the headband did not contain a return code").

## Command reference

The app's command builders are in `interaxon::cmd::nevis`, observed.

| Command | Builder | Meaning | Reply |
| --- | --- | --- | --- |
| `v7` | `version(7)`, called from `VersionState::on_enter` | Version query. The digit is the protocol version the app offers (printed in hex). Public clients send `v1` (muse-js), `v4` (muse-rs) or `v6` (amused) | version JSON |
| `s` | `status()` | Status / configuration | status JSON |
| `h` | `halt_streaming()` | Stop streaming | `{"rc":0}` |
| `p<code>` | `set_preset(preset)` | Select a preset, e.g. `p21` or `p1035`; see [Presets](#presets) | `rc` |
| `dc001` | `start_streaming(0xC001)` | Start streaming: `d` + hex(`0xC001`). muse-js and the per-sensor path in muse-rs send plain `d` (Public) | `rc` |
| `k` | `keep_alive()` | Keep-alive while paused, every 2.5 s | `rc` |
| `*1` | `boot_to_headset()` | Leave the bootloader and start the headset application | `rc` (`1` = CRC failure) |
| `*0` | `boot_to_bootloader()` | Reboot into the bootloader (firmware update) | — |
| `L1` / `L0` | `indicator_led_on/off()` | LED indicator on / off. `MU_04`, `MU_05` and `MS_03` only | none |
| `F1` … | `licensing()` | Optional licence upload; see [Licensing](#licensing) | `rc` |
| `Q<k> C,<12 hex>` | `ConnectorImpl::sync_command` | Clock-sync reply, universal v3 only; see [Time sync](#time-sync) | none |

**`rc` meanings** (from the app's error strings):

- `p…`:
  - the headband refuses while streaming;
  - an invalid preset gives "are you mixing up MU-01 & MU-02 presets?".
- `dc001`: `2` = "The headband license is not valid". Another non-zero value is treated as "the headband was already streaming data".

**Notch filter.** `set_notch_frequency` sends nothing on BLE headbands; it only logs.

### Version reply

Keys read in `bridge::MuseVersion::make_version`. Meanings are inferred from the `MuseVersion` getters.

| Key | Meaning | Values seen in code |
| --- | --- | --- |
| `rc` | return code | `0` |
| `ap` | running state | `"headset"`, `"bootloader"` |
| `sp` | BSP version | |
| `tp` | firmware type | `"consumer"`, `"research"`, `"test"` |
| `hw` | hardware version | |
| `bn` | firmware build number | |
| `fw` | firmware version | |
| `bl` | bootloader version | |
| `pv` | protocol version (int) | the app accepts 1–7 |
| `be` | unknown (read by the app; not in older libmuse) | |
| `fi` | not read by the app; a Muse S on firmware 1.0.1 sent `"9623a79"`, which looks like a commit hash | live check |

### Status reply

Keys read in `bridge::MuseConfigurationImpl::make_configuration`. Meanings are inferred from the `MuseConfiguration` getters.

| Key | Meaning | Required |
| --- | --- | --- |
| `rc` | return code | yes |
| `hn` | headband name, e.g. `Muse-1234` | yes |
| `sn` | serial number (selects the model) | yes |
| `ma` | Bluetooth MAC | yes |
| `id` | microcontroller ID | yes |
| `bp` | battery percent | yes |
| `ps` | current preset: the code as a hex number, sent as an int (33 = preset `21`; live check) | no |
| `ts` | test-mode flag (logs "test mode enabled") | no |
| `hs` | headset serial number | no |
| `ln` | licence nonce | no |
| `ms` | unknown | no |

## Connection lifecycle

`nevis::ConnectorImpl` is a table-driven state machine. The tables are `next_state_s_` (goal: streaming), `next_state_p_` (paused), `next_state_d_` (disconnected), `next_state_u_` (firmware update) and `next_state_cs_` (configuration changed), observed. The path to streaming is:

| # | State | Host action | Waits for | Timeout |
| --- | --- | --- | --- | --- |
| 1 | `Connecting` | GATT connect, MTU 512, discover | link up | 25 s (`BLE_CONNECT`) |
| 2 | `SerialSetup` | enable notifications on `273e0001` | CCCD written | 6 s (`ENCRYPTION`) |
| 3 | `Version` | send `v7` | version JSON | 10 s (`VERSION`) |
| 4 | `VersionCheck` | send `s` | status JSON | 8 s (`IX_STATUS`) |
| 5 | `Halt` | send `h` | `{"rc":0}`; any other content → disconnect | 6 s (`SERIAL`) |
| 6 | `Preset` | send `p<code>` | `rc` | 6 s (`SERIAL`) |
| 7 | `Override` | — (no-op) | | |
| 8 | `Status` | send `s` | status JSON | 8 s (`IX_STATUS`) |
| 9 | `SetupBleChars` | enable notifications on the data characteristics | CCCDs written | 6 s (`SERIAL`) |
| 10 | `StartStreaming` | send `dc001` | `rc` | 6 s (`SERIAL`) |
| 11 | `Streaming` | — | data; 6 s with no data is an error | 6 s (`DATA`) |

Other app timeouts (`interaxon::cmd::*`, ms):

| Constant | Value | Note |
| --- | --- | --- |
| `KEEP_ALIVE_TIMEOUT` / `KEEP_ALIVE_DELTA` | 2500 / 2500 | paused keep-alive |
| `DISCONNECT_TIMEOUT` | 6000 | |
| `RECONNECT_TIMEOUT` | 5000 | |
| `HEADSET_BOOT_TIMEOUT` | 10000 | |
| `LICENSE_TIMEOUT` | 8000 | |
| `TIMESYNC_INTERVAL` | 5000 | |
| `BLE_DATA_TIMEOUT` | 150000 | unit and use unconfirmed |
| `DRAIN_TIMEOUT` | 3500 | |
| `EVENT_TRIGGER_TIMEOUT` | 40000 | |
| `TICK_TIMEOUT` | 20 | |

**Version check** (`VersionCheckState`):

- `ap == "bootloader"` → send `*1`, wait for the reboot, then reconnect from step 1.
- The protocol version handshake (`do_protocol_version_handshake`) accepts `1 ≤ pv ≤ 7`. Outside that range the connection fails with "firmware too old" or "libmuse too old".
- `DataHandlerImpl::handle` routes data:
  - `pv` < 4 → `handle_legacy`: per-sensor packets, or universal v3 on `273e0013`;
  - `pv` ≥ 4 → `handle_ble4`.
- For `athena` with `pv` ≥ 5, the app also subscribes to `273e0015` and runs time sync. `StartStreamingState` has an `on_time_synchronized` hook (inferred: streaming starts once the clocks are aligned).

**Other goals.**

- *Pause:* `Streaming → StopStreaming (h) → Paused`. `Paused` sends `k` every 2.5 s.
- *Disconnect:* `h` if streaming, then GATT disconnect.
- *Preset change while connected:* the configuration-changed table returns to `Halt` and repeats steps 6–11.

There is no keep-alive while streaming; the data stream is the liveness signal.

**Public start-up sequences for Athena**, for comparison:

- muse-rs: `v4` → `s` → `h` → `p1045` → `dc001` × 2 → `d` → `L1`.
- amused: `v6` → `s` → `h` → `p21` → subscribe `273e0013` → `dc001` + `L1` → `h` → `p1034` → `dc001` + `L1`. amused notes that `dc001` must be sent twice.

The app's state machine sends `dc001` once per start. Why public clients need two is an open question.

### Licensing

`LicensingState` is not on the normal path. It runs only after the app has been given licence data.

- The blob must be under 4096 bytes.
- It is sent as serial commands that start with `F1` (`cmd::nevis::licensing`) and carry `0 `, a hex offset and `,` around raw bytes.
- `rc` `1` = out of memory; `2` = licence error.

A client that does not use licensed features never needs this.

## Presets

A preset is sent as `p` + the code, for example `p21\n`. The codes are observed in `muse_command.cpp`'s `PRESET_MAP`:

- `10`, `12`, `14`, `AB`, `AD`: Muse 2014;
- `20`–`23`, `31`, `32`, `50`–`55`, `60`, `61`, `63`;
- Athena: `1021`–`1029`, `102A`, `1031`–`1036`, `1041`–`1046`.

`model_for_preset` maps every code from `1021` up to `MS_03`. EEG channel counts for the older presets come from `PRESET_CHANNELS`, observed.

| Code | EEG ch (app) | Contents (Public) |
| --- | --- | --- |
| `20` | 5 | EEG + AUX (muse-js, muse-rs) |
| `21` | 4 | EEG only; default for every non-Athena BLE model |
| `22` | 4 | |
| `23` | 6 | |
| `50` | 5 | EEG + PPG (muse-js, muse-rs) |
| `51`, `52` | 4 | |
| `53`, `54` | 6 | |
| `55` | 4 | |
| `60` | 5 | |
| `61` | 4 | |
| `63` | 6 | |
| `31`, `32` | 4, 0 | glasses only |

Athena presets as described by OpenMuse, which notes the table is "derived from the signature of the data packets" (Public):

| Code | EEG | Optics | Red LED |
| --- | --- | --- | --- |
| `1034`, `1043` | EEG8 | Optics8 | bright |
| `1044` | EEG8 | Optics8 | dim |
| `1035` | EEG4 | Optics4 | dim |
| `1041`, `1042` | EEG8 | Optics16 | bright |
| `1045` | EEG8 | Optics4 | dim |
| `1046` | EEG8 | Optics4 | — |

All of these also stream accelerometer/gyro and battery. muse-lsl defaults to `p1041`; amused uses `p1034`; muse-rs uses `p1045`. The app's own default for `MS_03` is `p1021`, which none of the public tables describe.

## Per-sensor data packets (`pv` 1–2)

All of these are 20-byte notifications. Observed in `DataHandlerImpl::handle_legacy`, `parse_packet12/16/24/32` and `PacketConverter::convert_packet`; matches muse-js (Public).

```
bytes 0..1   : packet counter, u16 big-endian, +1 per notification on that characteristic
bytes 2..19  : samples, big-endian, packed as below
```

| Width | Unpack (index `i` from 0) | Max samples |
| --- | --- | --- |
| 12-bit | byte offset `o = 2 + (3*i)//2`; even `i`: `b[o]<<4 \| b[o+1]>>4`; odd `i`: `(b[o]&0x0F)<<8 \| b[o+1]` | 12 |
| 16-bit | `b[2+2i]<<8 \| b[3+2i]` | 9 |
| 24-bit | `b[2+3i]<<16 \| b[3+3i]<<8 \| b[4+3i]` | 6 |
| 32-bit | `b[2+4i..5+4i]` big-endian | 4 |

| Characteristic | Parse | Layout | App conversion | Public conversion |
| --- | --- | --- | --- | --- |
| EEG `0002`–`0007` | 12 × u12 | 12 samples of one channel, 256 Hz (Public) | µV = raw × 805.86/2000 ≈ 0.40293 (= 1650/4095); no offset subtracted | `(raw − 2048) × 0.48828125` (muse-js, muse-rs) |
| DRL/REF `0008` | 12 × u12 | 6 samples × (DRL, REF), interleaved | µV = raw × 805.86 | — |
| Battery `000b` | 4 × u16 | `[0]` charge, `[1]` fuel gauge, `[2]` ADC, `[3]` temperature | % = `[0]`/512; mV = `[1]`×2.2; ADC mV = `[2]`×4.4; °C = `[3]` | same `[0]`/512, `[1]`×2.2, `[3]` (muse-js) |
| Accelerometer `000a` | 9 × s16 | 3 samples × (x, y, z), 52 Hz | g = raw / 16384 | 0.0000610352 g/LSB |
| Gyro `0009` | 9 × s16 | 3 samples × (x, y, z), 52 Hz | °/s = raw × **−**0.0074768 | +0.0074768 (muse-js) |
| Magnetometer `000c` | 9 × s16 | 3 × (x, y, z) | raw / 4096 | — |
| Pressure `000d` | 2 × u32 | | `[0]`/4096 and `[1]`/480 + 42 | — |
| UV `000e` | 4 × u16 | | linear mix (constants −2.22, −1.33, −2.95, −1.74, 0.001461, 0.002591, ×0.5) | — |
| PPG `000f`/`0010`/`0011` | 6 × u24 | 6 samples of one wavelength, 64 Hz | raw × 805.86 | raw 24-bit (muse-js) |
| Thermistor `0012` | 12 × u12 | 12 samples | V = raw/4096 × 2.9; R = 62000·V/(2.9−V); °C = 1/(1/298.15 + ln(R/100000)/4700) − 273.15 | — |

IMU values are two's complement; the app computes `(v & 0x7FFF) − (v & 0x8000)`. Other widths are unsigned. The app logs out-of-order and duplicate counters and fills gaps with NaN packets.

## Universal v3 stream (`pv` 3)

Observed in `UniversalDataHandler::handle`, the `EegBuffer`/`DrlBuffer`/`PpgBuffer`/`ImuBuffer`/`BattBuffer`/`ThermBuffer::receive_data` functions, and `PacketBuffer::add_timestamp`. The app unpacks each sub-packet and repacks it into the per-sensor packets above, so the same converter is used. No public project documents this revision; it appears to precede the BLE4 framing that current Athena firmware uses.

**Frame.** One notification on `273e0013`:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | frame length; must equal the notification length |
| 1 | 2 | not read |
| 3 | 6 | frame time, u48 little-endian. The app multiplies it by 1000 |
| 9 | … | sub-packets |

**Sub-packet:**

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | tag: low nibble = type, high nibble = rate code |
| 1 | 1 | sequence number, u8, per type |
| 2 | 3 | time offset, s24 little-endian; sample time = frame time × 1000 + offset × 10 |
| 5 | n | payload |

**Rate code:** 1 = 256 Hz, 2 = 128, 3 = 64, 4 = 52, 5 = 32, 6 = 16, 7 = 10, 8 = 0.1 Hz.

| Type | Payload | Contents |
| --- | --- | --- |
| 1 | 24 B | EEG, 4 samples × 4 ch × 12-bit |
| 2 | 27 B | EEG, 5 channels sent as 6: 3 samples × 6 ch × 12-bit |
| 3 | 27 B | EEG, 3 samples × 6 ch × 12-bit |
| 4 | 18 B | DRL/REF, 12 × 12-bit |
| 5 | 24 B | PPG, 3 rows of 8 bytes; each row is 3 × 20-bit values, one per wavelength |
| 6 | 12 B | accel x, y, z then gyro x, y, z, s16 little-endian |
| 7 | 8 B | battery, 4 × u16 little-endian (same fields as the per-sensor packet) |
| 8 | 3 B | thermistor, u24 little-endian |
| 9 | 13 B after the tag | time sync; see [Time sync](#time-sync) |

**Packing.**

- **12-bit** values are packed little-endian, two per three bytes: `s0 = b0 | (b1 & 0x0F) << 8`, `s1 = b1 >> 4 | b2 << 4` (`pack1x12`). Within an EEG payload, the channels of one time step are consecutive.
- **20-bit** PPG rows `r0..r7`: `v0 = r0 | r1<<8 | (r2&0x0F)<<16`; `v1 = r2>>4 | r3<<4 | r4<<12`; `v2 = r5 | r6<<8 | (r7&0x0F)<<16` (`pack3x19`).

**Channel order**, from the buffer accessors (`EegBuffer::TP10()` = 0, `FP2()` = 1, and so on):

| Stream | 0 | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- | --- |
| EEG | TP10 | AF8 | TP9 | AF7 | AUX right | AUX left |
| PPG | red | IR | ambient | | | |
| IMU | accelerometer | gyro | | | | |

## BLE4 stream (`pv` ≥ 4)

Observed in `Ble4DataHandler::handle`, `parse_subpackets`, the `Ble4*Buffer::receive_data` functions, `Ble4PacketBuffer::add_timestamp` and `ParsedPacket::convert`. The tag values and payload sizes match amused and muse-rs exactly (Public).

**Frame.** One notification on `273e0013` (muse-rs also reads frames on `273e0014`):

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | frame length; must equal the notification length |
| 1 | 2 | frame counter, u16 little-endian. The app reorders out-of-order notifications by this counter (`Ble4NotificationReorderer`) |
| 3 | 6 | device clock, u48 little-endian. muse-rs describes it as a 256 kHz clock (Public). The app shifts it left by 28 bits before adding sub-packet offsets |
| 9 | … | sub-packets |

**Sub-packet:** tag byte, then 4 metadata bytes, then the payload:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | tag: low nibble = type, high nibble = rate code |
| 1 | 1 | sequence number, u8, per type; duplicates are skipped and gaps logged |
| 2 | 3 | time offset, s24 little-endian, × 100 |
| 5 | n | payload |

**Rate code** (`BLE4_PACKET_ID_1CHAR_FREQUENCY`): 1 = 256 Hz, 2 = 128, 3 = 64, 4 = 52, 5 = 32, 6 = 16, 7 = 10, 8 = 1, 9 = 0.1 Hz.

| Type | Common tag | Sample struct | Payload | Contents | Public |
| --- | --- | --- | --- | --- | --- |
| 1 | `0x11` | `Samples_4x14bit` | 28 B | EEG, 4 ch × 4 samples | EEG 4ch, 256 Hz |
| 2 | `0x12` | `Samples_4x14bit` | 28 B | EEG, 8 ch × 2 samples | EEG 8ch, 256 Hz |
| 3 | `0x53` | `Samples_2x16bit` | 24 B | DRL/REF, 6 × 2 values | DRL/REF, 32 Hz |
| 4 | `0x34` | `Samples_4x20bit` | 30 B | optics, 4 ch × 3 samples | Optics 4ch, 64 Hz |
| 5 | `0x35` | `Samples_4x20bit` | 40 B | optics, 8 ch × 2 samples | Optics 8ch |
| 6 | `0x36` | `Samples_4x20bit` | 40 B | optics, 16 ch × 1 sample | Optics 16ch |
| 7 | `0x47` | `Samples_6x16bit` | 36 B | IMU, 3 samples × (accel xyz, gyro xyz) | ACC/GYRO, 52 Hz |
| 8 | `0x88`/`0x98` | `Samples_10x16bit` | 20 B | battery (rate code 8 = 1 Hz, 9 = 0.1 Hz) | muse-rs: `0x88` newer firmware, 188–230 B, ~0.2 Hz; `0x98` older firmware, 20 B, 1 Hz |

"Common tag" is the full tag byte for the usual rate. Any other type is rejected ("received unexpected BLE packet type").

**Packing.** Values are packed least-significant bit first.

- `Samples_4x14bit` reads 7 bytes as a little-endian 56-bit word and takes 14-bit fields at bit 0, 14, 28 and 42.
- `Samples_4x20bit` packs four 20-bit values into 10 bytes the same way.
- 16-bit values are signed little-endian.

This matches amused ("14-bit unsigned, LSB-first", "20-bit unsigned, LSB-first") and muse-rs (Public).

**Conversion** (`ParsedPacket::convert`, observed):

| Data | App | Public |
| --- | --- | --- |
| EEG | µV = raw × 177.0128/2000 = raw × 1450/16383 ≈ 0.08851; no offset subtraction found | `1450/16383` µV/bit (amused, muse-lsl); `(raw − 8192) × 0.0885` (muse-rs) |
| Accelerometer | g = raw / 16384 | 0.0000610352 g/bit |
| Gyro | °/s = raw × −0.0074768 | −0.0074768 (amused, muse-rs) |
| Optics | raw × 3.0517607e-5 (`OPTICS` packets) | raw 20-bit |
| Battery | % = `[0]` / 256; other fields scaled by 0.078125, 0.7143, 5.625, 156.25 (meaning unknown) | `u16_LE / 256` (muse-rs) |
| DRL/REF | raw | — |

**Channel order** (Public; not resolved in the app):

- EEG (muse-rs): TP9, AF7, AF8, TP10 for 4 channels; 8 channels add FPz, AUX_R, AUX_L, AUX. OpenMuse describes "4 EEG channels + 4 amplified Aux channels".
- Optics 4 ch (muse-rs): channels 0–2 are ambient, infrared and red. OpenMuse lists 850 nm IR, 730 nm near-IR and 660 nm red.

## Time sync

**Universal v3** (`pv` 3), from the time-sync branch of `UniversalDataHandler::handle` and `ConnectorImpl::clock_sync_response` / `sync_command`. The type-9 sub-packet is 14 bytes including the tag:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | tag |
| 1 | 4 | not read |
| 5 | 6 | device time, u48 little-endian |
| 11 | 2 | u16 little-endian |
| 13 | 1 | flag; `1` resets the app's sync filters |

The app answers with the fire-and-forget command `Q<k> C,<host time, 12 hex digits, most significant first>\n`. Host time is wall-clock ms. The app filters several rounds with medians (`SyncBuffer`).

**BLE4 with `pv` ≥ 5.** `ConnectorImpl::timesync()` builds a binary message: a leading byte plus up to three 64-bit timestamps (`push_back64`). It writes the message to `TIME_SYNC` (`273e0015`, id 20 passed to the write), repeating every `TIMESYNC_INTERVAL` (5 s). The field meanings are unresolved; see the open questions.

## Implementation notes

A minimal client needs these steps:

1. Scan for `0xFE8D`.
2. Connect and request a large MTU.
3. Enable notifications on `273e0001`.
4. Send the version query, then `s`, then `h`, then `p<preset>`, then `s`.
5. Subscribe to the data characteristics. If `pv` ≥ 3, subscribe to `273e0013` (and `273e0014` for BLE4) instead.
6. Send `dc001` (or `d` on older headbands, as muse-js does).

To stop, send `h` before disconnecting.

### Minimal client (pseudocode)

```python
import json

SERVICE = "0000fe8d-0000-1000-8000-00805f9b34fb"


def muse_uuid(n: int) -> str:
    return f"273e{n:04x}-4c4d-454d-96be-f03bac821358"


CONTROL = muse_uuid(0x0001)
UNIVERSAL = muse_uuid(0x0013)
DEBUG = muse_uuid(0x0014)
EEG = {"TP9": 0x0003, "AF7": 0x0004, "AF8": 0x0005, "TP10": 0x0006}


def encode(cmd: str) -> bytes:
    body = (cmd + "\n").encode("ascii")
    assert len(body) <= 19
    return bytes([len(body)]) + body


class Replies:
    def __init__(self):
        self.buf = ""

    def feed(self, data: bytes):
        n = data[0] & 0x1F
        self.buf += data[1 : 1 + n].decode("ascii", "replace")
        try:
            reply = json.loads(self.buf)
        except ValueError:
            return None  # wait for more chunks
        self.buf = ""
        return reply  # always has "rc"


def unpack_u12_be(pkt: bytes) -> tuple[int, list[int]]:
    counter = pkt[0] << 8 | pkt[1]
    out = []
    for i in range(12):
        o = 2 + 3 * i // 2
        if i % 2 == 0:
            out.append(pkt[o] << 4 | pkt[o + 1] >> 4)
        else:
            out.append((pkt[o] & 0x0F) << 8 | pkt[o + 1])
    return counter, out


def unpack_lsb_first(payload: bytes, bits: int) -> list[int]:
    word = int.from_bytes(payload, "little")
    count = len(payload) * 8 // bits
    return [(word >> (bits * i)) & ((1 << bits) - 1) for i in range(count)]


BLE4_PAYLOAD = {1: 28, 2: 28, 3: 24, 4: 30, 5: 40, 6: 40, 7: 36, 8: 20}
BLE4_RATE_HZ = {1: 256, 2: 128, 3: 64, 4: 52, 5: 32, 6: 16, 7: 10, 8: 1, 9: 0.1}


def ble4_subpackets(frame: bytes):
    if frame[0] != len(frame):
        raise ValueError("frame length mismatch")
    counter = int.from_bytes(frame[1:3], "little")  # reorder frames by this
    clock = int.from_bytes(frame[3:9], "little")
    i = 9
    while i < len(frame):
        kind, rate = frame[i] & 0x0F, frame[i] >> 4
        seq = frame[i + 1]
        offset = int.from_bytes(frame[i + 2 : i + 5], "little", signed=True)
        n = BLE4_PAYLOAD[kind]
        payload = frame[i + 5 : i + 5 + n]
        if kind in (1, 2):
            values = unpack_lsb_first(payload, 14)  # EEG: × 1450 / 16383 µV
        elif kind in (4, 5, 6):
            values = unpack_lsb_first(payload, 20)  # optics
        else:
            values = [
                int.from_bytes(payload[j : j + 2], "little", signed=True)
                for j in range(0, n, 2)
            ]
        yield counter, clock, kind, BLE4_RATE_HZ.get(rate), seq, offset, values
        i += 5 + n


async def start(gatt, preset="21"):
    replies = Replies()
    await gatt.start_notify(CONTROL, on_control)  # CCCD 01 00
    for cmd in ("v7", "s", "h", "p" + preset, "s"):
        await gatt.write(CONTROL, encode(cmd), response=False)
        reply = await next_reply(replies, timeout=10)
        if cmd == "v7":
            pv = reply.get("pv", 1)
    if pv >= 4:
        for char in (UNIVERSAL, DEBUG):
            await gatt.start_notify(char, on_ble4)
    elif pv == 3:
        await gatt.start_notify(UNIVERSAL, on_universal_v3)
    else:
        for n in EEG.values():
            await gatt.start_notify(muse_uuid(n), on_eeg)
    await gatt.write(CONTROL, encode("dc001"), response=False)
```

### Timing and flow control (app behaviour worth copying)

| Rule | Value | Source |
| --- | --- | --- |
| One command in flight; wait for its JSON reply | except `L…`/`Q…` | `ConnectorImpl::send` |
| Command length | ≤ 19 bytes including `\n` | `ConnectorImpl::send` |
| Reply timeout | 6–10 s by state | `interaxon::cmd::*_TIMEOUT` |
| Keep-alive when paused | `k` every 2.5 s | `PausedState`, `KEEP_ALIVE_DELTA` |
| Stream watchdog | no data for 6 s → error and reconnect | `StreamingState`, `DATA_TIMEOUT` |
| Preset change | halt first; never while streaming | configuration-changed table, preset `rc` |
| MTU | request 512 before discovery, 5 s watchdog | `LeDevice` |
| BLE4 frame order | reorder by the u16 frame counter | `Ble4NotificationReorderer` |
| Athena time sync (`pv` ≥ 5) | every 5 s on `273e0015` | `ConnectorImpl::timesync`, `TIMESYNC_INTERVAL` |

### Library choices

Where the app and public work disagree, or neither settles a point, `openble-muse` does this:

| Point | Library | Why |
| --- | --- | --- |
| Per-sensor and universal v3 EEG | `(raw − 2048) × 0.48828125` µV; the app's `1650/4095` without offset is `readings.EEG12_UV_PER_BIT_APP` | muse-js and muse-rs have run on hardware |
| BLE4 EEG | `raw × 1450/16383`, no offset; `eeg_offset=8192` gives muse-rs's form | the app, amused and muse-lsl agree |
| Gyro sign | negative (−0.0074768) in every layout | the app and the Athena projects; muse-js uses + |
| BLE4 sample order | rows are time steps, channels within a row | amused, OpenMuse and muse-rs decode it that way (Public) |
| BLE4 `0x88` battery | the payload runs to the end of the frame; `0x98` is 20 bytes | OpenMuse and muse-rs see 188–230 bytes; the app reads 20 |
| Several frames in one notification | walked by their length bytes (`ble4.parse_notification`) | OpenMuse does this; the app's one-frame case still parses |
| Unknown sub-packet type | parsing stops and the rest is kept in `Frame.unparsed` | the app rejects the frame; keeping the bytes helps a live capture |
| BLE4 channel names | muse-rs's EEG names; optics are `optics_0`… | the app does not name them and the public projects differ on optics |
| `TIME_SYNC` | not subscribed and not written | its message format is open |

OpenMuse and muse-rs read the BLE4 header differently from the app: byte 1 as a u8 packet index and bytes 2–5 as a u32 clock at 256 kHz, where the app reads a u16 counter at bytes 1–2 and a u48 clock at bytes 3–8. `ble4.Frame` follows the app.

### Open questions

These need a capture from real hardware or more static work. The Muse S live check answered some of them for that headband: `pv` 1, one `dc001` is enough, and `ps` is the preset code in hex.

- [ ] What `pv` does current Athena firmware report to `v7`? Does the reply depend on the number sent (`v4`, `v6`, `v7`)?
- [ ] The meaning of `0xC001` in `dc001`, and why public clients send it twice.
- [ ] BLE4 device-clock units: the app's `<< 28` shift against muse-rs's 256 kHz.
- [ ] The BLE4 time-sync message format on `273e0015`, and how the headband uses it.
- [ ] Which BLE4 frames arrive on `273e0013` and which on `273e0014`.
- [ ] BLE4 EEG offset: the app scales by 1450/16383 with no offset found; muse-rs subtracts 8192.
- [ ] Per-sensor EEG scale and offset: the app uses 0.40293 µV with no offset; muse-js uses `(raw−2048)×0.488`. Needs a capture with the headband worn.
- [ ] Per-sensor battery: `[0]`/512 gave 30 % while the status reply's `bp` said 25 on the same connection.
- [ ] PPG and optics units: per-sensor PPG is scaled ×805.86, BLE4 optics ×3.05e-5.
- [ ] The app's default Athena preset `p1021` and the other `102x`/`103x` codes that public tables don't list.
- [ ] BLE4 battery: muse-rs sees 188–230-byte `0x88` sub-packets, while the app parses a fixed 20 bytes. Also unknown: the battery fields after `[0]`; status keys `ms`, `ts`; version keys `be`, `fi`.
- [ ] Which product `letto` (hardware generation 6) is.

### Evidence

REA 6.4.0 with the Hopper 6.6.0 provider on `libdorothy.so` (SHA-256 above). The batch stopped after nine functions; everything else was read from the annotated disassembly and is cited by function name in each section.

| Claim | REA evidence ID |
| --- | --- |
| BLE4 frame length, counter, clock (`Ble4DataHandler::handle`) | `ev_394abe4700a429edb92de98e9428d5bc3fc98797990866501a6039bff2a06025` |
| BLE4 tag split and type dispatch (`Ble4DataHandler::parse_subpackets`) | `ev_6b566e453be7f97569742fb9bb5dfef9209ec1ddbf8ad5bc9db60cb167343584` |
| BLE4 frame counter tracking (`Ble4DataHandler::observe_packet_counter`) | `ev_29869683b8900f3db5f33991ab8fb8c6aba35a5daa21d0793fbdc72a0535f503` |
| BLE4 rate and channel tables (`Ble4DataHandler::Ble4DataHandler`) | `ev_92bf1ffdcc98c4bd211ffac521f19ddff96c166c325843ed71863cdceb332c5c` |
| BLE4 notification reordering (`Ble4NotificationReorderer::push`) | `ev_2d0d3ab099fed99199467bdab9f251809a1c17ce6715d9761bfe7b87e57f0ead` |
| BLE4 counter wrap (`Ble4NotificationReorderer::to_seq`) | `ev_6c3a1c1d8a576379f274b904b09635d0677ebf7403da5e5d74383886700a0a0d` |
| BLE4 sub-packet sequence and offset (`Ble4PacketBuffer::add_timestamp`) | `ev_b4448a1f2fa9bb67da270fb1e67c68535d95c57028364cc11e4e7f599391a25f` |
| BLE4 EEG (`Ble4EegBuffer::receive_data`) | `ev_da81fd857d873fa458a8d0c9a2c7303296f1d307d42c17ee888be44f396c8803` |
| BLE4 optics (`Ble4OpticsBuffer::receive_data`) | `ev_ed6997258e9fc6d2d65dd2b97bf4508c10bbe1d61b0208f96b1ae8e070294cad` |

The libmuse C++ names are the vendor's own and should stay stable across app builds. Addresses and object offsets apply to app 55.1 only.
