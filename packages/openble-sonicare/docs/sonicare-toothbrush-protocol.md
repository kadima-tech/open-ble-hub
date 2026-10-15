# Philips Sonicare toothbrush protocol

Static protocol notes for the toothbrush path in Philips Sonicare (`com.philips.cdp.ohc.tuscany` 10.21.1). The handle speaks a GATT family whose UUIDs share the base `477ea600-a260-11e4-ae37-0002a5d5`. The app discovers the brush, connects with the shared Philips Bluetooth adapter, and reads and writes those characteristics from Kotlin handlers in the `cbt` package.

This is interoperability documentation of a local app binary. It is not a capture from a live toothbrush.

The weight-scale notes for the sibling Philips Health app are in [lifesense-scale-protocol.md](../../openble-lifesense/docs/lifesense-scale-protocol.md).

## How this was read

| Item | Value |
| --- | --- |
| Package | `/Volumes/Development/Dev/Philips Healthsuite/com.philips.cdp.ohc.tuscany_10.21.1-256_4arch_7dpi_79f17031170db29b4c8f951b1861544a_apkmirror.com.apkm` |
| SHA-256 | `1886dbdf1c399ee0e30f401f3d8a172fa62eacd6c27e0f661c94e209d80c29bb` |
| Container | APKM v5 zip. `info.json` names `com.philips.cdp.ohc.tuscany`, version 10.21.1, versionCode 256, `min_api` 31, posted 2026-09-29. `base.apk` is 85,721,012 bytes and holds `classes.dex` through `classes6.dex`. ABI splits hold the native libraries. `base.apk` was read inside the zip. |
| REA | `inspect_android_package` returned `capability_unavailable` (`provider_id` jadx) and reported that the APKM is a zip. No JADX binary was on the machine, and none was installed. `open_binary` was not called, so this manual has no REA evidence ids. |
| DEX walk | A Dalvik walker over `base.apk`. A method is cited only when the walk consumed `insns_size` exactly (`walk_ok`). UUID strings in the tables below were checked again against `classes4.dex` and `classes5.dex` while this file was written. |
| const/4 | Format `11n`: the register is `(word >> 8) & 0xF` and the literal is `(word >> 12) & 0xF`, sign-extended. Literals in this manual use that decode. |

Three labels are used below.

- **Observation.** An instruction, string, or field in the package.
- **Inference.** A conclusion that follows from those observations and is marked as such.
- **Unresolved.** Searched, and the bytecode does not answer it.

The connection path in this manual is the Java and Kotlin GATT code in `base.apk`. The ABI splits ship `libwatsonWrapper.so` (`com.philips.cdp.ohc.watson`), `libtoolChecker.so`, `libexecutorch.so`, `libsqlcipher.so`, and the usual AndroidX and image libraries. `assets/handle_feature.json` has a flag `isWatsonCalibrationRequired`. Watson is the brush-sensor calibration library.

`classes6.dex` contains `258EAFA5-E914-47DA-95CA-C5AB0DC85B11`, the RFC 6455 WebSocket GUID. No CBT handler loads it.

## 1. Which code owns the brush

**Observation.** Two device plugins are constructed from `classes4.dex` `Log/h` method `v`: `new Lng/a` and `new Lrg/a`. Both implement `Lzq/a` and `Lzq/e`.

### 1.1 Current handle plugin, `Lng/a`

**Observation.** `<init>` holds the strings `Philips OHC`, `Philips Sonicare`, and `NA`.

**Observation.** Static field `j` is `10000000-0000-0000-0000-0002a5d50001`. Method `g` returns it with `sget j`. That value is the plugin id.

**Observation.** Static field `k` is `477ea600-a260-11e4-ae37-0002a5d50001`. `<init>` stores `k` into instance field `f` (`Lar/h`). Method `f` is three instructions and returns that field:

```
iget-object Lng/a;->f:Lar/h;
return-object v0
```

**Observation.** The foreground scan filter takes the UUID from `Lng/a.f()` as the member of its service-UUID set (`j0.d`). The advertised service used to find this plugin's brush is `477ea600-a260-11e4-ae37-0002a5d50001`.

**Unresolved.** The other `ScanFilter` arguments (address, name, manufacturer data) on that plugin filter were not read. Only the service-UUID set was confirmed.

**Observation.** Method `d(peripheral)` builds the handler list: `CBTBattery`, `CBTDeviceInformation`, `CBTSonicare`, `CBTRoutine`, `CBTDeviceDiagnostic`, `CBTExtended`, `CBTStorage`, `CBTSensor`, `CBTBrushHead`, and `ByteStreamingServiceHandler$a.a(...)`. The last of those is the `a651…` family in section 7.

**Observation.** `PeripheralImpl` logs `Plugin declares support for service UUID ` and `No service handler registered for service uuid: `. A handler whose service is absent on the peripheral is tolerated.

### 1.2 Second plugin, `Lrg/a`

**Observation.** `<init>` holds `Philips Sonicare`, `Philips`, and `NA`.

**Observation.** Static field `j` is `10000000-0000-0000-0000-0002a5d50002`. Method `g` returns it. That value is the plugin id.

