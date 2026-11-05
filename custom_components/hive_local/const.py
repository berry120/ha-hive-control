"""Constants for supported Hive SLT3b / SLR1c installations."""

DOMAIN = "hive_local"
NAME = "Hive Local Control"
VERSION = "0.5.0"
ENDPOINT = 5
THERMOSTAT_ENDPOINT = 9
THERMOSTAT_CLUSTER = 0x0201
HOLIDAY_CLUSTER = 0xFD00
TIME_CLUSTER = 0x000A
MANUFACTURER = 4153
CARD_URL = "/hive_local/hive-local-card.js"
DEFAULTS = {
    "name": "Heating",
    "receiver_ieee": "",
    "thermostat_ieee": "",
    "boost_minutes": 10,
    "boost_temperature": 30.0,
}
