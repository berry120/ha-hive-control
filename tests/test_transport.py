from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from zigpy.zcl import Cluster, foundation
from zigpy.zcl.clusters.general import Time
from zigpy.zcl.clusters.hvac import Thermostat

from custom_components.hive_local.const import HOLIDAY_CLUSTER, THERMOSTAT_CLUSTER, TIME_CLUSTER
from custom_components.hive_local.transport import TransportError, ZhaTransport


def transport_with_cluster(cluster):
    transport = ZhaTransport(None, "02:00:00:00:00:00:00:01")
    transport.cluster = Mock(return_value=cluster)
    return transport


async def test_real_zigpy_write_schema_emits_one_typed_combined_request():
    # Exercise zigpy's global-command serializer, not a copy of our serializer.
    endpoint = Mock()
    endpoint.device.get_sequence.return_value = 42
    endpoint.request = AsyncMock(return_value=[])
    cluster = Thermostat(endpoint, is_server=True)
    transport = transport_with_cluster(cluster)
    await transport.write(THERMOSTAT_CLUSTER, {0x1C: 5, 0x24: 10, 0x23: 1, 0x12: 1900})
    assert endpoint.request.await_count == 1
    assert endpoint.request.call_args.kwargs["retries"] == 0
    data = endpoint.request.call_args.kwargs["data"]
    header, payload = foundation.ZCLHeader.deserialize(data)
    assert header.frame_control.is_general and header.manufacturer is None
    assert header.command_id == foundation.GeneralCommand.Write_Attributes
    assert payload == bytes.fromhex("1c0030052400210a00230030011200296c07")


async def test_manufacturer_header_and_holiday_wire_types():
    endpoint = Mock()
    endpoint.device.get_sequence.return_value = 42
    endpoint.request = AsyncMock(return_value=[])
    cluster = Cluster(endpoint, is_server=True)
    cluster.cluster_id = HOLIDAY_CLUSTER
    transport = transport_with_cluster(cluster)
    await transport.write(HOLIDAY_CLUSTER, {0x22: "20300110", 0x23: 1350, 0x26: 700, 0x20: 0})
    assert endpoint.request.call_args.kwargs["retries"] == 0
    header, payload = foundation.ZCLHeader.deserialize(endpoint.request.call_args.kwargs["data"])
    assert header.manufacturer == 4153
    assert payload == bytes.fromhex("2200420832303330303131302300214605260029bc0220003000")


async def test_get_schedule_uses_cluster_command_not_global_write():
    endpoint = Mock()
    endpoint.device.get_sequence.return_value = 42
    endpoint.request = AsyncMock(return_value=[])
    transport = transport_with_cluster(Thermostat(endpoint, is_server=True))
    await transport.get_schedule(2)
    header, payload = foundation.ZCLHeader.deserialize(endpoint.request.call_args.kwargs["data"])
    assert header.frame_control.is_cluster and header.command_id == 2
    assert header.manufacturer is None and payload == bytes.fromhex("0201")
    values = [390, 1800, 510, 100, 720, 100, 840, 100, 1020, 1750, 1200, 100]
    await transport.set_schedule(2, values)
    assert endpoint.request.call_args.kwargs["retries"] == 0
    header, payload = foundation.ZCLHeader.deserialize(endpoint.request.call_args.kwargs["data"])
    assert header.frame_control.is_cluster and header.command_id == 1
    assert payload.startswith(bytes.fromhex("060201"))
    assert bytes.fromhex("fc03d606") in payload


async def test_read_raw_handles_modern_schema_and_missing_attributes():
    records = [
        foundation.ReadAttributeRecord(
            attrid=0x26,
            status=foundation.Status.SUCCESS,
            value=foundation.TypeValue(type=0x29, value=700),
        ),
        foundation.ReadAttributeRecord(attrid=0x21, status=foundation.Status.UNSUPPORTED_ATTRIBUTE),
    ]
    schema = foundation.GENERAL_COMMANDS[foundation.GeneralCommand.Read_Attributes_rsp].schema
    cluster = SimpleNamespace(read_attributes_raw=AsyncMock(return_value=schema(records)))
    transport = transport_with_cluster(cluster)
    assert await transport.read(HOLIDAY_CLUSTER, [0x26, 0x21]) == {0x26: 700}
    cluster.read_attributes_raw.assert_awaited_once_with([0x26, 0x21], manufacturer=4153)


async def test_read_rejects_default_ack():
    cluster = SimpleNamespace(read_attributes_raw=AsyncMock(return_value=[0, 0]))
    with pytest.raises(TransportError):
        await transport_with_cluster(cluster).read(HOLIDAY_CLUSTER, [0x26])


async def test_clock_uses_utc_wire_type_without_changing_zone_or_dst():
    endpoint = Mock()
    endpoint.device.get_sequence.return_value = 42
    endpoint.request = AsyncMock(return_value=[])
    transport = transport_with_cluster(Time(endpoint, is_server=True))
    await transport.write(TIME_CLUSTER, {0: 846973369})
    header, payload = foundation.ZCLHeader.deserialize(endpoint.request.call_args.kwargs["data"])
    assert header.command_id == foundation.GeneralCommand.Write_Attributes
    assert header.manufacturer is None
    assert payload == bytes.fromhex("0000e2") + (846973369).to_bytes(4, "little")
    assert endpoint.request.await_count == 1
    assert endpoint.request.call_args.kwargs["retries"] == 0
