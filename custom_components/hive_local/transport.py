"""Small ZHA boundary; resolve devices afresh to survive ZHA reloads."""

from __future__ import annotations

import zigpy.types as t
from zigpy.exceptions import ZigbeeException
from zigpy.zcl import foundation

from .const import ENDPOINT, HOLIDAY_CLUSTER, MANUFACTURER, THERMOSTAT_CLUSTER, TIME_CLUSTER
from .protocol import HEATING_TYPES, HOLIDAY_TYPES, TIME_TYPES, ProtocolError


class TransportError(ProtocolError):
    """The receiver could not be reached or returned incomplete data."""


class ZhaTransport:
    def __init__(self, hass, receiver_ieee):
        self.hass = hass
        self.receiver_ieee = receiver_ieee

    def cluster(self, cluster_id):
        from homeassistant.components.zha.helpers import get_zha_gateway

        try:
            device = get_zha_gateway(self.hass).get_device(t.EUI64.convert(self.receiver_ieee))
            if device is None:
                raise TransportError("Receiver is not paired with ZHA")
            return device.device.endpoints[ENDPOINT].in_clusters[cluster_id]
        except (KeyError, ValueError, AttributeError) as exc:
            raise TransportError("ZHA receiver endpoint 5 is not available") from exc

    async def read(self, cluster_id, attributes):
        cluster = self.cluster(cluster_id)
        try:
            reply = await cluster.read_attributes_raw(
                list(attributes),
                manufacturer=MANUFACTURER if cluster_id == HOLIDAY_CLUSTER else None,
            )
        except (TimeoutError, ZigbeeException) as exc:
            raise TransportError("No attribute response from the receiver") from exc
        if hasattr(reply, "as_tuple"):
            reply = reply.as_tuple()
        if not isinstance(reply, (list, tuple)) or not reply:
            raise TransportError("Unexpected attribute response")
        records = reply[0]
        if not isinstance(records, (list, tuple)):
            raise TransportError("Receiver sent an acknowledgement instead of attribute values")
        result = {}
        for record in records:
            if record.status == foundation.Status.SUCCESS and record.value is not None:
                result[int(record.attrid)] = record.value.value
        return result

    async def write(self, cluster_id, attributes):
        """One global Write Attributes frame, with explicit discovered wire types."""
        types = {
            HOLIDAY_CLUSTER: HOLIDAY_TYPES,
            THERMOSTAT_CLUSTER: HEATING_TYPES,
            TIME_CLUSTER: TIME_TYPES,
        }[cluster_id]
        records = []
        for key, value in attributes.items():
            type_id = types[key]
            python_type = foundation.DataType.from_type_id(type_id).python_type
            records.append(
                foundation.Attribute(
                    attrid=key,
                    value=foundation.TypeValue(type=type_id, value=python_type(value)),
                )
            )
        return await self.cluster(cluster_id).write_attributes_raw(
            records,
            manufacturer_code=MANUFACTURER if cluster_id == HOLIDAY_CLUSTER else None,
            retries=0,
        )

    async def get_schedule(self, day):
        return await self.cluster(THERMOSTAT_CLUSTER).command(
            0x02,
            days_to_return=day,
            mode_to_return=1,
            manufacturer=None,
            retries=0,
        )

    async def set_schedule(self, day, values):
        return await self.cluster(THERMOSTAT_CLUSTER).command(
            0x01,
            num_transitions_for_sequence=len(values) // 2,
            day_of_week_for_sequence=day,
            mode_for_sequence=1,
            values=values,
            manufacturer=None,
            retries=0,
        )

    def cached_battery(self, ieee):
        """Never wake or poll the battery thermostat just for a dashboard."""
        from homeassistant.components.zha.helpers import get_zha_gateway

        try:
            device = get_zha_gateway(self.hass).get_device(t.EUI64.convert(ieee))
            value = device.device.endpoints[9].in_clusters[0x0001].get(0x0021)
        except (AttributeError, KeyError, ValueError):
            return None
        return value / 2 if value is not None and 0 <= value <= 200 else None

    def thermostat_available(self, ieee):
        """Use ZHA's sleepy-device availability instead of waking the thermostat."""
        from homeassistant.components.zha.helpers import get_zha_gateway

        try:
            device = get_zha_gateway(self.hass).get_device(t.EUI64.convert(ieee))
            return device is not None and bool(device.available)
        except (AttributeError, KeyError, ValueError):
            return False
