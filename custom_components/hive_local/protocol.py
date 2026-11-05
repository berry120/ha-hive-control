"""Pure validation and encoding. Unknown Hive attributes are deliberately excluded."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

DAY_MASKS = (1, 2, 4, 8, 16, 32, 64)
WEEK_ORDER = (2, 4, 8, 16, 32, 64, 1)
DAY_NAMES = dict(
    zip(
        WEEK_ORDER,
        ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        strict=True,
    )
)
STATE_ATTRIBUTES = (0x0000, 0x0012, 0x0015, 0x0016, 0x001C, 0x0023, 0x0024, 0x0029)
HOLIDAY_TYPES = {0x20: 0x30, 0x22: 0x42, 0x23: 0x21, 0x24: 0x42, 0x25: 0x21, 0x26: 0x29}
HEATING_TYPES = {0x0012: 0x29, 0x001C: 0x30, 0x0023: 0x30, 0x0024: 0x21}
TIME_TYPES = {0x0000: 0xE2}
ZIGBEE_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


class ProtocolError(ValueError):
    """Invalid input or an unexpected response from the receiver."""


def ieee_address(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[0-9a-fA-F]{2}:){7}[0-9a-fA-F]{2}", value
    ):
        raise ProtocolError(
            "Enter the device's IEEE address: eight pairs of hexadecimal digits separated by colons"
        )
    return value.lower()


def integer(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProtocolError(f"{label} must be a whole number from {minimum} to {maximum}")
    return value


def temperature(value, *, whole=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProtocolError("Enter a temperature in degrees Celsius") from exc
    if not number.is_finite() or not Decimal(5) <= number <= Decimal(32):
        raise ProtocolError("Temperature must be between 5 and 32°C")
    scaled = number if whole else number * 2
    if scaled != scaled.to_integral_value():
        raise ProtocolError("Use whole degrees" if whole else "Use half-degree increments")
    return int(number * 100)


def minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ProtocolError("Use a time in HH:MM format")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def day_mask(value):
    if isinstance(value, bool) or not isinstance(value, int) or value not in DAY_MASKS:
        raise ProtocolError("Select one day (Sunday=1, Monday=2, …, Saturday=64)")
    return value


def encode_transitions(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 6:
        raise ProtocolError("A day must contain 1–6 complete transitions")
    values = []
    previous = -1
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"time", "temperature"}:
            raise ProtocolError("Each transition needs time and temperature (null for Off)")
        minute = minutes(row["time"])
        if minute <= previous:
            raise ProtocolError("Times must be unique and in increasing order")
        previous = minute
        target = 100 if row["temperature"] is None else temperature(row["temperature"])
        values.extend((minute, target))
    return values


def decode_schedule(reply, day):
    day_mask(day)
    if hasattr(reply, "as_tuple"):
        reply = reply.as_tuple()
    if not isinstance(reply, (list, tuple)) or len(reply) != 4:
        raise ProtocolError("Receiver did not return schedule data")
    count, returned_day, mode, values = reply
    integer(count, 1, 6, "Transition count")
    if (
        returned_day != day
        or mode != 1
        or not isinstance(values, (list, tuple))
        or len(values) != 2 * count
    ):
        raise ProtocolError("Unexpected schedule day, mode or transition count")
    rows = []
    for minute, target in zip(values[::2], values[1::2], strict=True):
        integer(minute, 0, 1439, "Transition time")
        integer(target, -32768, 32767, "Setpoint")
        rows.append(
            {
                "time": f"{minute // 60:02}:{minute % 60:02}",
                "temperature": None if target == 100 else target / 100,
            }
        )
    encode_transitions(rows)
    return rows


def revision(day, rows):
    return hashlib.sha256(json.dumps([day, rows], sort_keys=True).encode()).hexdigest()


def selected_days(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 7:
        raise ProtocolError("Select between one and seven days")
    for value in values:
        day_mask(value)
    if len(set(values)) != len(values):
        raise ProtocolError("Select each day only once")
    return [day for day in WEEK_ORDER if day in values]


def encode_time(value, zone, now):
    """Convert an HA-zone wall-clock entry to the standard Zigbee UTC epoch."""
    if value is None:
        instant = now
    else:
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", value
        ):
            raise ProtocolError("Enter a date and time as YYYY-MM-DDTHH:MM[:SS]")
        try:
            local = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ProtocolError("Invalid date or time") from exc
        instant = local.replace(tzinfo=zone, fold=0)
        if instant.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset():
            raise ProtocolError("Choose a time outside the daylight-saving clock change")
    seconds = int((instant.astimezone(UTC) - ZIGBEE_EPOCH).total_seconds())
    return integer(seconds, 0, 0xFFFFFFFE, "Zigbee clock value")


def decode_time(value):
    return ZIGBEE_EPOCH + timedelta(seconds=integer(value, 0, 0xFFFFFFFE, "Zigbee clock value"))


def classify_state(raw):
    mode, hold, duration = (raw.get(a) for a in (0x1C, 0x23, 0x24))
    if mode == 0 and hold == 0:
        return "off"
    if mode == 5 and hold == 1 and duration is not None and 0 < duration < 65535:
        return "boost"
    if (mode, hold, duration) == (4, 0, 0):
        return "schedule"
    if mode == 4 and hold == 1 and duration in (0, 65535):
        return "manual"
    return "unknown"


def encode_holiday(start, end, target, zone, now):
    """Use wall-clock fields; reject untested DST boundaries and ambiguous times."""
    parsed = []
    for value in (start, end):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
            raise ProtocolError("Holiday dates must use YYYY-MM-DDTHH:MM")
        try:
            local = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ProtocolError("Invalid holiday date") from exc
        first, second = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ProtocolError("Holiday time falls in a daylight-saving clock change")
        parsed.append(first)
    start_dt, end_dt = parsed
    if start_dt <= now or end_dt <= start_dt:
        raise ProtocolError("Choose a future start and an end after the start")
    if end_dt - start_dt > timedelta(days=366):
        raise ProtocolError("Holiday intervals must be no longer than one year")
    # Compare intermediate dates as well: a year-long interval can cross two changes.
    probe = start_dt
    while probe < end_dt:
        if probe.utcoffset() != start_dt.utcoffset():
            raise ProtocolError("Choose a holiday interval within one daylight-saving period")
        probe += timedelta(days=1)
    if end_dt.utcoffset() != start_dt.utcoffset():
        raise ProtocolError("Choose a holiday interval within one daylight-saving period")
    return {
        0x22: start_dt.strftime("%Y%m%d"),
        0x23: start_dt.hour * 60 + start_dt.minute,
        0x24: end_dt.strftime("%Y%m%d"),
        0x25: end_dt.hour * 60 + end_dt.minute,
        0x26: temperature(target, whole=True),
    }


def status_codes(reply):
    """Collect every status, including zigpy CommandSchema containers."""
    if hasattr(reply, "status"):
        return [int(reply.status)]
    if hasattr(reply, "as_tuple"):
        reply = reply.as_tuple()
    if isinstance(reply, (list, tuple)):
        return [code for item in reply for code in status_codes(item)]
    return []
