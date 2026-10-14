# Lifesense weight-scale protocol in the Philips Health app

Static protocol notes for the body-weight scale path in Philips Health (`com.philips.moonshot`). The scale speaks a bundled Lifesense BLE stack. Philips code discovers the device, pairs it in the app, and stores the reading. The bytes on the wire are parsed by Lifesense classes.

This is interoperability documentation of a local app binary. It is not a capture from a live scale.

## How this was read

| Item | Value |
| --- | --- |
| APK | `/Volumes/Development/Dev/Philips Healthsuite/com-philips-moonshot-145-61604772-2022658bb8582546b36e2d7f3999ed9f.apk` |
| SHA-256 | `637d313f5124d43bea4d5e85d2710fcc62a2e3354c62d6401b729df8c8e20ed8` |
| Container | Zip APK, `classes.dex` (9377 classes) and `classes2.dex` (414 classes) |
| REA | `open_binary` succeeded. `inspect_artifact` evidence `ev_bdf95b131069f2e983e796f6afcc22b8303026d9d2f7fd6ccc5eda0500daf5b5`, inventory `ev_9e540a35e8b082e7f3109f49304d8307384af85b66d75b4c08a5251e346c3d89`, manifest `agm_513daf7627512df37be4f53d744003620fa1341040c7906fe0725a39164deb2a`, root artifact `art_760db2018d705f99644a055fa05e673bdcc1317694b84d99693039481b353a8e`, graph `a82d1f72b9b403e6f5d712587ed1f28fc66f2480e950024b8202b2ac34bcc771` (1585 nodes). Session closed with `close_binary`. |
| JADX | `inspect_android_package` returned `capability_unavailable`. No JADX binary was on the machine, and none was installed. There is no Java decompilation in this manual. |
| DEX walk | A Dalvik walker over `classes.dex`. A method is cited only when the walk consumed `insns_size` exactly (`walk_ok`). |

Three labels are used below.

- **Observation.** An instruction, string, or field in the APK.
- **Inference.** A conclusion that follows from those observations and is marked as such.
- **Unresolved.** Searched, and the bytecode does not answer it.

The sibling file `com.philips.cdp.ohc.tuscany_10.21.1-…apkm` is Philips Sonicare (`com.philips.cdp.ohc.tuscany`, version 10.21.1). Its protocol notes are in [sonicare-toothbrush-protocol.md](sonicare-toothbrush-protocol.md).

## 1. Which code owns the scale

**Observation.** The scale tracker id is the string `transtek-scale`. The HealthSuite type string is `urn:phs|weightscale_`. Both are returned from `TrackerType.java`, class `Lcom/philips/moonshot/f/b`.

**Observation.** `SHNCapabilityDeviceInformationLifeSense.java` also contains `transtek-scale`, `transtek-bpm-arm`, `transtek-bpm-wrist`, and `DL8780`. The same Lifesense package serves the scale and the blood-pressure monitors. This manual follows the weight and body-fat parsers. Blood pressure, pedometer, height, and kitchen scale are mentioned only where the same dispatcher handles them.

**Observation.** The app assets include `video/180915_Philips_Pairing_scale_1_V05.mp4` and a second scale pairing video.

**Observation.** `libICPClient.so` and the `A6510001`–`A6510005` / `A651FFF1` UUIDs (base `4074-4131-BCE9-56D4261BC7B1` in `SHNServiceMoonshineStreaming`) belong to the Moonshine wrist-tracker path. They are not referenced by the Lifesense weight parsers.

### Call stack

```
Philips UI
  DevicesPairingActivity
  PairingService
  PairingServiceFlowScale          com.philips.moonshot.pair_devices.a.ap
                                   source PairingServiceFlowScale.java
    builds PairingServiceFlowTranstekMultipleUserDevice
                                   …pair_devices.a.ax
  BPMAndScaleAndThermometerSyncService
  DeviceDiscoveryService
  MoonSHNDeviceScannerInternal

Philips ShineLib
  SHNAssociationProcedureLifeSenseWS / Impl
                                   Lcom/philips/pins/c/a/e
  SHNDeviceLifeSenseImpl           Lcom/philips/pins/c/h
                                   source SHNDeviceLifeSenseImpl.java
  LSBleManagerWrapper              source LSBleManagerWrapper.java
  SHNLSPairer                      source SHNLSPairer.java ("Start pairing")
  BTGatt                           Lcom/philips/pins/shinelib/b/c
                                   source BTGatt.java

Lifesense SDK (obfuscated, usually no source file name)
  bean/o                           UUID constants
  c/g                              service maps and model-name table
  c/e                              advertisement and device-type helpers
  c/f                              measurement byte parsers
  n.a(LsDeviceInfo, byte[], UUID)  notification dispatcher
  d/g, d/n                         pairing state machine and command names
```

## 2. Android BLE entry

**Observation.** The binary `AndroidManifest.xml` contains the UTF-16 strings `android.permission.BLUETOOTH`, `android.permission.BLUETOOTH_ADMIN`, `android.permission.ACCESS_COARSE_LOCATION`, `android.permission.ACCESS_FINE_LOCATION`, and the feature `android.hardware.bluetooth_le`. The manifest strings do not include `BLUETOOTH_SCAN` or `BLUETOOTH_CONNECT`.

**Observation.** Scanning uses `BluetoothAdapter.startLeScan` and `stopLeScan`.

**Observation.** The ShineLib GATT wrapper (`BTGatt.java`, `Lcom/philips/pins/shinelib/b/c`) calls `connectGatt`, `discoverServices`, `readCharacteristic`, `writeCharacteristic`, `setCharacteristicNotification`, `writeDescriptor`, `disconnect`, and `close`.

