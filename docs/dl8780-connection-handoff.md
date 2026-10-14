# DL8780 connection handoff

Status of the local Mac client against this Philips Lifesense scale, written 2026-10-13 so another session can continue. The static protocol manual is [lifesense-scale-protocol.md](lifesense-scale-protocol.md). Sections 5.2 and 9 of that manual still say the password, XOR, and user-info bytes were not recovered. Those bytes were recovered later, from dexdump, and exercised live. This file is the later record. Do not treat the manual's "unresolved frame" sentences as current.

**Resolved 2026-10-13 17:58 UTC.** The Mac client now receives full measurements: Bluetooth symbol and `BIA` on the display, then `8A24` (weight 97.5 kg, impedance 491.1) and `8A22` (fat 25.2 %, water 56.2 %, muscle 37.7 %, bone 3.8) for user 1. See "Resolution" below. The earlier sections are kept as the investigation record.

## Resolution: what PHS Health sends (HCI capture)

A Pixel 9a ran PHS Health 2.2.10 (`com.philips.moonshot`), patched to work without the offline account backend, and paired and weighed with Bluetooth HCI snoop logging enabled. The ATT traffic, with the parts that differed from this client in bold:

```
pair   <dev A0 d9 00 74 c9            app> 21 <new random broadcast id>
       <dev A1 01 00 91 a4            app> 20 <xor>
       <dev 83 01 … 83 08             (app waits for the whole list, then the user picks a slot)
       app> 03 01 <name>              app> 51 df 01 01 24 b7 e0 00 00 00 00 00 ff 00 00
       app> 02 <utc>                  app> 22
sync   <dev A1 01 00 91 50            app> 20 <xor>
       app> **21 <broadcast id>**     app> 02 <utc>
       <dev **C0 17 01 01 24 26 d7**  (scale recognises the user; Bluetooth symbol on)
       app> 51 … (profile)            app> 22
       (link stays up; about 8 s later) <dev 8A24 weight, <dev 8A22 body composition
```

1. **The broadcast id is written again on every sync**, after the XOR (`OPERATING_WRITE_BROADCAST_ID_ON_SYNC`). This is what tells the scale which paired user's app is connecting. Without it the scale never sends `C0`, shows weight and `kg` only, and stores nothing. The earlier attempt at this failed only because pairing itself was still broken then.
2. **UTC is the phone's local wall-clock time** counted from 2010-01-01 as naive times (`02 75 50 91 1f` at 19:50:13 CEST). It is not the Shanghai instant. The "do not switch the UTC epoch" note further down is superseded.
3. **The scale keeps the link after the sync `0x22`** and pushes the measurement when the weigh finishes. The client holds the link (`watch --idle-seconds`) and parses both packets.
4. Each pair from another app replaces the scale's stored broadcast id, so after the phone paired, the Mac had to pair again to put `E58FCA70` back.

Client changes: `_pair` waits for the `0x83` list and ends with `0x22`. `_sync` writes XOR, broadcast id, UTC, waits up to 3 s for `0xC0`, then writes the profile and `0x22`. `utc_frame` uses local wall-clock time. Profile byte 7 (activity) and bytes 9–12 (goal weight) can be set in `.philips-scale.json` as `activity_level` and `goal_kg`. PHS Health itself sends 0 for both, and they are not required.

How the reference capture was made: Developer options, "Enable Bluetooth HCI snoop log" set to Enabled (the shell cannot read the property, so check with `adb bugreport` and look for `FS/data/misc/bluetooth/logs/btsnoop_hci.log`). PHS Health was rebuilt with apktool with three changes: `android:debuggable`, `common/app_util/g.a()Z` and `g.g()Z` returning true (to skip login), and `a/ai.a(String,Z)` returning a local `DBUserProfile` (male, 183 cm, born 1990-01-01, 80 kg) through an identity cipher class `common/f/LocalProfile`. The `DBUserProfile.b` cipher field was made public for that. The rebuilt app shows a 16 KB page-size warning. It is harmless on this phone (page size 4096).