**Observation.** Static field `k` is `e50ba3c0-af04-4564-92ad-fef019489de6`. The same store-and-return pattern puts `k` in instance field `f`, and method `f` returns it. The scan filter service UUID for this plugin is that `e50b…` UUID. The condor `BluetoothCommunicationStrategy` uses the same service UUID.

**Observation.** Method `d` builds `CBTDeviceInformation` and `ByteStreamingServiceHandler$a.b(...)`, the `e50b0001`–`e50b0007` family. It does not build the `477ea600` handlers.

**Unresolved.** Which retail model selects `Lng/a` and which selects `Lrg/a` was not tied. `assets/ProductsConfiguration.json` (and the country variants beside it) were not read for that mapping.

### Call stack

```
Philips Sonicare UI and workers          classes4.dex
  Lng/a                                  handle plugin, scan service …0001
  Lrg/a                                  second plugin, scan service e50ba3c0-…
  tuscany.ble.blesync…workermanager.b    background scan by advertised name
  ScanIntentReceiver
  NativeScanWorker / NativeConnectWorker

CBT handlers                             classes4.dex
  CBTSonicareServiceHandler              service …0001
  CBTRoutineServiceHandler               service …0002
  CBTStorageServiceHandler               service …0004
  CBTSensorServiceHandler                service …0005
  CBTBrushHeadServiceHandler             service …0006
  CBTDeviceDiagnosticServicesHandler     service …0007
  CBTExtendedServiceHandler              service …0008
  CBTBatteryServiceHandler               standard Battery service 180F
  CBTDeviceInformationServiceHandler     standard Device Information 180A

Shared Philips connectivity adapter      classes5.dex
  AndroidCentral / Scanner
  PendingIntentScanReceiver
  Lrq/t                                  the connectGatt caller
  Lrq/v                                  BluetoothGattCallback forwarder
  PeripheralImpl                         service-handler setup and GATT queue
  Lwq/n                                  WaitingUntilBondedState, createBond
```

`Lar/h` is the app's UUID wrapper. Companion `Lar/h$a.a(String)` builds one from the DEX string. Each handler's `<clinit>` does that, then `sput`s the next static field. The service is the `…00NN` value. The characteristics are the `40xx` / `42xx` / `43xx` / `44xx` values. A read or write method is tied to a field when it `sget`s that field immediately before `new-instance` of the surviving Kotlin `$$inlined$` class.

## 2. Android BLE entry

**Observation.** The binary `AndroidManifest.xml` contains these UTF-16 strings: `android.permission.BLUETOOTH`, `android.permission.BLUETOOTH_ADMIN`, `android.permission.BLUETOOTH_CONNECT`, `android.permission.BLUETOOTH_SCAN`, `android.permission.ACCESS_FINE_LOCATION`, `android.permission.ACCESS_COARSE_LOCATION`, `android.permission.ACCESS_BACKGROUND_LOCATION`, and the feature `android.hardware.bluetooth_le`. The same scan found `com.philips.cdp.ohc.tuscany.permission.INTERNAL_BROADCAST`, `com.philips.cdp.ohc.tuscany.ble.blesync.backgroundtask.workermanager.ScanIntentReceiver`, `com.philips.connectivity.bluetooth.adapter.ACTION_BLE_SCAN`, and `com.philips.connectivity.bluetooth.adapter.internal.scanning.PendingIntentScanReceiver`.

**Observation.** `com.philips.connectivity.bluetooth.adapter.scanning.ACTION_RESTART_SCAN` is a string in `classes5.dex`. It was not in the manifest UTF-16 runs.

**Observation.** The manifest string scan did not find `NEARBY_WIFI_DEVICES` or a companion-device permission. `classes4.dex` does contain the log `Near BY permission not given.`.

### 2.1 Foreground scan

**Observation.** `Scanner.v` (`startLeScan`) checks a permission helper (`Lqq/k.a`), that the adapter is enabled (log `Bluetooth adapter not enabled.`, error `SCAN_FAILED_BLUETOOTH_OFF`), and that location is enabled (`Lqq/k.c`, log `Not scanning. Location is disabled.`, error `SCAN_FAILED_LOCATION_OFF`). It then calls `BluetoothLeScanner.startScan(List, ScanSettings, PendingIntent)`. The `PendingIntent` comes from `PendingIntentScanReceiver$a.a`.

**Observation.** `Scanner.w` builds `ScanSettings`. The instruction immediately before `setScanMode` is `const/4 v4, #0`.

**Observation.** Empty filters can be replaced. `Scanner.i` and `AndroidCentral.A` refer to `isUnfilteredScanningForced`. The shared scanner converts the app's filter objects through `Ltq/a.b`. `ScanFilter` fields present in that type are `serviceUUIDs`, `peripheralAddress`, `name`, and `manufacturerDataFilterOptions`.

### 2.2 Background scan

**Observation.** The app-level scanner is `classes4.dex` `tuscany.ble.blesync.backgroundtask.workermanager.b`, separate from the shared `Scanner`. Method `e()` loads `Philips Sonicare` and calls `ScanFilter.Builder.setDeviceName`. That filter is a name filter.