**Observation.** Notification setup uses the Client Characteristic Configuration descriptor `00002902-0000-1000-8000-00805f9b34fb` (UUID field `bean/o.g`).

**Observation.** `BluetoothGatt.getServices` is called from `Lcom/lifesense/ble/a/c` `onServicesDiscovered`, which logs `successfully discovered gatt services...`, `service uuid-`, `characteristic uuid-`, `descriptor uuid-`, and the two failure strings `Failed to discovered gatt services,try again ...` and `Failed to discover gatt services...`. That callback reads UUID fields `q` (`180A`) and `g` (`2902`).

**Observation.** The standard Bluetooth SIG Weight Scale service `0x181D` and Body Composition service `0x181B` do not occur in this APK. Glucose in the same SDK uses the SIG service `0x1808` and characteristics `0x2A18`, `0x2A34`, `0x2A51` (fields `z`, `x`, `y`, `w`). Those are not the scale.

## 3. How a device is recognized

### 3.1 Advertisement

**Observation.** `Lcom/lifesense/ble/c/e` `a([B)Ljava/util/List` walks BLE advertising AD structures. A packed-switch matches AD type `0x02` and `0x03` (16-bit service UUID lists). Each UUID is little-endian (`low | (high << 8)`) and expanded with the format string `%08x-0000-1000-8000-00805f9b34fb`. The log line is `current scan service:`.

**Observation.** `c/e` `b([B)Ljava/lang/String` walks the same AD list. A packed-switch matches AD type `0x09` only. Type `0x09` is the Complete Local Name. The payload of that AD element is copied and decoded as a string. The caller `a([B, String)` logs `current scan device broadcast name:` and `;protocol :`, or `Failed to parse device broadcast name:`.

**Observation.** The protocol value in that log is the method's string argument. It is not sliced out of the local name inside this method. `c/e` `b(List)` walks discovered service UUIDs, looks each one up in `c/g.b`, and on a hit logs `set device type—?` plus ` uuid—?` plus `UUID.toString().substring(4, 8)`. On a miss it logs `Error,set device type failure-`. `c/e` `b(UUID)` returns that same `substring(4, 8)`, or the string `unknown uuid`.

**Inference.** The two-digit protocol id is the short form of the advertised 16-bit service UUID, translated through the map in section 3.2. The local name is a separate field (AD type `0x09`).

**Observation.** Max user count is `c/e` `a(String name, String protocol)`:

- Protocol `"00"` logs `Error!get max user number,type is unknow?-` and does not parse a count.
- For any other protocol, the count is `Integer.parseInt` of the substring after the last `'.'` in the local name. The log is ` Max user number-`.
- Protocol `"08"` (the blood-pressure family) uses `2` when the name has no dot, or when the parsed count is `0`.

**Observation.** A custom broadcast id must match `[0-9a-fA-F]{8}`. The success log is `set custom broadcast id :`. The failure log is `Error , Broadcast ID is invalid...`. The prefix string `LS-BLE` is in the same method (`c/e` `b(String)Z`).

**Unresolved.** The model-code table in section 3.3 is keyed by 5-character codes. The method that slices one of those codes out of the local name was not isolated. The max-user suffix (text after the last `.`) is the only name slice this pass recovered.

### 3.2 Protocol digit to GATT service

**Observation.** Device-type enum `Lcom/lifesense/ble/c/b` `<clinit>` (walk ok, 55 instructions) stores:

| Enum name | Field |
| --- | --- |
| `UNKNOWN` | `b.f` |
| `WEIGHT_SCALE` | `b.g` |
| `PEDOMETER` | `b.d` |
| `KITCHEN_SCALE` | `b.c` |
| `HEIGHT_RULER` | `b.b` |
| `SPHYGMOMANOMETER` | `b.e` |
| `FAT_SCALE` | `b.a` |

**Observation.** `Lcom/lifesense/ble/c/g` `<clinit>` (walk ok, 539 instructions) fills two maps from UUID fields in `bean/o`, then a digit-to-enum map. Duplicate puts are several lists, not a broken multimap.

Digit to service UUID (Bluetooth base `0000XXXX-0000-1000-8000-00805f9b34fb`):

| Digit | Enum | Service short ids |
| --- | --- | --- |
| `00` | `UNKNOWN` | none |
| `01` | `WEIGHT_SCALE` | `7802` |
| `02` | `FAT_SCALE` | `7892`, `7882`, `78A2`, `78D2` |
| `03` | `HEIGHT_RULER` | `7803` |
| `04` | `PEDOMETER` | `7801` |
| `08` | `SPHYGMOMANOMETER` | `7809`, `7889`, `78E9`, `7899` |
| `09` | `KITCHEN_SCALE` | `780A` |

The inverse map `g.l` (UUID to digit) matches that table and also tags `A400` and `FEE7` as digit `04`.

**Observation.** `c/e` `b` derives the type from the service UUID's `substring(4, 8)`.

### 3.3 Model-name table

**Observation.** The same `<clinit>` builds an unmodifiable map and stores it in `c/g.m` (`Collections.unmodifiableMap` at the end of the method). Keys are broadcast model codes. Values are product strings. The table mixes scales and blood-pressure monitors. Scale-relevant pairs present in that method:

