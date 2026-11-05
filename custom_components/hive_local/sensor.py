"""One state entity carries the compact card's current receiver observation."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([HiveState(entry.runtime_data, entry)])


class HiveState(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=coordinator.options["name"],
            manufacturer="Computime",
            model="Hive SLR1c + SLT3b",
        )

    @property
    def native_value(self):
        if not self.coordinator.last_update_success:
            return None
        return (self.coordinator.data or {}).get("mode")

    @property
    def extra_state_attributes(self):
        # HA may retain coordinator.data after a failed poll. Never publish it as
        # current, and handle the first failed poll before any data exists.
        state = (self.coordinator.data or {}) if self.coordinator.last_update_success else {}
        return {
            **state,
            "hive_local_control": True,
            "reachable": self.coordinator.last_update_success and bool(state),
            "entry_id": self.entry.entry_id,
            **self.coordinator.options,
            "timezone": str(self.coordinator.controller.zone),
        }
