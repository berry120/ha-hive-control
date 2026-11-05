"""Poll only the mains-powered receiver; the schedule remains on Hive."""

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from zigpy.exceptions import ZigbeeException

from .const import DOMAIN
from .protocol import ProtocolError

_LOGGER = logging.getLogger(__name__)


class HiveCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, controller, options):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=30),
        )
        self.controller = controller
        self.options = options

    async def _async_update_data(self):
        try:
            state = await self.controller.read_state()
            if not self.controller.transport.thermostat_available(self.options["thermostat_ieee"]):
                raise ProtocolError("Wall thermostat is unavailable in ZHA")
        except (ProtocolError, TimeoutError, ZigbeeException) as exc:
            raise UpdateFailed(f"Thermostat unreachable: {str(exc) or 'no response'}") from exc
        state["battery_percentage"] = self.controller.transport.cached_battery(
            self.options["thermostat_ieee"]
        )
        return state