| Code | Name |
| --- | --- |
| `12300` | `A2` |
| `12301` | `A2` |
| `202B6` | `BS 440 connect` |
| `106A0` | `BS-705-BT` |
| `106A1` | `BS-705-B` |
| `12510`, `1251B` | `GBF-1251-B` |
| `1255B` | `BF-1255-B` |
| `12560`, `1256B` | `BF-1256-B` |
| `12570`, `1257B`, `12571` | `GBF-1257-B` |
| `1144B` | `GBF-1144-B` |
| `12550` | `vs-3100` |
| `12660`, `12661`, `12662` | `WEB COACH One` |
| `12670`, `12671` | `WEB COACH` |
| `1136B`, `305A0` | `GKS-1136-BT` |

`GKS-1136-BT` is the kitchen scale (digit `09`). `GBF-*` and `BF-*` are body-fat scale names. Blood-pressure names in the same map include `LS802-B`, `LS805-B`, `LS808-B`, `LS810-B`, `TMB-1014-BT`, `TMB-1018-BT`, `BU 550 connect`, `BU 575 connect`, and `BW 300 connect`.

## 4. GATT catalog

All 16-bit ids below expand to `0000XXXX-0000-1000-8000-00805f9b34fb` except where the DEX string keeps a capital letter. The strings are the exact `UUID.fromString` arguments in `Lcom/lifesense/ble/bean/o` `<clinit>` (walk ok).

### 4.1 Fields

| Field | UUID | Role established by a later `sget` or by the map in section 3.2 |
| --- | --- | --- |
| `q` | `180A` | Device Information service. Read in `a/c.onServicesDiscovered` and `d/g.a`. |
| `j` | `2A29` | Manufacturer Name. Read in `a/a.b` and `d/g.a`. |
| `k` | `2A24` | Model Number. Same readers. |
| `m` | `2A25` | Serial Number. Same readers. |
| `i` | `2A27` | Hardware Revision. Same readers. |
| `h` | `2A26` | Firmware Revision. Same readers. |
| `n` | `2A28` | Software Revision. Same readers. |
| `o` | `2A23` | System ID. Declared. No scale `sget` found. |
| `l` | `2A50` | PnP ID. Declared. No scale `sget` found. |
| `p` | `2A2A` | Regulatory. Declared. No scale `sget` found. |
| `g` | `2902` | CCCD. |
| `W` | `7802` | Service. Digit `01`, `WEIGHT_SCALE`. |
| `Y` | `8A20` | Declared immediately after the `7802` group. No measurement `sget`. |
| `Z` | `8A21` | A2 weight notification. See section 6. |
| `X` | `8A22` | A2 fat / append notification. See section 6. |
| `F` | `8A23` | Declared in the `7802` group. No measurement `sget`. |
| `U` | `8A22` | Second field with the same UUID as `X`. A3 append notification. |
| `V` | `8A24` | A3 weight notification. |
| `e` | `7809` | Service. Digit `08`. |
| `c`, `d`, `D` | `8A90`, `8A91`, `8A92` | Declared with `7809`. |
| `N` | `7801` | Service. Digit `04`, pedometer. |
| `L`, `M` | `8A10`, `8A11` | Declared with `7801`. |
| `C` | `7803` | Service. Digit `03`, height. |
| `A`, `B`, `E` | `8A30`, `8A31`, `8A32` | Declared with `7803`. |
| `u` | `7892` | Service. Digit `02`, fat scale. |
| `t` | `7882` | Service. Digit `02`. |
| `v` | `78A2` | Service. Digit `02`. Also declared beside the A4 cluster. |
| `s` | `78D2` | Service. Digit `02`. |
| `b` | `7889` | Service. Digit `08`. |
| `f` | `78E9` | Service. Digit `08`. |
| `a` | `7899` | Service. Digit `08`. |
| `J` | `780A` | Service. Digit `09`, kitchen scale. |
| `G`, `I`, `H` | `8AA0`, `8AA1`, `8AA2` | `d/g.s` enables notify on `8AA2` with service `780A` and CCCD `2902`. |
| `O` | `A400` | Inverse map tags this as digit `04`. |
| `S` | `A401` | Declared between `A400` and `A402`. |
| `K` | `A402` | `d/g.r` enables notify on `A402` with CCCD `2902`. |
| `P` | `FEE7` | Inverse map tags this as digit `04`. |
| `Q`, `R` | `FEC8`, `FEC7` | Declared. No scale `sget`. |

**Observation.** `d/g.a` reads service `180A` and characteristics `2A29`, `2A24`, `2A25`, `2A27`, `2A26`, `2A28`, and logs `;maxUserNumber-`.

**Inference, characteristic families.** In `<clinit>` the characteristics are stored in a block immediately after their service. That grouping is consistent with the `sget` evidence where a `sget` exists (`7802` with `8A20`–`8A23`, `780A` with `8AA2`). It is not, by itself, proof that a characteristic was added to that service at runtime.

### 4.2 Which characteristic is A2, A3, and A4

**Observation.** Dispatcher `Lcom/lifesense/ble/n` `a(LsDeviceInfo, byte[], UUID)` (1175 instructions, walk ok) switches on `LsDeviceInfo.e()`:

| `e()` | Parser |
| --- | --- |
| `"04"` | `c/f.b([B)` pedometer |
| `"03"` | `c/f.c([B)` height |
| `"01"` | Weight scale, characteristics below |
| `"02"` | Fat scale, characteristics below |
| `"08"` | `c/f.e([B)` blood pressure |
| `"09"` | `c/f.o([B)` kitchen scale |

Inside digit `"01"`:

| Characteristic | Field | What runs |
| --- | --- | --- |
| `8A21` | `o.Z` | `c/f.a([B)WeightData_A2`. If `WeightData_A2.l()` is false the log is `Weight(A2) measure data-no fat data` and the reading is delivered. `l()` returns field `j` (`hasAppendMeasurement`). |
| `8A22` | `o.X` | Log `Weight(A2) measure data-has fat data`, then `c/f.a(WeightData_A2, byte[])` merges the fat packet into the stored A2 object. |