**Observation.** Method `g` logs `proceedForScanning > 26` and `ProceedForScanning failed`. The instruction immediately before `setScanMode` is `const/4 v1, #0`. It then calls `b.f()` for the `PendingIntent` and `BluetoothLeScanner.startScan`. Stop-path logs are `Unexpected runtime exception stopping Android O background scanner:`, `NullPointerException stopping Android O background scanner:`, and `SecurityException stopping Android O background scanner:`.

**Observation.** `f()` builds the `PendingIntent` with `PendingIntent.getBroadcast`. The request-code immediate is `0x181e5`.

**Observation.** `NativeScanWorker` returns without scanning when Bluetooth is off, when the app is in the foreground, when a firmware upgrade is in progress, and when it logs `Background sync stopped after detecting rooted device`. `ScanIntentReceiver` reads `android.bluetooth.le.extra.LIST_SCAN_RESULT` and `android.bluetooth.le.extra.CALLBACK_TYPE`, and logs `PendingIntent broadcast received device address`. `NativeConnectWorker` connects a stored `deviceAddress` when the app is not in the foreground. Periodic scan work stores `scan_filters`.

**Inference.** The immediate `0` passed to `ScanSettings.setScanMode` is `ScanSettings.SCAN_MODE_LOW_POWER` in the public Android API. Both the shared scanner and the background worker pass that immediate.

### 2.3 GATT connect

**Observation.** The only `BluetoothDevice.connectGatt` caller found is `classes5.dex` `Lrq/t.c` (walk ok, 49 instructions). `Lrq/t` extends `BluetoothGattCallback`. The overload invoked is `connectGatt(Context, boolean autoConnect, BluetoothGattCallback, int transport) -> BluetoothGatt`.

The call site, after the permission check `Lnq/a.a` (tags `ConnectivityBluetoothAdapter` / `GattClient`):

```
@13 const/4 v0, #0          ; returned early when the permission check fails
@17 iget Lrq/t;->a          ; BluetoothDevice
@19 iget Lrq/t;->b          ; Context
@21 invoke Lrq/t.i          ; regs v5, v6
@24 move-result v3
@25 const/4 v4, #2
@26 invoke BluetoothDevice.connectGatt
                            ; regs v6, v2, v3, v5, v4
```

`v6` is the `BluetoothDevice`, `v2` is the `Context`, `v3` is the boolean returned by `Lrq/t.i`, `v5` is the `Lrq/t` instance used as the callback, and `v4` is `2`.

**Inference.** `BluetoothDevice.TRANSPORT_LE` is `2`. The transport argument is that constant.

**Unresolved.** `Lrq/t.i` was not disassembled. The `autoConnect` boolean is whatever that method returns.

**Observation.** On failure the log is `Unable to connect GATT client.` On success it is `GATT client connected.` `Lrq/v` is the callback object and forwards `onConnectionStateChange`, `onServicesDiscovered`, `onCharacteristicRead`, `onCharacteristicWrite`, `onCharacteristicChanged`, `onDescriptorRead`, `onDescriptorWrite`, and `onMtuChanged` to `Lrq/t`. `Lrq/v.b` and `Lrq/w.b` call `Lrq/t.c`.

**Observation.** `AndroidCentral` builds a peripheral from an address with `BluetoothAdapter.getRemoteDevice` after `toUpperCase(Locale.ROOT)`. One `AndroidPeripheral` constructor passes `BondInitiator.NONE`. The address constructor takes a bond-initiator argument.

**Observation.** After connect, `PeripheralImpl` logs `Connecting.`, `Connected`, `Disconnected`, `Service handler setup complete`, and `No services available!`, and queues GATT reads, writes, and notifications. Descriptor failures log `SERVICE_UUID`, `CHARACTERISTIC_UUID`, and `DESCRIPTOR_UUID`. Reconnect is scheduled with `Reconnect with delay of` and the field `reconnectAfterDisconnect`. A watchdog surrounds GATT requests.

### 2.4 Notifications

**Observation.** The Client Characteristic Configuration descriptor `00002902-0000-1000-8000-00805f9b34fb` is built with `UUID.fromString` in `classes5.dex` `Lcom/philips/connectivity/bluetooth/adapter/internal/a` `<clinit>`.

**Observation.** CBT notifications go through `CBTServiceHandler.h1` (enable) and `g1` (disable), via `notifyCharacteristicIO`. Explicit enables are in section 6.

**Inference.** Many `CharacteristicDescription` constructors are passed the integer `16`. That matches the standard GATT notify property bit `0x10`. The walk did not prove the constructor stores it as the property mask. Nearby `const/4` defaults in an early pass were mis-decoded, so this stays an inference.

## 3. How a device is recognized

Two scan paths feed the same connect call.

| Path | Filter | Where |
| --- | --- | --- |
| Foreground, handle plugin | Service UUID `477ea600-a260-11e4-ae37-0002a5d50001` from `Lng/a.f()` | Shared `Scanner.v`, scan-mode immediate `0`, `PendingIntent` from `PendingIntentScanReceiver` |
| Foreground, second plugin | Service UUID `e50ba3c0-af04-4564-92ad-fef019489de6` from `Lrg/a.f()` | Same scanner |
| Background sync | Advertised name `Philips Sonicare` via `setDeviceName` | `workermanager.b`, scan-mode immediate `0`, `PendingIntent` request code `0x181e5` |

