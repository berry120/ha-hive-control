import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from custom_components.hive_local.const import HOLIDAY_CLUSTER, THERMOSTAT_CLUSTER, TIME_CLUSTER
from custom_components.hive_local.controller import HiveController
from custom_components.hive_local.protocol import WEEK_ORDER, ProtocolError

VALUES = [390, 1800, 510, 100, 720, 100, 840, 100, 1020, 1800, 1200, 100]


class Receiver:
    def __init__(self):
        self.raw = {
            THERMOSTAT_CLUSTER: {
                0: 1938,
                0x12: 100,
                0x15: 500,
                0x16: 3200,
                0x1C: 4,
                0x23: 0,
                0x24: 0,
                0x29: 0,
            },
            HOLIDAY_CLUSTER: {
                0x20: 1,
                0x22: "20300110",
                0x23: 1350,
                0x24: "20300117",
                0x25: 553,
                0x26: 700,
            },
        }
        self.values = VALUES[:]
        self.schedules = {day: VALUES[:] for day in WEEK_ORDER}
        self.schedules[2] = self.values
        self.read_failures = set()
        self.save_failures = set()
        self.raw[TIME_CLUSTER] = {0: 846973369}
        self.writes = []
        self.schedule_writes = []
        self.timeout = False
        self.apply = True
        self.codes = [0]

    async def read(self, cluster, attributes):
        return {a: self.raw[cluster][a] for a in attributes if a in self.raw[cluster]}

    async def write(self, cluster, attributes):
        self.writes.append((cluster, attributes))
        if self.apply:
            self.raw[cluster].update(attributes)
        if self.timeout:
            raise TimeoutError()
        return [[SimpleNamespace(status=c) for c in self.codes]]

    async def get_schedule(self, day):
        if day in self.read_failures:
            raise TimeoutError()
        values = self.values if day == 2 else self.schedules[day]
        return [len(values) // 2, day, 1, values[:]]

    async def set_schedule(self, day, values):
        self.schedule_writes.append((day, values))
        if day in self.save_failures:
            raise TimeoutError()
        if self.apply:
            self.schedules[day] = values[:]
            if day == 2:
                self.values = self.schedules[day]
        if self.timeout:
            raise TimeoutError()
        return [[SimpleNamespace(status=c) for c in self.codes]]


@pytest.fixture
def pair():
    receiver = Receiver()
    return receiver, HiveController(receiver, timezone="Europe/London")


async def test_boost_and_cancel_are_each_one_combined_write(pair):
    receiver, controller = pair
    result = await controller.execute("boost", {"minutes": 10, "temperature": 19})
    assert receiver.writes == [(THERMOSTAT_CLUSTER, {0x1C: 5, 0x24: 10, 0x23: 1, 0x12: 1900})]
    assert result["read_back"] and result["acknowledged"] and not result["effective_on_device"]
    await controller.execute("resume_schedule", {})
    assert receiver.writes[-1] == (THERMOSTAT_CLUSTER, {0x1C: 4, 0x23: 0, 0x24: 0})
    await controller.execute("off", {})
    assert receiver.writes[-1] == (THERMOSTAT_CLUSTER, {0x1C: 0, 0x23: 0})


async def test_timeout_does_not_repeat_applied_write(pair):
    receiver, controller = pair
    receiver.timeout = True
    result = await controller.execute("boost", {"minutes": 10, "temperature": 19})
    assert result["read_back"] and not result["acknowledged"]
    assert len(receiver.writes) == 1


async def test_timeout_without_readback_is_unknown_not_success(pair):
    receiver, controller = pair
    receiver.timeout, receiver.apply = True, False
    with pytest.raises(ProtocolError, match="outcome is unknown"):
        await controller.execute("off", {})
    assert len(receiver.writes) == 1


async def test_partial_status_failure_is_not_success(pair):
    receiver, controller = pair
    receiver.codes = [0, 0x87]
    with pytest.raises(ProtocolError, match="rejected part"):
        await controller.execute("off", {})


async def test_ack_without_matching_readback_is_explicit(pair):
    receiver, controller = pair
    receiver.apply = False
    result = await controller.execute("off", {})
    assert result["acknowledged"] and not result["read_back"]
    assert "not matched" in result["message"]


async def test_schedule_save_after_timeout_matches_full_day(pair):
    receiver, controller = pair
    original = await controller.execute("read_schedule", {"day": 2})
    edit = deepcopy(original["transitions"])
    edit[4]["temperature"] = 17.5
    receiver.timeout = True
    result = await controller.execute(
        "set_schedule", {"day": 2, "transitions": edit, "revision": original["revision"]}
    )
    assert result["read_back"] and not result["acknowledged"]
    assert receiver.schedule_writes == [
        (2, [390, 1800, 510, 100, 720, 100, 840, 100, 1020, 1750, 1200, 100])
    ]


async def test_stale_edit_refused_before_write(pair):
    receiver, controller = pair
    original = await controller.execute("read_schedule", {"day": 2})
    receiver.values[1] = 1950  # A change made at the wall thermostat.
    with pytest.raises(ProtocolError, match="changed since"):
        await controller.execute("set_schedule", original)
    assert receiver.schedule_writes == []


async def test_schedule_ack_is_not_persistence(pair):
    receiver, controller = pair
    original = await controller.execute("read_schedule", {"day": 2})
    original["transitions"][4]["temperature"] = 17.5
    receiver.apply = False
    with pytest.raises(ProtocolError, match="differs"):
        await controller.execute("set_schedule", original)
    assert len(receiver.schedule_writes) == 1


async def test_respects_reported_limits_without_clamping_off(pair):
    receiver, controller = pair
    receiver.raw[THERMOSTAT_CLUSTER][0x15] = 1000
    with pytest.raises(ProtocolError, match="limits"):
        await controller.execute("boost", {"minutes": 10, "temperature": 7})
    assert receiver.writes == []
    state = await controller.read_state()
    assert state["scheduled_off"] and state["target_temperature"] == 1


async def test_holiday_flag_means_enabled_not_currently_away(pair):
    receiver, controller = pair
    result = await controller.execute("read_holiday", {})
    assert result["enabled"]
    assert "active" not in result
    assert result["start"] == "2030-01-10T22:30"
    await controller.execute("set_holiday_temperature", {"temperature": 7})
    await controller.execute("cancel_holiday", {})
    assert receiver.writes == [(HOLIDAY_CLUSTER, {0x26: 700}), (HOLIDAY_CLUSTER, {0x20: 0})]


@pytest.mark.parametrize("operation", ["set_frost", "set_child_lock"])
async def test_undefined_controls_cannot_write_arbitrary_attributes(pair, operation):
    receiver, controller = pair
    with pytest.raises(ProtocolError):
        await controller.execute(operation, {})
    assert receiver.writes == []


async def test_holiday_disables_stages_and_enables_without_options_gate(pair):
    receiver, controller = pair
    receiver.raw[HOLIDAY_CLUSTER][0x20] = 0
    result = await controller.execute(
        "create_holiday", {"start": "2030-11-10T22:30", "end": "2030-12-17T09:13", "temperature": 7}
    )
    assert receiver.writes == [
        (HOLIDAY_CLUSTER, {0x20: 0}),
        (HOLIDAY_CLUSTER, {0x22: "20301110", 0x23: 1350, 0x24: "20301217", 0x25: 553, 0x26: 700}),
        (HOLIDAY_CLUSTER, {0x20: 1}),
    ]
    assert result["read_back"] and not result["effective_on_device"]


async def test_failed_holiday_stage_never_enables(pair):
    receiver, controller = pair
    receiver.raw[HOLIDAY_CLUSTER][0x20] = 0
    receiver.apply = False
    with pytest.raises(ProtocolError, match="setup stopped"):
        await controller.execute(
            "create_holiday",
            {"start": "2030-11-10T22:30", "end": "2030-12-17T09:13", "temperature": 7},
        )
    assert len(receiver.writes) == 2
    assert receiver.writes[0] == (HOLIDAY_CLUSTER, {0x20: 0})
    assert all(fields.get(0x20) != 1 for _, fields in receiver.writes)


@pytest.mark.parametrize("flag", [1, 2, None])
async def test_create_cannot_replace_enabled_or_unknown_holiday(pair, flag):
    receiver, controller = pair
    receiver.raw[HOLIDAY_CLUSTER][0x20] = flag
    with pytest.raises(ProtocolError, match="Cancel the existing|Could not check"):
        await controller.execute(
            "create_holiday",
            {"start": "2030-11-10T22:30", "end": "2030-12-17T09:13", "temperature": 7},
        )
    assert receiver.writes == []


async def test_cancel_allows_planning_another_holiday(pair):
    receiver, controller = pair
    await controller.execute("cancel_holiday", {})
    result = await controller.execute(
        "create_holiday",
        {"start": "2030-11-10T22:30", "end": "2030-12-17T09:13", "temperature": 8},
    )
    assert result["holiday"]["enabled"]
    assert result["holiday"]["temperature"] == 8


async def test_disabled_holiday_ignores_unused_interval(pair):
    receiver, controller = pair
    receiver.raw[HOLIDAY_CLUSTER] = {0x20: 0, 0x26: 700, 0x22: "invalid"}
    result = await controller.execute("read_holiday", {})
    assert not result["enabled"]
    assert result["start"] is None and result["end"] is None
    assert result["temperature"] == 7


async def test_default_boost_target_is_sent_in_one_command(pair):
    from custom_components.hive_local.const import DEFAULTS

    receiver, controller = pair
    await controller.execute(
        "boost",
        {"minutes": DEFAULTS["boost_minutes"], "temperature": DEFAULTS["boost_temperature"]},
    )
    assert receiver.writes == [(THERMOSTAT_CLUSTER, {0x1C: 5, 0x24: 10, 0x23: 1, 0x12: 3000})]


async def test_serializes_overlapping_clients(pair):
    receiver, controller = pair
    entered, release = asyncio.Event(), asyncio.Event()
    original_write = receiver.write

    async def slow_write(cluster, attributes):
        entered.set()
        await release.wait()
        return await original_write(cluster, attributes)

    receiver.write = slow_write
    first = asyncio.create_task(controller.execute("off", {}))
    await entered.wait()
    second = asyncio.create_task(controller.execute("resume_schedule", {}))
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert receiver.writes == [
        (THERMOSTAT_CLUSTER, {0x1C: 0, 0x23: 0}),
        (THERMOSTAT_CLUSTER, {0x1C: 4, 0x23: 0, 0x24: 0}),
    ]


async def test_incomplete_state_not_reused_or_reported_as_schedule(pair):
    receiver, controller = pair
    del receiver.raw[THERMOSTAT_CLUSTER][0x23]
    with pytest.raises(ProtocolError, match="incomplete"):
        await controller.read_state()