Inside digit `"02"`, `LsDeviceInfo.p()` selects the variant:

| `p()` and characteristic | What runs |
| --- | --- |
| `p()` equals `GENERIC_FAT`, characteristic `8A21` | `c/f.a(byte[], h)`. Parses an A2 weight packet, then fills body-composition floats from the user-profile object `h`. Log `Fat(Generic_fat) measure data...`. |
| `p()` equals `A3`, or `p()` equals `a.c.toString()`, characteristic `8A24` (`o.V`) | `c/f.d([B)WeightData_A3`. Log `Weight(A3) measure data-has append measurement ?` and `;impedance=`. Then either `has append measure data,wait for 0x8a22` or `no append measure data,return measure data from 0x8a24`. |
| same A3 gate, characteristic `8A22` (`o.U`) | `c/f.a(WeightData_A3, byte[])`. Log `Weight(A3) measure data-has fat data ?` and `return measure data from 0x8a22`. |
| same A3 gate, characteristic `8A21` | Parses with the A2 weight parser, and when `l()` is false logs `Weight(A3) measure data-no fat data` and copies the A2 bean into a new A3 bean. |
| same A3 gate, characteristic `8A22` reached via field `o.X` | Parses with the A2 fat parser, logs `Weight(A2) measure data-has fat data`, and copies floats onto an A3 bean. |

**Observation.** A2 and A3 pairing both log the runtime service UUID from field `g.z`. The strings are `Pro(A3)-Pair,service uuid-` and `Pro(A2)-Pair,service uuid-` in `Lcom/lifesense/ble/d/g` `i` (123 instructions, walk ok). Both arms read the same field. This method does not load `7802` or `8A24` as an immediate.

**Observation.** A4: `d/g.r` loads CCCD `2902` and characteristic `A402` (`bean/o.K`) twice. Class `b/a` contains the log tag `/A4-WeightScale-log(`. The pairing state machine also has directive name `WORKING_DEVICE_PAIRING_FOR_A4` (section 5).

**Inference.**

- Digit `01` / `WEIGHT_SCALE` / service `7802` is the A2 body-weight service. Its measurement characteristic is `8A21`. Its fat characteristic is `8A22`. `8A20` and `8A23` sit in that UUID group and are not selected by the dispatcher.
- A3 is a fat-scale variant (digit `02`, device protocol name `A3`). Its weight characteristic is `8A24`. Its append characteristic is `8A22`.
- A4 notifications are turned on for `A402`.
- Kitchen notify `780A` / `8AA2` is digit `09`. It is not the body-weight scale.

**Unresolved.** No `sget` pairs characteristic `8A24` with one of the digit-`02` services `7892`, `7882`, `78A2`, `78D2`. The dispatcher compares the characteristic UUID only. `78A2` is both a digit-`02` service and the UUID stored next to `A400` / `A401` / `A402` in `bean/o`. Those two facts are not enough to call `78A2` the A4 service. `A400` and `FEE7` are tagged digit `04` in the inverse map.

## 5. Pairing, and `createBond`

### 5.1 Android bonding

**Observation.** `BluetoothDevice.createBond` is method id 797 in `classes.dex`. Its only callers are:

- `BTDevice.java`, `Lcom/philips/pins/shinelib/b/b` method `d`
- `BTGatt.java`, inner class `c$14` method `run`

`classes2.dex` has no `createBond` reference. No class under `com.lifesense.ble` calls `createBond`.

**Observation.** `BTGatt.e` reads `getBondState` and posts `c$14`. Callers of `BTGatt.e` are `c$4.<init>` and `BTGatt.a`. The caller of `BTDevice.d` is `SHNDeviceImpl.b` (`SHNDeviceImpl.java`). Callers of `SHNDeviceImpl.b` are inside `SHNDeviceImpl` (`SHNDeviceImpl$1.run`, `SHNDeviceImpl$4.a`, `SHNDeviceImpl.a`, `SHNDeviceImpl.j`) and `SHNMoonshineDeviceDefinition.java` (class `g`, method `a`). No Lifesense class and no LifeSense scale class is in that list.

**Observation.** The Lifesense GATT callback uses `BluetoothGatt.getServices` and the in-band sequence in section 5.2 (password, random, XOR, broadcast id, user slot). `SHNDeviceImpl` has a `SHNBondInitiator`. Moonshine has its own `SHNAssociationProcedureMoonshine`.

**Answer.** The scale path does not call `BluetoothDevice.createBond`. The only `createBond` sites are ShineLib `BTGatt` / `BTDevice`, reached from `SHNDeviceImpl`, whose out-of-class caller in this DEX is the Moonshine device definition.

**Unresolved residual.** `SHNDeviceImpl.b` is also called from other methods of `SHNDeviceImpl`. A subclass that goes through `SHNDeviceImpl.j` or `SHNDeviceImpl.a` could still bond. No LifeSense scale class was among those callers. The search covered every method named `createBond`, every method whose name contains `Bond`, and the caller chains of `BTGatt.e`, `c$14.<init>`, `BTDevice.d`, and `SHNDeviceImpl.b`.

### 5.2 In-band pairing vocabulary

**Observation.** `Lcom/lifesense/ble/d/n` contains these operating-directive strings:

