"""Exercise offline setup, unavailable sensor output and recovery at the HA boundary."""

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
from zigpy.exceptions import ZigbeeException

from custom_components.hive_local.const import DEFAULTS, DOMAIN
from custom_components.hive_local.protocol import ProtocolError
from custom_components.hive_local.settings import entry_options
from custom_components.hive_local.transport import ZhaTransport

COMPONENT = Path(__file__).parents[1] / "custom_components/hive_local"
# Fictional identifiers for test installations; never application defaults.
THERMOSTAT = "02:00:00:00:00:00:00:02"
INSTALLATION = {
    **DEFAULTS,
    "receiver_ieee": "02:00:00:00:00:00:00:01",
    "thermostat_ieee": THERMOSTAT,
}


def declaration(file, name, namespace, parent=None):
    """Use production declarations without importing HA's OS-specific runtime."""
    tree = ast.parse((COMPONENT / file).read_text(encoding="utf-8"))
    body = (
        tree.body
        if parent is None
        else next(n for n in tree.body if getattr(n, "name", None) == parent).body
    )
    node = next(n for n in body if getattr(n, "name", None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), file, "exec"), namespace)
    return namespace[name]


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator


class SensorEntity:
    pass


def sensor(coordinator):
    cls = declaration(
        "sensor.py",
        "HiveState",
        {
            "CoordinatorEntity": CoordinatorEntity,
            "SensorEntity": SensorEntity,
            "DeviceInfo": dict,
            "DOMAIN": DOMAIN,
        },
    )
    entry = SimpleNamespace(entry_id="heating", unique_id=INSTALLATION["receiver_ieee"])
    return cls(coordinator, entry)


@pytest.mark.parametrize(
    "cached",
    [
        None,
        {
            "mode": "boost",
            "current_temperature": 19.4,
            "target_temperature": 30,
            "heating": True,
            "remaining_minutes": 8,
            "read_at": "2026-11-04T12:00:00+00:00",
        },
    ],
)
def test_failed_poll_publishes_identity_without_cached_readings(cached):
    coordinator = SimpleNamespace(
        data=cached,
        last_update_success=False,
        options=INSTALLATION,
        controller=SimpleNamespace(zone=ZoneInfo("Europe/London")),
    )
    entity = sensor(coordinator)
    assert entity.native_value is None
    attributes = entity.extra_state_attributes
    assert attributes["hive_local_control"] and attributes["entry_id"] == "heating"
    assert attributes["reachable"] is False
    assert (
        not {"current_temperature", "target_temperature", "remaining_minutes", "read_at", "heating"}
        & attributes.keys()
    )

    coordinator.data = {
        "mode": "schedule",
        "current_temperature": 20,
        "target_temperature": 21,
        "read_at": "2026-11-05T12:00:00+00:00",
    }
    coordinator.last_update_success = True
    assert entity.native_value == "schedule"
    assert entity.extra_state_attributes["reachable"] is True
    assert entity.extra_state_attributes["current_temperature"] == 20


async def test_offline_startup_still_creates_sensor_and_installs_update_listener():
    coordinator = SimpleNamespace(
        async_refresh=AsyncMock(),
        async_config_entry_first_refresh=AsyncMock(),
        data=None,
        last_update_success=False,
        options=INSTALLATION,
        controller=SimpleNamespace(zone=ZoneInfo("Europe/London")),
    )
    entry = SimpleNamespace(
        data=INSTALLATION,
        options={},
        entry_id="heating",
        unique_id=INSTALLATION["receiver_ieee"],
        add_update_listener=Mock(return_value=Mock()),
        async_on_unload=Mock(),
    )
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        config=SimpleNamespace(time_zone="Europe/London"),
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    listener = Mock()
    setup = declaration(
        "__init__.py",
        "async_setup_entry",
        {
            "entry_options": entry_options,
            "HiveController": Mock(),
            "ZhaTransport": Mock(),
            "HiveCoordinator": Mock(return_value=coordinator),
            "DOMAIN": DOMAIN,
            "PLATFORMS": ["sensor"],
            "async_update_options": listener,
        },
    )
    assert await setup(hass, entry)
    coordinator.async_refresh.assert_awaited_once_with()
    coordinator.async_config_entry_first_refresh.assert_not_awaited()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(entry, ["sensor"])
    assert hass.data[DOMAIN]["heating"] is entry.runtime_data is coordinator
    entry.add_update_listener.assert_called_once_with(listener)
    assert sensor(entry.runtime_data).extra_state_attributes["reachable"] is False


class UpdateFailed(Exception):
    pass


@pytest.mark.parametrize(
    "failure",
    [TimeoutError(), ProtocolError("No response"), ZigbeeException("Delivery failed"), None],
)
async def test_poll_rejects_unreachable_receiver_or_wall_thermostat_then_recovers(failure):
    transport = SimpleNamespace(
        thermostat_available=Mock(return_value=failure is not None),
        cached_battery=Mock(return_value=86),
    )
    controller = SimpleNamespace(
        transport=transport,
        read_state=AsyncMock(return_value={"mode": "schedule"}, side_effect=failure),
    )
    coordinator = SimpleNamespace(controller=controller, options=INSTALLATION)
    update = declaration(
        "coordinator.py",
        "_async_update_data",
        {
            "ProtocolError": ProtocolError,
            "ZigbeeException": ZigbeeException,
            "UpdateFailed": UpdateFailed,
        },
        parent="HiveCoordinator",
    )
    with pytest.raises(UpdateFailed, match="Thermostat unreachable"):
        await update(coordinator)
    transport.cached_battery.assert_not_called()
    controller.read_state.side_effect = None
    transport.thermostat_available.return_value = True
    assert await update(coordinator) == {"mode": "schedule", "battery_percentage": 86}
    transport.thermostat_available.assert_called_with(THERMOSTAT)


@pytest.mark.parametrize(
    "device", [None, SimpleNamespace(available=False), SimpleNamespace(available=True)]
)
def test_wall_availability_uses_zha_without_sending_requests(monkeypatch, device):
    gateway = SimpleNamespace(get_device=Mock(return_value=device))
    helpers = ModuleType("homeassistant.components.zha.helpers")
    helpers.get_zha_gateway = Mock(return_value=gateway)
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)
    transport = ZhaTransport(None, INSTALLATION["receiver_ieee"])
    assert transport.thermostat_available(THERMOSTAT) is (device is not None and device.available)
    helpers.get_zha_gateway.assert_called_once_with(None)
    gateway.get_device.assert_called_once()
    gateway.get_device.return_value = SimpleNamespace(available=True)
    assert transport.thermostat_available(THERMOSTAT) is True
    assert gateway.get_device.call_count == 2


def test_zha_reload_is_unavailable_until_gateway_returns(monkeypatch):
    helpers = ModuleType("homeassistant.components.zha.helpers")
    helpers.get_zha_gateway = Mock(side_effect=ValueError("No gateway object exists"))
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)
    assert (
        ZhaTransport(None, INSTALLATION["receiver_ieee"]).thermostat_available(THERMOSTAT) is False
    )
