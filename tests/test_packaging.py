"""Check the service/UI schema contract using HA's current schema library."""

import ast
import json
from pathlib import Path

import probatio as vol
import pytest
import yaml

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "hive_local"


def service_fields():
    # Load the actual declaration without substituting a fake HA runtime.
    tree = ast.parse((COMPONENT / "__init__.py").read_text(encoding="utf-8"))
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SERVICE_FIELDS" for t in n.targets)
    )
    return eval(compile(ast.Expression(node.value), "service schema", "eval"), {"vol": vol})


def test_services_have_matching_ui_metadata_and_required_fields():
    fields = service_fields()
    metadata = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    assert set(fields) == set(metadata)
    for service, declaration in fields.items():
        assert {"entry_id", *map(str, declaration)} == set(metadata[service]["fields"])
        schema = vol.Schema({vol.Required("entry_id"): str, **declaration})
        with pytest.raises(vol.Invalid):
            schema({"receiver_ieee": "02:00:00:00:00:00:00:01"})
    assert metadata["boost"]["fields"]["temperature"]["selector"]["number"]["step"] == 0.5
    assert (
        metadata["set_holiday_temperature"]["fields"]["temperature"]["selector"]["number"]["step"]
        == 1
    )


def test_card_payloads_validate_with_current_ha_schema():
    fields = service_fields()
    payloads = {
        "boost": {"minutes": 10},
        "set_boost_temperature": {"temperature": 30},
        "resume_schedule": {},
        "off": {},
        "set_target": {"temperature": 18.5},
        "read_schedule": {"day": 2},
        "read_week": {},
        "set_schedule_group": {
            "days": [2, 4],
            "revisions": {"2": "1" * 64, "4": "2" * 64},
            "transitions": [{"time": "08:30", "temperature": None}],
        },
        "read_time": {},
        "set_time": {"time": "2030-11-10T12:34:56"},
        "set_schedule": {
            "day": 2,
            "revision": "1" * 64,
            "transitions": [{"time": "08:30", "temperature": None}],
        },
        "create_holiday": {
            "start": "2030-11-10T22:30",
            "end": "2030-12-17T09:13",
            "temperature": 7,
        },
    }
    for service, values in payloads.items():
        schema = vol.Schema({vol.Required("entry_id"): str, **fields[service]})
        data = {"entry_id": "example", **values}
        assert schema(data) == data
        with pytest.raises(vol.Invalid):
            schema({**data, "arbitrary_attribute": 0x9543})


def test_config_form_defaults_validate_and_translate():
    tree = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "form_schema"
    )
    namespace = {"vol": vol}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "config form", "exec"), namespace)
    from custom_components.hive_local.const import DEFAULTS

    schema = namespace["form_schema"](DEFAULTS, setup=True)
    with pytest.raises(vol.Invalid):
        schema({})
    addresses = {
        "receiver_ieee": "02:00:00:00:00:00:00:01",
        "thermostat_ieee": "02:00:00:00:00:00:00:02",
    }
    assert schema(addresses) == {**DEFAULTS, **addresses}
    assert DEFAULTS["receiver_ieee"] == DEFAULTS["thermostat_ieee"] == ""
    translations = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert set(map(str, schema.schema)) == set(translations["config"]["step"]["user"]["data"])
    assert (COMPONENT / "translations" / "en.json").read_bytes() == (
        COMPONENT / "strings.json"
    ).read_bytes()


def test_config_requires_distinct_addresses_and_keeps_saved_installations():
    from types import SimpleNamespace

    from custom_components.hive_local.const import DEFAULTS
    from custom_components.hive_local.protocol import (
        ProtocolError,
        ieee_address,
        integer,
        temperature,
    )
    from custom_components.hive_local.settings import entry_options

    tree = ast.parse((COMPONENT / "config_flow.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validate")
    namespace = {
        "DEFAULTS": DEFAULTS,
        "ProtocolError": ProtocolError,
        "ieee_address": ieee_address,
        "integer": integer,
        "temperature": temperature,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "config validation", "exec"), namespace)
    validate = namespace["validate"]
    with pytest.raises(ProtocolError):
        validate({})
    with pytest.raises(ProtocolError):
        validate(
            {"receiver_ieee": "RECEIVER_IEEE_ADDRESS", "thermostat_ieee": "THERMOSTAT_IEEE_ADDRESS"}
        )
    with pytest.raises(ProtocolError, match="different"):
        validate(
            {
                "receiver_ieee": "02:00:00:00:00:00:00:01",
                "thermostat_ieee": "02:00:00:00:00:00:00:01",
            }
        )
    saved = validate(
        {"receiver_ieee": "02:00:00:00:00:00:00:01", "thermostat_ieee": "02:00:00:00:00:00:00:02"}
    )
    assert entry_options(SimpleNamespace(data=saved, options={})) == saved
