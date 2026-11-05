"""Serialized receiver operations, with readback and stale-edit protection."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from zigpy.exceptions import ZigbeeException

from .const import HOLIDAY_CLUSTER, THERMOSTAT_CLUSTER, TIME_CLUSTER
from .protocol import (
    DAY_NAMES,
    HOLIDAY_TYPES,
    STATE_ATTRIBUTES,
    WEEK_ORDER,
    ProtocolError,
    classify_state,
    day_mask,
    decode_schedule,
    decode_time,
    encode_holiday,
    encode_time,
    encode_transitions,
    integer,
    revision,
    selected_days,
    status_codes,
    temperature,
)


def timestamp():
    return datetime.now(UTC).isoformat()


class HiveController:
    def __init__(self, transport, *, timezone):
        self.transport = transport
        self.zone = ZoneInfo(timezone)
        self.lock = asyncio.Lock()

    async def read_state(self):
        async with self.lock:
            raw = await self.transport.read(THERMOSTAT_CLUSTER, STATE_ATTRIBUTES)
            if not all(key in raw for key in (0x001C, 0x0023, 0x0024, 0x0012)):
                raise ProtocolError("Receiver returned incomplete heating state")
            local = raw.get(0)
            return {
                "mode": classify_state(raw),
                "current_temperature": local / 100
                if local is not None and local != -32768
                else None,
                "target_temperature": raw[0x12] / 100 if raw[0x12] != -32768 else None,
                "scheduled_off": classify_state(raw) == "schedule" and raw[0x12] == 100,
                "heating": bool(raw[0x29] & 1) if 0x29 in raw else None,
                "remaining_minutes": int(raw[0x24]) if classify_state(raw) == "boost" else None,
                "minimum_temperature": raw[0x15] / 100 if 0x15 in raw else None,
                "maximum_temperature": raw[0x16] / 100 if 0x16 in raw else None,
                "raw_system_mode": int(raw[0x1C]),
                "hold": int(raw[0x23]),
                "hold_duration": int(raw[0x24]),
                "running_state": int(raw[0x29]) if 0x29 in raw else None,
                "read_at": timestamp(),
            }

    async def execute(self, operation, data):
        async with self.lock:
            if operation == "boost":
                target = temperature(data["temperature"])
                duration = integer(data["minutes"], 1, 360, "Boost duration")
                await self._check_limits(target)
                return await self._write_checked(
                    THERMOSTAT_CLUSTER,
                    {0x1C: 5, 0x24: duration, 0x23: 1, 0x12: target},
                )
            if operation == "resume_schedule":
                return await self._write_checked(THERMOSTAT_CLUSTER, {0x1C: 4, 0x23: 0, 0x24: 0})
            if operation == "off":
                return await self._write_checked(THERMOSTAT_CLUSTER, {0x1C: 0, 0x23: 0})
            if operation in ("set_target", "manual"):
                target = temperature(data["temperature"])
                await self._check_limits(target)
                attributes = {0x12: target}
                if operation == "manual":
                    attributes = {0x1C: 4, 0x12: target, 0x23: 1, 0x24: 0}
                return await self._write_checked(THERMOSTAT_CLUSTER, attributes)
            if operation == "read_schedule":
                return await self._read_day(day_mask(data["day"]))
            if operation == "read_week":
                return await self._read_week()
            if operation == "set_schedule_group":
                return await self._save_group(data)
            if operation == "set_schedule":
                return await self._save_day(data)
            if operation == "read_holiday":
                return await self._read_holiday()
            if operation == "cancel_holiday":
                return await self._write_checked(HOLIDAY_CLUSTER, {0x20: 0})
            if operation == "set_holiday_temperature":
                return await self._write_checked(
                    HOLIDAY_CLUSTER,
                    {0x26: temperature(data["temperature"], whole=True)},
                )
            if operation == "create_holiday":
                attributes = encode_holiday(
                    data["start"],
                    data["end"],
                    data["temperature"],
                    self.zone,
                    datetime.now(UTC),
                )
                existing = await self.transport.read(HOLIDAY_CLUSTER, [0x20])
                if existing.get(0x20) == 1:
                    raise ProtocolError("Cancel the existing holiday before creating a new one.")
                if existing.get(0x20) != 0:
                    raise ProtocolError(
                        "Could not check the current holiday. Reload before trying again."
                    )
                # Each stage must read back before enabling the interval.
                for fields in ({0x20: 0}, attributes, {0x20: 1}):
                    result = await self._write_checked(HOLIDAY_CLUSTER, fields)
                    if not result["read_back"]:
                        raise ProtocolError(
                            "Holiday setup stopped: receiver readback did not match. "
                            "Check the wall thermostat before retrying."
                        )
                result["holiday"] = await self._read_holiday()
                result["message"] = "Holiday saved and read back from the receiver."
                return result
            if operation == "read_time":
                return await self._read_time()
            if operation == "set_time":
                return await self._set_time(data.get("time"))
            raise ProtocolError("Unsupported operation")

    async def _read_time(self):
        raw = await self.transport.read(TIME_CLUSTER, [0])
        server_time = datetime.now(UTC)
        if 0 not in raw:
            raise ProtocolError("Receiver did not return its clock time")
        instant = decode_time(raw[0])
        return {
            "time": instant.astimezone(self.zone).strftime("%Y-%m-%dT%H:%M:%S"),
            "utc_time": instant.isoformat(),
            "zigbee_time": int(raw[0]),
            "timezone": str(self.zone),
            "server_time": server_time.isoformat(),
            "clock_delta_seconds": round((instant - server_time).total_seconds(), 3),
            "read_at": server_time.isoformat(),
        }

    async def _set_time(self, value):
        seconds = encode_time(value, self.zone, datetime.now(UTC))
        started = time.monotonic()
        result = await self._send_once(lambda: self.transport.write(TIME_CLUSTER, {0: seconds}))
        try:
            clock = await self._read_time()
        except (ProtocolError, TimeoutError, ZigbeeException) as exc:
            raise ProtocolError(
                "Time was sent, but could not be read back. Reopen Settings to check."
            ) from exc
        if any(code != 0 for code in result["write_status_codes"]):
            raise ProtocolError(
                "Receiver rejected the clock change. Reopen Settings to check its clock."
            )
        # The device clock advances during the write and read, unlike ordinary settings.
        tolerance = math.ceil(time.monotonic() - started) + 2
        if not seconds <= clock["zigbee_time"] <= seconds + tolerance:
            raise ProtocolError(
                "Receiver clock does not match the requested time. Reopen Settings to check."
            )
        return {
            **result,
            **clock,
            "read_back": True,
            "message": "Time set and read back from the receiver.",
        }

    async def _read_week(self):
        days, errors = [], {}
        for day in WEEK_ORDER:
            try:
                days.append(await self._read_day(day))
            except (ProtocolError, TimeoutError, ZigbeeException) as exc:
                errors[str(day)] = str(exc) or "No schedule response"
        return {"days": days, "errors": errors, "read_at": timestamp()}

    async def _save_group(self, data):
        days = selected_days(data["days"])
        encode_transitions(data["transitions"])
        revisions = data["revisions"]
        if not isinstance(revisions, dict) or set(revisions) != {str(day) for day in days}:
            raise ProtocolError("Load every selected day before saving")
        # Check the whole selection before any write. Each individual save checks again.
        for day in days:
            fresh = await self._read_day(day)
            if fresh["revision"] != revisions[str(day)]:
                raise ProtocolError(
                    f"{DAY_NAMES[day]} changed since loading. Reload the week before saving."
                )
        saved = []
        for index, day in enumerate(days):
            try:
                saved.append(
                    await self._save_day(
                        {
                            "day": day,
                            "transitions": data["transitions"],
                            "revision": revisions[str(day)],
                        }
                    )
                )
            except (ProtocolError, TimeoutError, ZigbeeException) as exc:
                saved_names = ", ".join(DAY_NAMES[item["day"]] for item in saved)
                message = f"Saved {saved_names}. " if saved else "No days were confirmed saved. "
                return {
                    "complete": False,
                    "days": saved,
                    "failed_day": day,
                    "remaining_days": days[index:],
                    "read_back": False,
                    "message": message + f"{DAY_NAMES[day]}: {str(exc) or 'No response'}. "
                    "Reload the week before retrying; later days were not sent.",
                }
        label = "Schedule" if len(saved) == 1 else f"{len(saved)} days"
        return {
            "complete": True,
            "days": saved,
            "read_back": True,
            "message": f"{label} saved and read back from the receiver.",
        }

    async def _check_limits(self, target):
        limits = await self.transport.read(THERMOSTAT_CLUSTER, [0x15, 0x16])
        if target < limits.get(0x15, 500) or target > limits.get(0x16, 3200):
            raise ProtocolError("Target is outside the receiver's configured heating limits")

    async def _send_once(self, send):
        timed_out = False
        try:
            reply = await send()
            codes = status_codes(reply)
        except (TimeoutError, ZigbeeException):
            # Delivery/acknowledgement errors do not prove the write was not applied.
            timed_out, codes = True, []
        return {
            "acknowledged": bool(codes) and all(code == 0 for code in codes),
            "write_status_codes": codes,
            "acknowledgement_missing": timed_out or not codes,
            "effective_on_device": False,
        }

    async def _write_checked(self, cluster, attributes):
        result = await self._send_once(lambda: self.transport.write(cluster, attributes))
        try:
            actual = await self.transport.read(cluster, list(attributes))
            matches = all(actual.get(key) == value for key, value in attributes.items())
            if attributes.get(0x1C) == 5 and cluster == THERMOSTAT_CLUSTER:
                # The native countdown can tick between the write and its readback.
                matches = all(
                    actual.get(key) == value
                    if key != 0x24
                    else actual.get(key) in (value, max(1, value - 1))
                    for key, value in attributes.items()
                )
            result["read_back"] = matches
        except (ProtocolError, TimeoutError, ZigbeeException):
            result["read_back"] = False
        if any(code != 0 for code in result["write_status_codes"]):
            raise ProtocolError(
                f"Receiver rejected part of the write ({result['write_status_codes']}). "
                "Some fields may have changed; refresh before retrying."
            )
        if not result["acknowledged"] and not result["read_back"]:
            raise ProtocolError(
                "Write outcome is unknown: no acknowledgement or matching readback. "
                "Check the thermostat before retrying."
            )
        result["message"] = (
            "Receiver values confirmed."
            if result["read_back"]
            else "Receiver accepted the request; readback has not matched yet. Refresh to check."
        )
        return result

    async def _read_day(self, day):
        rows = decode_schedule(await self.transport.get_schedule(day), day)
        return {
            "day": day,
            "transitions": rows,
            "revision": revision(day, rows),
            "read_at": timestamp(),
        }

    async def _save_day(self, data):
        day = day_mask(data["day"])
        values = encode_transitions(data["transitions"])
        expected = data.get("revision")
        if not isinstance(expected, str) or len(expected) != 64:
            raise ProtocolError("Load the day before saving it")
        fresh = await self._read_day(day)
        if fresh["revision"] != expected:
            raise ProtocolError(
                "This day changed since it was loaded. Reload the day before editing."
            )
        for target in values[1::2]:
            if target != 100:
                temperature(target / 100)
        limits = await self.transport.read(THERMOSTAT_CLUSTER, [0x15, 0x16])
        if any(
            t != 100 and not limits.get(0x15, 500) <= t <= limits.get(0x16, 3200)
            for t in values[1::2]
        ):
            raise ProtocolError("A scheduled target is outside the receiver's heating limits")
        result = await self._send_once(lambda: self.transport.set_schedule(day, values))
        try:
            after = await self._read_day(day)
        except (ProtocolError, TimeoutError, ZigbeeException) as exc:
            raise ProtocolError(
                "Schedule was sent once, but readback failed. Reload this day before retrying."
            ) from exc
        if encode_transitions(after["transitions"]) != values:
            raise ProtocolError(
                "Receiver schedule differs from your edit. Reload the day before retrying."
            )
        if any(code != 0 for code in result["write_status_codes"]):
            raise ProtocolError(
                "Schedule readback matches, but receiver reported a write error. Reload to check."
            )
        return {
            **result,
            **after,
            "read_back": True,
            "message": "Day saved and read back from the receiver.",
        }

    async def _read_holiday(self):
        raw = await self.transport.read(HOLIDAY_CLUSTER, list(HOLIDAY_TYPES))
        if raw.get(0x20) not in (0, 1):
            raise ProtocolError("Receiver did not return a valid holiday enabled flag")
        enabled = bool(raw[0x20])
        required = HOLIDAY_TYPES if enabled else (0x20, 0x26)
        if not all(key in raw for key in required):
            raise ProtocolError("Receiver returned incomplete holiday settings")

        def date_time(date_key, time_key):
            date = str(raw[date_key]).strip()
            minute = raw[time_key]
            if not date:
                return None
            try:
                day = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")
                integer(minute, 0, 1439, "Holiday time")
            except ValueError as exc:
                raise ProtocolError("Receiver returned an invalid holiday date or time") from exc
            return f"{day}T{minute // 60:02}:{minute % 60:02}"

        return {
            "enabled": enabled,
            "start": date_time(0x22, 0x23) if enabled else None,
            "end": date_time(0x24, 0x25) if enabled else None,
            "temperature": raw[0x26] / 100,
            "timezone": str(self.zone),
            "read_at": timestamp(),
        }
