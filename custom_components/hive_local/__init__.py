"""Self-contained Hive controls over the existing ZHA network."""

from pathlib import Path

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from zigpy.exceptions import ZigbeeException

from .const import CARD_URL, DOMAIN, VERSION
from .controller import HiveController
from .coordinator import HiveCoordinator
from .protocol import ProtocolError
from .schema import vol
from .settings import entry_options, migrate_legacy_settings, save_boost_temperature
from .transport import ZhaTransport

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_FIELDS = {
    "boost": {vol.Optional("minutes"): int, vol.Optional("temperature"): vol.Any(int, float)},
    "resume_schedule": {},
    "off": {},
    "set_target": {vol.Required("temperature"): vol.Any(int, float)},
    "manual": {vol.Required("temperature"): vol.Any(int, float)},
    "read_schedule": {vol.Required("day"): int},
    "read_week": {},
    "set_schedule_group": {
        vol.Required("days"): list,
        vol.Required("transitions"): list,
        vol.Required("revisions"): dict,
    },
    "set_schedule": {
        vol.Required("day"): int,
        vol.Required("transitions"): list,
        vol.Required("revision"): str,
    },
    "read_holiday": {},
    "set_holiday_temperature": {vol.Required("temperature"): vol.Any(int, float)},
    "cancel_holiday": {},
    "create_holiday": {
        vol.Required("start"): str,
        vol.Required("end"): str,
        vol.Required("temperature"): vol.Any(int, float),
    },
    "refresh": {},
    "read_time": {},
    "set_time": {vol.Optional("time"): str},
    "set_boost_temperature": {vol.Required("temperature"): vol.Any(int, float)},
}


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL, str(Path(__file__).parent / "frontend" / "hive-local-card.js"), False
            )
        ]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")

    async def handle(call):
        entry_id = call.data["entry_id"]
        coordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                "Hive integration is not loaded. Check Settings → Devices & services."
            )
        if call.context.user_id:
            user = await hass.auth.async_get_user(call.context.user_id)
            entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, entry_id)
            if (
                user is None
                or not entity_id
                or not user.permissions.check_entity(entity_id, POLICY_CONTROL)
            ):
                raise Unauthorized()
        if call.service == "refresh":
            await coordinator.async_refresh()
            if not coordinator.last_update_success:
                raise HomeAssistantError(
                    "Thermostat unreachable. Check its power and Zigbee connection."
                )
            return {"message": "Receiver state refreshed.", **coordinator.data}
        if call.service == "set_boost_temperature":
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                raise ServiceValidationError("Hive installation no longer exists")
            try:
                return save_boost_temperature(hass, entry, coordinator, call.data["temperature"])
            except ProtocolError as exc:
                raise ServiceValidationError(str(exc)) from exc
        data = {
            "minutes": coordinator.options["boost_minutes"],
            "temperature": coordinator.options["boost_temperature"],
            **call.data,
        }
        try:
            result = await coordinator.controller.execute(call.service, data)
        except (ProtocolError, TimeoutError, ZigbeeException) as exc:
            # Refresh after partial failures too; never leave optimistic UI state behind.
            await coordinator.async_request_refresh()
            raise HomeAssistantError(str(exc) or "Receiver did not respond") from exc
        if call.service not in ("read_schedule", "read_week", "read_holiday", "read_time"):
            await coordinator.async_request_refresh()
        return result

    for service, fields in SERVICE_FIELDS.items():
        hass.services.async_register(
            DOMAIN,
            service,
            handle,
            schema=vol.Schema({vol.Required("entry_id"): str, **fields}),
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def async_setup_entry(hass, entry):
    options = entry_options(entry)
    controller = HiveController(
        ZhaTransport(hass, options["receiver_ieee"]),
        timezone=hass.config.time_zone,
    )
    coordinator = HiveCoordinator(hass, entry, controller, options)
    # Create the sensor even while offline. Its coordinator keeps retrying every 30s;
    # first_refresh would defer entity setup and leave the card without a sensor.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass, entry):
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    options = entry_options(entry)
    if coordinator is not None and all(
        options[key] == coordinator.options[key]
        for key in ("name", "receiver_ieee", "thermostat_ieee")
    ):
        if coordinator.options != options:
            coordinator.options = options
            coordinator.async_update_listeners()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass, entry):
    if entry.version != 1:
        return False
    if entry.minor_version < 2:
        data, options = migrate_legacy_settings(entry)
        hass.config_entries.async_update_entry(entry, data=data, options=options, minor_version=2)
    return True


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