## Earlier status

No weight packet had arrived before the capture. The scale display had not shown its Bluetooth symbol during any session in the log below.

## Update, second session (2026-10-13, from 16:55 UTC)

Pairing now completes. Two fixes, both from dexdump of `d/g`:

1. **Bind waits for the user list.** After the XOR is acknowledged, `d/g.i` logs `waiting for write user id...` and stops. `d/g.d` collects one `0x83` per slot and reports the list once `maxUserNumber` entries have arrived. `d/g.a(I,String)` binds only in that state, and `d/g.c(I)` only accepts a user number that is in the list. The Philips pairer states are `WaitingForBroadCastID`, `WaitingForUserList`, `WaitingForUserSelection`, `WaitingForPairResult`, `WaitingForInitialMeasurement`, `WaitingForMeasurementConfirmation`, `Done` (`pins/c/a/b`). The old client wrote bind, user info and UTC while `83 01`…`83 08` were still arriving. `_pair` now waits for the list (8 slots, or 3 s quiet).
2. **`0x22` straight after UTC.** In `d/g.i`, after UTC is acknowledged, only `d/a.d` (`BLOOD_PRESSURE_COMMAND_START_PROTOCOL`) parks before the disconnect step. A3 writes `0x22` at once, and the link drop is `Done!the pairing is successful.` The client now does the same on the pair path, and on the sync path after a 3 s grace period, matching `d/f.g`.

Results observed live:

- Slot 1 now comes back as `83 01 55 73 65 72 …` (`User`). Before the fix all eight names were blank.
- The display ends pairing with `[ ]` instead of the `EI` seen before.
- The scale advertises `1DL87801` in pairing mode and `0DL87801` otherwise. The SDK scanner (`ble/d.a(String,[B,I)`) only connects for data when the name starts with `0`.
- After the pair, the `0xA1` random became `01 00 91 99` / `01 00 91 9a`, following the clock written in the pair (`0x1f9199xx`). Before, it crept up slowly all day, which suggests UTC writes were ignored until a pair completed.
- Sync now writes XOR, the 15-byte profile, UTC, `0x22`. The scale re-advertises about 5 s after every `0x22` while awake.

Tried and ruled out: holding the pairing link open after UTC (no `0x22`) and weighing during it. The scale gives up after about 57 s and shows `E1`. `0x22` right after UTC is required.

Also tried, with no change on the display (weight and `kg` only) and no `8A24` / `8A22` traffic:

- Full profile, following the user's memory that "all profile values had to be set" when it used to work with the app: activity level 3 (byte 7) and goal weight 80 kg (`20 03 00 ff`, bytes 9–12, `c/f.a(F)` encoding). Frame `51 df 01 01 24 b7 e0 03 00 20 03 00 ff 00 00`, written on the pair and on every sync. The values live in `.philips-scale.json` as `activity_level` and `goal_kg`. Note that the current Philips converter (`pins/c/i`) only sets sex, age and height. An older app may have set more.
- Waking the scale and letting it connect before stepping on, also from the user's memory of the old routine.
- Checked statically: the app sets the profile's user number from `LsDeviceInfo.f()` (the bound slot) in `pins/c/b/b.a(bean/l)`, so sync byte 2 = 1 matches.

Next step suggested: an Android Bluetooth HCI snoop capture of the Philips app pairing this scale and completing one recognised weigh, to diff against this client.

Still open: **no measurement arrives, and the display shows weight and `kg` only (no user number, no percentages, no Bluetooth symbol)**, even for a barefoot weigh straight after `[ ]`. A weight-only result is neither stored nor sent, so the scale has not tied the weigh to slot 1. The SDK receives measurements passively (`ble/n.a(LsDeviceInfo,[B,UUID)`). It sends no acknowledgement, so the missing piece is on the scale's side of user recognition. The profile frame matches the scale's own `0xC0` parser (`c/f.f`) field for field: flags `0xDF` cover sex, age, height, activity, unit, goal weight (4 bytes) and a final 2-byte SFLOAT, and bit `0x20` is unused.

