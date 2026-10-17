# OBD-II adapter protocol (ELM327 over Bluetooth)

Static protocol notes for Bluetooth OBD-II adapters, read from a widely used Android OBD-II app. They cover how the app finds an adapter, which Bluetooth link it opens, and what it says over that link to read live data and fault codes from a car.

This is interoperability documentation of a local app binary. Nothing here has been checked against a live adapter yet; see [Open questions](#open-questions).

## Overview

An OBD-II adapter plugs into the car's diagnostic port and bridges the car's buses (CAN, K-line, J1850) to the phone. Almost every consumer adapter speaks the **ELM327 command set**: plain ASCII commands ending in `\r`, ASCII hex replies, and a `>` prompt when the adapter is ready for the next command. Some adapters use the genuine ELM327 chip. Many are clones, and OBDLink adapters use the STN chip, which adds `ST` commands.

Bluetooth only carries that text. The app has four links (Classic Bluetooth SPP, two BLE serial services, and TCP for WiFi adapters), and all four hand the same byte stream to one ELM327 driver. There is no app-level framing, checksum, pairing token or encryption.

| Item | Value |
| --- | --- |
| Source artifact | Android OBD-II app, version 1.2.22 (versionCode 1222), single APK from the APKPure mirror |
| APK SHA-256 | `ae6262945cd2fb75ce0376b12ed1939dc746e2bf1e7e2825c922b6b947acc163` |
| Build | `classes.dex` dated 2018-01-12; minSdk 9, targetSdk 22 |
| Code size | 1 dex file, 2,240 classes (jadx 1.5), obfuscated into package `o` |
| Bluetooth stacks | Android `BluetoothSocket` (SPP); in-house `BLESerialPort` service (BLE `FFE0`); the Zentri/ACKme Truconnect library (PLX Kiwi 3); a bundled gerdavax stack for Android before 2.0 |
| Native code | None |
| Permissions | `BLUETOOTH`, `BLUETOOTH_ADMIN`, `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`, `INTERNET`, `ACCESS_WIFI_STATE`, `WAKE_LOCK`, others |

**Scope.** Talking to an OBD-II adapter you own from an open-source client: discovery, the Bluetooth link, ELM327 set-up, protocol detection, live data (mode 01), fault codes and vehicle information. The car-side protocols (ISO 15765, ISO 14230, J1850) are handled inside the adapter and are covered only where the app's commands depend on them. The ELM327 commands are documented publicly in the ELM Electronics ELM327 datasheet; this manual records which of them the app uses, in what order, and how it reads the replies.

## Adapter families

The app sorts adapters into four links. `btv.C1035.m7604` picks one per connection attempt from the saved device name and address:

| Condition | Link | Factory key | Classes |
| --- | --- | --- | --- |
| Name starts with `Kiwi ` or `Kiwi_` | BLE Truconnect | `kiwi` | `bui`, `buj`, `bst`, `bse`, `bsa` |
| Address starts with `BLE:` | BLE serial `FFE0` | `ble` | `buc`, `bud`, `BLESerialPort` |
| WiFi selected in settings | TCP | — | `btv.C1035` |
| Anything else | Classic Bluetooth SPP | (default) | `bug`, `buh` |

`bua.m7663` caches one link object per key. If `android.bluetooth.BluetoothAdapter` cannot be loaded (Android before 2.0), it falls back to the gerdavax stack (`bue`, `buf`), which opens RFCOMM channel 1.

Every link implements `btz`: an `InputStream`, an `OutputStream` and `close()`. Nothing above `btz` knows which link is in use, apart from two timing tweaks (an extra 3 s wait before `ATZ` on Kiwi, and no "no response" warning on WiFi).

## Discovery

The adapter list in settings (the settings activity, around the "Building adapter list..." dialog) merges three sources:

1. **Bonded Classic devices.** `getBondedDevices()`, shown by name, stored by MAC address. The user pairs the adapter in Android's Bluetooth settings first; with none paired the app says "No devices paired, please pair one in your phones bluetooth settings". The app never pairs or sets a PIN itself.
2. **BLE `FFE0` devices.** A 2.2 s `startLeScan` through `BLESerialPort`. A device is listed if its advertisement carries the 16-bit service UUID `FFE0`. The app parses the advertisement itself (`BLESerialPort.m16668`): AD types `0x02`/`0x03` (16-bit UUIDs) and `0x06`/`0x07` (128-bit UUIDs). These are stored as `BLE:<MAC>`.
3. **Kiwi devices.** A 2.3 s Truconnect scan (`bui.m7715`). Any device whose name starts with `kiwi` (any case) is listed. **The name is stored as the address**, and the app reconnects by scanning for that name.

The app does not filter Classic devices by name or class; the user picks one.

## Links

### Classic Bluetooth SPP

`bug.mo7664` opens RFCOMM to the Serial Port Profile UUID `00001101-0000-1000-8000-00805F9B34FB`:

1. Close any old socket, sleep 200 ms, cancel discovery.
2. `createInsecureRfcommSocketToServiceRecord` when the device or address is on an internal list (`bvi.m7976`, `bvi.m7978`), otherwise `createRfcommSocketToServiceRecord`.
3. `connect()`, with a watchdog thread (`bug.C1045if`) that closes the socket if `connect()` hangs. On `IOException`: sleep 1 s, recreate the socket, connect once more.
4. If both fail: sleep 1 s, then use reflection to call `createRfcommSocket(1)` (channel 1, skipping SDP), with one retry.
5. Wrap the streams in `buh`. In "faster communication" mode the input is buffered (`BufferedInputStream`, 1024 bytes). Each dead-stream failure increments `bua.f6162`, and buffering is used only while that counter is even, so the app alternates between buffered and unbuffered reads until one works.

An exception that mentions `SPP port object` produces the toast "Your bluetooth driver has failed, please reboot your device".

### BLE serial (`FFE0`/`FFE1`)

This is the HM-10 style "transparent UART" used by most cheap BLE adapters. `BLESerialPort` is a bound Android `Service`. `bud` wraps it as streams.

| UUID | Role |
| --- | --- |
| `0000ffe0-0000-1000-8000-00805f9b34fb` | Service, also the scan filter |
| `0000ffe1-0000-1000-8000-00805f9b34fb` | **Both** TX and RX: the app writes commands to it and subscribes to notifications on it |
| `00002902-…` on `FFE1` | CCCD, written `01 00` |

Connect sequence (`buc.mo7664`, order checked in smali):

1. Bind the `BLESerialPort` service; wait up to 3 s (30 × 100 ms) for the binding.
2. Sleep 1 s.
3. `connectGatt(autoConnect=false)`. On `STATE_CONNECTED` with status 0: `discoverServices()`.
4. On services discovered: look up `FFE0`/`FFE1`. If either is missing, report "not ready" and stop.
5. Enable notifications on `FFE1` (`setCharacteristicNotification` + CCCD write).
6. On API 21+: `requestConnectionPriority(CONNECTION_PRIORITY_HIGH)` and `requestMtu(128)`, issued straight after the CCCD write without waiting for it.
7. Mark the link ready. `buc` polls for ready for up to 5 s (50 × 100 ms), then returns the stream either way. Writes on a link that is not ready throw `IOException`.

Writes (`BLESerialPort.m16686`): each `OutputStream.write` call becomes **one** `writeCharacteristic` with the whole buffer, then waits up to 5 s for `onCharacteristicWrite`. The driver writes one command per call (for example `010C\r`, 5 bytes), so commands never need splitting. The app never calls `setWriteType`. Inferred: Android then uses write-without-response whenever `FFE1` advertises it, which HM-10 modules do.

Reads: every `FFE1` notification is appended to a ring buffer in `bud.C1043`, which the driver reads one byte at a time. Notifications carry raw ELM327 output with no framing; one reply can arrive across several notifications.

`BLESerialPort.m16694` (scan and connect) instead connects to the first `FFE0` device it sees, with `autoConnect=true`.

### BLE Truconnect (PLX Kiwi 3)

The PLX Kiwi 3 uses the Zentri (formerly ACKme, now Silicon Labs) Truconnect serial service. The bundled library names it so (`hasTruconnectChars` in `o.C1814`).

| UUID | Role |
| --- | --- |
| `175f8f23-a570-49bd-9627-815a6a27de2a` | Truconnect service |
| `cacc07ff-ffff-4c48-8fae-a9ef71b75e26` | TX, adapter → phone, notify |
| `1cce1ea8-bd34-4813-a00a-c76e028fadcb` | RX, phone → adapter, write |
| `20b9794f-da1a-4d14-8014-a0fb9cefb2f7` | Mode, `uint8`, values 1–3 valid |
| `b2e7d564-c077-404e-9d29-b547f4512dce` | OTA service: control `48cbe15e-642d-4555-ac66-576209c50c1e` (notify), data `db96492d-cf53-4a43-b896-14cbbf3bf4f3` |
| `0000180a-…` / `00002a26-…` | Device Information, firmware revision string |

A service counts as Truconnect only if TX, RX and Mode are all present (`bse`, service discovery). The app enables notifications on TX, then writes ASCII strings to RX. The library splits each string into **20-byte packets** and sends the next one only after `onCharacteristicWrite` echoes back the packet it sent (`bse`, around the `substring(0, 20)` call). The app never writes Mode, so the adapter stays in its default mode. Inferred: that is Truconnect stream mode.

Connect sequence (`bui.mo7664`): start a scan, wait up to 5 s (25 × 200 ms) for the saved name to appear, stop the scan, connect by name, then wait up to 5 s (10 × 500 ms) for the connection. Failure throws "Not in range or kiwi adapter(not found)" or "Unable to connect to kiwi adapter". The driver then sleeps 3 s before `ATZ`.

The interface `bub` also declares `e47c8027-cca1-4e3b-981f-bdc47abeb5b5`, which nothing uses.

### WiFi

`btv.C1035` opens a plain TCP socket to the configured host and port, default `192.168.0.10:35000` (settings defaults), with up to 10 attempts. It carries the same ELM327 stream.

## ELM327 framing

Commands are ASCII, sent as one write, ending in `\r` (`0x0D`). The app never sends `\n`. Spaces inside commands are optional; the app writes `ATSH7E0` and `AT SH 7E0` in different places.

Replies are read one byte at a time by `btv.C1034if.run`:

| Byte | Action |
| --- | --- |
| `\r` or `\n` | End of line. A non-empty trimmed line is added to the current reply |
| `>` (`0x3E`) | End of reply. Any partial line is added, and the reply (a list of lines) is queued for the waiting caller |
| `0x00`–`0x09` | Dropped |
| anything else | Appended to the current line |
| `-1` (no data) | Sleep 10 ms; after 850 empty reads (about 8.5 s) the stream counts as dead: "End of stream reached" |

A reply that grows past 100 lines is queued early. In monitor mode (protocol 15, `ATMA`) every line is queued on its own.

Callers wait for a queued reply in steps of 350 ms, at most 20 steps, so about 7 s (`btv.C1034if.m7588`). The formula also adds the command's post-write delay ÷ 350, but that delay is back to 0 by the time the wait starts. An empty result means "no data".

Before each lookup the parser lower-cases the line and strips spaces, so `41 0C 1A F8`, `410C1AF8` and `410c1af8` all match the same way. The app turns spaces off (`ATS0`) when the adapter supports it.

### Watchdog

A timer task (`btv.C1037`) runs every second, starting 6 s after connect. The reader arms it with a 2.5 s deadline before each byte:

| Condition | Action |
| --- | --- |
| A command is in flight and no byte arrives within 2.5 s | Send a bare `\r` and wait 380 ms. Inferred: on an ELM327, an empty line repeats the last command, so this re-sends the request |
| More than three such retries | Sets `btv.f5896`, which nothing in this build reads |
| No command in flight and silent for 7.6 s after the deadline | Send `ATI\r` as a keepalive |
| Silent for 14 s past the deadline | Close the socket and reconnect |

In monitor mode the watchdog sends `\r` (1280 ms) and then `ATMA\r` instead.

## Connection lifecycle

The connection thread (`btv.C1035.run`) loops for as long as the app is connected:

1. Open the link (see above). If the adapter is not found: "Adapter not found, retrying...", wait, try again; after repeated failures, "Not connected. Retrying in 60 seconds...".
2. [Initialise the adapter](#adapter-initialisation).
3. [Find the vehicle protocol](#protocol-detection). If none answers, close and go back to 1.
4. [Identify ECUs and headers](#headers-and-ecu-addresses), then send any custom init string from the vehicle profile.
5. `0100` ("Checking vehicle model"), then the supported-PID bitmaps `0120`, `0140`, `0160` if the previous bitmap says they exist.
6. [Poll](#live-data-mode-01) until the link drops, then go back to 1.

If the polling loop sees `unabletoconnect`, it re-runs step 2 in place. Queued one-off requests (fault codes, adapter info, clearing codes) go into a list (`btv.m7498` ignores duplicates, `btv.m7500` allows them) and run between polls.

## Adapter initialisation

`btv.m7517` runs the reset and set-up:

| Step | Command | Wait | Notes |
| --- | --- | --- | --- |
| 1 | — | 100 ms | Drain the input. Kiwi: also sleep 3 s |
| 2 | `ATZ` | 1800 ms (fast) / 2000 ms | Full reset. The banner is read after a further 250 / 500 ms |
| 3 | `ATE0` | until `>` | Echo off |
| 4 | `ATM0` | until `>` | Memory off. Skipped on ELM323 |
| 5 | `ATL0` | until `>` | Linefeeds off, then drain 100 ms |
| 6 | `ATS0` | until `>` | Spaces off. Skipped when the banner contains `ELM327 v1.2`, `ELM323` or `DIAMEX` |
| 7 | `AT@1` | until `>` | Device description. `?` is stored as "Not present" |
| 8 | `ATI` | until `>` | Version string |
| 9 | `STI` | until `>` | Only when `AT@1` contains `SCANTOOL`: a reply containing `stn` marks an STN chip |
| 10 | `ATH0` or `ATH1` | until `>` | Headers; off unless the caller asks for them |
| 11 | `ATAT2` / `ATAT1` / `ATAT0` | until `>` | Adaptive timing: "faster communication" / normal / "slow" setting. Skipped on ELM323 and DIAMEX |
| 12 | — | 200 ms | Drain |

"Until `>`" means `btv.m7512`: write, wait for one reply, and retry up to 5 times while the reply is empty, `?` or `ERROR`. It backs off 40, 80 and 120 ms around each retry.

If `ATZ` gets no reply on a Bluetooth link, the user sees "No response from OBD Adapter, Did you select the right device? / Reboot Android device." (from the second failure onwards). On Android before 4.1 the app also turns Bluetooth off (waiting up to 12 s) and on again (up to 17 s) (`btv.m7548`, `btv.m7541`).

### Adapter detection

The app reads the `ATZ` banner, `AT@1` and `ATI` and sets an internal adapter type (`btv.f5977`):

| Match | Type | Effect |
| --- | --- | --- |
| default | 0, ELM327 | All of the above |
| `AT@1` contains `SCANTOOL` and `STI` contains `stn` | 1, STN (OBDLink) | Forces fast mode. Sends the STN sleep commands below. Adapter info adds `ST DI`, `ST I`, `ST MFR`, `ST SN`, `ST SLCS` |
| `ATI` contains `DIAMEX` | 2, DIAMEX | Disables fast mode. Appends `AT!00` to the version. Uses `ATP<n>` for the protocol, `ATN` to read it back and `AT!10` for voltage |
| `ATI` contains `ELM323` | 3, ELM323 | No `ATM0`, `ATS0` or `ATAT` |
| Device name contains `PLX` and `-` gets reply byte `128` | 4, PLX iMFD | Sends `-`, reads one raw byte, then sends `+\r` |
| `ATI` contains `OBDKey` | (flag) | Special-cased elsewhere |
| Banner contains `ELM327 v1.2` | (flag) | No `ATS0`. Inferred: `ATS0` was added in ELM327 v1.3 |

STN sleep set-up, after `ATPP 0E OFF`:

| Setting | Commands |
| --- | --- |
| Default | `ST SLX off,on`, `ST SLU off,on`, `ST SLVL off,on`, `ST SLVG off` |
| "Wake on voltage" option | `ST SLVGW 0.1,950`, `ST SLVLW >13.3, 1`, `ST SLUIT 500`, `ST SLX off,off`, `ST SLU on,off`, `ST SLVL off,on`, `ST SLVG on` |

## Protocol detection

The protocol numbers are the ELM327 `ATSP` numbers. `btv.m7535` holds the display names:

| `ATSP` | Name in the app |
| --- | --- |
| 0 | Automatic search |
| 1 | J1850 PWM (41.6K) |
| 2 | J1850 VPW (10.4K) |
| 3 | ISO9141-2 5 baud |
| 4 | ISO14230-4 KWP 5bd |
| 5 | ISO14230-4 KWP fast |
| 6 | ISO15765-4 CAN 11/500 |
| 7 | ISO15765-4 CAN 29/500 |
| 8 | ISO15765-4 CAN 11/250 |
| 9 | ISO15765-4 CAN 29/250 |
| A | SAE J1939 CAN 29/250 |
| B, C | User1 CAN, User2 CAN |
| 14 (app only) | Subaru SSM |
| 15 (app only) | Bus monitor (`ATMA`) |
| 16 (app only) | VW Group Diagnostic Protocol |
| 17 (app only) | Fiat proprietary ("not yet finished") |
| 18 (app only) | Harley-Davidson |

`btv.m7523` walks this candidate list: `{last good, 0, 1, 6, 3, 2, 5, 4, 8, 7, 9, 3, 4, 1, 2, 0, 6, 5, 7, 8, 9}` (`btv.f5964`). If the previous attempt was less than 20 s ago, it resumes where it stopped. A protocol fixed in the vehicle profile replaces the list: it is tried on the first five attempts and on odd ones after that, with automatic search in between.

For each candidate:

1. Re-initialise the adapter (warm start, headers off).
2. `ATDPN`. Strip a leading `A` (the ELM327 marks an automatically chosen protocol `A6`). Send `ATSP<n>` (hex) only if it differs. DIAMEX: `ATP<n>`.
3. A reply containing `?` means the adapter rejected the protocol; move on.
4. Up to 7 rounds of a test request, cycling through `0100` (140 ms wait, expects `4100`), `010D` (240 ms, `410D`) and `010C` (240 ms, `410C`). A profile with a custom init string tests with `ATH1` instead.
5. A matching reply means the protocol is found. After the 12th candidate without one, the app warns "No response from ECU - Possible faulty adapter or Ignition not ON".

Overrides from the vehicle profile:

| Profile protocol | Commands |
| --- | --- |
| 14, Subaru SSM | `ATZ`, `ATPC`, `ATE0`, `ATI`; then `ATSPC` if the version contains `1.3`, else `ATSPS` |
| 15, monitor | `ATH1`, then `ATSP0` + `ATAL` (DIAMEX: `ATP0`), then `ATMA` |
| 17, Fiat | `ATCFC0`, `ATS0`, `ATCAF0`, `ATCRA7B0`, `ATSH7B0`, `ATST44` |

## Headers and ECU addresses

After a protocol is found (`btv.C1035`, "Identifying ECU(s) in system"), the app sends `ATH1`, reads the protocol back (`ATDPN`, or `ATN` on DIAMEX) and picks a header table. `btv.m7519` switches headers with `AT SH <header>` and skips the command when the header is already set. `btv.m7549` maps a module name to its header:

| Module | J1850 PWM (1) | J1850 VPW (2) | ISO 9141 (3) | KWP (4, 5) | CAN 11-bit (6, 8, B, C) | CAN 29-bit (7, 9, A) |
| --- | --- | --- | --- | --- | --- | --- |
| default (functional) | `616AF1` | `686AF1` | `686AF1` | `C233F1` | `7DF` | `DB33F1` |
| abs | `6128F1` | `6828F1` | `6828F1` | `C228F1` | `760` | `DB28F1` |
| srs | `6158F1` | `6858F1` | `6858F1` | `C258F1` | `737` | `DB58F1` |
| tcm | `6118F1` | `6818F1` | `6818F1` | `C218F1` | `7E1` | `DB18F1` |
| ins | `6110F1` | `6810F1` | — | `C230F1` | `720` | `DB10F1` |
| pam | — | `6C1AF1` | — | `C241F1` | `736` | — |
| tcmb | — | `6C28F1` | — | `8618F1` | `7E2` | — |
| bcm | — | `6C40F1` | — | `8658F1` | `7E0` | — |
| aux1 | — | `6C58F1` | `686AF1` | `8628F1` | `7E3` | — |
| aux2 | — | `6C10F1` | — | `8111F1` | `7E4` | — |
| auto | `C410F1` | `6C10F1` | `686AF1` | `C233F1` | `7E0` | `DB33F1` |

The columns follow the app's internal bus types, which group the ELM327 protocols as shown. A profile option switches the default to a physical address (`7E0` on CAN, `6C 10 F1` on VPW). A custom init string from the profile is sent next. Commands in it are separated by the two characters `\n`, and each is followed by 100 ms; `AT SI` and `AT FI` (slow and fast K-line init) get 3.3 s. An `AT SH` inside it becomes the new default header.

### Multi-ECU detection

The first `0100` after identification is read with headers on (`btv.C1036`, "Checking how many ECU(s) we have in the system..."). Leading `searching` lines are dropped. Then the shape of the first line decides:

| Reply (spaces removed) | Header shape | Which ECU the app keeps |
| --- | --- | --- |
| More than one line; starts `7e`, `4100` from character 5 (`7E8064100…`) | CAN 11-bit: 3 hex digits + length byte | `7E8` (engine) if present, else the first line's ID |
| More than one line; `4100` from character 10 | 4-byte header + length byte (CAN 29-bit) | Header whose source byte (byte 3) is `0x10`; else the last one with `0x11`; else the first line's |
| More than one line; `4100` from character 6 | 3-byte header (J1850, ISO 9141, KWP) | Source byte (byte 2) `0x10`; else the last line with `0x11`, `0x12`, `0x13` or `0x17`; else `0x40`; else the first line's |
| Anything else | One ECU | — |

On a multi-ECU car the app shows "Multi ECU system detected", keeps `ATH1` on, and filters later replies by the chosen header prefix (`btv.f6028`). With one ECU it sends `ATH0` and polls without headers.

## Live data (mode 01)

### Request format

`btv.C1035.m7609` builds one request per PID: mode `01`, the PID as two hex digits, and `\r`. **One PID per request**; the app never packs several PIDs into one CAN request. After each write it waits 0 ms (fast), 14 ms (normal) or 28 ms (once errors have been counted), plus 25 ms before and 70 ms after in "slow" mode.

**Response count.** In fast mode the app appends the number of ECUs that answered this PID last time: `010C1\r`. The ELM327 then returns as soon as that many replies have arrived, instead of waiting out its timeout. The count is learned per PID on the first reply (`btv.m7507` → `btn.m7209`). When a later reply has a different count, all learned counts are cleared (`btn.m7176`). A `?` while fast mode is on disables it for the session ("Data corruption detected - disabling full rate (fast) mode") and sends `ATAT1`.

Some PIDs (`btn.m7243`) are sent at most once every 1.2 s. When a pass of the loop sent nothing, it sleeps 150 ms. On CAN 11-bit and ISO 9141 buses it first sends one keepalive on the default header: `010D`, `010C`, `0111`, `0105` or `0100`, whichever is supported first.

### NO DATA escalation

Each `NO DATA`, `CAN ERROR` or bus-init error increments a counter (`btv.f5993`). Any valid reply resets it to 0:

| Count | Action |
| --- | --- |
| any, in a "reduced sensor" mode with nothing queued | `ATWS` (warm start), `ATE0`, `ATM0`, `ATL0`, `ATH1` if headers were on, 700 ms, `ATAT0`, `ATSP<n>`, `0100` |
| 22 | `0100` |
| 25 | `ATAT0`. CAN 11-bit: switch the default header to `7E0` (`AT SH 7E0`). ISO 9141: re-run the protocol search |
| over 32 | Re-run the protocol search |

### Supported-PID bitmaps

`0100`, `0120`, `0140`, … return 4 bytes, one bit per PID; the most significant bit of the first byte is the first PID in the range. `btv.m7515` stores each as a 32-character `0`/`1` string, and `btv.m7530` looks a PID up there. Every 32nd PID (`0x20`, `0x40`, …) says whether the next bitmap exists. `410000000000` (nothing supported) produces the warning "ECU does not support any PIDs!".

### Value formulas

`btv.m7507` decodes mode 01 data with the SAE J1979 formulas. `A`, `B`, `C` are the data bytes after `41 <pid>`:

| PID | Value | Formula |
| --- | --- | --- |
| `04` | Engine load, % | A × 100 / 255 |
| `05` | Coolant temperature, °C | A − 40 |
| `06`–`09` | Fuel trims, % | (A − 128) × 100 / 128 |
| `0A` | Fuel pressure, kPa | A × 3 |
| `0B` | Intake manifold pressure, kPa | A |
| `0C` | Engine speed, rpm | (256A + B) / 4. With the vehicle profile's filter on, values under 340 are discarded |
| `0D` | Speed, km/h | A × the profile's speed correction factor |
| `0E` | Timing advance, ° | A / 2 − 64 |
| `0F` | Intake air temperature, °C | A − 40 |
| `10` | Mass air flow, g/s | (256A + B) / 100 |
| `11` | Throttle position, % | A × 100 / 255 |
| `1F` | Run time since start, s | 256A + B |
| `21` | Distance with MIL on, km | 256A + B |
| `22` | Fuel rail pressure (relative), kPa | (256A + B) × 10 / 128 |
| `23` | Fuel rail pressure (direct), kPa | (256A + B) × 10 |
| `24`–`2B`, `34` | O2 sensor equivalence ratio | (256A + B) / 32768 |
| `2F` | Fuel level, % | A × 100 / 255 |
| `31` | Distance since codes cleared, km | 256A + B |
| `32` | Evap system vapour pressure, Pa | (signed A × 256 + B) / 4 |
| `3C`–`3F` | Catalyst temperature, °C | (256A + B) / 10 − 40 |
| `42` | Control module voltage, V | (256A + B) / 1000 |
| `43` | Absolute load, % | (256A + B) × 100 / 255 |
| `44` | Commanded equivalence ratio | (256A + B) / 32768 |
| `52` | Ethanol, % | A × 100 / 255 |
| `5C` | Oil temperature, °C | A − 40 |
| `5E` | Fuel rate, L/h | (256A + B) × 0.05 |

`14`–`1B` (O2 sensor voltages) use B for the trim byte; `7C`, `78` and `79` use the later bytes. User-defined PIDs go through an equation evaluator with byte variables `A` … `HZ` (`btv.f5887`).

Freeze-frame replies (`42 <pid> <frame> …`) are decoded with the same formulas and stored under a separate key.

## Fault codes

### Reading

Each request runs as a queued job with headers off:

| Job | Commands |
| --- | --- |
| Stored codes (`btv.C1035.m7613`) | `03`, `0100`, `ATI`, `ATAT0`, `03`, `ATAT<previous>` |
| Pending codes (`m7615`) | `07` |
| "Historic/cleared" codes (`m7596`) | `0A` (permanent DTCs in SAE J1979 terms) |
| KWP2000 (`m7598`) | `1800FF00`, `1802FF00`; `ATAL` first when the current protocol is 5 |
| Full scan (`m7614`) | `0100`, `ATSTA0`, `ATAT2`, `1900FF00`, `0101`, `03`, `1902FF00`, `07`, … |

The `ATAT0` around the second `03` gives slow modules the adapter's full timeout. The custom-init check (`btv.m7574`) skips `ATAT` and `ATST` changes when the vehicle profile has its own init string.

### Reply layout

`buk.m7754` decodes reply lines by prefix:

| Prefix | Meaning | Bytes per code |
| --- | --- | --- |
| `43` or `7F0378` | Stored | 2 |
| `47` or `7F0778` | Pending | 2 |
| `4A` or `7F0A78` | "Historic/cleared" | 2 |
| `53` or `7F1378` | Manufacturer, mode 13 | 2 |
| `58` or `7F1878` | Manufacturer, mode 18 | 2 + 1 status byte |
| `59` or `7F1978` | Manufacturer, mode 19 | 2 + 1 status byte |

A line exactly 14 hex characters long is a non-CAN reply (`43` plus three codes), so the app skips 2 characters. Any other length is treated as CAN (`43`, a count byte, then the codes), and the app skips 4. It stops at the end of the line or at `0000`.

The first hex digit of each code picks the letter and first digit:

| Nibble | `0`–`3` | `4`–`7` | `8`–`B` | `C`–`F` |
| --- | --- | --- | --- | --- |
| Code | `P0`–`P3` | `C0`–`C3` | `B0`–`B3` | `U0`–`U3` |

The next three digits are copied as they are: `0133` → `P0133`, `C123` → `U0123`. A line that contains `ERROR` produces the toast "Data Error from Adapter" (at most every 5 s).

### Clearing

`btv.C1035.m7610` sends `04`, `14`, `14FF00`, `140000` (the OBD and KWP2000 clear commands), sends `0100`, and repeats the set twice. It then sends the same four commands under each module header in turn: `ABS` (skipped on J1850 PWM), `SRS`, `TCM`, then `INS`, `PAM`, `BCM`, `AUX1` and `AUX2` where the bus has one (see [Headers](#headers-and-ecu-addresses)). It ends with `ATH1` if headers were on.

## Vehicle and adapter information

The "adapter information" job (`btv.C1035.m7605`) queues: `ATCS`, `ATI`, `AT@1`, `0100`, `0900`, `0902` (VIN), `0904` (calibration ID), `090A` (ECU name), `ATDPN`, `ATDP`, `ATRV`, and the KWP identification requests `1A88`, `1A90`, `1A86`, `1A87`. On STN adapters it adds `ST DI`, `ST I`, `ST MFR`, `ST SN` and `ST SLCS`. It then waits 3.7 s for the replies.

Multi-frame CAN replies come back as numbered lines (`0:`, `1:`, …), which the app joins in order before decoding. For `490A` (ECU name) it strips leading `00` padding.

Battery voltage is `ATRV` (`AT!10` on DIAMEX). The ELM327 measures it at pin 16 of the OBD connector, so it is available without an ECU.

## Reply handling

`btv.C1036` matches each reply line (lower-cased, spaces removed) against these, in this order:

| Line | Meaning | App action |
| --- | --- | --- |
| contains `searching` | Automatic protocol search in progress | "Searching for ECU (Is your ignition on?)..." |
| contains `?` | Unknown command, or corrupted data | Count an error. In fast mode: disable fast mode and send `ATAT1` |
| contains `elm327 v` | The adapter reset itself (brown-out) | Re-send `ATE0`, `ATM0`, `ATL0`, `ATH1` if headers were on, and `ATSP<n>` |
| contains `nodata`, `canerror` or `butinit:error` | No ECU answered / CAN fault / K-line init failed | See [NO DATA escalation](#no-data-escalation) |
| contains `stopped` | The adapter was interrupted mid-reply | Sleep 1 s, re-send `010D` (2 s wait) |
| starts with `unabletoconnect` | No protocol could be started | Re-run adapter initialisation |
| starts with `41` | Mode 01 data | Decode (see [Value formulas](#value-formulas)) |
| starts with `42` | Freeze frame | Decode under the freeze-frame key |
| starts with `43`, `47`, `4a`, `53`, `58`, `59` or `7f..78` | Fault codes | See [Fault codes](#fault-codes) |
| starts with `44` | Codes cleared | Reset the NO DATA counter |
| starts with `46` | Mode 06 test results | Decode 9-byte records on CAN: MID, TID, unit/scaling, value, min, max |
| starts with `48`, `45`, `61`, `62` | Mode 08/05 replies, KWP/UDS local identifier replies | Fed to user-defined PIDs |

`butinit:error` is a typo in the app (smali: `const-string "butinit:error"`). The ELM327 prints `BUS INIT: ...ERROR`, which normalises to `businit:...error`, so this check never matches. That error then falls through to the generic handling.

## Timing summary

| What | Value | Where |
| --- | --- | --- |
| Wait after `ATZ` | 1800 ms fast, 2000 ms normal, plus 250 / 500 ms before reading | `btv.m7517` |
| Extra wait before `ATZ` on Kiwi | 3000 ms | `btv.m7517` |
| Command retries until `>` | 5, backing off 40 / 80 / 120 ms | `btv.m7512` |
| Reply wait | about 7 s (20 × 350 ms) | `btv.C1034if.m7588` |
| Byte watchdog | 2.5 s, then `\r` | `btv.C1037` |
| Idle keepalive | `ATI` 7.6 s past the byte deadline | `btv.C1037` |
| Socket kill | 14 s past the byte deadline | `btv.C1037` |
| Dead stream | 8.5 s of `-1` reads | `btv.C1034if.run` |
| BLE write timeout | 5 s per write | `BLESerialPort.m16686` |
| BLE ready wait | up to 5 s after `connectGatt` | `buc.mo7664` |
| Kiwi scan / connect wait | 5 s / 5 s | `bui.mo7664` |
| Poll idle sleep | 150 ms | `btv.C1035.run` |

## Implementation notes

### Minimal client (bleak, `FFE0` adapter)

```python
import asyncio

from bleak import BleakClient, BleakScanner

SERIAL_SERVICE = "0000ffe0-0000-1000-8000-00805f9b34fb"
SERIAL_CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"


class Elm327:
    def __init__(self, client):
        self.client = client
        self.buffer = bytearray()
        self.prompt = asyncio.Event()
        char = client.services.get_characteristic(SERIAL_CHAR)
        self.response = "write-without-response" not in char.properties

    def on_notify(self, _char, data):
        self.buffer += data
        if b">" in data:
            self.prompt.set()

    async def command(self, text, timeout=7.0):
        self.buffer.clear()
        self.prompt.clear()
        payload = text.encode() + b"\r"
        await self.client.write_gatt_char(SERIAL_CHAR, payload, self.response)
        await asyncio.wait_for(self.prompt.wait(), timeout)
        raw = bytes(self.buffer).split(b">")[0].decode("ascii", "replace")
        lines = raw.replace("\n", "\r").split("\r")
        return [line.strip() for line in lines if line.strip()]


async def main():
    device = await BleakScanner.find_device_by_filter(
        lambda _d, adv: SERIAL_SERVICE in adv.service_uuids
    )
    async with BleakClient(device) as client:
        elm = Elm327(client)
        await client.start_notify(SERIAL_CHAR, elm.on_notify)
        await elm.command("ATZ", timeout=3.0)
        for cmd in ("ATE0", "ATM0", "ATL0", "ATS0", "ATH0", "ATAT1", "ATSP0"):
            await elm.command(cmd)
        print(await elm.command("0100", timeout=15.0))  # SEARCHING... then 4100...
        lines = await elm.command("010C")
        reply = bytes.fromhex(lines[-1].replace(" ", ""))
        if reply[:2] == b"\x41\x0c":
            print("rpm", (reply[2] * 256 + reply[3]) / 4)


asyncio.run(main())
```

Notes for a library:

- **Collect until `>`, not until a timeout.** Notifications split replies at arbitrary points, and the prompt is the only reliable end marker.
- **Expect `SEARCHING...`** on the first request after `ATSP0`. It can take several seconds on K-line cars.
- **One command at a time.** The ELM327 has no queue. A byte sent while it is busy aborts the current request (the reply then ends in `STOPPED`).
- **Strip spaces and lower-case** before matching, as the app does. Adapters differ in `ATS0` support and in case.
- **Use the response count** (`010C1`) once you know how many ECUs answer. It cuts each request from the adapter's timeout (about 200 ms by default) to the ECU's real response time.
- **Classic SPP adapters** (most ELM327 clones, OBDLink LX and MX) are not BLE. On Linux, use an RFCOMM socket (`socket.AF_BLUETOOTH`, `BTPROTO_RFCOMM`, channel 1); macOS has no comparable Python API.
- **Kiwi 3**: write to `1cce1ea8-…` in chunks of 20 bytes or less, and read notifications from `cacc07ff-…`. The rest is identical.

### Open questions

These need a capture from real hardware or more static work:

- [ ] Whether HM-10 style adapters accept write-with-response on `FFE1`, and whether the app's write-without-response default (inferred from Android) is what they need.
- [ ] Whether `requestMtu(128)` while the CCCD write is still pending succeeds on current Android versions, or silently fails (Android GATT allows one operation at a time).
- [ ] Which adapters, other than the HM-10 style and the PLX Kiwi 3, the app supports over BLE. Other common BLE adapters advertise `FFF0` (`FFF1` notify, `FFF2` write) or vendor UUIDs; this build has no code for them.
- [ ] Whether the `59` (mode 19) fault-code parser is right. It reads 3 bytes per code (2-byte code + status), while UDS `19 02` replies carry 4 (3-byte code + status).
- [ ] What `bvi.m7976` and `bvi.m7978` select for the insecure RFCOMM path (Android version or device lists).
- [ ] The exact meaning of the PLX iMFD `-` / `+` handshake and its reply byte `128`.

### Evidence

REA 6.4.0 `decode-android-resources` (apktool 3.0.3) on the APK above:

| Claim | REA evidence ID |
| --- | --- |
| App identity (1.2.22 / 1222), minSdk 9, targetSdk 22, SHA-256, manifest permissions, `BLESerialPort` service declaration | `ev_ee99941f49eb4b1c0e43aefcbe6358b2e9c9f5e3ee96caa40e81d9d521801fc9` |

REA's Android code operations were unavailable (no `jadx-headless-mcp` JAR), so everything else comes from reading a full jadx 1.5 decompile (`--deobf`). Each section cites its classes. Where jadx's control flow was ambiguous (the BLE connect order in `buc.mo7664`, the `butinit:error` literal), the facts were checked against apktool smali. Obfuscated names (`btv`, `m7517`, `C1035`, …) apply to version 1.2.22 of the app only.
