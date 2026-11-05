"""UI setup for an already paired thermostat and receiver."""

from homeassistant import config_entries
from homeassistant.core import callback

from .const import DEFAULTS, DOMAIN, HOLIDAY_CLUSTER, THERMOSTAT_CLUSTER
from .protocol import ProtocolError, ieee_address, integer, temperature
from .schema import vol
from .transport import ZhaTransport


def form_schema(values, *, setup=False):
    def address_field(key):
        return vol.Required(key, **({"default": values[key]} if values.get(key) else {}))

    fields = {vol.Required("name", default=values["name"]): str}
    if setup:
        fields[address_field("receiver_ieee")] = str
    fields.update(
        {
            address_field("thermostat_ieee"): str,
            vol.Required("boost_minutes", default=values["boost_minutes"]): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=360)
            ),
            vol.Required("boost_temperature", default=values["boost_temperature"]): vol.All(
                vol.Coerce(float), vol.Range(min=5, max=32)
            ),
        }
    )
    return vol.Schema(fields)


def validate(values):
    values = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    values["receiver_ieee"] = ieee_address(values["receiver_ieee"])
    values["thermostat_ieee"] = ieee_address(values["thermostat_ieee"])
    if values["receiver_ieee"] == values["thermostat_ieee"]:
        raise ProtocolError("Receiver and thermostat must be different devices")
    values["name"] = values["name"].strip()
    if not values["name"]:
        raise ProtocolError("Enter a name")
    integer(values["boost_minutes"], 1, 360, "Boost duration")
    temperature(values["boost_temperature"])
    return values


class HiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                values = validate({**DEFAULTS, **user_input})
            except ProtocolError:
                errors["base"] = "invalid_settings"
            else:
                await self.async_set_unique_id(values["receiver_ieee"])
                self._abort_if_unique_id_configured()
                try:
                    transport = ZhaTransport(self.hass, values["receiver_ieee"])
                    transport.cluster(THERMOSTAT_CLUSTER)
                    transport.cluster(HOLIDAY_CLUSTER)
                except ProtocolError:
                    errors["base"] = "receiver_not_found"
                else:
                    return self.async_create_entry(title=values["name"], data=values)
        return self.async_show_form(
            step_id="user",
            data_schema=form_schema({**DEFAULTS, **(user_input or {})}, setup=True),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HiveOptionsFlow()


class HiveOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        current = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            try:
                values = validate({**current, **user_input})
            except ProtocolError:
                errors["base"] = "invalid_settings"
            else:
                return self.async_create_entry(title="", data=values)
        return self.async_show_form(
            step_id="init",
            data_schema=form_schema({**current, **(user_input or {})}),
            errors=errors,
        )