**Observation.** Plugin ids `10000000-0000-0000-0000-0002a5d50001` and `…0002` are returned by method `g`. They are not the scan-filter service UUIDs. The scan filters use field `k` through method `f`.

**Observation.** `ScanIntentReceiver` delivers `LIST_SCAN_RESULT` into the app. `NativeConnectWorker` then connects a stored address. The foreground path reaches `AndroidCentral`, which builds `AndroidPeripheral` for the address and enters `Lrq/t.c`.

## 4. GATT catalog

Every `477ea600` string in `classes4.dex` is listed in the tables below. The suffix is the last four hex digits of `477ea600-a260-11e4-ae37-0002a5d5XXXX`, in the case stored in the DEX. There is no `…0003` string.

`classes5.dex` also contains the standard UUIDs `00001801-0000-1000-8000-00805f9b34fb` (Generic Attribute) and `00002A05-0000-1000-8000-00805f9b34fb` (Service Changed). They were not assigned to a CBT handler.

### 4.1 Handle service, `CBTSonicareServiceHandler`

Superclass `CBTServiceHandler`. Interfaces `Lmh/a` and `Lph/a`. Log tag `SonicareServiceHandler`.

| Field | UUID suffix | Role |
| --- | --- | --- |
| `l` | `0001` | Service. This is also `Lng/a` field `k`, the foreground scan UUID. |
| `m` | `4010` | Handle state. The read builds `readHandleState$$inlined$readCharacteristicIO$1` (method `A1`). Enable `i0` (`enableHandleState`) calls `h1` on `m`. Disable `r0` calls `g1`. Change consumer `s1` logs `handle state changed to` and parses `HandleState`. |
| `n` | `4050` | Handle time. Read method `g` builds `readHandleTime$$inlined$readIntCharacteristicIO$1`. `w1` returns `n` and is used by `writeHandleTime$1`. One log is `readTimeBeforeAssociationAndWriteCurrentTime`. Change consumer `t1` logs `changeConsumer handle time read`. |
| `o` | `4020` | Available brushing routines. Setup callback `Lcom/philips/cdp/ohc/cbt/services/a0` reaches `r1` and then `u1`, which logs `changeConsumer AVAILABLE_BRUSHING_ROUTINES_CHAR_UUID`. |
| `p` | `4022` | Routine ids. Method `o` builds `readAvailableRoutineIds`. Method `v` builds `writeRoutineId`. Callback `b0` logs `AVAILABLE_BRUSHING_ROUTINES_IDS_UUID` (`v1`). |
| `q` | `4040` | Cumulative motor runtime. Method `e0` builds `readCumulativeMotorRuntime`. |

**Observation.** The service-description method `K0` registers `m`, `n`, `o`, and `p`. `q` is read by `e0` and is outside that registration list.

### 4.2 Routine service, `CBTRoutineServiceHandler`

Log tag `RoutineServiceHandler`. Service field `l` is `0002`.

| Field | UUID suffix | Read / write tied by `sget` |
| --- | --- | --- |
| `m` | `4090` | `readBrushingTime` (`L1`). |
| `n` | `4080` | `readRoutineId` (`N1`). |
| `o` | `4091` | `readRoutineLength` (`O1`). |
| `p` | `4070` | `readCurrentSessionId` (`e`). |
| `q` | `40b0` | `readIntensity` (`M1`) and `writeIntensity` (`P`). |
| `r` | `4082` | `writeRoutineState` (`P1`). |

**Observation.** `enableUpdates` method `C1` notifies fields `o`, `p`, `m`, `n`, and `q` (`4091`, `4070`, `4090`, `4080`, `40b0`).

**Observation.** Log strings on the notify side: `notifyBrushingTime` / `BRUSHING_TIME_CHAR_UUID` (`D1`), `notifyRoutineNumber` / `ROUTINE_NUMBER_CHAR_UUID` (`G1`), `notifyRoutineLength` (`F1`), `notifySessionId` (`I1`), `INTENSITY_CHAR_UUID` / `notifyIntensity` (`u1` / `E1`), `notifyRoutineState` / `changeConsumer routine state` (`H1` / `v1`).

**Unresolved.** `D1`, `E1`, `F1`, `G1`, `H1`, and `I1` were not re-checked for the `sget` that would pin each log to a field. The read and write rows above are the solid mapping. `C1` is the solid enable list.

**Observation.** Method `m` logs `feature is not supported` on the routine-id write. Coverage, overpressure, scrubbing, and brushing-type listeners log the same string.

### 4.3 Session storage, `CBTStorageServiceHandler`

Log tag `CBTStorageServiceHandler`. Service field `q` is `0004`. Session access is named SACP in the logs. The bytes written to these characteristics were not recovered.

