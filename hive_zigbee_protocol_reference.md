# Hive SLT3b / SLR1c Zigbee protocol reference

**Revision:** 0.2 — working investigation record  
**Last updated:** 4 November 2026  
**Scope:** Hive SLT3b wall thermostat and SLR1c single-channel heating receiver, operating locally through Home Assistant ZHA.  
**Purpose:** Preserve the information needed to implement the demonstrated controls, including exact payloads, units, acknowledgement behaviour, and unresolved questions.

This is an empirical reference, not a complete Hive specification. Findings concern one device pair and firmware combination. Manufacturer-specific behaviour should be verified on other models before generalising it.

Installation identifiers have been removed for publication. Replace `RECEIVER_IEEE_ADDRESS`, `THERMOSTAT_IEEE_ADDRESS` and `COORDINATOR_IEEE_ADDRESS` with the corresponding device addresses from ZHA when using examples. Holiday dates have been replaced with illustrative dates; their formats and minute encodings reflect the observed protocol. See [setup instructions](README.md#before-installing) for prerequisites and finding addresses.

## Contents

1. [Evidence and implementation status](#1-evidence-and-implementation-status)
2. [Devices, addressing and topology](#2-devices-addressing-and-topology)
3. [Pairing and network recovery](#3-pairing-and-network-recovery)
4. [Zigbee conventions and transport](#4-zigbee-conventions-and-transport)
5. [Thermostat cluster attribute map](#5-thermostat-cluster-attribute-map)
6. [Weekly schedules](#6-weekly-schedules)
7. [Heat boost and returning to schedule](#7-heat-boost-and-returning-to-schedule)
8. [Manual heating and Off](#8-manual-heating-and-off)
9. [Holiday mode](#9-holiday-mode)
10. [Additional discovered settings](#10-additional-discovered-settings)
11. [Monitoring, time and diagnostics](#11-monitoring-time-and-diagnostics)
12. [Toolkit commands and helper code](#12-toolkit-commands-and-helper-code)
13. [Implementation guidance](#13-implementation-guidance)
14. [Unfinished tests](#14-unfinished-tests)
15. [Sources and investigation artifacts](#15-sources-and-investigation-artifacts)

## 1. Evidence and implementation status

The following distinctions are essential:

- **Device verified:** observed on the physical thermostat or confirmed by a relevant readback, with the exact scope stated.
- **Discovered:** the device advertises the attribute/command and its access/type, but the intended effect has not been tested.
- **Candidate:** a plausible interpretation or externally documented recipe that has not been verified on this pair.
- **Unknown:** no established meaning or implementation.

An accepted Zigbee write proves acceptance of attribute data; it does not necessarily prove that the wall thermostat has changed mode, resumed scheduling, or displayed the new value.

| Function | Evidence and current status |
|---|---|
| Pair receiver and thermostat through ZHA | Verified after a clean receiver-first pairing sequence |
| Read heating target, mode, hold and duration | Verified on receiver endpoint 5 |
| Set a target from HA | Verified using the receiver's climate entity; the wall thermostat's climate entity did not work for this purpose |
| Read one day's onboard schedule | Verified for Monday and Wednesday |
| Edit one day's onboard schedule | Verified: Monday's 17:00 target changed from 18°C to 17.5°C |
| Start native boost | Verified: one combined write starts 10 minutes at 19°C, shown on the wall thermostat |
| Cancel boost and resume current schedule | Verified with one combined write: mode 4, hold 0, duration 0 |
| Change boost duration alone | Receiver accepted and read back the value; wall display synchronisation was not established |
| Read holiday configuration | Verified against dates/times/temperature entered on the wall thermostat |
| Change holiday temperature | Verified: writing 700 changed it to 7°C |
| Cancel a scheduled holiday | Verified by user: write 0 to manufacturer attribute 0x0020 |
| Write holiday dates/times | Encodings established by reads; writes not yet tested |
| Enable/configure a holiday entirely remotely | Not yet tested |
| Enter Off and return to schedule | Verified: combined mode 0 / hold 0 displayed Off; user_hive_auto returned to schedule. Frost threshold and cold-trigger behaviour remain untested |
| Child lock, frost threshold, temperature limits | Device features or discovered attributes; effects over Zigbee not yet tested |

## 2. Devices, addressing and topology

### 2.1 Device characteristics and address placeholders

| Item | Observed value |
|---|---|
| Receiver | Hive SLR1c, manufacturer Computime |
| Receiver IEEE | `RECEIVER_IEEE_ADDRESS` |
| Wall thermostat | Hive SLT3b, manufacturer Computime |
| Thermostat IEEE | `THERMOSTAT_IEEE_ADDRESS` |
| Coordinator IEEE | `COORDINATOR_IEEE_ADDRESS` |
| Coordinator hardware shown in ZHA | Texas Instruments CC2652 |
| Receiver logical type | Router, numeric value 1 |
| Thermostat logical type | End device, numeric value 2; battery powered |
| Zigbee application profile | Home Automation, `0x0104` / decimal 260 |
| Manufacturer code | **4153 decimal = `0x1039`** |
| ZHA Toolkit | v1.2.6 |
| zigpy | 2.3.0 |
| RF library version reported by Toolkit | 1.1.1 |

**Manufacturer-code trap:** the scan rendered a summary field as `manufacturer_id: '0x4153'`, but its actual numeric `manf_id` and node descriptor value were **4153 decimal**. Use `manf: 4153` or `manf: 0x1039`, not hexadecimal `0x4153`.

IEEE addresses are stable identifiers. Short network addresses changed during reset/rejoin experiments: their values are specific to each network session. Never persist these NWK values as device identity.

### 2.2 Endpoint signatures

**Thermostat endpoint 9:** profile `0x0104`, device type `0x0302`.

| Direction in signature | Clusters |
|---|---|
| Input/server | `0000`, `0001`, `0003`, `0009`, `000a`, `0020`, `0201`, `0204`, `0402`, `fd00` |
| Output/client | `0000`, `0003`, `000a`, `0019`, `0201`, `fd00` |

**Receiver:**

| Endpoint | Profile | Device type | Input/server clusters | Output/client clusters |
|---:|---|---|---|---|
| 5 | `0x0104` | `0x0301` | `0000`, `0003`, `0009`, `000a`, `0201`, `fd00` | `0003`, `0019`, `0402` |
| 6 | `0x0104` | `0x0301` | `0201` | None |
| 242 | `0xa1e0` | `0x0061` | None | `0021` |

All demonstrated heating controls target **receiver endpoint 5**. The presence of endpoint 6 on an SLR1c is not evidence of a usable second relay or hot-water output; it has not been investigated.

### 2.3 Control architecture

The receiver provides the working heating-control endpoint. The thermostat provides the physical controls and temperature measurement and has its own local relationship with the receiver. Both can be visible in ZHA while their Hive pairing is incomplete.

Control the **SLR1c climate entity** in HA. Changing the target on the SLT3b climate entity initially produced no useful result. Selecting the receiver entity fixed this immediately.

An SLR1c is a heating-demand relay receiver. These experiments provide no boiler flow-temperature, pressure, modulation or OpenTherm control. They also provide no separate domestic-hot-water output on this model.

## 3. Pairing and network recovery

### 3.1 Sequence that succeeded

The ultimately successful setup followed removal/reset of both devices and receiver-first commissioning:

1. Remove the thermostat from ZHA while powered/awake where possible.
2. Factory-reset the thermostat using Back + Menu through the complete countdown; remove a battery after reset.
3. Remove the receiver from ZHA while powered where possible.
4. Power-cycle the receiver through the normal boiler isolation supply.
5. Hold the receiver heating button to enter pink/white flashing mode, release, then hold again until **double-flashing amber**, and release.
6. Start a normal ZHA Add device search and allow the receiver to join and finish setup.
7. Confirm **single-flashing amber** on the receiver.
8. Exit that search, open the receiver's device page and use **Add devices via this device**.
9. Replace the thermostat battery, complete language prompts and allow pairing to complete nearby.
10. Verify physical target changes operate the receiver and HA changes through the receiver entity reach the thermostat.

The clean receiver-first sequence succeeded without subsequently recreating the exploratory manual bindings.

### 3.2 Observed failure modes

- The thermostat could appear in HA yet remain on Searching, Pairing, Re-connecting or No signal.
- A solid green receiver light was observed with the thermostat battery removed. It is not sufficient evidence of a currently working thermostat link.
- A power cycle did not clear the receiver's existing pairing state.
- Resetting the thermostat cleared an experimentally added receiver binding.
- Reconfigure alone did not fix the incomplete pairing.
- A successful attribute read, join or firmware query through HA does not prove the thermostat/receiver application pairing is complete.

### 3.3 Binding observations

An exploratory direct binding was successfully stored:

```text
source:      thermostat THERMOSTAT_IEEE_ADDRESS, endpoint 9
cluster:     0x0201
destination: receiver   RECEIVER_IEEE_ADDRESS, endpoint 5
```

A reciprocal receiver endpoint 5 → thermostat endpoint 9 binding was also accepted. These did **not** by themselves fix pairing. Their necessity for a normally commissioned pair has not been established.

ZHA's binding dropdown only offered the coordinator during the failed setup. Toolkit could create the receiver binding even though the UI omitted it.

```yaml
action: zha_toolkit.bind_ieee
data:
  ieee: "THERMOSTAT_IEEE_ADDRESS"
  command_data: "RECEIVER_IEEE_ADDRESS"
  cluster: 0x0201
  endpoint: 9
  dst_endpoint: 5
```

Use `zha_toolkit.binds_get` with the source IEEE to verify actual stored bindings. An outgoing binding produced `result: {}` / `success: false` even though it had been stored. Inspection of Toolkit source found that its outgoing-binding path failed to populate the result used to calculate success. Do not treat that particular result as proof that no binding was created.

## 4. Zigbee conventions and transport

### 4.1 Numeric representations

All `0x` values below are hexadecimal. YAML integers without `0x` are decimal. Quote dates and IEEE addresses. Use explicit `HH:MM` strings for human-facing schedule times.

| ZCL type | Name | Use in this pair |
|---|---|---|
| `0x18` | bitmap8 | Manufacturer flags; some alarm/time flags |
| `0x19` | bitmap16 | Thermostat running state |
| `0x20` | uint8 | Counts and manufacturer settings |
| `0x21` | uint16 | Durations, transition time, other manufacturer fields |
| `0x23` | uint32 | Time-cluster values |
| `0x29` | int16 | Temperatures in hundredths of °C |
| `0x2b` | int32 | Timezone / DST shift |
| `0x30` | enum8 | System mode and temperature hold |
| `0x42` | Character string | Holiday date strings |
| `0xe2` | UTC time | Time-cluster UTC time |

The hold attribute was advertised as **enum8**, so the tested Toolkit write used `attr_type: 0x30`, not boolean `0x10`.

### 4.2 Standard versus manufacturer-specific operations

- Cluster **`0x0201`**: standard Thermostat cluster; demonstrated schedule and boost operations used **no manufacturer header**.
- Cluster **`0xFD00`**: manufacturer-specific settings; demonstrated reads/writes used **manufacturer code 4153**.
- Some manufacturer-specific attributes also exist on `0x0201`; see section 10.

### 4.3 Command namespaces must not be confused

ZCL global/general commands and cluster-specific commands have separate namespaces:

| Frame type | Command | Meaning |
|---|---|---|
| Global | `0x00` | Read Attributes |
| Global | `0x01` | Read Attributes Response |
| Global | `0x02` | Write Attributes |
| Cluster-specific, Thermostat | `0x01` | Set Weekly Schedule |
| Cluster-specific, Thermostat | `0x02` | Get Weekly Schedule |

Use Toolkit `attr_read`/`attr_write` for the single-attribute global operations, and `zcl_cmd` for the demonstrated weekly-schedule commands. Setting `cmd: 0x02` in `zcl_cmd` is **Get Weekly Schedule**, not a general multi-attribute write.

For combined boost/mode writes, use one `cluster.write_attributes({...})` call. This emits one global Write Attributes request containing the attribute records. A HA script containing several single-attribute writes is not the same thing.

Numeric ZCL multi-byte fields are little-endian on the wire. Wire-layout descriptions in this document are derived from the ZCL schemas; the investigation captured decoded Toolkit/zigpy messages, not independent raw-radio packet captures for every operation.

### 4.4 Toolkit read and write templates

```yaml
action: zha_toolkit.attr_read
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0x0201
  attribute: 0x0012
  tries: 1
```

Typical result:

```yaml
result_read:
  - '18': 1900
  - []
success: true
```

Keys such as `'18'` are decimal attribute IDs; 18 decimal is `0x0012`.

```yaml
action: zha_toolkit.attr_write
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0x0201
  attribute: 0x0024
  attr_type: 0x21
  attr_val: 10
  read_before_write: true
  read_after_write: true
  tries: 1
```

`read_before_write` and `read_after_write` improve visibility but are separate reads around the write. They do not make a write atomic with unrelated callers.

## 5. Thermostat cluster attribute map

Receiver endpoint 5, cluster **`0x0201`**. R/W/P means Read/Write/Report advertised by discovery; P does not establish the reporting interval or that a report was observed.

| Attribute | Decimal | Type | Access | Meaning / observations |
|---|---:|---|---|---|
| `0x0000` | 0 | int16 `0x29` | R/P | Local temperature ×100; scan example 2438 = 24.38°C |
| `0x0011` | 17 | int16 | R/W/P | Occupied cooling setpoint; scan 2100; not evidence of actual cooling capability |
| `0x0012` | 18 | int16 | R/W/P | Occupied heating setpoint ×100; 1900 = 19°C; 100 is the observed scheduled Off encoding |
| `0x0015` | 21 | int16 | R/W/P | Minimum heating target limit; scan 500 = 5°C |
| `0x0016` | 22 | int16 | R/W/P | Maximum heating target limit; scan 3200 = 32°C |
| `0x001b` | 27 | enum8 | R/W/P | Control sequence; scan 2 |
| `0x001c` | 28 | enum8 | R/W/P | System mode; must be interpreted with hold and duration |
| `0x001d` | 29 | bitmap8 | R/P | Alarm mask; scan 0 |
| `0x0020` | 32 | enum8 | R/P | Start of week; scan 1 |
| `0x0021` | 33 | uint8 | R/P | Number of weekly transitions; scan 42 |
| `0x0022` | 34 | uint8 | R/P | Number of daily transitions; scan 6 |
| `0x0023` | 35 | enum8 `0x30` | R/W/P | Temperature setpoint hold; 1 during boost, 0 in verified schedule recipe |
| `0x0024` | 36 | uint16 `0x21` | R/W/P | Temperature hold duration, minutes; 0 after cancellation; 65535 is documented as unused/indefinite in some other states |
| `0x0029` | 41 | bitmap16 | R/P | Running state; heating/idle should be distinguished from requested mode |
| `0xfffd` | 65533 | uint16 | R/P | Cluster revision; value not returned in final scan section |

### 5.1 Mode interpretation: critical Hive-specific finding

| Mode and related state | Interpretation / evidence |
|---|---|
| Mode 5, hold 1, finite duration, target | Native boost; physically verified |
| Mode 4, hold 0, duration 0, written together | Resume Hive's onboard schedule; physically observed change and scheduled target readback verified |
| Mode 4 alone | Exited boost in one test but left manual heating at the existing target; not sufficient to establish schedule mode |
| Mode 4, hold 1, target | Externally supported manual-heat recipe; full raw combined recipe not separately verified in this investigation |
| Mode 1 | Standard Zigbee Auto value; accepted/read back, but did not reliably restore Hive's schedule in these tests |
| Mode 0, hold 0, written together | Enter Off; physical Off indication verified. Actual frost threshold/activation not tested |

**Do not implement Hive schedule mode by blindly writing system mode 1.** The demonstrated recipe uses mode **4 + hold 0 + duration 0** in one write. HA's UI concept of Auto is not a direct one-to-one mapping to the raw mode enum on this setup.

## 6. Weekly schedules

### 6.1 Storage and units

The receiver exposes the schedule through endpoint 5, cluster `0x0201`.

- Times: minutes after midnight, e.g. 390 = 06:30.
- Heating targets: hundredths of °C, e.g. 1750 = 17.5°C.
- Mode bitmap: bit 0 / value 1 = heating; cooling has not been tested.
- Six transitions per day were returned; scan advertised six daily and 42 weekly.
- A target of **100 = 1°C is Hive's observed schedule Off/cold encoding**. The physical schedule displayed those periods as Off.
- This Off encoding is not a demonstrated configuration of the actual frost-protection threshold. Do not substitute 5°C or 7°C when reading/writing a stored Off period.
- Half-degree schedule targets work: 17.5°C was written and verified.
- All successful date/time tests occurred in November/December UK time, when London is UTC. DST behaviour remains untested.

### 6.2 Day masks

| Day | Decimal | Hex |
|---|---:|---|
| Sunday | 1 | `0x01` |
| Monday | 2 | `0x02` |
| Tuesday | 4 | `0x04` |
| Wednesday | 8 | `0x08` |
| Thursday | 16 | `0x10` |
| Friday | 32 | `0x20` |
| Saturday | 64 | `0x40` |
| Away, defined by generic Zigbee schema | 128 | `0x80` — **not tested; do not assume this is Hive holiday mode** |

Combined-day masks exist in the generic schema, but only individual-day requests/writes have been verified here. Do not assume all-day writes or multi-response handling work without testing.

### 6.3 Read a day

Cluster-specific command **`0x02`**, Get Weekly Schedule:

```yaml
action: zha_toolkit.zcl_cmd
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0x0201
  cmd: 0x02
  dir: 0
  kwargs:
    days_to_return: 2
    mode_to_return: 1
  tries: 1
```

`dir: 0` in this tested Toolkit call selects the client-to-server command path. Monday's request payload fields are `uint8 days=2`, `uint8 mode=1`; excluding the ZCL header, bytes are `02 01`.

Captured Monday response before editing:

```yaml
cmd_reply:
  - 6
  - 2
  - 1
  - [390, 1800, 510, 100, 720, 100, 840, 100, 1020, 1800, 1200, 100]
success: true
```

Interpretation:

```text
[number_of_transitions, day_mask, mode_mask, alternating_time_and_target_values]
```

The generic Thermostat response is cluster-specific **`0x00`**, Get Weekly Schedule Response, server to client. Payload: count (uint8), day mask (uint8), mode (uint8), followed by transitions. For the tested heating-only mode, each transition is a uint16 time followed by an int16 heating setpoint. The zigpy schema exposes the tail as a flat list of signed 16-bit values; the observed 0–1439 time values remain nonnegative in that representation.

Validate the day mask, heating mode and exact `2 × count` list length before accepting a response. Do not accept a default acknowledgement as schedule data.

### 6.4 Captured schedule and edit

| Time | Minute | Original target | Encoding | Monday after edit |
|---|---:|---|---:|---|
| 06:30 | 390 | 18°C | 1800 | Unchanged |
| 08:30 | 510 | Off | 100 | Unchanged |
| 12:00 | 720 | Off | 100 | Unchanged |
| 14:00 | 840 | Off | 100 | Unchanged |
| 17:00 | 1020 | 18°C | 1800 | **17.5°C / 1750** |
| 20:00 | 1200 | Off | 100 | Unchanged |

The user initially reported all other days matching the original pattern. Wednesday was independently read on 4 November and matched it; the other five days were not individually captured in the investigation.

### 6.5 Write one day

Cluster-specific command **`0x01`**, Set Weekly Schedule:

```yaml
action: zha_toolkit.zcl_cmd
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0x0201
  cmd: 0x01
  dir: 0
  kwargs:
    num_transitions_for_sequence: 6
    day_of_week_for_sequence: 2
    mode_for_sequence: 1
    values:
      - 390
      - 1800
      - 510
      - 100
      - 720
      - 100
      - 840
      - 100
      - 1020
      - 1750
      - 1200
      - 100
  tries: 1
```

This replaces the selected day's transition list. Supply the full intended day, including unchanged transitions. Do not send just the evening transition when intending to preserve the morning entries.

The payload fields are count, day mask, mode mask, then transitions. For example, 17:00 / 17.5°C encodes time 1020 as `fc 03` and setpoint 1750 as `d6 06`, excluding all surrounding fields and headers.

### 6.6 Missing acknowledgement is not failed persistence

The Monday write returned:

```yaml
errors: [TimeoutError()]
success: false
```

The subsequent Monday read returned the requested 1750 evening target, and the user confirmed success. Therefore:

1. Save the original day.
2. Send the intended replacement once.
3. Read that day back, including after an acknowledgement timeout.
4. Compare the complete transition list.
5. Report verified persistence only if it matches.

Do not automatically resend a schedule write just because the acknowledgement is missing. If another actor changed the day since the editor loaded, refuse the stale edit and refresh before writing.

### 6.7 Other schedule commands

Discovery advertised Setpoint Raise/Lower `0x00`, Clear Weekly Schedule `0x03`, and Get Relay Status Log `0x04`. These were **not exercised**. Do not use Clear Weekly Schedule as a step in ordinary editing; the successful edit required only Set Weekly Schedule.

## 7. Heat boost and returning to schedule

### 7.1 Read observations from a physical boost

A boost started on the physical thermostat produced:

| Attribute | Before / after observation |
|---|---|
| System mode `0x001c` | 4 before, 5 during boost |
| Hold `0x0023` | 1 during boost |
| Duration `0x0024` | 29 minutes at the captured read |
| Heating target `0x0012` | 1900 = 19°C |

The observed countdown is a remaining-duration value, not a fixed original-duration setting.

### 7.2 Start native boost: verified combined write

Use the receiver's Thermostat cluster. Send **one Write Attributes request** with:

```python
{
    0x001C: 5,     # enum8: Hive native boost
    0x0024: 10,    # uint16: requested duration, minutes
    0x0023: 1,     # enum8: temperature hold enabled
    0x0012: 1900,  # int16: target 19°C
}
```

Equivalent zigpy operation on the already resolved receiver:

```python
cluster = device.endpoints[5].in_clusters[0x0201]
reply = await cluster.write_attributes({
    0x001C: 5,
    0x0024: 10,
    0x0023: 1,
    0x0012: 1900,
})
```

The numeric keys use the built-in Thermostat attribute definitions to select correct data types. No manufacturer code is supplied.

Actual response contained four `WriteAttributesStatusRecord(status=SUCCESS)` records. More importantly, the user saw **10 minutes at 19°C in Boost on the physical thermostat**. A subsequent start/cancel test was also reported successful.

The helper restricts duration to 1–360 minutes and target to 5–32°C in 0.5°C steps. These are implementation/documentation bounds, not a measurement of every accepted value. Only the 10-minute/19°C remote-start combination was explicitly confirmed in this investigation.

### 7.3 Cancel boost and resume the onboard schedule: verified combined write

Send these three fields together:

```python
reply = await cluster.write_attributes({
    0x001C: 4,  # Heat, with Hive scheduling enabled by hold/duration combination
    0x0023: 0,  # Disable temperature hold
    0x0024: 0,  # Clear hold duration
})
```

**Do not include a heating target in this recipe.** Allow Hive to select the scheduled target.

Evidence:

- All three attributes acknowledged success.
- The physical thermostat's behaviour changed to the expected schedule-style prompt.
- At Wednesday noon, the stored schedule was Off.
- A subsequent heating-target read returned **100**, matching that Off period instead of the previously forced 500 or boost target 1900.
- The user then tested start boost followed by this single cancellation command and reported success.

This verifies cancellation **to schedule**. It is not yet a verified general-purpose restoration of whichever Manual/Off state preceded boost. Store previous state if that alternative behaviour is required, and test each restoration path separately.

### 7.4 Failed/incomplete approaches: preserve these distinctions

| Operation | Receiver result | Physical result / conclusion |
|---|---|---|
| Write duration 10 during an existing boost | Read before 28; write SUCCESS; readback 10 | Wall display update not established; user accidentally cancelled boost |
| Write duration 0 during boost | Read before 9; write SUCCESS; readback 0 | **Boost remained on wall thermostat** |
| Then write mode 4 alone | Read before 5; write SUCCESS; readback 4 | Boost disappeared, but heating remained manual at existing target |
| Write mode 1 during another boost | Read before 5; write SUCCESS; readback 1 | Boost disappeared but target remained 19°C |
| Then write hold 0 | Read before 1; write SUCCESS; readback 0 | Still 19°C; schedule resumption not established |
| Physical selection of Schedule followed by manual 5°C change | Later mode 1 / hold 0 / duration 1 / target 500 | Intermediate mixed state; not a reliable schedule-mode reference |
| Combined mode 4 / hold 0 / duration 0 | All writes SUCCESS | **Scheduled target 100 restored; later full start/cancel test successful** |

Do not reduce the working combined cancellation to an individual mode or duration write based only on successful acknowledgements.

## 8. Manual heating and Off

### 8.1 Verified manual target control

HA target changes worked when applied to the **receiver's climate entity**. They had not worked when applied to the wall thermostat's climate entity.

The receiver heating-target attribute is `0x0201 / 0x0012`, int16, hundredths of °C. The wall dial's minimum manual target was observed as 5°C, and a physical manual adjustment produced receiver readback 500.

Setting only the target can interact with the current scheduling/hold state. Do not conflate target change, permanent manual mode and temporary schedule override.

### 8.2 Candidate full manual-mode recipe

External Hive Local Thermostat implementation uses mode Heat, target, hold enabled and duration zero together:

```python
# Candidate full manual recipe: not separately tested as this exact raw write here.
await cluster.write_attributes({
    0x001C: 4,
    0x0012: 2000,
    0x0023: 1,
    0x0024: 0,
})
```

That implementation also has additional handling for setpoint changes. Do not assume this document has established every manual-target transition path.

### 8.3 Enter Off: verified combined write

On 4 November 2026 at 12:23:56 UTC, the following combined request was accepted:

```python
await cluster.write_attributes({
    0x001C: 0,  # enum8: Off
    0x0023: 0,  # enum8: hold disabled
})
```

Target: receiver endpoint 5, Thermostat cluster `0x0201`, no manufacturer header. Send both attributes in one global Write Attributes request. No duration or target temperature is included in this tested recipe.

The receiver returned two `WriteAttributesStatusRecord(status=SUCCESS)` records. The user confirmed that the **physical thermostat displayed Off**. This is therefore a verified mode-entry operation, not merely an acknowledged write.

Toolkit invocation, after appending the `user_hive_off` helper to `custom_components/zha_toolkit/local/user.py`:

```yaml
action: zha_toolkit.execute
data:
  command: user_hive_off
  ieee: "RECEIVER_IEEE_ADDRESS"
```

The user then ran `user_hive_auto` and confirmed a return to the schedule. This verifies the **Off → Schedule** path in addition to the previously verified **Boost → Schedule** path. The schedule command remains the same combined mode 4 / hold 0 / duration 0 write; no schedule contents need to be rewritten.

**Frost protection is still only partially understood:**

- The user reported “No frost protection temperature set.” No numeric configured threshold was supplied or read over Zigbee.
- Entering Off did not explicitly write or alter a frost-protection temperature.
- No cold-temperature experiment tested when, or whether, the receiver calls for heating while in this state.
- No post-Off mode/hold/duration/target attribute readback was captured in this test; only the write statuses and physical mode indication were supplied.
- Do not infer that frost protection is disabled, has a particular default, or triggers at the schedule Off sentinel of 1°C.

The thermostat has a separate frost-protection setting whose Zigbee mapping remains unidentified. Actual threshold configuration and low-temperature relay activation remain open tests.

## 9. Holiday mode

### 9.1 Addressing and manufacturer header

All demonstrated holiday reads/writes target:

```text
receiver endpoint 5
cluster 0xfd00
manufacturer code 4153 decimal / 0x1039
```

`0xFD00` also appeared in the thermostat signature on endpoint 9, but no holiday writes to that endpoint were needed or tested.

### 9.2 Discovered and observed holiday map

| Attribute | Decimal | Type | Meaning | Evidence |
|---|---:|---|---|---|
| `0x0020` | 32 | enum8 `0x30` | Holiday enabled/scheduled flag | 0 before configuration, 1 after future holiday configured; writing 0 cancelled it |
| `0x0021` | 33 | enum8 | Unknown adjacent field | Discovered R/W/P; do not assign a role |
| `0x0022` | 34 | string `0x42` | Start date `YYYYMMDD` | A single space before configuration; `20300110` after |
| `0x0023` | 35 | uint16 `0x21` | Start time, minutes after midnight | 1350 matched 22:30 |
| `0x0024` | 36 | string `0x42` | End date `YYYYMMDD` | `20300117` matched 17 January 2030 |
| `0x0025` | 37 | uint16 `0x21` | End time, minutes after midnight | 553 matched 09:13 |
| `0x0026` | 38 | int16 `0x29` | Holiday temperature ×100 | 1000 matched 10°C; writing 700 changed physical setting to 7°C |

**Cluster distinction:** `0x0201 / 0x0023` is temperature hold, whereas `0xFD00 / 0x0023` is holiday start time. Attribute IDs are not globally unique.

The holiday flag was 1 for a **future** holiday. Therefore 1 means at least configured/enabled; it must not be presented as proof that the user is currently within the away interval.

### 9.3 Illustrative holiday encoding

For the following local dates and times:

```text
Start:       10 January 2030, 22:30
End:         17 January 2030, 09:13
Temperature: 10°C
```

The observed encoding gives these attribute values (dates anonymized):

```text
0x0020 = 1
0x0022 = "20300110"
0x0023 = 1350
0x0024 = "20300117"
0x0025 = 553
0x0026 = 1000
```

The first pasted result labelled 0x0024 accidentally duplicated the 0x0023 read; a subsequent explicit read of attribute 36 confirmed the end-date string. Use the corrected value above.

### 9.4 Read any holiday field

```yaml
action: zha_toolkit.attr_read
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0xfd00
  attribute: 0x0022
  manf: 4153
  tries: 1
```

The scan discovered manufacturer-specific attributes but did not supply their values. Direct reads with the manufacturer code succeeded. Missing `attribute_value` in the scan must not be interpreted as absence of support.

### 9.5 Change holiday temperature: verified

```yaml
action: zha_toolkit.attr_write
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0xfd00
  attribute: 0x0026
  attr_type: 0x29
  attr_val: 700
  manf: 4153
  read_before_write: true
  read_after_write: true
  tries: 1
```

The user confirmed this set 7°C on the thermostat. A preceding attempt at 10.5°C did not visibly change it, and the physical holiday UI only permits whole-degree selection. Implement whole-degree holiday temperature inputs initially. The precise firmware rejection/rounding behaviour for fractions was not captured, and the full permitted holiday-temperature range is not established.

Schedule temperature and holiday temperature therefore need different UI step sizes: half degrees for the demonstrated schedule editor, whole degrees for holiday.

### 9.6 Cancel holiday: verified

```yaml
action: zha_toolkit.attr_write
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  cluster: 0xfd00
  attribute: 0x0020
  attr_type: 0x30
  attr_val: 0
  manf: 4153
  read_before_write: true
  read_after_write: true
  tries: 1
```

The user reported perfect operation. Whether dates/times remain stored after cancellation was not read back; preserving stored fields is not required to infer cancellation, but should be tested before designing an enable-toggle UI.

### 9.7 Creating/enabling holidays remotely: not yet verified

The discovered types and established read encodings are sufficient to construct candidate writes, but these remain untested:

- Writing start/end date strings.
- Writing start/end time uint16 values.
- Enabling the flag by writing 1.
- Whether fields must be written together or in a particular order.
- Whether an adjacent attribute acts as a mode/commit field.
- Local-time versus UTC interpretation across DST changes.
- Behaviour for invalid ranges, same-day holidays, already-started periods or power cycles.

Do not label a remote holiday-creation implementation verified based only on the successful temperature and cancellation tests. A reasonable future experiment is to write a complete **future** interval while disabled, verify it on the wall thermostat, then enable and verify. That is a proposed test sequence, not an established requirement.

## 10. Additional discovered settings

### 10.1 Unknown manufacturer attributes on Thermostat cluster 0x0201

Receiver endpoint 5 advertised these attributes with manufacturer code 4153:

| Attribute | Type | Access | Meaning |
|---|---|---|---|
| `0x9540` | uint8 | R/W/P | Unknown |
| `0x9541` | uint8 | R/W/P | Unknown |
| `0x9542` | bitmap8 | R/W/P | Unknown |
| `0x9543` | int16 | R/W/P | Unknown |

No values or effects were established. Do not identify any of them as frost protection, calibration or child lock without controlled comparisons.

### 10.2 Complete discovered manufacturer cluster 0xFD00 list

Receiver endpoint 5; every listed field was discovered with manufacturer code 4153.

| Attribute | Type | Access | Interpretation |
|---|---|---|---|
| `0x0000` | bitmap8 | R/W/P | Unknown |
| `0x0001` | uint16 | R/W/P | Unknown |
| `0x0002` | int16 | R/P | Unknown |
| `0x0003` | uint8 | R/P | Unknown |
| `0x0004` | uint8 | R/P | Unknown |
| `0x0005` | uint16 | R/P | Unknown |
| `0x0006` | uint8 | R/W/P | Unknown |
| `0x0007` | uint8 | R/W/P | Unknown |
| `0x0008` | uint8 | R/W/P | Unknown |
| `0x0009` | uint8 | R/W/P | Unknown |
| `0x000a` | uint8 | R/W/P | Unknown |
| `0x0011` | enum8 | R/W/P | Unknown |
| `0x0020` | enum8 | R/W/P | Holiday enabled/scheduled; cancellation verified |
| `0x0021` | enum8 | R/W/P | Unknown |
| `0x0022` | string | R/W/P | Holiday start date |
| `0x0023` | uint16 | R/W/P | Holiday start minute |
| `0x0024` | string | R/W/P | Holiday end date |
| `0x0025` | uint16 | R/W/P | Holiday end minute |
| `0x0026` | int16 | R/W/P | Holiday temperature |
| `0x0027` | enum8 | R/W/P | Unknown |
| `0x0028` | enum8 | R/W/P | Unknown |
| `0x0029` | int16 | R/W/P | Unknown |
| `0x0030` | enum8 | R/W/P | Unknown |
| `0x0031` | int16 | R/W/P | Unknown |
| `0x0032` | enum8 | R/W/P | Unknown |
| `0xfffd` | uint16 | R/P | Generic cluster-revision ID; no value captured |

Discovery returned no cluster-specific commands in this cluster. The demonstrated holiday operations are global attribute reads/writes. Empty command discovery does not prove that undocumented commands are impossible.

### 10.3 Further functionality candidates

- **Child lock:** present on the physical SLT3b. Its signature includes Thermostat UI Configuration cluster `0x0204`; that is a sensible discovery target, not proof that the standard keypad-lock attribute controls Hive's lock.
- **Frost threshold:** adjustable in the physical UI; mapping not established. Do not confuse it with minimum heat setpoint or Off sentinel.
- **Target limits:** minimum/maximum attributes were discovered and readable. Their enforcement on the wall dial and remote commands is untested.
- **Display units and related UI settings:** standard cluster support is a lead; no writes tested.
- **Identify:** receiver Identify cluster advertises writable identify time and Identify commands. User-visible behaviour untested.

## 11. Monitoring, time and diagnostics

### 11.1 Receiver identification scan

Basic cluster examples:

| Attribute | Value |
|---|---|
| Manufacturer `0x0004` | Computime |
| Model `0x0005` | SLR1c |
| ZCL version `0x0000` | 3 |
| Application version `0x0001` | 13 |
| Stack version `0x0002` | 2 |
| Hardware version `0x0003` | 1 |
| Date code `0x0006` | `20201021` |
| Power source `0x0007` | 1 |

The receiver originally appeared as `unk_manufacturer / unk_model`, yet a direct Basic/model read returned SLR1c. Missing HA identification did not mean the radio could not read it. Reconfigure alone did not resolve the earlier pairing issue.

### 11.2 Time cluster 0x000A

Receiver endpoint 5 exposed:

| Attribute | Type | Access | Scan value |
|---|---|---|---:|
| `0x0000` Time | UTC time | R/W/P | 846973369 |
| `0x0001` Time status | bitmap8 | R/W/P | 5 |
| `0x0002` Timezone | int32 | R/W/P | 0 |
| `0x0003` DST start | uint32 | R/W/P | 0 |
| `0x0004` DST end | uint32 | R/W/P | 0 |
| `0x0005` DST shift | int32 | R/W/P | 0 |
| `0x0007` Local time | uint32 | R/P | 846973369 |
| `0xfffd` Cluster revision | uint16 | R/P | 1 |

The standard Zigbee UTC epoch is 2000-01-01, not Unix 1970-01-01. Conversion and daylight-saving writes were not tested in this investigation.

During failed pairing, the receiver repeatedly requested Time Status (attribute 1) about every ten seconds. HA generated a response value 5 (`Master | Master_for_Zone_and_DST`). A debug message complained of incorrect cluster direction, but the request was decoded and a reply generated. No causal connection to the pairing failure was established. Do not patch clock/direction handling solely because of that log.

### 11.3 Firmware queries and network visibility

The thermostat sent an OTA Query Next Image request on endpoint 9, cluster `0x0019`. HA responded `NO_IMAGE_AVAILABLE`. This is normal update-query behaviour, not an indication that joining or heating failed.

A received OTA query proves some thermostat-to-coordinator communication. It does not prove the receiver/thermostat application link is working or the schedule/target synchronisation is correct.

The receiver scan returned current firmware version 1271328 on its OTA cluster. The thermostat OTA query reported current version 84279826. These decimal values identify the captured software, without asserting compatibility across versions.

### 11.4 Reporting

Temperature, target, running state and battery are useful monitoring candidates. Some were already exposed by ZHA; exact reporting policies were not exhaustively tested.

An external first-hand report describes Hive receivers expecting thermostat communication within approximately ten minutes while an unsuitable reporting configuration used fifteen minutes. That report proposed configuring thermostat endpoint 9, Temperature Measurement cluster `0x0402`, attribute 0 with min interval 5 seconds, max 120 seconds, and change 50 (0.5°C). This workaround was **not tested as part of the successful clean pairing here**, and should not be installed automatically without diagnosing a recurrence.

### 11.5 Getting useful logs

In this installation, browser log downloads failed and `ha core logs --follow` failed with:

```text
No systemd-journal-gatewayd Unix socket available
```

Docker logs worked:

```bash
docker logs --since 5m homeassistant
```

Enable focused debug logging using HA actions:

```yaml
action: logger.set_level
data:
  custom_components.zha_toolkit: debug
  zigpy: debug
  zha: debug
```

Turn these back down after capture. For filtering, **do not search simply for `timeout`**: every decoded packet contains `extended_timeout=False`, so that filter admits unrelated packets. Also distinguish periodic `Device seen`/availability messages from actual newly received packets. Include device announcements when looking for a changed NWK address.

## 12. Toolkit commands and helper code

### 12.1 Setup

ZHA Toolkit must be installed and enabled in HA configuration:

```yaml
zha_toolkit:
```

Restart HA after enabling it. A missing `zha_toolkit.execute` action is a Toolkit setup issue, not a device-protocol response.

### 12.2 Read-only discovery used in the investigation

```yaml
action: zha_toolkit.scan_device
data:
  ieee: "RECEIVER_IEEE_ADDRESS"
  endpoint: 5
  manf: 4153
  tries: 1
```

This scans the endpoint's clusters; it is not limited to 0xFD00. It discovers attributes, types and access flags. Direct reads may still be needed for values.

### 12.3 Complete minimal combined-write helpers

Append these functions to:

```text
<HA configuration directory>/custom_components/zha_toolkit/local/user.py
```

Preserve any existing custom functions. The code uses Toolkit's documented user-command entry point and `get_device` utility. Toolkit reloads the user module on invocation. It is not a separate HA integration or HA `python_script`.

The following minimal versions send the same attribute sets as the tested helpers. They expose acknowledgement status separately from physical verification and never retry a timed-out write automatically. The exact installed helpers additionally included input checks and richer response text.

```python
def _hive_write_statuses(value):
    if hasattr(value, "status"):
        return [int(value.status)]
    if isinstance(value, (list, tuple)):
        return [code for item in value for code in _hive_write_statuses(item)]
    return []


async def _hive_write_once(app, listener, ieee, attributes, event_data):
    from .. import utils as toolkit_utils

    device = await toolkit_utils.get_device(app, listener, ieee)
    cluster = device.endpoints[5].in_clusters[0x0201]
    event_data["success"] = False
    event_data["verified_on_device"] = False
    try:
        reply = await cluster.write_attributes(attributes)
    except TimeoutError:
        event_data.setdefault("errors", []).append(
            "Acknowledgement timed out; inspect/read back before retrying")
        return
    codes = _hive_write_statuses(reply)
    event_data["write_reply"] = str(reply)
    event_data["write_status_codes"] = codes
    event_data["success"] = bool(codes) and all(code == 0 for code in codes)


async def user_hive_boost(app, listener, ieee, cmd, data, service, params, event_data):
    from decimal import Decimal

    options = service.data.get("kwargs") or {}
    minutes = options.get("minutes", 10)
    temperature = Decimal(str(options.get("temperature", 19)))
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 360:
        raise ValueError("Duration must be 1–360 whole minutes")
    if not temperature.is_finite() or not Decimal(5) <= temperature <= Decimal(32):
        raise ValueError("Target must be 5–32 degrees C")
    if temperature * 2 != (temperature * 2).to_integral_value():
        raise ValueError("Use half-degree target increments")
    await _hive_write_once(app, listener, ieee, {
        0x001C: 5,
        0x0024: minutes,
        0x0023: 1,
        0x0012: int(temperature * 100),
    }, event_data)


async def user_hive_auto(app, listener, ieee, cmd, data, service, params, event_data):
    await _hive_write_once(app, listener, ieee, {
        0x001C: 4,
        0x0023: 0,
        0x0024: 0,
    }, event_data)


async def user_hive_off(app, listener, ieee, cmd, data, service, params, event_data):
    await _hive_write_once(app, listener, ieee, {
        0x001C: 0,
        0x0023: 0,
    }, event_data)
```

Invoke a new boost:

```yaml
action: zha_toolkit.execute
data:
  command: user_hive_boost
  ieee: "RECEIVER_IEEE_ADDRESS"
  kwargs:
    minutes: 10
    temperature: 19
```

Cancel it and resume scheduling in **one action and one combined attribute write**:

```yaml
action: zha_toolkit.execute
data:
  command: user_hive_auto
  ieee: "RECEIVER_IEEE_ADDRESS"
```

`verified_on_device: false` in the helper's response is deliberate: the helper itself has not checked the wall display or performed a semantic readback. It does not contradict the successful physical verification reported in this investigation.

## 13. Implementation guidance

### 13.1 Suggested separation

1. Transport: resolve receiver by IEEE and use endpoint 5.
2. Typed protocol layer: schedules, combined mode/boost writes, manufacturer holiday attributes.
3. Device state: raw mode, hold, duration, target, running state and schedule/holiday data, each with timestamps.
4. UI/HA entities: present confirmed semantics rather than exposing the raw mode enum as a complete state machine.

A future consolidated integration can call zigpy directly instead of depending on Toolkit, but the correct ZHA device-resolution API and lifecycle must be tested against the HA version used. The existing schedule component uses Toolkit service calls to avoid relying on private ZHA access APIs.

### 13.2 Verification policy

- Keep `requested`, `acknowledged`, `read_back`, and `effective_on_device` distinct.
- Serialize operations per receiver within the component.
- Use one combined write for verified mode/boost transitions.
- After a timeout, read before deciding to retry; do not equate timeout with failure.
- Check every returned write status, not just the first.
- Validate schedule response day/mode/count before decoding.
- Treat target 100 as a schedule Off value where observed; do not clamp it to the minimum manual target 500.
- Match the user's actual device/timezone and make unresolved DST semantics explicit.
- Do not infer that an advertised writable attribute is a tested feature.

### 13.3 State modelling

Mode alone is insufficient. At minimum retain:

```text
raw_system_mode
temperature_setpoint_hold
temperature_setpoint_hold_duration
occupied_heating_setpoint
running_state
```

For a robust entity, report unknown/transitional when these values conflict rather than falsely claiming schedule/manual/boost based on one read. A schedule-resumption command can be considered successful after its target matches the current period, but a continuous implementation should also observe normal transitions and repeat with a different scheduled temperature.

Returning to schedule is different from restoring a previous manual target. The demonstrated cancellation action intentionally returns to schedule. Avoid promising restoration of the prior state unless its fields were captured and that restoration path has been tested.

### 13.4 Repository implementation

The accompanying Hive Local Control integration implements the documented operations, grouped schedule editing and a bundled dashboard card. See [README](README.md) for installation and [validation notes](docs/VALIDATION.md) for automated coverage and the remaining hardware checks. The schedule remains stored on the receiver; Home Assistant reads are observations rather than the authoritative schedule.

## 14. Unfinished tests

Recommended next experiments, with no assumptions of successful support:

1. Create a complete future holiday remotely, including date/time writes and enabling; verify all fields on the physical thermostat.
2. Determine whether holiday dates survive disable/re-enable and whether 0x0021 has any role.
3. Verify holiday ranges, integer temperature limits, DST and cross-year intervals.
4. With Off entry and return to schedule now verified, identify/read the actual frost threshold and test low-temperature activation separately.
5. Test manual Heat as one combined mode/hold/duration/target write.
6. Test boost target/duration combinations beyond 10 minutes at 19°C and allow one boost to expire naturally.
7. Test cancellation to the prior Manual and Off states if desired; distinguish this from cancellation to schedule.
8. Confirm scheduled operation through a real time transition after cancellation, preferably from Off to heating and back.
9. Map child lock and frost threshold by controlled UI changes and before/after reads.
10. Test minimum/maximum target-limit enforcement without assuming it from access flags.
11. Validate clock/DST handling and any time synchronisation requirements.
12. Confirm reporting intervals and availability over an extended period without reinstating unnecessary bindings.
13. Install and test the packaged HA component, including restart/reload/error paths.

## 15. Sources and investigation artifacts

### Primary evidence

The decisive evidence is recorded Toolkit responses and physical observations in this investigation, 2 and 4 November 2026:

- Successful receiver-first commissioning after clean removal/reset.
- Endpoint signatures and manufacturer-aware receiver scan.
- Schedule reads, the timed-out Monday write and successful readback.
- Controlled holiday date/time/temperature reads and verified writes/cancellation.
- Physical-boost attribute reads, unsuccessful single-field cancellation experiments, successful combined boost write, successful combined return-to-schedule write, and scheduled-target readback 100.
- Off-mode test at 12:23:56 UTC on 4 November: combined mode 0 / hold 0 acknowledged; physical thermostat displayed Off; user_hive_auto then restored schedule operation.

### External implementation references

- [ZHA Toolkit documentation and user commands](https://github.com/mdeweerd/zha-toolkit)
- [Toolkit binding implementation](https://github.com/mdeweerd/zha-toolkit/blob/main/custom_components/zha_toolkit/binds.py)
- [Toolkit attribute read/write implementation](https://github.com/mdeweerd/zha-toolkit/blob/main/custom_components/zha_toolkit/zcl_attr.py)
- [zigpy Thermostat cluster definitions](https://github.com/zigpy/zigpy/blob/dev/zigpy/zcl/clusters/hvac.py)
- [Hive device definitions in zigbee-herdsman-converters](https://github.com/Koenkk/zigbee-herdsman-converters/blob/master/src/devices/hive.ts)
- [Zigbee2MQTT SLR1c reference](https://www.zigbee2mqtt.io/devices/SLR1c.html)
- [SLR1 reference with native-boost timing notes](https://www.zigbee2mqtt.io/devices/SLR1.html)
- [Hive Local Thermostat coordinator implementation](https://github.com/andrew-codechimp/HA-Hive-Local-Thermostat/blob/main/custom_components/hive_local_thermostat/coordinator.py): source of the mode Heat + hold 0 + duration 0 schedule recipe subsequently verified on this pair. The project was marked retired when checked; its MQTT integration is not required for these direct Zigbee commands.
- [Hive pairing report and manual-binding experiment](https://community.home-assistant.io/t/hive-slt3b-and-slr1b-via-zha-pairing-never-completes/634178)
- [First-hand reporting-interval and manufacturer-cluster investigation](https://community.home-assistant.io/t/zha-with-hive-via-zigbee-slr1b/637164)

External sources are implementation leads, not substitutes for the device-specific verification labels above. Links may evolve; the exact payloads and observed outcomes are preserved in this document.

### Repository files

- [Installation and usage](README.md).
- [Validation coverage](docs/VALIDATION.md).
- `dist/hive-local-control.zip`: current installation package.
- `dist/preview.html`: standalone simulated preview.
- The Toolkit helpers in section 12 provide reference code; the integration does not require Toolkit.


## Revision history

- **0.1 (4 November 2026):** Initial protocol reference covering pairing, schedules, holiday investigation, boost and return to schedule.
- **0.2 (4 November 2026):** Confirmed combined Off command and Off-to-Schedule transition; added exact request/helper; retained frost threshold and cold-trigger behaviour as unknown.