## Device

| Item | Value |
| --- | --- |
| Model | Philips DL8780, advertised name `0DL87801` |
| Core Bluetooth address | `D6E45925-525A-8D69-AA6B-B056E0BEA6EA` |
| Serial | `21CED90074C9` |
| Hardware / firmware | `B2` / `3.8` |
| Manufacturer | `Philips` |
| Software string | `A3` (this selects the A3 queues, not A3_1) |
| Protocol digit | `02` (FAT_SCALE) |
| Service | `000078d2-0000-1000-8000-00805f9b34fb` |
| Characteristics on that service | `8A24` A3 weight indicate, `8A22` append indicate, `8A20` read (`00 00`, role unresolved), `8A81` command write, `8A82` command indicate |
| Not present | `8A21`. No Weight Scale `0x181D`, no Body Composition `0x181B` |
| Local store | `.philips-scale.json`, key `21CED90074C9` |

Stored after the profile pair:

```json
{
  "password": "D90074C9",
  "broadcast_id": "E58FCA70",
  "user_number": 1,
  "user_name": "User",
  "age": 36,
  "height_cm": 183,
  "sex": "male"
}
```

**Observation.** Every pairing connection sent `a0 d9 00 74 c9` on `8A82`. The four password bytes are `D90074C9`, which is the last eight characters of the serial text. The same four bytes came back on three pairing connections, so they are stable for this unit. The client stores what the scale sent. There is no default password constant in the APK, and the DEX was not shown to derive the password from the serial.

## What the scale is supposed to show

From the DL8780 user manual (measurement-with-the-app pages):

- Hold the measurement-unit button for 3 seconds to start pairing. Display symbols alternate while the connection is being established. A success symbol shows if it is established.
- With the app connected, the Bluetooth symbol lights. It flashes when a measurement is transmitted.
- Then step on barefoot. A weigh with shoes is weight-only and is not stored or sent. Barefoot body-composition is stored (up to 40 results per user) and can upload later.
- The initial barefoot weigh while the pairing connection is up assigns that weight to the user profile.
- The scale holds 8 profiles.

The Bluetooth symbol is drawn by the scale. GATT being up on the Mac is not that symbol. The user watched the display through the sessions below and reported no Bluetooth icon.

## Client

- Tree is not a git repo. Package `philips_ble/`. Venv `.venv`, bleak 3.0.2, Homebrew Python 3.14.4.
- Run unbuffered: `.venv/bin/python -u -m philips_ble …`
- `scale` does one connection and writes disconnect `0x22` after the listen window. `0x22` drops this scale's link.
- `watch` scans, connects on the first advertisement, holds the link, and does not write `0x22`. `--idle-seconds` defaults to 180. The idle timer starts after the handshake.
- Connect timeout is 40 seconds. Writes use `write_gatt_char(..., response=True)`, which matches the SDK `setWriteType(2)` (`WRITE_TYPE_DEFAULT`) at dexdump address `3ea9b4`.
- Do not call `BleakClient.pair`. On Core Bluetooth it raises `NotImplementedError`. The Lifesense scale path does not call `BluetoothDevice.createBond`. The only `createBond` sites are ShineLib `BTDevice.d` and `BTGatt` inner `c$14`, and they are not on the scale caller chain.
- `python -m unittest discover -s tests` — 32 tests, OK, after the sync path was reduced to XOR plus UTC.

Profile used for this person: age 36, height 183 cm, sex male. Athlete, activity level, and goal weight were not supplied. The Philips converter leaves those at constructor defaults too (see below).

## Frames that are recovered

Authority is dexdump of the Moonshot APK, not guessed layouts. APK:

`/Volumes/Development/Dev/Philips Healthsuite/com-philips-moonshot-145-61604772-2022658bb8582546b36e2d7f3999ed9f.apk`