| Field | UUID suffix | Role |
| --- | --- | --- |
| `k` | `40d0` | `readLatestSessionId` (`z1`). Change consumer `u1` logs `onActiveSessionId` and parses an int with `Ldh/c.g`. |
| `l` | `40D5` | `writeSessionType` (`r`). |
| `m` | `40E0` | `writeActiveSessionId` (`O`). Also notified. |
| `n` | `4110` | `requestSessionData` (`i`), `requestBulkSessionData` (`t`, log `writeSacpToReadBulkSessions`), `cancelSessionReadInProgress` (`k0`, log `writeSacpToCancelSessionReadInProgress`). Change consumer `v1` logs `onSacp`. |
| `o` | `4100` | Notified. Callback class `storage/j`. Change consumer `x1` logs `onSessionData`. |
| `p` | `40d2` | `readAvailableSessionCount` (`y1`). |

**Observation.** `enableStorageNotifications` (`Q`) calls `h1` on `m`, `o`, and `n` (`40E0`, `4100`, `4110`). Writes use `Characteristic$WriteType.a`. The enum constant behind `a` was not decoded.

### 4.4 Sensor service, `CBTSensorServiceHandler`

Service field `l` is `0005`.

| Field | UUID suffix | Role |
| --- | --- | --- |
| `m` | `4130` | `enableAllNotification` (`i0`) calls `h1` on `m`. |
| `n` | `4120` | `enableSensorNotification` writes `n` (`o1`). Change consumer `n1` logs `changeConsumer selectedSensorData`. |

**Unresolved.** The sensor notification payload was not recovered.

### 4.5 Brush-head service, `CBTBrushHeadServiceHandler`

Log tag `SonicareBrushHeadServiceHandler`. Service field `l` is `0006`.

| Field | UUID suffix | Role |
| --- | --- | --- |
| `m` | `4210` | Registered in `K0` with callback class `Lcom/philips/cdp/ohc/cbt/services/a`. That callback's method `a` calls `CBTBrushHeadServiceHandler.o1`. `o1` has no const-strings. |
| `n` | `4230` | Method `k` logs `readNfcTagVersion` and constructs `readBrushHeadSerialNumber$$inlined$readCharacteristicIO$1`. `enableUpdates` `l0` and `disableBrushHeadUpdates` `a` call `h1` / `g1` on `n`. Callback class `b` method `a` calls `m1`. `m1` has no const-strings. |
| `o` | `4220` | `readFactoryMode` (`Y`). |
| `p` | `4280` | `readLifetimeLimit` (`o0`). |
| `q` | `4290` | `readLifetimeUsage` (`h0`). |
| `r` | `42C0` | `readRingId` (`p`). |

**Observation.** `K0` callback classes are `m` → `a`, `n` → `b`, `o` → `c`, `p` → `d`, `q` → `e`, `r` → `f`. Those classes were not fully disassembled.

**Observation.** Separate change consumers: `q1` logs `changeConsumer nfc tag version read`. `r1` logs `byteArray`, `: changeConsumer serial Number `, and `BLE_CBT`. Further consumers exist for factory mode, lifetime limit, lifetime usage, and ring id (`s1`, `t1`, `u1`, `v1`).

**Unresolved.** The read-method name for `4210` was not recovered. Method `k` carries both the `readNfcTagVersion` log and the `readBrushHeadSerialNumber` class name for `4230`, and `q1` / `r1` were not linked to `m` versus `n`.

**Observation.** Dental-diary and connected-devices screens also const-string `…4290` and `…4280`. That is display code using the same UUIDs.

### 4.6 Diagnostic service, `CBTDeviceDiagnosticServicesHandler`

Service field `j` is `0007`.

| Field | UUID suffix | Read |
| --- | --- | --- |
| `k` | `4310` | `readErrorValuePersistent` |
| `l` | `4320` | `readErrorValueVolatile` |
| `m` | `4330` | `readProximityValue` |
| `n` | `4340` | `readExternalFlash` |
| `o` | `4350` | `readPressureSensor` |
| `p` | `4360` | `readInvalidChargerCount` |
| `q` | `4370` | `readDebugInformation` |

**Observation.** The service description `K0` registers `k`, `l`, and `p`.

### 4.7 Extended service, `CBTExtendedServiceHandler`

| Field | UUID suffix | Role |
| --- | --- | --- |
| `j` | `0008` | Service. |
| `k` | `4420` | `readHandleSettings` and `writeHandleSettings`. |

**Observation.** Method `I` logs `enableUpdates: not supported for ExtendedServiceHandler` under the tag `BLE_CONDOR`. Change consumer `l1` logs `errorValuePersistent`. The diagnostic handler has a read of the same name on `4310`. These are two services.

### 4.8 Battery

**Observation.** `CBTBatteryServiceHandler` extends `Lfr/b` (`BatteryServiceHandler`). `Lfr/b.<clinit>` (walk ok, 27 instructions) stores:

| Field | UUID | Role |
| --- | --- | --- |
| `k` | `0000180F-0000-1000-8000-00805f9b34fb` | Battery service. |
| `l` | `00002A19-0000-1000-8000-00805f9b34fb` | Battery Level. |

