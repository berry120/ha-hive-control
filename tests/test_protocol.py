from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from zigpy.zcl import foundation
from zigpy.zcl.clusters.hvac import Thermostat

from custom_components.hive_local.protocol import (
    ProtocolError,
    classify_state,
    day_mask,
    decode_schedule,
    encode_holiday,
    encode_transitions,
    ieee_address,
    minutes,
    status_codes,
    temperature,
)

VALUES = [390, 1800, 510, 100, 720, 100, 840, 100, 1020, 1750, 1200, 100]


def test_captured_schedule_round_trip_and_off_sentinel():
    schema = Thermostat.ClientCommandDefs.get_weekly_schedule_response.schema
    response = schema(6, 2, 1, VALUES)
    rows = decode_schedule(response, 2)
    assert rows[1] == {"time": "08:30", "temperature": None}
    assert rows[4] == {"time": "17:00", "temperature": 17.5}
    assert encode_transitions(rows) == VALUES


@pytest.mark.parametrize(
    "reply",
    [
        [0, 2, 1, []],
        [6, 4, 1, VALUES],
        [6, 2, 3, VALUES],
        [5, 2, 1, VALUES],
        [6, 2, 1, VALUES[:-1]],
        [6, 2, 1, None],
        [1, 2, 1, [1440, 1800]],
        [1, 2, 1, [10, -32768]],
        [2, 2, 1, [100, 1800, 50, 1800]],
        [2, 2, 1, [100, 1800, 100, 1800]],
        foundation.GENERAL_COMMANDS[foundation.GeneralCommand.Default_Response].schema(
            command_id=1, status=foundation.Status.SUCCESS
        ),
    ],
)
def test_reject_bad_schedule_and_acknowledgement(reply):
    with pytest.raises(ProtocolError):
        decode_schedule(reply, 2)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 4.5, 32.5, 19.25, "oops"])
def test_temperature_validation(value):
    with pytest.raises(ProtocolError):
        temperature(value)


def test_distinct_temperature_steps():
    assert temperature(17.5) == 1750
    assert temperature(7, whole=True) == 700
    with pytest.raises(ProtocolError):
        temperature(7.5, whole=True)


@pytest.mark.parametrize("value", [0, 3, 127, 128, True, "2"])
def test_only_single_calendar_day(value):
    with pytest.raises(ProtocolError):
        day_mask(value)


def test_ieee_and_time_validation():
    assert ieee_address("02:00:00:00:00:00:AB:CD") == "02:00:00:00:00:00:ab:cd"
    assert minutes("22:30") == 1350
    for invalid in ("24:00", "6:30", "12:60"):
        with pytest.raises(ProtocolError):
            minutes(invalid)


@pytest.mark.parametrize(
    ("mode", "hold", "duration", "expected"),
    [
        (4, 0, 0, "schedule"),
        (4, 0, 10, "unknown"),
        (1, 0, 0, "unknown"),
        (5, 1, 10, "boost"),
        (5, 0, 10, "unknown"),
        (5, 1, 65535, "unknown"),
        (4, 1, 0, "manual"),
        (0, 0, 65535, "off"),
        (0, 1, 0, "unknown"),
    ],
)
def test_mode_is_not_just_system_mode(mode, hold, duration, expected):
    assert classify_state({0x1C: mode, 0x23: hold, 0x24: duration}) == expected


def test_statuses_check_every_record_and_modern_schema():
    records = [
        foundation.WriteAttributesStatusRecord(status=foundation.Status.SUCCESS),
        foundation.WriteAttributesStatusRecord(status=foundation.Status.INVALID_VALUE, attrid=0x12),
    ]
    schema = foundation.GENERAL_COMMANDS[foundation.GeneralCommand.Write_Attributes_rsp].schema
    assert status_codes(schema(records)) == [0, 0x87]
    assert status_codes([]) == []


def test_holiday_uses_observed_field_encodings_with_example_dates():
    result = encode_holiday(
        "2030-01-10T22:30",
        "2030-01-17T09:13",
        7,
        ZoneInfo("Europe/London"),
        datetime(2026, 11, 4, tzinfo=UTC),
    )
    assert result == {0x22: "20300110", 0x23: 1350, 0x24: "20300117", 0x25: 553, 0x26: 700}


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-01-03T22:30", "2026-01-17T09:13"),
        ("2030-01-10T22:30", "2030-01-10T22:30"),
        ("2027-03-27T12:00", "2027-03-29T12:00"),
        ("2027-03-28T01:30", "2027-03-30T12:00"),
        ("2027-01-10T12:00", "2028-01-10T12:00"),
        ("2026-11-31T12:00", "2026-12-10T12:00"),
    ],
)
def test_reject_unverified_or_invalid_holiday_intervals(start, end):
    with pytest.raises(ProtocolError):
        encode_holiday(start, end, 7, ZoneInfo("Europe/London"), datetime(2026, 11, 4, tzinfo=UTC))