`OPERATING_CONNECT_DEVICE`, `READ_DEVICE_INFO`, `SET_INDICATE`, `SET_NOTIFY`, `WRITE_AUTH_RESPONSE`, `WRITE_BIND_USER_NUMBER`, `WRITE_BROADCAST_ID`, `WRITE_C3`, `WRITE_C4`, `WRITE_C7`, `WRITE_C9`, `WRITE_CA`, `WRITE_CB`, `WRITE_CC`, `WRITE_CE`, `WRITE_DISCONNECT`, `WRITE_INIT_RESPONSE`, `WRITE_START_MEASURE_COMMAND`, `WRITE_UNBIND_USER_NUMBER`, `WRITE_USER_INFO`, `WRITE_UTC_TIME`, `WRITE_XOR_RESULTS`, `WRITE_VIBRATION_VOICE`, `PAIRED_RESULTS_PROCESS`, `WORKING_DEVICE_PAIRING_FOR_A2`, `WORKING_DEVICE_PAIRING_FOR_A3`, `WORKING_DEVICE_PAIRING_FOR_A4`, `WORKING_DATA_UPLOADING_FOR_A2`, `WORKING_DATA_UPLOADING_FOR_A3`, `WORKING_DATA_UPLOADING_FOR_A3_1`.

**Observation.** `d/f` logs `custom fat scale user info` and `write weight scale vibration voice`. `d/g` `i` logs `Pro(A3)-Pair,service uuid-`, `waiting for write user id...`, and `Pro(A2)-Pair,service uuid-`. `d/h` logs `Error,failed to discover service...`, `Error,failed to discover notify characteristic...`, `current discover service uuid =`, `;protocol=`, and `waiting for start to measuring,service uuid-`.

**Observation.** `SHNDeviceLifeSenseImpl` persists `LsDeviceInfo` under the keys `DEVICE_ID`, `DEVICE_NAME`, `DEVICE_TYPE`, `DEVICE_SN`, `DEVICE_PASSWORD`, `DEVICE_BROADCAST_ID`, `DEVICE_MODEL_NUMBER`, `SOFTWARE_VERSION`, `HARDWARE_VERSION`, `FIRMWARE_VERSION`, `MANUFACTURE_NAME`, `DEVICE_SYSTEM_ID`, `DEVICE_USER_NUMBER`, `DEVICE_PAIR_STATUS`, `DEVICE_MAX_USER_NUMBER`, `DEVICE_PAIR_SING_SIGNATURE`, `DEVICE_PROTOCOL_TYPE`, `DEVICE_SUPPORT_DOWNLOAD_INFO_FEATURE`.

**Inference from the log lines and directive names, not from a single straight-line trace.** Connect by address, read Device Information, exchange a password with a random and an XOR result, write the broadcast id, enable notify, bind a user slot, write user info, write UTC, wait for a measurement, write disconnect. The UI tells the person to stand on the scale and reports when every user slot is taken.

**Unresolved.** The byte values of `WRITE_C3`, `WRITE_C4`, `WRITE_C7`, `WRITE_C9`, `WRITE_CA`, `WRITE_CB`, `WRITE_CC`, `WRITE_CE`, and the layout of the password, random, and XOR frames were not recovered. Knowing the directive name is not the frame format.

## 6. Measurement packets

Parsers live in `Lcom/lifesense/ble/c/f`. Field names come from `toString` in `WeightData_A2` and `WeightData_A3` (the string is followed by a field read of that letter) and from the setter that the parser calls. Setter bodies are a single `iput`.

Multi-byte numbers are little-endian. `aget-byte` sign-extends. The helpers below mask with `0xFF` before they shift, so the assembled integers are unsigned.

### 6.1 Number helpers

**Observation.** `c/f.l([B)J` builds a 32-bit value:

```
byte[0] | (byte[1] << 8) | (byte[2] << 16) | (byte[3] << 24)
```

Each byte is masked to 8 bits. Byte 0 is the least significant byte.

**Observation.** `c/f.j([B)I` is the 16-bit form (`byte[0] | (byte[1] << 8)`). `c/f.k([B)I` is the 24-bit form.

**Observation.** `c/f.m([B)F` takes four bytes. The magnitude is `l()` of `(byte[0], byte[1], byte[2], 0)`, so a 24-bit little-endian integer. The value is that integer times `10` raised to `byte[3]`. `byte[3]` is sign-extended before `Math.pow`. A stored hundredths value is exponent `-2` (`0xFE`). The exponent is inside the packet. The parser does not divide by a fixed constant.

**Observation.** `c/f.i([B)String` treats `l()` as seconds since `2010-01-01 00:00:00` in time zone `Asia/Shanghai`, and formats `yyyy-MM-dd HH:mm:ss`.

**Observation.** `c/f.n([B)F` decodes two bytes as a decimal float used for body-composition fields. `uint16 = byte[0] | (byte[1] << 8)`.

- Bits 12–15 are the exponent nibble.
- Bit 15 set selects a transformed exponent: `exponent = -(((nibble - 1) ^ -1) & 0x0F)`.
- Bit 11 clear: mantissa is `uint16 & 0x0FFF`.
- Bit 11 set: mantissa is the negation of the 11-bit two's complement of `uint16 & 0x07FF`.
- The float is `mantissa * 10^exponent`.

That is the operation sequence in the method. No captured notification was checked against it.

**Observation.** `c/f.a(B)S` returns `byte & 0xFF`.

### 6.2 A2 weight packet — characteristic `8A21`

**Observation.** Parser `c/f.a([B)WeightData_A2` (412 instructions, walk ok). Called from `n.a` when the protocol digit is `"01"` and the characteristic is `8A21`.

Fixed header:

| Offset | Width | Destination |
| --- | --- | --- |
| 0 | 1 | Flag byte. |
| 1–3 | 3 | Magnitude of `weight` (field `G`, double), via `m()`. |
| 4 | 1 | Signed exponent of that weight, via `m()`. Setter `f(D)`. |