SHA-256 `637d313f5124d43bea4d5e85d2710fcc62a2e3354c62d6401b729df8c8e20ed8`. Extracts still on this machine: `/tmp/classes.dex`, `/tmp/classes2.dex`. Useful dumps: `/tmp/bean-l.txt` (`bean/l.a()[B` at `3efafc`), `/tmp/pins-ci.txt`, `/tmp/df-full.txt` (`d/f.g` at `3f5a9c`, `d/f.a(String)[B` at `3f5514`), `/tmp/cd2.txt`, `/tmp/bean-j.txt`.

Command writes go to `8A81`. Command indications arrive on `8A82`.

| Frame | Builder | Bytes |
| --- | --- | --- |
| Broadcast id | `c/d.a(String)[B` | `21` + 4 id bytes. Live id `E58FCA70` → `21 e5 8f ca 70` |
| XOR | `c/d.b(String,[B)[B` plus a `0x20` wrapper | `20` + (password XOR random), 4 bytes. Example: password `d9 00 74 c9` XOR random `01 00 00 c4` = `20 d8 00 74 0d` |
| Bind user | `c/d.a(int, String)[B` | 18 bytes. `03`, user number, UTF-8 name, `0x20` padding through index 17. Live: `03 01 55 73 65 72` + 12 spaces (`User`) |
| User info | `bean/l.a()[B` | 15 bytes. See the next section |
| UTC | `c/d.b()[B` | `02` + uint32 LE seconds since 2010-01-01 00:00:00 Asia/Shanghai. A live write `02 1c 93 91 1f` at 16:34:36 UTC matched that epoch with delta 0 |
| Disconnect | `c/d.c()[B` | `22`. Drops the link. The watch path does not send it |

Random indications on this scale are `a1 01 00 00 XX`. The first three payload bytes stay `01 00 00`. The last byte increments slowly (`a0`, `ab`, `af`, `b0`, `b2`, `be`, `c0`, `c1`, `c4` across the day). A public Lifesense log also starts `a1 01 …`, so the leading `01` is normal.

### User-info frame

`bean/l.a()[B` allocates 15 bytes, writes indices 0–12, and returns. Indices 13–14 stay zero. Device id, member id, and waistline are fields on the object and appear in `toString`. This method does not copy them into the array.

`SHNLSUserConfigurationConverter` (`Lcom/philips/pins/c/i`, source `SHNLSUserConfigurationConverter.java`) builds the bean only when sex, age, and height are present. Age must be 18–100. Height must be 100–204 cm. It sets only those three: age, height as centimetres / 100, and sex. Athlete stays false, activity stays 0, unit stays null, goal weight stays 0.0.

Null unit takes the else arm of `bean/l.b(j)` and encodes as 0. Enum `bean/j` is `UNIT_KG`, `UNIT_LB`, `UNIT_ST`; the encoder returns 1 for LB and 2 for ST, so 0 is kilograms. Goal weight 0.0 goes through `c/f.a(F)` and becomes `00 00 00 ff`. The flags byte is the writer's constant `0xDF` (`const/16 -33`), not a value read from the flags field.

Frame this client builds for the stored profile, and the frame already written on the wire during pairing and during several syncs:

```
51 df 01 01 24 b7 e0 00 00 00 00 00 ff 00 00
```

| Index | Bytes | Field |
| --- | --- | --- |
| 0 | `51` | Opcode |
| 1 | `df` | Flags constant |
| 2 | `01` | User slot. `d/g` overwrites this with the user number |
| 3 | `01` | Male, not an athlete. Athlete male would be `03`, female `02`, athlete female `04` |
| 4 | `24` | Age 36 |
| 5–6 | `b7 e0` | 183 cm |
| 7 | `00` | `athleteActivityLevel`, constructor default |
| 8 | `00` | Kilograms |
| 9–12 | `00 00 00 ff` | Goal weight 0.0 |
| 13–14 | `00 00` | Never written |

That is the full 15-byte profile the SDK serializes. The current `watch` / sync path does not send it. See "What the code does now".

## Queues for software `A3`

