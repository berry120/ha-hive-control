from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from test_controller import Receiver

from custom_components.hive_local.const import THERMOSTAT_CLUSTER, TIME_CLUSTER
from custom_components.hive_local.controller import HiveController
from custom_components.hive_local.protocol import (
    WEEK_ORDER,
    ProtocolError,
    decode_time,
    encode_time,
    selected_days,
)


@pytest.fixture
def pair():
    receiver = Receiver()
    return receiver, HiveController(receiver, timezone="Europe/London")


async def group_edit(controller, days):
    week = await controller.execute("read_week", {})
    rows = week["days"][0]["transitions"]
    rows[4]["temperature"] = 19.5
    return {
        "days": days,
        "transitions": rows,
        "revisions": {
            str(item["day"]): item["revision"] for item in week["days"] if item["day"] in days
        },
    }


async def test_week_reads_every_day_individually_and_keeps_failures_visible(pair):
    receiver, controller = pair
    receiver.read_failures.add(8)
    result = await controller.execute("read_week", {})
    assert [item["day"] for item in result["days"]] == [2, 4, 16, 32, 64, 1]
    assert set(result["errors"]) == {"8"}
    assert receiver.schedule_writes == []


async def test_group_save_writes_only_selected_days_with_full_off_periods(pair):
    receiver, controller = pair
    edit = await group_edit(controller, [2, 4, 8, 16, 32])
    result = await controller.execute("set_schedule_group", edit)
    assert result["complete"] and result["read_back"]
    assert [day for day, _ in receiver.schedule_writes] == [2, 4, 8, 16, 32]
    assert all(
        values == [390, 1800, 510, 100, 720, 100, 840, 100, 1020, 1950, 1200, 100]
        for _, values in receiver.schedule_writes
    )
    assert receiver.schedules[64][9] == 1800
    assert receiver.schedules[1][9] == 1800


async def test_stale_last_day_prevents_all_group_writes(pair):
    receiver, controller = pair
    edit = await group_edit(controller, [2, 4, 8, 16, 32])
    receiver.schedules[32][1] = 2050
    with pytest.raises(ProtocolError, match="Friday changed"):
        await controller.execute("set_schedule_group", edit)
    assert receiver.schedule_writes == []


async def test_later_day_failure_reports_confirmed_days_and_stops(pair):
    receiver, controller = pair
    edit = await group_edit(controller, [2, 4, 8, 16, 32])
    receiver.save_failures.add(8)
    result = await controller.execute("set_schedule_group", edit)
    assert not result["complete"] and not result["read_back"]
    assert [item["day"] for item in result["days"]] == [2, 4]
    assert result["failed_day"] == 8
    assert result["remaining_days"] == [8, 16, 32]
    assert [day for day, _ in receiver.schedule_writes] == [2, 4, 8]
    assert "Saved Monday, Tuesday" in result["message"]


async def test_clock_read_uses_zigbee_epoch_and_ha_zone(pair):
    receiver, controller = pair
    result = await controller.execute("read_time", {})
    expected = decode_time(receiver.raw[TIME_CLUSTER][0])
    assert result["utc_time"] == expected.isoformat()
    assert result["time"] == expected.astimezone(controller.zone).strftime("%Y-%m-%dT%H:%M:%S")
    assert result["timezone"] == "Europe/London"


@pytest.mark.parametrize("delta", [-301, -120, 0, 120, 300, 301])
async def test_clock_difference_uses_server_utc_and_keeps_its_sign(pair, delta):
    receiver, controller = pair
    server = decode_time(receiver.raw[TIME_CLUSTER][0]) - timedelta(seconds=delta)
    clock = Mock(wraps=datetime)
    clock.now.return_value = server
    with patch("custom_components.hive_local.controller.datetime", clock):
        result = await controller.execute("read_time", {})
    assert result["clock_delta_seconds"] == delta
    assert result["server_time"] == server.isoformat() == result["read_at"]


@pytest.mark.parametrize("timeout", [False, True])
async def test_clock_write_once_and_tick_tolerant_readback(pair, timeout):
    receiver, controller = pair
    receiver.timeout = timeout
    original = receiver.write

    async def write(cluster, attributes):
        try:
            return await original(cluster, attributes)
        finally:
            receiver.raw[TIME_CLUSTER][0] += 1

    receiver.write = write
    result = await controller.execute("set_time", {"time": "2026-07-15T12:30:00"})
    assert result["read_back"] and result["acknowledged"] != timeout
    assert result["utc_time"] == "2026-07-15T11:30:01+00:00"
    assert result["time"] == "2026-07-15T12:30:01"
    assert len(receiver.writes) == 1
    cluster, attributes = receiver.writes[0]
    assert cluster == TIME_CLUSTER and set(attributes) == {0}


async def test_sync_time_uses_server_clock_not_browser_clock(pair):
    receiver, controller = pair
    before = datetime.now(UTC)
    result = await controller.execute("set_time", {})
    after = datetime.now(UTC)
    written = decode_time(receiver.writes[0][1][0])
    assert before.replace(microsecond=0) <= written <= after
    assert result["read_back"]


async def test_acknowledged_clock_change_must_read_back(pair):
    receiver, controller = pair
    receiver.apply = False
    with pytest.raises(ProtocolError, match="does not match"):
        await controller.execute("set_time", {"time": "2030-11-10T12:00:00"})
    assert len(receiver.writes) == 1


async def test_clock_read_failure_after_write_does_not_retry(pair):
    receiver, controller = pair
    receiver.read = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(ProtocolError, match="could not be read back"):
        await controller.execute("set_time", {"time": "2030-11-10T12:00:00"})
    assert len(receiver.writes) == 1


async def test_manual_hold_available_without_options_flag(pair):
    receiver, controller = pair
    result = await controller.execute("manual", {"temperature": 20})
    assert result["read_back"]
    assert receiver.writes == [(THERMOSTAT_CLUSTER, {0x1C: 4, 0x12: 2000, 0x23: 1, 0x24: 0})]


@pytest.mark.parametrize("selection", [[], [2, 2], [3], [128], [True], "weekdays", [2, "4"]])
def test_reject_invalid_day_selections(selection):
    with pytest.raises(ProtocolError):
        selected_days(selection)


def test_week_order_and_epoch_zero():
    assert selected_days(list(reversed(WEEK_ORDER))) == list(WEEK_ORDER)
    assert decode_time(0) == datetime(2000, 1, 1, tzinfo=UTC)
    assert encode_time("2000-01-01T00:00:00", ZoneInfo("UTC"), datetime.now(UTC)) == 0


@pytest.mark.parametrize(
    "value",
    [
        "2027-03-28T01:30",
        "2027-10-31T01:30",
        "1999-12-31T23:59:59",
        "2300-01-01T12:00",
        "2026-02-30T00:00",
        "2030-01-10T22:30Z",
    ],
)
def test_invalid_ambiguous_and_out_of_range_time(value):
    with pytest.raises(ProtocolError):
        encode_time(value, ZoneInfo("Europe/London"), datetime.now(UTC))


def test_unset_device_clock_is_not_displayed_as_real_date():
    with pytest.raises(ProtocolError):
        decode_time(0xFFFFFFFF)
