# SwitchBot BLE protocol

Static protocol notes for SwitchBot devices (Woan Technology), read from the official SwitchBot Android app. They cover how the app recognises a device from its advertisement, the one GATT service every device shares, the `0x57` command frame, the optional password, the AES-CTR layer used by locks and other newer devices, and the commands for the most common device families.

This is interoperability documentation of a local app binary. Nothing here has been checked against a live device yet; see [Open questions](#open-questions). Where the open-source [pySwitchbot](https://github.com/sblibs/pySwitchbot) library (MIT) or SwitchBot's own [SwitchBotAPI-BLE](https://github.com/OpenWonderLabs/SwitchBotAPI-BLE) notes cover the same ground, they are cited, and disagreements are called out.

## Overview

Every SwitchBot device talks to the phone the same way. It advertises its type and live state in BLE service data and manufacturer data, so passive sensors (thermometers, contact and motion sensors) never need a connection at all. For control, the phone connects, writes a short binary command to one characteristic, and reads the reply from a notification on another. Commands start with the magic byte `0x57` ("W" for Wonder). Most fit in 20 bytes.

There are three security levels:

- **None.** Curtains, meters, plugs, bulbs, strips, blind tilts and roller shades accept plain commands from anyone in range.
- **Password.** A Bot (and a few older devices) can be given a password in the app. Commands then carry a CRC-32 of the password.
- **Encryption.** Locks, keypads, relay switches, air purifiers, the evaporative humidifier and some others need AES-128-CTR. The 16-byte key is issued per user by SwitchBot's cloud. The phone fetches it once and can work offline from then on.

| Item | Value |
| --- | --- |
| Source artifact | SwitchBot 9.11.15.13 (versionCode 40000051), `com.theswitchbot.switchbot`, XAPK from the APKPure mirror (`d.apkpure.net/b/APK/com.theswitchbot.switchbot?version=latest`) |
| XAPK SHA-256 | `0ecfb7692ceefcc4124e95f005bdc76c48ef7aa96fb2575496d394a93d3f7af4` |
| Base APK SHA-256 | `cd186f0a3e47c7ec8ec6f53882bae5f680eb05e90f66ab6b8aa698c44dfa3304` |
| Other splits | `config.arm64_v8a.apk` (`3bd435b0…`), `switchbot_assets.apk` (`c0b71cdd…`, React Native bundles), three density splits |
| Build | minSdk 23, targetSdk 34 |
| Code size | 12 dex files, 46,779 classes (jadx 1.5.6), of which 6,856 under `com.theswitchbot`. SwitchBot's own BLE classes keep their real names |
| BLE stack | In-house `com.theswitchbot.common.ble` (`WoBleClient`, `WoBleManager`, `WoBleScanner`) on top of Nordic's `Android-BLE-Library` (`no.nordicsemi.android.ble`) |
| Other runtimes | Plain-JS device scripts in `assets/jsCode/` run in J2V8 (`libj2v8.so`); React Native bundles per device in `switchbot_assets.apk`; a Flutter module (`libapp.so`); the Tuya "Thing" SDK for Tuya-based products (not covered here) |
| Native code | None found on the SwitchBot BLE path. `libBleLib.so` and `libThing*.so` belong to the Tuya SDK and were not examined |

**Method.** Static analysis only. REA 6.4.0 (`decode-android-resources`, apktool 3.0.3) gave the package identity and manifest. REA's Android code tools need a `jadx-headless-mcp` JAR that is not installed, so the code was read from two full jadx 1.5.6 decompiles (`--deobf`, and `--deobf --no-replace-consts` because jadx otherwise swaps literal bytes for unrelated constant names such as `DeviceByteType.WO_BLE_TYPE_CEILING_LIGHT_PRO_ADD` for `0x4E`). One branch that jadx inverted was settled in apktool smali (see [Encryption](#encryption)). The JS device scripts and the advertisement rule file were read as shipped. Nothing was observed at runtime.

**Evidence key.** "Observed" means read directly from code, with its class or file cited. "Inferred" means reasoned from code but not proven. "pySwitchbot" means the fact comes from that library, not from the app.

**Scope.** Talking to a SwitchBot device you own from an open-source client: discovery, the GATT link, framing, passwords, encryption, and the everyday commands for each common device. Wi-Fi provisioning of hubs, firmware updates, cameras, robot vacuums and the Tuya-based products are mentioned only in passing. Obtaining the encryption key needs a SwitchBot account; that cloud call is described because there is no offline alternative in the app.

## Where the protocol lives in the app

The app has three layers of BLE code, and newer devices have moved upward through them.

| Layer | Where | What it holds |
| --- | --- | --- |
| Kotlin core | `com.theswitchbot.common.ble.*` | Scanning, GATT connection, one-at-a-time request queue, reply matching |
| Kotlin protocol | `com.theswitchbot.device.protocol.*` | `CmdGenerator` (most command builders), `BleMsgParser` (status codes, reply parsers), `DeviceSecurityWriter` and friends (encryption), `CmdMapper` (named command tables), `scan/` (advertisement parsers) |
| Kotlin devices | `com.theswitchbot.device.impl.<device>` | Per-device helpers, for example `hand/` (Bot), `curtain/`, `lock/`, `humidifier/`, `plugmini/`, `striplight/`, `blindtilt/` |
| JS device scripts | `assets/jsCode/*.js` in the base APK | Command builders and reply parsers for Lock Pro, Lock Ultra, Keypad, relay switches, air purifier, evaporative humidifier, roller shade, water detector, finder card, doorbells, Hub 2 and Hub 3. Every BLE write goes through `writeBle(mac, hex, timeout, encrypt, callback)` in `main.js`, which calls the native `jsBleWrite` |
| Advertisement rules | `assets/jsCode/ble_parse_rule.json` (SHA-256 `5b90c4ec…`) | A declarative bit map for 23 newer device types, read by `ParserRuleManager` and `JsonRuleBleParser` |
| React Native | `switchbot_assets.apk`, `assets/<Device>/index.android.bundle` | UI. It calls the JS scripts through "thing model" property and service IDs; the bundles hold almost no raw BLE bytes |

## Device identification

### Advertisement sources

`WoBleMacUtil.getServiceDataByRecord` picks the service data the app parses (Observed):

1. If the advertisement lists service UUID `cba20d00-224d-11e6-9fb8-0002a5d5c51b` or `0000fd3d-…`, use the service data for 16-bit UUID **`0x0D00`** (older devices).
2. Else, if it lists `36000001-0001-0002-0003-010203040506`, use that UUID's service data.
3. Otherwise use the service data for 16-bit UUID **`0xFD3D`** (current devices).

Manufacturer data uses company ID **`0x0969`** (2409, Woan Technology; `BleUuid.WOAN_UUID`). As on Android, the bytes below start after the two company-ID bytes. Bytes 0–5 are the device's MAC address. The app reads them in `WoBleMacUtil.getMacByScanResult` for the safety alarm, which advertises from a random address; pySwitchbot reads them for every device. Byte 6 is a sequence number that changes when the state changes. The rule file names it with `"sq": 6`, and the app attaches it to every advertised property. Device fields start at byte 7.

The scanner (`WoBleScanner`) runs an unfiltered `SCAN_MODE_LOW_LATENCY` scan and parses every result. Two background services use hardware filters instead. `LockProUnlockService` matches `FD3D` service data `24 80 64` under mask `7F 00 00`, and `FinderCardService` matches `31 00 64` (Observed).

### Model byte

Service data byte 0, masked with `0x7F`, is the model. Bit 7 is a flag. On the Bot it means a password is set (`WoHandParser`, `WO_HAND_IS_ENCRYPT`), and on the battery circulator fan the rule file names it `WO_FAN_IS_ENCRYPT`.

Each model has two codes. A device that is in setup ("add") mode advertises the second one, which is usually the first minus `0x20`, an upper-case letter for a lower-case one. The values come from `com.theswitchbot.device.consts.DeviceByteType` and the parser classes in `device/protocol/scan/delegate/` (Observed):

| Device | App type code | Normal | Setup mode |
| --- | --- | --- | --- |
| Bot | `WoHand` | `0x48` `H` | none |
| Curtain | `WoCurtain` | `0x63` `c` | `0x43` `C` |
| Curtain 3 | `WoCurtain3` | `0x7B` `{` | `0x5B` `[` |
| Blind Tilt | `WoBlindTilt` | `0x78` `x` | `0x58` `X` |
| Roller Shade | `WoRollerShade` | `0x2C` `,` | `0x0C` |
| Meter | `WoMeter` | `0x54` `T` | `0x74` `t` (the reverse of the usual rule) |
| Meter Plus | `WoMeterPlus` | `0x69` `i` | `0x49` `I` |
| Indoor/Outdoor Thermo-Hygrometer | `WoIOSensor` | `0x77` `w` | `0x57` `W` |
| Meter Pro | `WoMeterPro` | `0x34` `4` | `0x14` |
| Meter Pro CO2 | `WoMeterProCO2` | `0x35` `5` | `0x15` |
| Contact Sensor | `WoContact` | `0x64` `d` | `0x44` `D` |
| Motion Sensor | `WoPresence` | `0x73` `s` | `0x53` `S` |
| Water Leak Detector | `WoWaterDetector` | `0x26` `&` | `0x06` |
| Plug Mini (US) | `WoPlugUS` | `0x67` `g` | `0x47` `G` |
| Plug Mini (JP) | `WoPlugJP` | `0x6A` `j` | `0x4A` `J` |
| Plug Mini (EU) | `W1104000` | `0x3F` `?` | `0x1F` |
| Relay Switch 1 | `W1083002` | `0x3B` `;` | `0x1B` |
| Relay Switch 1PM | `W1083000` | `0x3C` `<` | `0x1C` |
| Relay Switch 2PM | `W1083001` | `0x3D` `=` | `0x1D` |
| Garage Door Opener | `W1083003` | `0x3E` `>` | `0x1E` |
| Color Bulb | `WoBulb` | `0x75` `u` | `0x55` `U` |
| Light Strip | `WoStrip` | `0x72` `r` | `0x52` `R` |
| Ceiling Light | `WoCeiling` | `0x71` `q` | `0x51` `Q` |
| Ceiling Light Pro | `WoCeilingPro` | `0x6E` `n` | `0x4E` `N` |
| Humidifier | `WoHumi` | `0x65` `e` | `0x45` `E` |
| Evaporative Humidifier (and Plus) | `WoHumi2`, `WoHumi2Plus` | `0x23` `#` | `0x03` |
| Battery Circulator Fan | `WoFan` | `0x66` `f` | `0x46` `F` |
| Circulator Fan (2) | `WoFan2` | `0x7E` `~` | `0x5E` `^` |
| Air Purifier (US / JP) | `WoAirPurifierUS`, `…JP` | `0x2A` / `0x2B` | `0x0A` / `0x0B` |
| Air Purifier Table (US / JP) | `WoAirPurifierUSPro`, `…JPPro` | `0x37` / `0x38` | `0x17` / `0x18` |
| Lock | `WoLock` | `0x6F` `o` | `0x4F` `O` |
| Lock Lite | `WoLockLite` | `0x2D` `-` | `0x0D` |
| Lock Pro | `WoLockPro` | `0x24` `$` | `0x04` |
| Keypad | `WoKeypad` | `0x6B` `k` | `0x4B` `K` |
| Keypad Touch | `WoKeypadTouch` | `0x79` `y` | `0x59` `Y` |
| Remote | `WoButton` | `0x62` `b` | `0x42` `B` |
| Hub 2 | `WoHub2` | `0x76` `v` | `0x56` `V` |
| Hub Mini | `WoLinkMini` | `0x6D` `m` | `0x4D` `M` |
| Hub Plus | `WoLinkPlus` | `0x70` `p` | `0x50` `P` |
| Hub Mini (Matter) | `WoLinkMatter` | `0x25` `%` | `0x05` |
| Finder Card | `WoFinderCard` | `0x31` `1` | `0x11` |
| Video Doorbell (indoor / outdoor unit) | `WoDoorbellIndoor`, `WoBasicOutdoor` | `0x3A` / `0x39` | `0x1A` / `0x19` |

The table leaves out cameras and robot vacuums. Their codes are in `DeviceByteType`.

**Long model IDs.** When byte 0 masked is `0x00`, the model is a 3-byte big-endian number in service data bytes 4–6, for example `1091000` for the Lock Ultra (`W1091000`) or `1110000` for the safety alarm. In that form, bit 0 of byte 3 means setup mode (`JsonRuleBleParser.parseData`, `WoBleMacUtil.getMacByScanResult`). The rule file maps these IDs, as well as the newer one-byte codes, to rule groups:

| Model ID or byte | Type | Rule group |
| --- | --- | --- |
| `0x3B`/`0x1B`, `0x3C`/`0x1C`, `0x3E`/`0x1E`, `0x3F`/`0x1F` | Relay Switch 1, 1PM, Garage Door Opener, Plug Mini EU | `switchBox` |
| `0x3D`/`0x1D` | Relay Switch 2PM | `switch2pm` |
| `0x2A`, `0x2B`, `0x37`, `0x38` (+ setup codes) | Air purifiers | `airPur` |
| `1096000` | Hub 3 | `hub3` |
| `1116000` | Circulator fan variant | `fan2` |
| `1102000`–`1102002`, `1123000` | Floor lamp and strip variants | `floorLamp` |
| `1102003`–`1102005` | RGBIC variants | `rgbic` |
| `1110000` | Safety alarm | `safetyAlarm` |
| `1106000`, `1107000`, `1113000`, `1096001` | Vacuums, others | `empty` (no fields) |

## Advertisement data

The tables give the bit positions the app reads. Bit 7 is the most significant bit. "svc" is service data, "mfr" is manufacturer data after the company ID. Battery is a percentage unless noted.

### Bot (`WoHandParser`)

| Field | Position |
| --- | --- |
| Password set | svc byte 0, bit 7 |
| Switch mode (vs press mode) | svc byte 1, bit 7 |
| Switch is off | svc byte 1, bit 6 (1 = off; pySwitchbot reports `isOn = not bit6` only in switch mode) |
| Battery | svc byte 2, bits 0–6 |

### Curtain and Curtain 3 (`WoCurtainParser`, `WoCurtain3Parser`)

| Field | Position |
| --- | --- |
| Is group master | svc byte 1, bit 7 |
| Calibrated | svc byte 1, bit 6 |
| Battery | svc byte 2, bits 0–6 |
| Position (0 open … 100 closed) | svc byte 3, bits 0–6 |
| In group | svc byte 4, bits 0–3 > 1 |
| Curtain 3: overheat alarm | svc byte 5, bits 0–2 = `7` |
| Curtain 3: temperature too high / too low | mfr byte 7, bits 6–7 = `10` / `01` |
| Curtain 3: magnetic (geomag) alarm | mfr byte 7, bit 2 |
| Pre-grouped | mfr byte 11, bit 7 |
| Rail ("ear") type | mfr byte 11, bits 0–3 |

pySwitchbot also reads a light level and the in-motion flag from these bytes.

### Meter and Meter Plus (`WoMeterParser`, rule groups `meter` and `meterPlus`, `MeterTempParser`)

| Field | Position |
| --- | --- |
| Battery | svc byte 2, bits 0–6 |
| High / low temperature alert | svc byte 3, bit 7 / bit 6 |
| High / low humidity alert | svc byte 3, bit 5 / bit 4 |
| Temperature, tenths | svc byte 3, bits 0–3 |
| Temperature, whole degrees | svc byte 4, bits 0–6 |
| Temperature sign | svc byte 4, bit 7 (1 = positive) |
| Unit shown on the display | svc byte 5, bit 7 (1 = °F) |
| Humidity | svc byte 5, bits 0–6 |
| Meter Plus comfort level | svc byte 1, bits 6–7 |

Temperature = `±((b4 & 0x7F) + (b3 & 0x0F) / 10)` °C, positive when bit 7 of byte 4 is set.

### Meter Pro, Meter Pro CO2, Indoor/Outdoor sensor, Hub 2

These move the reading into manufacturer data. The temperature uses the same encoding but in different bytes (`MeterProTempParser`, `IOSensorTempParser`, `Hub2TempParser`): tenths in the low nibble of the first byte, whole degrees and sign in the second.

| Field | Meter Pro / CO2 | Indoor/Outdoor | Hub 2 |
| --- | --- | --- | --- |
| Battery | mfr 7, bits 0–6 | svc 2, bits 0–6 | — |
| Temperature (tenths, then whole + sign) | mfr 8 bits 0–3, mfr 9 | mfr 8 bits 0–3, mfr 9 | mfr 13 bits 0–3, mfr 14 |
| Humidity | mfr 10, bits 0–6 | mfr 10, bits 0–6 | mfr 15, bits 0–6 |
| Unit (1 = °F) | mfr 10, bit 7 | — | mfr 15, bit 7 |
| Temperature / humidity alarm state | mfr 8, bits 6–7 / 4–5 | mfr 8, bits 6–7 / 4–5 | mfr 13, bits 6–7 / 4–5 |
| Dew point / VPD / absolute humidity alarm | mfr 11, bits 6–7 / 4–5 / 2–3 | mfr 7, bits 6–7 / 4–5; mfr 11, bits 0–1 | — |
| Comfort level | mfr 11, bits 0–1 | mfr 7, bits 2–3 | — |
| CO2 ppm (Meter Pro CO2) | mfr 13–14, big-endian | — | — |
| CO2 alert / level | mfr 15, bit 7 / bits 5–6 | — | — |
| Light level | — | — | mfr 12, bits 0–4 |

### Contact Sensor (`WoContactSensorParser`)

| Field | Position |
| --- | --- |
| Motion detected (PIR) | svc byte 1, bit 6 |
| Battery | svc byte 2, bits 0–6 |
| Door state | svc byte 3, bits 1–2: `0` closed, `1` open, `2` open too long |
| Light | svc byte 3, bit 0 |
| Seconds since last motion | bit 7 of byte 3 as bit 16, then bytes 4–5 |
| Seconds since last door change | bit 6 of byte 3 as bit 16, then bytes 6–7 |
| Button presses (counter) | svc byte 8, bits 0–3 (pySwitchbot) |

pySwitchbot prefers the newer manufacturer-data copy when it is 13 bytes or longer: motion in byte 7 bit 7, light in bit 6, timeout in bit 5, open in bit 4, button count in byte 12.

### Motion Sensor (`WoMotionSensorParser`)

| Field | Position |
| --- | --- |
| Motion detected | svc byte 1, bit 6 |
| Battery | svc byte 2, bits 0–6 |
| Seconds since last motion | bit 7 of byte 5 as bit 16, then bytes 3–4 |
| LED enabled | svc byte 5, bit 5 |
| Cloud (IoT) reporting | svc byte 5, bit 4 (pySwitchbot) |
| Sensing distance | svc byte 5, bits 2–3 |
| Light level | svc byte 5, bits 0–1 |

### Plug Mini (`WoPlugMiniUSParser`, rule group `PlugMini`, `PlugMiniPowerParser`)

| Field | Position |
| --- | --- |
| On | mfr byte 7, bit 7 |
| Delay timer set | mfr byte 8, bit 0 |
| Needs time sync | mfr byte 8, bits 2–7 = 0 |
| Network status (the app's name; pySwitchbot reads it as Wi-Fi RSSI, negated) | mfr byte 9 |
| Power | mfr bytes 10–11, 15 bits big-endian. If bit 7 of byte 10 is set, the app shows 0. pySwitchbot divides by 10 for watts |

### Locks

**Lock and Lock Lite** (`WoLockParser`, rule group `lock`):

| Field | Position |
| --- | --- |
| Calibrated | mfr byte 7, bit 7 |
| Lock state | mfr byte 7, bits 4–6 (enum below) |
| Door state comes from the sensor | mfr byte 7, bit 3 = 0 (`WoLockParser`; the rule file says bit 4, which overlaps the lock state) |
| Door state (pySwitchbot: open) | mfr byte 7, bit 2 |
| Battery band | mfr byte 7, bits 0–1: `0`→9 %, `1`→15 %, `2`→35 %, `3`→80 % |
| Paired with a second lock | mfr byte 8, bit 7 |
| Second lock online | mfr byte 8, bit 0 |

**Lock Pro and Lock Ultra** (rule groups `lockPro` and `lock2`; the app stores these as thing-model property IDs):

| Property | Meaning (from the JS notify parser) | Position |
| --- | --- | --- |
| 820 | Battery | svc byte 2, bits 0–6 (`LockProBatteryParser`) |
| 843 | Calibrated | mfr byte 7, bit 7 |
| 1600 | Lock state (enum below) | mfr byte 7, bits 3–6 |
| 1607 | Not named | mfr byte 7, bits 0–2 |
| 1602 | Door-state source | mfr byte 8, bits 6–7 |
| 1601 | Door state | mfr byte 8, bit 4 |
| 1609 | Not named | mfr byte 8, bit 3 |
| 1635 | Charging | mfr byte 9, bit 7 |
| 837 | Two locks grouped | mfr byte 10, bit 7 |
| 1605, 1617 | Not named | mfr byte 10, bits 6, 5 |
| 1606 | Second lock online | mfr byte 10, bit 4 |
| 1610, 1611, 1636–1640 | Alarms (jam, door left open and others, not named in the rule file) | mfr byte 11, bits 7 down to 1 (Lock Ultra: 1639 and 1640 are replaced by 1702 in bits 0–2) |

Lock state enum (`com.theswitchbot.device.impl.lock.enums.LockStatus`): `0` locked, `1` unlocked, `2` locking, `3` unlocking, `4` locking blocked, `5` unlocking blocked, `6` latch locked, `7` partially locked.

### Other rule groups

The rest of `ble_parse_rule.json`, in the same notation (all manufacturer data):

| Group | Fields |
| --- | --- |
| `switchBox` (Relay Switch 1/1PM, Garage Door Opener, Plug Mini EU) | relay on 7.7; switch input 7.5; overload 7.2; over-temperature 7.1; calibrated 7.0; channel mode 9.0–3; property 7214 in bytes 10–11 |
| `switch2pm` | relay 1 on 7.7; relay 2 on 7.6; channel 2 overload 7.3; channel 1 overload 7.2; over-temperature 7.1; roller calibrated 8.6; property 7250 in 8.4–5; roller motion (0 idle, 1 opening, 2 closing) 8.2–3; channel modes 9.0–3 and 9.4–7; property 7214 in bytes 10–11; roller position in byte 14 |
| `airPur` | on 7.7; mode 7.0–2; speed 9.0–6; air quality level 10.1–3; flags 13.0–3. pySwitchbot reads child lock and AQI-valid from byte 8 and filter hours from bytes 11–12 |
| `rollerShade` | motion 7.1–2; property 6401 in 7.0; calibrated 8.7; position 8.0–6; light level 9.4–7; chain length 9.0–3; properties 6405/6406 in 10.4–5/10.0–3; battery 11.0–6; motor state 12.5–7; flags 12.0–3 |
| `blindTilt` | battery svc 2.0–6; direction set 7.7; direction 7.6; calibrated 7.0; tilt percent 8.0–6; stuck when 8.7 = 0 and 7.3 = 1; group size 9.0–2; connectable 10.7 |
| `fan2` | on 7.7; mode 7.4–6; night light 7.2–3; horizontal / vertical oscillation 7.1 / 7.0; charging 8.7; battery 8.0–6 |
| `bulb` | on 7.7; delay set 8.7; mode 8.0–2; brightness and colour by `BulbIndexParser` / `BulbAlParser` |
| `floorLamp`, `rgbic`, strip (`WoStripParser`) | on 7.7; brightness 7.0–6; delay 8.7; mode 8.0–3; colour temperature 16–17 (`floorLamp`) or 10–11 (`rgbic`) |
| `ceilingLight` | brightness 7; colour temperature 8–9; on 10.7; light type 10.6; channel type 10.0 |
| `finderCard`, `safetyAlarm` | battery 7.0–6 |

`B.b` means byte B, bit b; `B.x–y` is a bit range.

## GATT

| UUID | Role | App name |
| --- | --- | --- |
| `cba20d00-224d-11e6-9fb8-0002a5d5c51b` | Service | `WOFINGER_SERVICE_UUID` |
| `cba20002-224d-11e6-9fb8-0002a5d5c51b` | **Write** (phone → device) | `WOFINGER_RX_CHAR_UUID` (named from the device's side) |
| `cba20003-224d-11e6-9fb8-0002a5d5c51b` | **Notify** (device → phone) | `WOFINGER_TX_CHAR_UUID` |
| `00002902-…` on `cba20003` | CCCD, notifications enabled | `CCCD` |

`WoBleClient.WoBleGattCallback.isRequiredServiceSupported` looks for the characteristics in this order (Observed):

1. Service `cba20d00-…`; if it is absent, service `0000fd3d-…`. In either case the write and notify characteristics are `cba20002` and `cba20003`.
2. Otherwise the FreqChip OTA service `02f00000-0000-0000-0000-00000000fe00` (write `…ff01`, notify `…ff02`).
3. Otherwise service `36000001-0001-0002-0003-010203040506` (write `36000002-…`, notify `36000003-…`).

The write type is "with response" when the write characteristic has the WRITE property, otherwise "without response". Firmware update uses separate services: Nordic legacy DFU `00001530-1212-efde-1523-785feabcd123`, Nordic secure DFU `0000fe59-…`, and a SwitchBot OTA service `0000d0ff-3c17-d293-8e48-14fe2e4da212` (`BleUuid`).

## Connection lifecycle

`WoBleClient` and `WoBleManager` (Observed):

1. `connectGatt` with `autoConnect = false` and an 8 s timeout. A failed attempt is retried after 1 s, up to a retry count chosen by the caller (2 to 4 in the app). A second connect within 30 s of an unfinished one waits for the first instead.
2. After service discovery: request high connection priority (`requestConnectionPriority(1)`), then enable notifications on `cba20003`.
3. The app does not raise the MTU for normal commands. It asks for a larger MTU only for long transfers such as firmware updates, and splits writes to `MTU − 3` bytes (`getMaxPkgLength`).
4. **One request at a time.** Requests wait in a queue. The next notification is the reply to the current request, with one exception: a notification whose first byte is `0x0F` is treated as unsolicited (a push from the device) and goes to the notification callback instead. With no request pending, every notification is a push.
5. The default reply timeout is 8 s (`IBleManager.write`). The JS scripts pass 15 to 20 s.
6. Some replies span several notifications. For those, the caller supplies a `LongAckSupport` that reads the total length from the first frame; frames are joined until that length is reached (`WoCommunicationModule.getLongAckParser`). Which commands need it is set per call in the React Native code.

pySwitchbot keeps the link open for 8.5 s after the last command, and its reply timeout is 5 s.

## Command frame

Every request starts with `0x57`. `CmdGenerator.newPack(command, payloadLen, password)` builds the header (Observed):

```
no password:   57  CC  payload...
with password: 57  CC|0x10  P0 P1 P2 P3  payload...
```

- `CC` is the command class. The low nibble picks the class, and bit 4 says that a password follows. The upper bits are zero in every builder the app has.
- `P0..P3` is the CRC-32 of the password's UTF-8 bytes, big-endian (`HexUtil.crc32`, `longToBytes`). The password `1234` becomes `9B E3 E0 A3`, so a password-protected Bot press is `57 11 9B E3 E0 A3 00`.

| Class `CC` | Name in `CmdGenerator` | Use |
| --- | --- | --- |
| `0x00` | `WOCODE_REQ_COMMON_CMD` | Common commands: hardware info, time sync, reset, logs |
| `0x01` | `WOCODE_REQ_CMD_ACTION` | Simple actions (Bot press, on, off; sensor and remote "find me") |
| `0x02` | `WOCODE_REQ_GET_SETTING` | Read basic info: battery and firmware |
| `0x03` | `WOCODE_REQ_SET_SETTING` | Write basic settings (Bot mode, sensor options) |
| `0x04` | `WOCODE_REQ_OTA` | Start a BLE firmware update |
| `0x05` | `WOCODE_REQ_GET_PAIR` | Read paired actions (sensors, remote) |
| `0x06` | `WOCODE_REQ_SET_PAIR` | Write paired actions |
| `0x07` | `WOCODE_REQ_SET_KEY` | Set or clear the password |
| `0x08` | `WOCODE_REQ_GET_TIME` | Read schedules |
| `0x09` | `WOCODE_REQ_SET_TIME` | Write schedules and the clock |
| `0x0E` | (`GeneralCmd`) | Enable or disable state notifications |
| `0x0F` | `WOCODE_REQ_EXT_CMD` | Extended commands; the next byte is a per-device command group |

Extended commands are `57 0F GG …`. The group `GG` is per device family, and families usually pair a write group with a read group one higher (curtain `0x45` write and `0x46` read, lock `0x4E` and `0x4F`). Group numbers are reused across families: `0x47` is the colour bulb on a bulb and the motor on a roller shade, and `0x20`/`0x21` are Bot custom actions on a Bot but key management on a lock. Read sub-command `0x81` usually returns the full device state.

### Replies

The reply's first byte is a status (`BleMsgParser`):

| Status | Constant | Meaning |
| --- | --- | --- |
| `0x00` | `WOCODE_RESP_STATUS_NULL` | No result |
| `0x01` | `WOCODE_RESP_STATUS_OK` | Success |
| `0x02` | `…_ERROR` | Error |
| `0x03` | `…_BUSY` | Busy |
| `0x04` | `WO_CODE_UN_SUPPORT2` | Unsupported |
| `0x05` | `…_UNSUPPORT` | Unsupported |
| `0x06` | `…_BTL` | Success. pySwitchbot reads it as "success, battery low" |
| `0x07` | `…_ENCRYPTED` | Device has a password, and none was sent |
| `0x08` | `…_UNENCRYPT` | Device has no password, and one was sent |
| `0x09` | `…_PASSWORD_INVALID` | Wrong password, or a stale encryption key |
| `0x0D` | `WO_CODE_UN_SUPPORT` | Unsupported |

`checkReplySuccess` accepts `0x01` and `0x06`. The rest of the reply is command-specific.

## Encryption

Devices in `DeviceType.encryptDeviceTypes` and every JS script that calls `writeBle(…, encrypt = true)` encrypt their commands. That covers Lock, Lock Lite, Lock Pro and Lock Ultra; the keypads; the relay switches, Garage Door Opener and Plug Mini EU; the finder card and safety alarm; air purifiers; the evaporative humidifier; and the video doorbell units. The classes are in `com.theswitchbot.device.protocol.security.base` (Observed).

### Key

A key is 16 bytes, used for AES-128, plus a one-byte key ID. `DeviceKeyGetter` caches it in `DeviceKeyStore`. On a cache miss it fetches it from the cloud:

```
POST https://<region API host>/wonder/keys/v1/communicate
{"device_mac": "<MAC, upper case, no separators>", "keyType": "user"}
→ body.communicationKey = {"keyId": "<hex byte>", "key": "<32 hex chars>"}
```

(`DeviceService.getLockCKey`, `LockCKReq`). pySwitchbot makes the same call (`async_retrieve_encryption_key`) after logging in to the account. Once you have the key it does not change until the device is reset or re-added, so a client can store it and work offline.

### IV ("random")

Before the first encrypted command, the app asks the device for an IV (`DeviceRandomGetter`):

```
→ 57 00 00 00  0F 21 03 KK        KK = key ID
← 01 xx xx xx  IV0 … IV15         IV = reply bytes 4–19
```

The three zero bytes are the unencrypted placeholder for the key-ID and IV header described next. The IV is cached per device and key ID (`DeviceRandomStore`) and forgotten when the device disconnects, so every new connection fetches a new one. pySwitchbot reads reply byte 2 as an encryption-mode flag (`0` CTR, `1` GCM); the app ignores bytes 1–3 (see [Open questions](#open-questions)).

### Encrypted frame

`DeviceSecurityWriter.writeCmd` turns a plain command `57 c1 c2 …` into:

```
57  KK  IV0 IV1  AES-128-CTR(key, IV, c1 c2 …)
```

That is the original first byte, the key ID, the first two IV bytes, then everything after `0x57` encrypted. Each frame uses a fresh `Cipher` initialised with the same 16-byte IV as the counter, so the keystream starts over for every frame in a connection (`DeviceCTRCipher`).

A reply is `SS r1 r2 r3 ciphertext…`. If the status `SS` is a success (`0x01` or `0x06`), the app decrypts bytes 4 onwards with the same key and IV and returns `SS` followed by the plaintext. If it is a failure, the app returns the reply unchanged. jadx shows this branch the other way round. The smali for `writeCmd` (`if-eqz` on `success()` jumping past the decrypt) confirms that only successful replies are decrypted.

On status `0x04`, `0x05`, `0x09` or `0x0D`, `DeviceSecurityWriter.write` deletes the cached key and IV, fetches both again, and retries once.

An encrypted device also accepts some plain commands. These use key ID `00` and IV bytes `00 00`, as in the IV request. pySwitchbot builds them the same way: `key[:2] + "000000" + key[2:]`.

### Setting up a new device (cloud-assisted)

A factory-fresh lock has only a master key, and that key never reaches the phone. `LockConnector` and `DeviceKeyInitializer` (Observed):

1. Read the IV for key ID 1: `57 00 00 00 0F 21 03 01`. The reply's bytes 4–19 are the IV.
2. Read the "encrypted MAC": `57 00 00 00 0F 21 04 01`. The reply's bytes 5–10 are sent to the cloud.
3. Send both to `/wonder/keys/v1/origin` (or `/wonder/keys/v1/sync`). From then on, commands under the master key are encrypted and decrypted by the cloud: `/wonder/keys/v1/encrypt` and `/wonder/keys/v1/decode`.
4. The user key is installed with `57 0F 20 03 KK TT` (set key ID and type), then two `57 0F 20 04 KK HH k0…k7` frames (`HH` = `00` for key bytes 0–7, `01` for 8–15; `CmdGenerator.lockSetKey`). Inferred: these frames are sent through the master-key channel in step 3. `57 0F 20 01` clears all keys, and `57 0F 20 02 KK` removes one.

An open client therefore cannot set up a new encrypted device by itself. It can use one that the official app has set up, with the user key from step 4.

## Common commands

These work on most devices. Fields after the header follow the class rules above.

| Bytes | Builder | Meaning |
| --- | --- | --- |
| `57 02` | `CmdGenerator.versionCmd`, `readBasicInfo` | Basic info. Reply: `[1]` battery %, `[2]` firmware version (pySwitchbot divides by 10). Lock and keypad: `[3]` hardware version. Hubs: `[11]` Wi-Fi firmware, `[12]` region |
| `57 00 02` | `getHardwareVersion` | Hardware version in reply `[2]`. The JS OTA code picks the chip from it: 0–19 Nordic, 20–39 Realtek, 60–79 FreqChip (`woDevice_service.js`, `service_804`) |
| `57 00 03` | `CommonCmd.readFirmwareInfo` | Firmware info (hubs: device and Wi-Fi info) |
| `57 00 05 03 ZZ T0…T7` | `setTime` | Set clock: `ZZ` = UTC offset in hours + 12, then Unix seconds as 8 bytes big-endian. `setDaylightSavingTime` adds a trailing minutes byte |
| `57 00 05 01 T0…T7` | `utcTime` | Set UTC time only |
| `57 00 0D 04` | `resetDevice` / `GeneralCmd.reboot` | Reboot. The two builders give the same bytes different names |
| `57 04` | `deviceOTA` | Start a BLE firmware update |
| `57 07 EE LL P0…` | `setPassword` | Set the password: `EE` = 1 to set or 0 to clear, `LL` = length (4), then the CRC-32. Send it with the current password header if one is set |
| `57 08 02` | `scheduleNum` | Read the number of schedules |
| `57 08 (i<<4 \| t)` | `botScheduleDetail` and others | Read schedule `i`. The type `t` is 3 for Bot, 5 for humidifier, fan and plug, 6 for curtain |
| `57 0E 01 UU II FF FF <read cmd>` | `WoBlindTiltDevice` (`enableNotify`) | Push state changes: `UU` time unit (bits 6–7), `II` interval, then the read command (without `57 0F GG`) the device should push |
| `57 0E 00` | `GeneralCmd.disableNotify` | Stop pushing |

## Device commands

### Bot

`CmdGenerator`, `device/impl/hand` (Observed). Every Bot command takes the optional password header.

| Bytes | Meaning |
| --- | --- |
| `57 01 00` | Press |
| `57 01 01` | Switch mode: on |
| `57 01 02` | Switch mode: off |
| `57 01 03` / `57 01 04` | Custom mode: down / up (the app sends `actionType + 1`; pySwitchbot names them down and up) |
| `57 03 64 MM` | Set mode: `MM` = `0x00` press, `0x10` switch, `0x20` custom, plus bit 0 = invert direction (`setModeCmd`, `SwitchBotMode`) |
| `57 0F 08 SS` | Hold time (`setBotPressTime`; unit not stated in the app) |
| `57 0F 20 AI N i R H1 H0 V1 V0 D1 D0` | Custom action step `i` of `N` for action `AI`: repeat count, hold, interval and delay, each 16-bit big-endian (`setBotAction`) |
| `57 0F 21 S A` / `57 0F 22` / `57 0F 23` | Load custom actions / stop / save (`loadActions`, `stopAction`, `saveBotAction`) |

The reply to `57 02` (`BleMsgParser.parseBaseInfo`) carries battery `[1]`, firmware `[2]`, force `[3]`, sensitivity `[4]`, calibration `[6..7]`, schedule count `[8]`, mode `[9] & 0x30`, inverted `[9] & 1` and hold time `[10]`.

### Curtain, Curtain 3 and Blind Tilt

Write group `0x45`, read group `0x46` (`CmdGenerator`, `BlindTiltCmd`; Observed).

| Bytes | Meaning |
| --- | --- |
| `57 0F 45 01 01 XX PP` | Move to position `PP` (0 open … 100 closed). `XX` = `01` for one curtain, `03` for a two-curtain group; a group sends `PP PP` |
| `57 0F 45 01 05 MM PP` | Move with speed mode `MM` (`setCurtainAction`). pySwitchbot: `0xFF` default, `0x00` normal, `0x01` slow (Curtain 3 only) |
| `57 0F 45 01 00 XX` | Stop |
| `57 0F 45 01 07 01` / `… 07 02` | Open / close fully, newer firmware (`setCurtainAction` with `newVersion`) |
| `57 0F 46 81 01` | Read state (`readCurtainInfo`): `[1]` bit 6 delay set, bits 0–3 motion; `[2]` mode and timer count; `[3]` group size; `[4]`/`[6]` solar flag and position for curtains 0 and 1; `[5]`/`[7]` charging flag and battery |
| `57 0F 46 04 01` / `… 04 02` | Read settings / advanced info |
| `57 0F 46 02 00 01` | Read chain info |

Blind Tilt uses the same group. `move` is `57 0F 45 01` plus either `05 FF PP` (firmware 20 and later) or `01 01 PP`. Force stop is `57 0F 45 01 00 01`, and reading the position is `57 0F 46 01 00` (`WoBlindTiltDevice.actionPayload`). pySwitchbot: 0 is closed down, 50 open, 100 closed up.

### Meters

| Bytes | Meaning |
| --- | --- |
| `57 0F 31` | Read temperature and humidity. Reply: `[1]` bits 0–3 tenths, `[2]` bit 7 sign (1 = positive) and bits 0–6 degrees, `[3]` humidity (`parseMeterValue`) |
| `57 0F 34 …` / `57 0F 35` | Write / read alert thresholds (`meterDesiredSetting`) |
| `57 0F 36 …` / `57 0F 37` | Write / read calibration offsets |
| `57 0F 3A`, `57 0F 3B SS`, `57 0F 3D` | History storage info, read a history section, clear history |
| `57 0F 68 …` / `57 0F 69 …` | Meter Pro settings (calibration `68 03`, comfort `68 02 01`, DST `68 05 04`) |

### Plug Mini (US, JP)

`PTwoCommandUtils` (Observed):

| Bytes | Meaning |
| --- | --- |
| `57 0F 50 01 01 80` / `… 01 01 00` | On / off |
| `57 0F 51 81` | Read state |
| `57 0F 51 06 N0…N3 D0…D3` | Read energy: now and the start of today, as 4-byte Unix seconds |

### Relay Switch 1, 1PM, 2PM and Garage Door Opener (encrypted)

`woSmartSwitch_service.js` (Observed):

| Bytes | Meaning |
| --- | --- |
| `57 0F 70 01 OO SS` | Control. `OO` = relay 1 action, plus relay 2 action shifted left by 2. Actions: `0` off, `1` on, `2` toggle, `3` leave unchanged. `SS` = source (1 = app) |
| `57 0F 71 81` | Read state |
| `57 0F 71 06 CC N… D…` | Read energy for channel `CC` |
| `57 0F 70 04/05/0A/0C/0D/0E/10/11 …` | Power-on mode, auto-off, direction, momentary mode, roller control, calibration, power-loss recovery, garage door control |

pySwitchbot's on and off are `57 0F 70 01 01 00` and `… 01 00 00`.

### Locks (encrypted)

The original Lock uses `CmdGenerator.lockAction`; Lock Pro and Lock Ultra use `woLockPro_service.js` and `woLock2_service.js` (Observed).

| Bytes | Meaning |
| --- | --- |
| `57 0F 4E 01 01 DD AA` (Lock) | Move. `DD` = `(source << 4) \| device`: source 1 app, 5 NFC; device 0 this lock, 3 both grouped locks. `AA` = `direction << 7 \| stop << 6 \| latch << 5` |
| `57 0F 4E 01 01 DD SS AA` (Lock Pro, Ultra) | Move. `DD` = `00` single, `03` group; `SS` = source; `AA`: `0x00` lock, `0x80` unlock, `0xA0` unlock to the latch position. Lock Ultra adds `0x08` half-lock and `0x10` force emergency power |
| `57 0F 4F 81 LL` | Read state. `LL` = `01` Lock (`02` group), `04` Lock Pro (`05` group), `07` Lock Ultra (`08` group) |
| `57 0E 01 00 1E 00 00 81 LL` | Enable state pushes (Lock, `lockSetNotify`). The JS scripts send `… 00 20 00 00 81 LL` |
| `57 0E 00` | Disable pushes |
| `57 0F 4E 04 …`, `57 0F 4F 04 0X` | Auto-lock, force-lock, delay and other settings |
| `57 00 14 01 T0…T3`, `57 00 14 05` | Set the log base time, then read log entries |

The pushed state and the `4F 81` reply share one layout (`lockproService_notify_parse`): `[1]` bit 7 calibrated, bits 3–6 lock state; `[2]` bits 6–7 door source, bit 4 door, bits 0–1 power source; `[3]` bit 7 charging, bits 0–6 battery; `[4]` bit 7 grouped, bit 4 second lock online, bit 3 rotation direction; `[5]` lock type and latch state; `[6]` alarm bits; `[7]` angle in steps of 2°. Bytes 8–14 repeat this for the second lock.

pySwitchbot sends `0x80` as "unlock" and `0xA0` as "unlock without unlatch". The app's comment calls `0xA0` the latch position, which sounds like the opposite. See [Open questions](#open-questions).

### Humidifier (original)

`WoHumidifierDevice` (Observed). Write group `0x43`, read group `0x44`.

| Bytes | Meaning |
| --- | --- |
| `57 0F 43 01 01` / `… 01 02` | On / off |
| `57 0F 43 02 01 GG HH LL TH TL` | Set level `GG`: 34, 67 or 100 for levels 1–3, with `0x80` set for auto. Then high and low humidity and temperature limits |
| `57 0F 43 81 01 OO GG HH LL TH TL` | Set everything at once. pySwitchbot sends on as `57 0F 43 81 01 01 80 FF FF FF FF` |
| `57 0F 43 04 01 BB`, `… 05 01 RR` | Night-light brightness, beep |
| `57 0F 44 81` | Read state |
| `57 0F 44 03` | Read delay timer |

The evaporative humidifier (encrypted) uses the same groups with its own sub-commands in `woHumi2.js`: `43 03` mode and target humidity, `43 04`, `43 05`, `43 07`, `43 08`, `43 0B` and `43 12` for settings, and `44 01`–`44 12` for reads. pySwitchbot names `43 01 01` on, `43 02` set mode, `43 05` child lock and `43 0A` auto-dry.

### Lights

| Device | Bytes | Meaning |
| --- | --- | --- |
| Light Strip | `57 0F 49 01 03` | On/off (`StripSetOnOffAction`). Inferred toggle: the app always sends `03` and reads the new state from reply `[1]` bit 7. pySwitchbot uses `… 01 01` on and `… 01 02` off |
| | `57 0F 49 01 14 LL` | Brightness (`StripLevelAction`) |
| | `57 0F 49 01 12 LL RR GG BB FF CT` | Colour (`SetStripSingleColorLevel`). pySwitchbot sends only `12 LL RR GG BB` |
| | `57 0F 4A 01` | Read state |
| Color Bulb | `57 0F 47 01 …`, `57 0F 47 08 …` | Control and music mode (`BulbCommandUtil`). pySwitchbot: `47 01 01` on, `47 01 02` off, `47 01 14` brightness, `47 01 12` colour, `47 01 13` colour temperature, `57 0F 48 01` read state |
| Ceiling Light | `57 0F 54 01 …` | Control (pySwitchbot) |

### Roller Shade

`woRollerShade_service.js` (Observed):

| Bytes | Meaning |
| --- | --- |
| `57 0F 47 01 05 SS MM PP` | Move to `PP` with mode `MM`, source `SS` |
| `57 0F 47 01 04 SS 01 (MM<<7 \| PP)` | Group move |
| `57 0F 48 81` | Read state |
| `57 0F 48 04 05/06/07` | Read settings |

### Air purifier (encrypted)

`woAirPurifier_service.js` (Observed): set group `0x4C`, read group `0x4D`. `4C 01 AA MM SS` sets power, mode and speed. `4C 04` is the timer, `4C 05 TT RR GG BB LL` the light colour, `4C 06` sound, `4C 07 LL` the light mode (`02` = follow the light sensor), `4C 0A` the do-not-disturb window, and `4C 09` and `4C 0B` other options. pySwitchbot sets the fan percentage with `4C 02 PP`. `4D 81` reads the state, and `4D 04`–`4D 0C` read individual settings. Schedules are `57 09 …` and `57 08 (i<<4 | 5)`.

### Hub 2 and Hub 3

Settings are written with `57 0F 56 …` and read with `57 0F 57 …` (`woHub2_property.js`, `woHub3.js`). Time sync is `57 0F 56 0F 00 T0…T3` and the time zone `57 0F 56 0F 01 S O0 O1 O2` (`utcTimeHub`, `timeZoneHub`). Wi-Fi setup for hubs and plugs uses `57 0F 01` (SSID, 11-byte chunks with total length and index), `57 0F 02` (password chunks), `57 0F 03` (done), `57 0F 04` (Wi-Fi status), `57 0F 09` (AWS key, which the app stores as the serial; `parseAwsKey`), `57 0F 0C` (region) and `57 0F 10`–`12` (scan for networks).

## Timing summary

| Item | Value | Source |
| --- | --- | --- |
| Connect timeout | 8 s | `WoBleManager.connect` |
| Connect retry delay | 1 s | `WoBleManager.connect` |
| Concurrent-connect guard | 30 s | `WoBleClient.connect` |
| Reply timeout | 8 s default; 15–20 s in JS scripts | `IBleManager.write`, `jsCode/*.js` |
| MTU request timeout | 5 s | `WoBleClient.requestMTU` |
| Lock push interval | 30 (`0x1E`) or 32 (`0x20`), unit 0 | `lockSetNotify`, `woLockPro_service.js` |

## Implementation notes

### Minimal client (bleak)

```python
import asyncio
import zlib

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

WRITE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
NOTIFY = "cba20003-224d-11e6-9fb8-0002a5d5c51b"
WOAN = 0x0969


def model_byte(adv):
    for uuid in ("00000d00-0000-1000-8000-00805f9b34fb", "0000fd3d-0000-1000-8000-00805f9b34fb"):
        data = adv.service_data.get(uuid)
        if data:
            return data[0] & 0x7F
    return None


class SwitchBot:
    def __init__(self, client, password=None, key_id=None, key=None):
        self.client = client
        self.replies = asyncio.Queue()
        self.pw = zlib.crc32(password.encode()).to_bytes(4, "big") if password else None
        self.key_id, self.key, self.iv = key_id, key, None

    def on_notify(self, _char, data):
        if data[:1] != b"\x0f":  # 0x0F-first frames are pushes, not replies
            self.replies.put_nowait(bytes(data))

    async def raw(self, frame, timeout=8.0):
        await self.client.write_gatt_char(WRITE, frame, response=True)
        return await asyncio.wait_for(self.replies.get(), timeout)

    async def plain(self, body):
        """body = command bytes after 0x57, e.g. b"\\x01\\x00" for a Bot press."""
        if self.pw:
            body = bytes([body[0] | 0x10]) + self.pw + body[1:]
        return await self.raw(b"\x57" + body)

    def _ctr(self):
        return Cipher(algorithms.AES(self.key), modes.CTR(self.iv))

    async def encrypted(self, body):
        if self.iv is None:  # once per connection
            reply = await self.raw(b"\x57\x00\x00\x00\x0f\x21\x03" + bytes([self.key_id]))
            if reply[0] not in (1, 6):
                raise RuntimeError(f"IV request failed: {reply.hex()}")
            self.iv = reply[4:20]
        enc = self._ctr().encryptor()
        frame = b"\x57" + bytes([self.key_id]) + self.iv[:2] + enc.update(body) + enc.finalize()
        reply = await self.raw(frame)
        if reply[0] not in (1, 6):
            return reply  # failures come back unencrypted
        dec = self._ctr().decryptor()
        return reply[:1] + dec.update(reply[4:]) + dec.finalize()


async def main():
    device = await BleakScanner.find_device_by_filter(
        lambda _d, adv: model_byte(adv) == 0x48  # 'H' = Bot
    )
    async with BleakClient(device) as client:
        bot = SwitchBot(client)
        await client.start_notify(NOTIFY, bot.on_notify)
        print("basic info", (await bot.plain(b"\x02")).hex())
        print("press", (await bot.plain(b"\x01\x00")).hex())


asyncio.run(main())
```

For a lock, build `SwitchBot(client, key_id=..., key=bytes.fromhex(...))` and call, for example, `await lock.encrypted(bytes.fromhex("0f4f8101"))` to read the state of an original Lock.

Notes for a library:

- **Read adverts first.** Meters, contact and motion sensors, plug power and lock state are all in the advertisement. Connecting drains the device's battery and blocks other clients.
- **One request at a time.** The device has no request IDs. Match replies by order, and ignore frames that start with `0x0F`.
- **Fetch a new IV after every reconnect.** The app forgets it on disconnect.
- **Status `0x09` on an encrypted device** usually means the key is stale (the device was re-added). Fetch the key again.
- **Command groups are per family.** Don't assume `57 0F 47` means the same thing on two devices.
- **Re-check the model byte** on firmware updates. Newer devices move to the 3-byte model ID in service data bytes 4–6.

### Open questions

- [ ] What reply bytes 1–3 carry in encrypted replies and in the IV reply. pySwitchbot reads byte 2 of the IV reply as the AES mode (`1` = GCM, with a 12-byte IV, a 2-byte tag in the header and an IV that increments per command). This app build has no GCM code on its BLE path (only the Tuya SDK uses GCM), so either GCM devices are handled by code not examined here, or they postdate 9.11.15.13.
- [ ] Whether CTR really restarts from the same IV for every frame in a connection, as `DeviceCTRCipher` implies, or whether the firmware advances it. A capture of two commands in one connection would settle this.
- [ ] Lock `0x80` versus `0xA0`: which one pulls the latch on a Lock Pro with a latch-type door. The app's JS comment and pySwitchbot's naming disagree.
- [ ] What the first byte of a pushed lock or blind-tilt notification is. The app routes `0x0F`-first frames as pushes, but the push parsers start reading at byte 1.
- [ ] Plug Mini power units. The app passes the raw 15-bit value on; pySwitchbot divides it by 10 to get watts.
- [ ] Why the Meter's setup-mode byte is `0x74` (`t`), the reverse of every other model.
- [ ] Meanings of the unnamed thing-model properties in the rule file (1607, 1609, 1605, 1617, 1702, 7214, 7250, the 66xx air purifier and 64xx roller shade flags).
- [ ] Which commands return multi-frame replies, and where their length field sits. These are set per call in the React Native code.
- [ ] Devices built on the Tuya "Thing" SDK (`com.thingclips`) use a different protocol and are not covered.

### Evidence

REA 6.4.0 `decode-android-resources` (apktool 3.0.3) on the base APK:

| Claim | REA evidence ID |
| --- | --- |
| App identity (9.11.15.13 / 40000051), minSdk 23, targetSdk 34, SHA-256, manifest and permissions | `ev_378b602eb5f692793b4fb3659501cb7c332265f7714fa6f9897f772456a2d0dd` |

REA's Android code operations were unavailable (no `jadx-headless-mcp` JAR), so everything else comes from two full jadx 1.5.6 decompiles of the base APK (`--deobf`, and `--deobf --no-replace-consts` for literal byte values), plus the shipped `assets/jsCode/*.js` scripts and `ble_parse_rule.json`. Each section cites its classes or files. The reply-decryption branch in `DeviceSecurityWriter.writeCmd`, which jadx inverted, was checked in apktool smali (`smali_classes7`). SwitchBot's class names are unobfuscated in this build. Generated names such as `C117381` or `m4448setGearPosition` belong to version 9.11.15.13 only.