The cursor then starts at offset 5. A flag bit selects the next field. The cursor advances only when the bit is set.

| Flag bit | Width | Setter | Field | `toString` name |
| --- | --- | --- | --- | --- |
| `0x01` | 4 | bytes copied into field `i`, then `i()` | `i`, `s` | `UTCbytes`, `date` |
| `0x02` | 4 | `m()` then `b(D)` | `A` | `resistance_1` |
| `0x04` | 4 | `m()` then `c(D)` | `B` | `resistance_2` |
| `0x08` | 1 | `d(I)` | `E` | `userNo` |
| `0x10` | 1 | status byte, see below | | |
| `0x20`, `0x40` | 0 | unit, taken from the flag byte itself | `u` | `deviceSelectedUnit` |
| `0x80` | | not read by this method | | |

Status byte (the `0x10` field):

| Bits | Stored as | Meaning in this parser |
| --- | --- | --- |
| bit 0 = 0 | `weightStatus` `H` = 0 | static `WeightData_A2.h` |
| bit 0 = 1 | `weightStatus` `H` = 1 | static `WeightData_A2.g` |
| bits 1–3 | `impedanceStatus` `x` = that 3-bit value | statics `d,e,f,a,c,b` are `0,1,2,3,4,5` |
| bit 4 = 0 | `hasAppendMeasurement` `j` = false | getter `l()` |
| bit 4 = 1 | `j` = true, and `flag` `w` = 1 | getter `l()` is what makes `n.a` keep the reading and wait |

The A3 parser assigns names to the same bit positions (section 6.4): weight bit 0 is `WEIGHT UNSTABLE` / `WEIGHT STABLE`, and impedance bits 1–3 are `IDLE`, `PROCESSING`, `SHOES`, `BAREFOOT`, `FINISH`, `ERROR`. A2 stores the integers. A3 stores the strings.

Unit bits of the original flag (`flag & 0x60`), sparse-switch:

| Mask | String passed to `d(String)` |
| --- | --- |
| `0x00` (default) | `Kg` |
| `0x20` | `LB` |
| `0x40` | `St` |
| `0x60` | `Kg` |

`lbWeightValue` (`y`), `stSectionValue` (`C`), and `stWeightValue` (`D`) are computed on the phone from `weight`. They are not extra packet fields.

- `c/f.a(D)D` turns the kilogram value into pounds. It keeps one decimal (`DecimalFormat` `"#.#"`, comma rewritten to dot), multiplies by `10`, then applies `(n * 11023 + 5000) / 10000 * 2 * 0.1`. That is the app's kg-to-lb factor (about `2.2046`).
- `stSectionValue` is `(int) lbWeight / 14`.
- `stWeightValue` is `lbWeight % 14`, formatted with `"#.##"`. The modulus is the double `14.0` (`const-wide/high16 0x402c`).
- `weight` is then rewritten through `"#.#"` so the stored kilogram value has one decimal place.

After the parse, `n.a` copies three device-info strings onto the bean: `LsDeviceInfo.d()` into `deviceSn` (`v`, setter `e(String)`), `LsDeviceInfo.a()` into `broadcastId` (`r`, setter `a(String)`), `LsDeviceInfo.b()` into `deviceId` (`t`, setter `c(String)`).

### 6.3 A2 fat / append packet — characteristic `8A22`

**Observation.** Parser `c/f.a(WeightData_A2, byte[])` (274 instructions, walk ok). Called from `n.a` on characteristic `8A22` for digit `"01"`.

| Flag bit | Width | Setter | Field | `toString` name |
| --- | --- | --- | --- | --- |
| header 0 | 1 | flag | | |
| header 1–4 | 4 | read into a local array that the next instruction overwrites | not stored | |
| cursor starts at 5 | | | | |
| `0x01` | 1 | `a(B)S` then `d(I)` | `E` | `userNo` |
| `0x02` | 2 | `n()` then `a(F)` | `k` | `BasalMetabolism` |
| `0x04` | 2 | `n()` then `b(F)` | `m` | `BodyFatRatio` |
| `0x08` | 2 | `n()` then `c(F)` | `n` | `BodyWaterRatio` |
| `0x10` | 2 | `n()` then `f(F)` | `q` | `VisceralFatLevel` |
| `0x20` | 2 | `n()` then `e(F)` | `p` | `MuscleMassRatio` |
| `0x40` | 2 | `n()` then `d(F)` | `o` | `BoneDensity` |
| `0x80` | 1, sometimes 2 | see below | `l`, `F` | `Battery`, `voltageData` |

When bit `0x80` is set, the next byte's low 3 bits go to `Battery` through `a(B)`. If bit 3 of that same byte is set, voltage is `((bit7 * 4096) + (bit6 * 256) + nextByte) / 100.0`. The divisor is the double `100.0` (`const-wide/high16 0x4059`). Setter `e(D)` writes `voltageData` (`F`).

### 6.4 A3 weight packet — characteristic `8A24`

**Observation.** Parser `c/f.d([B)WeightData_A3` (380 instructions, walk ok). Called from `n.a` when digit is `"02"`, the device protocol name is `A3` (or `a.c`), and the characteristic is `8A24`.

| Flag bit | Width | Setter | Field | `toString` name |
| --- | --- | --- | --- | --- |
| header 0 | 1 | flag | | |
| header 1–4 | 4 | `m()` then `d(D)` | `v` | `weight` |
| cursor starts at 5 | | | | |
| `0x01` | 4 | `l()` then `a(J)`; `i()` then `c(String)` | `t`, `i` | `utc`, `date` |
| `0x02` | 4 | `m()` then `e(D)` | `w` | `weightDifferenceValue` |
| `0x04` | 4 | `m()` then `a(D)` | `m` | `impedance` |
| `0x08` | 1 | `a(B)S` then `e(I)` | `s` | `userId` |
| `0x10` | 1 | status byte below | | |
| `0x60` (`>> 5`) | 0 | unit from the flag | `k` | `deviceSelectedUnit` |
| `0x80` | | not read | | |