`d/f` selects the queue from the software string. `"A3"` plus `DEVICE_PAIR` is `d/f.i`. `"A3"` plus `DATA_RECEIVE` is `d/f.g`. `START_MEASURING_BY_COMMAND` is the blood-pressure queue `d/f.c`. It is not selected for `"A3"`. Do not send a guessed start-measure payload. `d/n.D` was not recovered as a concrete byte array, and it is not on either A3 queue.

A3 pairing `d/f.i`: connect, read device info, set notify, receive password (`0xA0`), write broadcast id, receive random, write XOR, bind user, user info, UTC, disconnect `0x22`, paired-results.

A3 upload `d/f.g`: connect, set notify, receive random, XOR, then user info only when `d/f.a(LsDeviceInfo.e())` returns the static `bean/l`, then UTC, disconnect `0x22`, uploaded-results. No broadcast id. `LsDeviceInfo.e()` is the protocol digit. For digit `"02"`, `d/f.a` returns `bean/l.a()[B` when static `d/f.b` is non-null. The Philips app therefore does send this 15-byte profile on an A3 upload when that bean has been set. A3_1 upload `d/f.b` writes the broadcast id after the XOR. This scale's software string is `A3`, so the app takes `d/f.g` and skips that write.

`SET_INDICATE`, `WRITE_AUTH_RESPONSE`, `WRITE_INIT_RESPONSE`, and the `C3`–`CE` directives are real and are not on the A3 pair or A3 upload queues. `0xC0` is the user-info indication the dispatcher parses with `c/f.f`. It has not been seen live.

`SHNLSPairer` (`Lcom/philips/pins/c/c/j`) logs "Start pairing" and delegates to `Lcom/lifesense/ble/c`. It does not build profile bytes.

## What the code does now

`philips_ble/scale_link.py`:

- `_pair` (scale sent `0xA0`): broadcast id, wait for `0xA1`, XOR, bind, user info, UTC. No `0x22` when the link is held.
- `_sync` (scale sent `0xA1`): XOR, then UTC. It does not write the broadcast id or the user-info frame.

The profile is still stored when `--age`, `--height-cm`, and `--sex` are passed. It is only written by the pair path.

Sessions that wrote the broadcast id on sync (`21 e5 8f ca 70` after the XOR) got no extra indication and no Bluetooth symbol. That write was removed. Sessions that wrote the 15-byte profile on sync also got no symbol and no weight. The profile write was then removed from sync as well. The A3 upload queue still inserts user info when the static bean is set, so the current sync path is shorter than `d/f.g` whenever that bean exists.

## Live sessions

All times UTC, 2026-10-13. Captures are under `/tmp` and are not in the repo. Every session subscribed to `8A24`, `8A22`, and `8A82`. `8A24` and `8A22` stayed silent. The only indications were on `8A82`.

| Capture | What happened |
| --- | --- |
| `philips-scale.jsonl` | Connect and Device Information reads. Standing on the scale produced no weight. One `0xA1`. |
| `philips-scale-pair.jsonl` | Unit button held. `0xA0`, handshake writes completed, disconnect write then failed because the scale dropped the link. |
| `philips-scale-sync.jsonl` | Repeat pair, empty 15-byte fallback user info. |
| `philips-scale-profile.jsonl` | Sync with the real profile frame. No weight. |
| `philips-scale-pair-profile.jsonl` | Full pair with bind `User` and the real profile. Scale replied `83 01` … `83 08`, each with sixteen `0x20` and `00 00`: users 1–8, empty names. Link held about 15:06:30–15:07:40, then `0x22`. No weight. The written name was not in those `0x83` packets. `c/f.h` reads the name from index 2 and trims spaces. |
| `philips-scale-weigh.jsonl` | Sync while standing. Random `a1 01 00 00 b0`. XOR, user info, UTC. 90 s. No weight. |
| `philips-scale-upload.jsonl` | After stepping off. Random `b2`. 60 s. No weight. |
| `philips-scale-live.jsonl` | Connect, then step on. Random `b2`. 150 s (15:19:39–15:22:09). XOR, profile, UTC. No weight. |
| `philips-scale-watch.jsonl` | Background `watch`. Several links. Broadcast-id-on-sync at 16:18:12, 16:19:11, 16:20:12, 16:22:14, and 16:22:33: each got exactly the one `0xA1`, then the scale closed the link (about 49 s, 29 s, 14 s, 14 s, 35 s). XOR-and-UTC only at 16:34:36, random `a1 01 00 00 c4`, writes `20 d8 00 74 0d` and `02 1c 93 91 1f`. Scale dropped the link at 16:35:18. Still one notification. |

