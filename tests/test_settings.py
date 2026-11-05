"""Persist boost defaults independently of device state and migrate old entries once."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.hive_local.const import DEFAULTS, DOMAIN
from custom_components.hive_local.protocol import ProtocolError
from custom_components.hive_local.settings import (
    entry_options,
    migrate_legacy_settings,
    save_boost_temperature,
)


def entry(**values):
    return SimpleNamespace(
        data={**DEFAULTS, **values}, options={}, entry_id="heating", version=1, minor_version=1
    )


def integration_function(name):
    # Exercise the actual config-entry callbacks without importing HA's OS-specific runtime.
    source = Path(__file__).parents[1] / "custom_components/hive_local/__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    namespace = {
        "DOMAIN": DOMAIN,
        "entry_options": entry_options,
        "migrate_legacy_settings": migrate_legacy_settings,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


def test_boost_setting_persists_across_new_coordinator_without_affecting_heating():
    configured = entry()
    coordinator = SimpleNamespace(
        options=entry_options(configured), async_update_listeners=Mock(), last_update_success=False
    )

    def update(entry, **changes):
        entry.__dict__.update(changes)

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=Mock(side_effect=update))
    )
    result = save_boost_temperature(hass, configured, coordinator, 28.5)
    assert result["temperature"] == 28.5
    assert (
        entry_options(configured)["boost_temperature"]
        == coordinator.options["boost_temperature"]
        == 28.5
    )
    assert coordinator.options["receiver_ieee"] == DEFAULTS["receiver_ieee"]
    assert coordinator.last_update_success is False
    coordinator.async_update_listeners.assert_called_once_with()


@pytest.mark.parametrize("target", [4, 33, 19.1, True, float("nan")])
def test_invalid_boost_setting_does_not_persist(target):
    hass, coordinator = Mock(), Mock()
    with pytest.raises(ProtocolError):
        save_boost_temperature(hass, entry(), coordinator, target)
    hass.config_entries.async_update_entry.assert_not_called()
    coordinator.async_update_listeners.assert_not_called()


async def test_only_device_or_name_changes_reload_the_integration():
    configured = entry()
    coordinator = SimpleNamespace(options=entry_options(configured), async_update_listeners=Mock())
    hass = SimpleNamespace(
        data={DOMAIN: {"heating": coordinator}},
        config_entries=SimpleNamespace(async_reload=AsyncMock()),
    )
    listener = integration_function("async_update_options")
    configured.options = {"boost_temperature": 27}
    await listener(hass, configured)
    assert coordinator.options["boost_temperature"] == 27
    hass.config_entries.async_reload.assert_not_awaited()
    configured.options["name"] = "Living room"
    await listener(hass, configured)
    hass.config_entries.async_reload.assert_awaited_once_with("heating")


async def test_old_default_migrates_once_but_later_manual_choice_survives():
    configured = entry(boost_temperature=19)
    configured.options = {"boost_temperature": 19, "boost_minutes": 25}

    def update(entry, **changes):
        entry.__dict__.update(changes)

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=Mock(side_effect=update))
    )
    migrate = integration_function("async_migrate_entry")
    assert await migrate(hass, configured)
    assert configured.minor_version == 2
    assert entry_options(configured)["boost_temperature"] == 30
    assert entry_options(configured)["boost_minutes"] == 25
    configured.options["boost_temperature"] = 19
    assert await migrate(hass, configured)
    assert entry_options(configured)["boost_temperature"] == 19
    assert hass.config_entries.async_update_entry.call_count == 1


def test_upgrade_keeps_custom_targets_and_new_entries_default_to_30():
    configured = entry(boost_temperature=21)
    configured.options = {"boost_temperature": 28}
    data, options = migrate_legacy_settings(configured)
    assert data["boost_temperature"] == 21 and options["boost_temperature"] == 28
    assert entry_options(SimpleNamespace(data={}, options={})) == {
        **DEFAULTS,
        "boost_temperature": 30,
    }