**Observation.** Method `g1` returns field `l`. Companion `Lfr/b$a.a` calls `g1`. Method `b0` logs `readBatteryLevel` and calls that companion. Method `h1` logs `Received battery level ` and parses the bytes with `Ler/a.a` into an integer. `<init>` registers service `k` and characteristic `l`. This handler has no `477ea600` UUID.

**Unresolved.** A `const/16` of `#17` sits next to the parser call. The width and layout of the integer were not recovered.

### 4.9 Device Information

**Observation.** `CBTDeviceInformationServiceHandler` extends the shared `DeviceInformationServiceHandler`. `<clinit>` `sput` order, from a walk that completed:

| Field | UUID | Role |
| --- | --- | --- |
| `k` | `0000180A-…` | Device Information service. |
| `l` | `00002A29-…` | Manufacturer Name. |
| `m` | `00002A24-…` | Model Number. |
| `n` | `00002A25-…` | Serial Number. |
| `o` | `00002A27-…` | Hardware Revision. |
| `p` | `00002A26-…` | Firmware Revision. |
| `q` | `00002A28-…` | Software Revision. |
| `r` | `00002A23-…` | System ID. |
| `s` | `00002A2A-…` | IEEE certification. |
| `t` | `00002A50-…` | PnP ID. |
| `u` | string `deviceInformation` | Log name, not a UUID. |

The `…` tail is `0000-1000-8000-00805f9b34fb`, and the strings in the DEX use that capitalisation (`0000180A`, `00002A24`, and so on).

**Observation.** Companion method `a` calls static `p1`, which returns field `p` (firmware `2A26`), used by `readFirmwareVersion` (log `firmware`). Companion `b` calls `q1`, which returns field `m` (model `2A24`), used by `readModelNumber` (log `model`). Companion `c` calls `r1`, which returns field `n` (serial `2A25`), used by `readSerialNumber` (log `serial`). Method `w1` logs `SystemID (...) is not equal to actual peripheral address`.

## 5. Bonding, and `createBond`

**Observation.** `BluetoothDevice.createBond() -> boolean` is `classes5.dex` method id 68. It takes no arguments. The only caller is `Lwq/n.d` at program counter 118.

**Observation.** `Lwq/n.<init>` holds the string `WaitingUntilBondedState`. The superclass is `Lwq/g`. The method reads `getBondState`, registers a bond-status listener through `AndroidCentral.H`, and switches on the `AndroidPeripheral$BondInitiator` ordinal (`Lwq/n$b.a`). The enum `<clinit>` strings are `NONE`, `PERIPHERAL`, and `APP`. `Lwq/n$b.<clinit>` `sget`s `PERIPHERAL` and `APP` for that when-map.

Logs in that state:

| Log | Meaning carried by the string |
| --- | --- |
| `Bond creation started.` | `createBond` was invoked. |
| `Already bonded, bonding or bond creation failed.` | Bond already present, or creation failed. |
| `Waiting for peripheral to initiate bonding!` | Initiator `PERIPHERAL`. |
| `Reached WaitingForBondState but there is no bond initiator, likely getting stuck!` | Initiator `NONE`. |
| `Bond created.` | Bond reached bonded. |
| `Bond state changed from` | Broadcast transition. |
| `Bond lost` | Error `ConnectionError.BOND_LOST`. |

**Observation.** Constructors of `Lwq/n` are reached from `Lwq/b.l` and `Lwq/d.g`.

**Observation.** The default `AndroidPeripheral.<init>` `sget`s `BondInitiator.NONE`. `Lwq/d.d` (`GattConnectingState`, log `onEnter.`) logs `GattConnectingState: Resetting bondInitiator to NONE (device is unbonded).` when the device is unbonded, `sget`s `NONE`, and calls `Lcom/philips/connectivity/bluetooth/adapter/internal/c.m`. The only callers of `internal/c.m` (method id 4749) are `Lwq/d.m` and `Lwq/d.d`, and both pass `NONE`. `Lwq/d.m` also compares the current initiator with `NONE` and `PERIPHERAL` and calls `getBondState`.

**Observation.** A prefix walk of `sget` / `sput` / `iget` / `iput` of fields named `APP`, `PERIPHERAL`, and `NONE` on `BondInitiator` found `APP` in the enum `$values`, the enum `<clinit>` `sput`, and `Lwq/n$b.<clinit>` (the when table). No caller `sget`s `BondInitiator.APP` to store it. Walks that failed before `insns_size` were skipped, so a method that loads `APP` and then fails the walk would have been missed.

**Observation.** `assets/handle_feature.json` (`handleFeature`, 6501 bytes) sets `isSupportBtPairing` to false on `featureSet_One` and `featureSet_Two`, and true on `featureSet_Three` through `featureSet_Seven`. `isRPASupported` is true only on `featureSet_Five`, `featureSet_Six`, and `featureSet_Seven`. The string `isSupportBtPairing` is also in the `classes4.dex` pool. No `walk_ok` method const-strings it.

**Unresolved.** The store that would put `BondInitiator.APP` into the peripheral was not found, and the feature flag was not shown selecting that enum. The `APP` arm that calls `createBond()` exists and runs if something sets `APP`.