Status byte:

| Bits | Value | String | Setter | Field |
| --- | --- | --- | --- | --- |
| bit 0 | 0 | `WEIGHT UNSTABLE` | `h(String)` | `weightStatus` `x` |
| bit 0 | 1 | `WEIGHT STABLE` | `h(String)` | `weightStatus` `x` |
| bits 1–3 | 0 | `IDLE` | `g(String)` | `impedanceStatus` `n` |
| bits 1–3 | 1 | `PROCESSING` | `g(String)` | `impedanceStatus` `n` |
| bits 1–3 | 2 | `SHOES` | `g(String)` | `impedanceStatus` `n` |
| bits 1–3 | 3 | `BAREFOOT` | `g(String)` | `impedanceStatus` `n` |
| bits 1–3 | 4 | `FINISH` | `g(String)` | `impedanceStatus` `n` |
| bits 1–3 | 5 | `ERROR` | `g(String)` | `impedanceStatus` `n` |
| bit 4 | 0 / 1 | boolean | `a(Z)` | `appendMeasurement` `b`, getter `k()` |
| bit 5 | 0 | `0.2LB division` | `a(String)` | `accuracyStatus` `a` |
| bit 5 | 1 | `0.1LB division` | `a(String)` | `accuracyStatus` `a` |

Unit from `(flag & 0x60) >> 5`: `0` → `Kg`, `1` → `lb`, `2` → `St`, via `e(String)`.

Pounds and stones are computed the same way as A2, into `lbWeightValue` (`o`), `stSectionValue` (`q`), and `stWeightValue` (`r`). The kilogram `weight` is rewritten through `"#.#"`.

`n.a` then copies `LsDeviceInfo.d()` to `deviceSn` (`l`), `a()` to `broadcastId` (`h`), and `b()` to `deviceId` (`j`).

On the no-fat `8A21` arm of the A3 gate, the code builds an A3 from an A2: date from `A2.e()` (field `s`), weight from `A2.j()` (field `G`), impedance from `A2.h()` (field `B`, which is `resistance_2`), user from `A2.i()` (field `E`). Integer status fields are passed through `WeightData_A3.a(I)String` and `b(I)String` into the A3 status strings. Those two string converters were not disassembled in this pass.

### 6.5 A3 append packet — characteristic `8A22`

**Observation.** Parser `c/f.a(WeightData_A3, byte[])` (224 instructions, walk ok).

| Flag bit | Width | Setter | Field | `toString` name |
| --- | --- | --- | --- | --- |
| header 0 | 1 | flag | | |
| header 1–4 | 4 | `l()` then `a(J)` | `t` | `utc` |
| cursor starts at 5 | | | | |
| `0x01` | 1 | `a(B)S` then `e(I)` | `s` | `userId` |
| `0x02` | 2 | `n()` then `a(F)` | `c` | `basalMetabolism` |
| `0x04` | 2 | `n()` then `b(F)` | `e` | `bodyFatRatio` |
| `0x08` | 2 | `n()` then `c(F)` | `f` | `bodyWaterRatio` |
| `0x10` | 2 | `n()` then `f(F)` | `u` | `visceralFatLevel` |
| `0x20` | 2 | `n()` then `e(F)` | `p` | `muscleMassRatio` |
| `0x40` | 2 | `n()` then `d(F)` | `g` | `boneDensity` |
| `0x80` | 1 | `a(B)S` then `c(I)` | `d` | `battery` |

Unlike the A2 fat parser, bytes 1–4 are stored (as UTC), and bit 7 is only the battery byte. There is no voltage field on this path.

### 6.6 Phone-side body composition

**Observation.** `c/f.a(byte[], h)` parses the A2 weight packet, then calls `a(DDDII)`, `a(DIDI)`, `a(DDI)`, `b(DIDI)`, and `a(DI)`. Those methods are polynomials over height, weight, and an integer sex/age flag from object `h` (`h.d()`, `h.b()`, `h.a()`, `h.c()`). Results are stored with `b(F)`, `c(F)`, `e(F)`, `a(F)`, `d(F)` on the A2 bean (body fat, body water, muscle, basal metabolism, bone). The coefficients are inline doubles in `c/f`. They are not BLE fields.

`GENERIC_FAT` on digit `"02"` and characteristic `8A21` is the path that runs this.

### 6.7 Worked layout, all optional bits set

A2 weight, flag `0x1F` (all five presence bits, unit bits clear so the unit stays `Kg`):

```
0     flags
1..4  weight = uint24_le * 10^(int8)
5..8  UTC seconds since 2010-01-01 00:00:00 Asia/Shanghai, and the formatted date
9..12 resistance_1, same decimal encoding as weight
13..16 resistance_2
17    userNo
18    status (weight bit, impedance bits, append bit)
```

A2 fat, flag `0x7F`, appended on `8A22` after that weight:

```
0     flags
1..4  read, not stored
5     userNo
6..7  basal metabolism
8..9  body fat
10..11 body water
12..13 visceral fat
14..15 muscle
16..17 bone
```

A3 weight, flag `0x1F`:

```
0     flags
1..4  weight
5..8  utc and date
9..12 weightDifferenceValue
13..16 impedance
17    userId
18    status (stable, foot contact, append, division)
```