Pairing-mode links stayed up until the client wrote `0x22`. Sync-mode links were closed by the scale. That difference is observed. It is not explained.

The `0x83` list arrived in the same second as XOR, bind, and user info. It does not prove the profile was stored. The names stayed blank.

Between 16:23:39 and 16:33:39 the scale stopped advertising. It advertised again at 16:34:35 (−75 dBm) after the watcher was restarted.

The notification counter in one `watch` process is cumulative across reconnects. Each link contributed one `0xA1`.

## Constraints for the next session

- Stay on the scale until a weight arrives or the user says to move on. The toothbrush has not been tested live.
- One listener process. A second `watch` will fight the first for the advertisement.
- If a `watch` from this session is still running, stop it before connecting. It was started as `.venv/bin/python -u -m philips_ble watch --address D6E45925-525A-8D69-AA6B-B056E0BEA6EA --idle-seconds 180 --age 36 --height-cm 183 --sex male --out /tmp/philips-scale-watch.jsonl` and it runs the XOR-and-UTC sync.
- Do not install JADX. Do not retry `inspect_android_package` on the Sonicare APKM. Android evidence here is dexdump at `~/Library/Android/sdk/build-tools/36.1.0/dexdump`. `JAVA_HOME` was `/Users/sjaakiejj/.jenv/versions/17`.
- Do not invent characteristic payloads, C3–CE bodies, or a start-measure command.
- (Superseded by the HCI capture: UTC is the local wall clock since 2010-01-01. See "Resolution".)
- Do not switch writes to write-without-response.
- Measurement parsers in `philips_ble/scale_packets.py` follow manual section 6. They have not been confirmed against a live weight packet.

## Open

1. The scale has not accepted this central as the connected app. No Bluetooth symbol, no `8A24` / `8A22` traffic.
2. The unfinished manual step is a barefoot weigh while a pairing-mode link is still up. Pairing sessions so far ended without that weigh. Later weighs were `0xA1` syncs, after pairing mode had ended. Whether that initial weigh is what makes the scale light the symbol is untested.
3. Whether the scale commits the `0xA0` password only after that weigh or a clean `0x22`, so later XOR checks fail against an older password. The identical `0xA0` across three pairs makes a one-time password unlikely. Commit versus announce was not proven.
4. Whether putting the same 15-byte profile back on the sync path would change anything. `d/f.g` inserts it when the bean is set. The same bytes were already written on earlier syncs, with no symbol and no weight.
5. Whether activity, athlete, or a non-zero goal weight would be required by the scale firmware. The Philips converter does not set them. Supplying them would be a new experiment, and the bytes would still have to match `bean/l.a()[B`.
6. `8A20` = `00 00`. Role unresolved.
7. Whether this Mac's pair replaced the phone app's stored password and broadcast id. Effect on the phone app was not observed.
8. C3–CE payloads, `d/n.D` start-measure bytes, and `0xC0` user-info indications. Not seen, not on the A3 queues that this software string selects.

## Command that matches the last listener

```
.venv/bin/python -u -m philips_ble watch \
  --address D6E45925-525A-8D69-AA6B-B056E0BEA6EA \
  --idle-seconds 180 \
  --age 36 --height-cm 183 --sex male \
  --out /tmp/philips-scale-watch.jsonl
```

Hold the unit button for 3 seconds until the pairing symbols alternate, then let this connect. The pair path is the one that still writes broadcast id, bind, and the 15-byte profile. Step on barefoot while that link is up and watch the scale's Bluetooth symbol.