**Observation.** `AndroidCentral$pairingRequestBroadcastReceiver$1` handles `android.bluetooth.device.action.PAIRING_REQUEST`. The method refers to `BLUETOOTH_PRIVILEGED`, `setPairingConfirmation`, and `setPin`. The bond-status broadcast is `android.bluetooth.device.action.BOND_STATE_CHANGED`, with extras `BOND_STATE`, `PREVIOUS_BOND_STATE`, and `DEVICE`. This receiver belongs to the shared adapter.

**Inference.** The connect path that was recovered writes `NONE` and does not call `createBond()`. Bonding is a separate state (`WaitingUntilBondedState`) that calls `createBond()` for initiator `APP`, waits for initiator `PERIPHERAL`, and logs the stuck warning for initiator `NONE`.

## 6. What the handlers do after connect

Once `PeripheralImpl` logs `Service handler setup complete`, the `Lng/a` handlers issue the reads, writes, and notifications in section 4. The order below is the set of operations the bytecode names, not a traced session transcript.

1. Identity and power. Device Information reads model (`2A24`), serial (`2A25`), and firmware (`2A26`). Battery reads `2A19` and parses an integer. Handle time `4050` is read and written (`readTimeBeforeAssociationAndWriteCurrentTime`).
2. Handle state `4010` is notified (`enableHandleState`).
3. Routine `0002` notifies brushing time, routine length, session id, routine id, and intensity (`C1` on `4090`, `4091`, `4070`, `4080`, `40b0`). Intensity `40b0` and routine state `4082` have write methods. A routine-id write logs `feature is not supported`.
4. Storage `0004` notifies active session id `40E0`, session data `4100`, and the SACP characteristic `4110`. Named writes are session type `40D5`, active session id `40E0`, session-data request, bulk session request (`writeSacpToReadBulkSessions`), and cancel (`writeSacpToCancelSessionReadInProgress`). Latest session id `40d0` and available session count `40d2` are reads. `onActiveSessionId` parses an int.
5. Sensor `0005` enables notification on `4130` and writes `4120` (`enableSensorNotification`). The change log is `changeConsumer selectedSensorData`.
6. Brush head `0006` enables notification on `4230`. Factory mode `4220`, lifetime limit `4280`, lifetime usage `4290`, and ring id `42C0` have read methods. `4210` is registered and its callback calls `o1`.
7. Diagnostic `0007` reads the seven characteristics in section 4.6. The description registers three of them (`4310`, `4320`, `4360`).
8. Extended `0008` reads and writes handle settings `4420`. `enableUpdates` logs that it is not supported.

**Unresolved.** SACP write bytes, the `HandleState` enum values, the sensor notification payload, the battery integer width, and the brush-head value on `4210` were not recovered. `Characteristic$WriteType.a` was not decoded.

## 7. The other UUID families

Both families are built by `ByteStreamingServiceHandler` companions and are present because that shared code is in this APK. The scale app's Moonshine wrist tracker uses the `a651` base as well. See the scale manual for that product.

### 7.1 `a651`, registered on the handle plugin

**Observation.** `ByteStreamingServiceHandler$a.a` builds these, and `Lng/a.d` registers that handler:

| UUID |
| --- |
| `a6510001-4074-4131-bce9-56d4261bc7b1` |
| `a6510002-4074-4131-bce9-56d4261bc7b1` |
| `a6510003-4074-4131-bce9-56d4261bc7b1` |
| `a6510004-4074-4131-bce9-56d4261bc7b1` |
| `a6510005-4074-4131-bce9-56d4261bc7b1` |
| `a651fff1-4074-4131-bce9-56d4261bc7b1` |

The handle scan UUID and the services in section 4 stay on the `477ea600` base.

### 7.2 `e50b`, the second plugin

**Observation.** `ByteStreamingServiceHandler$a.b` builds `e50b0001` through `e50b0007` on the base `af04-4564-92ad-fef019489de6`. The service UUID `e50ba3c0-af04-4564-92ad-fef019489de6` is `Lrg/a` field `k` and the condor `BluetoothCommunicationStrategy` service. `Lrg/a.d` registers Device Information plus this byte-streaming handler.

## 8. Questions that were open

### How does the app find the toothbrush?

Answered in section 3. The handle plugin's foreground filter is service `477ea600-a260-11e4-ae37-0002a5d50001`. The second plugin's filter is service `e50ba3c0-af04-4564-92ad-fef019489de6`. Background sync filters the advertised name `Philips Sonicare`. Both use `BluetoothLeScanner.startScan` with a `PendingIntent` and scan-mode immediate `0`.

### How does it connect?

Answered in section 2.3. `Lrq/t.c` calls `BluetoothDevice.connectGatt(context, autoConnect, callback, 2)`. The callback is the `Lrq/t` instance. Transport `2` is `TRANSPORT_LE`. `autoConnect` is the return value of `Lrq/t.i`, which was not disassembled. `PeripheralImpl` then matches discovered services to the handlers from `Lng/a.d` or `Lrg/a.d`.

### Does the brush path call `BluetoothDevice.createBond`?