A3 append on `8A22`, flag `0xFF`:

```
0     flags
1..4  utc
5     userId
6..7  basal metabolism
8..9  body fat
10..11 body water
12..13 visceral fat
14..15 muscle
16..17 bone
18    battery
```

Presence bits change the later offsets. A capture has to honour the flag byte. The exponent byte, not a hard-coded `/100`, sets the decimal place.

## 7. What Philips stores

**Observation.** Sync goes through `BPMAndScaleAndThermometerSyncService`. Body-weight types in ShineLib are `SHNDataBodyWeight` (`Lcom/philips/pins/shinelib/datatypes/f`, fields `float a`, `int b`, `float c`), `SHNDataWeight` (`datatypes/t`), and `SHNDataExtendedWeight` (`pins/c/a`). Units in the Lifesense beans are `kg`, `lb`, and `st`, with the A2 default string `kg` written in `<init>`.

**Unresolved.** The three `SHNDataBodyWeight` fields were not tied to kilogram, user id, and a second float by disassembling the sync call. The Philips layer records product name, machine id, the user list, and the first weight plus the extended weight. The assignment of those onto `f.a`, `f.b`, and `f.c` is still open.

## 8. Questions that were open

### Packet byte layout

Answered for the four weight parsers in section 6, from `c/f` methods whose walks landed on `insns_size`. Endianness is little-endian. The weight scale factor is `10` to the power of a signed byte in the packet (`c/f.m`). Body-composition fields use the 16-bit decimal float `c/f.n`. Pounds and stones are computed in the phone.

Still open inside that answer: a live notification to confirm a real exponent byte, and the A4 (`A402`) payload, which has no parser of this shape in the methods above.

### Which GATT service is A2, A3, and A4

Answered at the characteristic and protocol-digit level in section 4.2.

- A2 is digit `01`, service `7802`, characteristics `8A21` (weight) and `8A22` (fat).
- A3 is digit `02` with protocol name `A3`, characteristics `8A24` (weight) and `8A22` (append). The service UUID that contains `8A24` is one of `7892`, `7882`, `78A2`, `78D2`, and which one was not proven.
- A4 enables notifications on `A402`. Its service handle and its bytes are open.
- `780A` / `8AA2` is the kitchen scale.

### Does the scale path call `BluetoothDevice.createBond`?

No Lifesense method does. The only callers are ShineLib `BTDevice.d` and `BTGatt` `c$14.run`, reached from `SHNDeviceImpl` and the Moonshine device definition. Scale pairing is the in-band password, XOR, broadcast-id, and user-slot exchange. The frame bytes of that exchange are still open. The subclass caveat is in section 5.1.

## 9. Still unresolved

These were searched in `classes.dex` and are not answered by the methods above.

1. Opcode bytes and payloads for `WRITE_C3`, `WRITE_C4`, `WRITE_C7`, `WRITE_C9`, `WRITE_CA`, `WRITE_CB`, `WRITE_CC`, `WRITE_CE`, `WRITE_XOR_RESULTS`, `WRITE_AUTH_RESPONSE`, and `WRITE_INIT_RESPONSE`.
2. The service UUID that owns characteristic `8A24`.
3. The A4 notification layout on `A402`, and whether service `78A2` is that A4 service or only a digit-`02` fat-scale service.
4. The character range of the local name that is used as the key into `c/g.m`.
5. `WeightData_A3.a(I)String` and `b(I)String`, which turn A2 integer statuses into A3 strings on the no-fat conversion path.
6. The mapping from Lifesense fields onto `SHNDataBodyWeight` `a`, `b`, and `c`.
7. Any check against a live scale. Every layout in section 6 is what the decoder accepts.

## 10. Evidence index

| Fact | Where |
| --- | --- |
| APK identity | Path and SHA-256 above. REA `open_binary`, `inspect_artifact` ids in the header. |
| Tracker id, HealthSuite type | `TrackerType.java`, `Lcom/philips/moonshot/f/b` |
| Pairing flow class | `PairingServiceFlowScale.java`, `Lcom/philips/moonshot/pair_devices/a/ap` |
| GATT wrapper | `BTGatt.java`, `Lcom/philips/pins/shinelib/b/c` |
| Scale device wrapper | `SHNDeviceLifeSenseImpl.java`, `Lcom/philips/pins/c/h` |
| UUID constants | `Lcom/lifesense/ble/bean/o` `<clinit>` |
| Digit and model maps | `Lcom/lifesense/ble/c/g` `<clinit>`, fields `g.b`, `g.l`, `g.m` |
| Device-type enum | `Lcom/lifesense/ble/c/b` `<clinit>` |
| Advertisement parse | `Lcom/lifesense/ble/c/e` `a([B)List`, `b([B)String`, `b(List)`, `a(String,String)I` |
| Notify enable | `Lcom/lifesense/ble/d/g` methods `r` (`A402`) and `s` (`780A` / `8AA2`) |
| Dispatcher | `Lcom/lifesense/ble/n` `a(LsDeviceInfo, byte[], UUID)` |
| Packet parsers | `Lcom/lifesense/ble/c/f` `a([B)WeightData_A2`, `a(WeightData_A2, byte[])`, `d([B)WeightData_A3`, `a(WeightData_A3, byte[])`, helpers `l`, `m`, `n`, `i`, `j`, `k` |
| Field names | `WeightData_A2.toString`, `WeightData_A3.toString`, and the one-instruction setters |
| `createBond` | method id 797, callers in section 5.1 |
| Moonshine, not the scale | `libICPClient.so`, `A651…` UUIDs, `SHNAssociationProcedureMoonshine` |
