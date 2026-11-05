"""Persist card settings without interrupting receiver operations."""

from .const import DEFAULTS
from .protocol import temperature


def entry_options(entry):
    configured = {**entry.data, **entry.options}
    return {key: configured.get(key, default) for key, default in DEFAULTS.items()}


def save_boost_temperature(hass, entry, coordinator, value):
    target = temperature(value) / 100
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "boost_temperature": target}
    )
    coordinator.options = {**coordinator.options, "boost_temperature": target}
    # Notify entities without marking an offline receiver available or restarting its poll.
    coordinator.async_update_listeners()
    return {"temperature": target, "message": "Boost temperature saved."}


def migrate_legacy_settings(entry):
    """Upgrade the old 19°C default once; preserve other saved targets."""
    data, options = dict(entry.data), dict(entry.options)
    for settings in (data, options):
        if settings.get("boost_temperature") == 19:
            settings["boost_temperature"] = DEFAULTS["boost_temperature"]
    return data, options