The only caller is `WaitingUntilBondedState` (`Lwq/n.d`), and it runs for `BondInitiator.APP`. The recovered connect path stores `NONE`: the default peripheral constructor loads `NONE`, and `GattConnectingState` resets an unbonded device to `NONE`. No store of `APP` was found. `isSupportBtPairing` is true for feature sets Three through Seven in `handle_feature.json`, and no `walk_ok` method loads that string. Section 5 has the search limit.

### Which GATT service is the handle?

Service `…0001` on `CBTSonicareServiceHandler`, which is the same UUID the handle plugin scans for. Routine, storage, sensor, brush head, diagnostic, and extended services are `…0002`, `…0004`, `…0005`, `…0006`, `…0007`, and `…0008`. Battery is standard `180F` / `2A19`. Identity is standard `180A` with model `2A24`, serial `2A25`, and firmware `2A26`.

## 9. Still unresolved

These were searched and are not answered by the methods above.

1. The boolean `Lrq/t.i` returns into `connectGatt` as `autoConnect`.
2. Which caller, if any, stores `BondInitiator.APP`, and whether `isSupportBtPairing` selects it. The `APP` arm and the JSON flag both exist. The store between them was not found. Failed walks were skipped.
3. The role of brush-head characteristic `4210`. Callback class `a` calls `o1`, and `o1` has no const-strings.
4. On `4230`, method `k` logs `readNfcTagVersion` and constructs `readBrushHeadSerialNumber`. Which of `q1` (`nfc tag version`) and `r1` (`serial Number`) belongs to `4210` and which to `4230` was not tied.
5. Notify-method-to-field links for routine methods `D1`, `E1`, `F1`, `G1`, `H1`, and `I1`. Read, write, and `C1` enable links are in section 4.2.
6. SACP and session write bytes, `HandleState` values, the sensor notification payload, and the battery integer width. `Characteristic$WriteType.a` was not decoded.
7. Which product selects plugin `Lng/a` versus `Lrg/a`, and which feature set in `handle_feature.json` a model uses. `ProductsConfiguration.json` was not read.
8. The address, name, and manufacturer-data arguments of the plugin `ScanFilter`. The service-UUID set was confirmed.
9. The property mask stored from the integer `16` passed into `CharacteristicDescription`.
10. Any check against a live brush. Every UUID in section 4 is what the handlers load.

## 10. Evidence index

| Fact | Where |
| --- | --- |
| Package identity | APKM path, SHA-256, and `info.json` in the header. |
| Manifest permissions and receivers | Binary `AndroidManifest.xml` UTF-16 runs, section 2. |
| Handle plugin and scan UUID | `classes4.dex` `Lng/a` `<init>`, fields `j` and `k`, method `f`. |
| Second plugin and scan UUID | `classes4.dex` `Lrg/a` `<init>`, fields `j` and `k`, method `f`. |
| Handler list | `Lng/a.d`, `Lrg/a.d`. |
| Foreground scan | `classes5.dex` `Scanner.v`, `Scanner.w`, `PendingIntentScanReceiver$a.a`. |
| Background scan | `classes4.dex` `workermanager.b` methods `e`, `g`, `f`; `NativeScanWorker`; `NativeConnectWorker`; `ScanIntentReceiver`. |
| `connectGatt` | `classes5.dex` `Lrq/t.c`. Callback forwarder `Lrq/v`. |
| CCCD | `classes5.dex` `Lcom/philips/connectivity/bluetooth/adapter/internal/a` `<clinit>`. |
| Handle characteristics | `CBTSonicareServiceHandler` `<clinit>` and the read methods in section 4.1. |
| Routine characteristics | `CBTRoutineServiceHandler` `<clinit>`, read/write methods, `C1`. |
| Storage / SACP | `CBTStorageServiceHandler` fields `k`–`p`, methods `z1`, `r`, `O`, `i`, `t`, `k0`, `y1`, `Q`. |
| Sensor | `CBTSensorServiceHandler` fields `m`, `n`, methods `i0`, `o1`. |
| Brush head | `CBTBrushHeadServiceHandler` fields `m`–`r`, methods `k`, `Y`, `o0`, `h0`, `p`, `l0`. |
| Diagnostic and extended | `CBTDeviceDiagnosticServicesHandler`, `CBTExtendedServiceHandler` method `I`. |
| Battery `180F` / `2A19` | `Lfr/b.<clinit>`, `g1`, `b0`, `h1`. |
| Device Information | `DeviceInformationServiceHandler` `<clinit>`, `p1` / `q1` / `r1`, companions `a` / `b` / `c`. |
| `createBond` | `classes5.dex` method id 68, caller `Lwq/n.d` at pc 118. |
| Bond initiator `NONE` | `AndroidPeripheral.<init>`, `Lwq/d.d`, `internal/c.m` callers `Lwq/d.d` and `Lwq/d.m`. |
| Pairing feature flag | `assets/handle_feature.json` keys `isSupportBtPairing`, `isRPASupported`. |
| `a651` and `e50b` | `ByteStreamingServiceHandler$a.a` and `$a.b`. |
| Pairing broadcast | `AndroidCentral$pairingRequestBroadcastReceiver$1`, action `PAIRING_REQUEST`. |
