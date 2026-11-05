# Hive Local Control

A compact Home Assistant dashboard card for the **Hive SLT3b thermostat + SLR1c receiver**, using your existing **ZHA** network. The card shows room temperature, the target and a quick heat-boost button. Click the temperature to open heating controls, a grouped weekly schedule, holiday settings and clock controls.

One custom integration includes both the backend and the card. No ZHA Toolkit, MQTT, cloud account, helper entities, separate card plugins or frontend build is required. The schedule and native boost run on Hive itself.

## Before installing

You need Home Assistant with **ZHA**, a **Hive SLT3b wall thermostat** and an **SLR1c receiver**. Pair both devices with ZHA and with each other before installing this control. Confirm that both appear in ZHA and that changing the temperature on the wall thermostat controls the receiver. Installing this integration does not pair or bind the devices for you.

The [protocol reference](hive_zigbee_protocol_reference.md#3-pairing-and-network-recovery) describes the receiver-first pairing procedure observed with this combination. Other Hive models have not been validated.

### Find your device addresses

1. Open the ZHA device list. In current Home Assistant versions, use **Settings → Connectivity → Zigbee**; in earlier versions, use **Settings → Devices & services → ZHA**.
2. Open the **SLR1c receiver**, then find its **IEEE address** under **Device info**. Copy all eight hexadecimal pairs, including their colons.
3. Repeat for the **SLT3b wall thermostat**. Keep the two addresses labelled so you can enter each in the correct field during setup.

Use each device's IEEE address, not its short network address, Home Assistant device/entity ID or the coordinator's address. Home Assistant's [ZHA documentation](https://www.home-assistant.io/integrations/zha/#modifying-the-device-type) describes where to find the IEEE address. No device addresses are supplied by default; preview and test addresses are fictional.

## Install

1. Download and extract [dist/hive-local-control.zip](dist/hive-local-control.zip) on your computer.
2. Copy the entire `custom_components/hive_local` folder to your Home Assistant configuration directory, producing `/config/custom_components/hive_local/manifest.json`. If `custom_components` already exists, merge into it; preserve its other integrations.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration**, search for **Hive Local Control**, and enter your receiver and thermostat IEEE addresses.
5. Refresh your browser. Edit the dashboard, choose **Add card**, then search for **Hive Local Control**. Select its heating sensor if needed, save, and drag the card into place. It supports Sections sizing as well as Masonry dashboards.

The card module registers automatically. No `configuration.yaml` edits or separate dashboard resource registration should be necessary. On an automatically managed dashboard, first take control of the dashboard or create one you can edit.

The integration options change the wall thermostat address, name and default boost duration/target. Holiday creation and manual hold are always available. The receiver address is chosen at setup and identifies the installation; remove and re-add this integration to change that address. This does not remove the devices from ZHA. Multiple receivers can have separate integration entries and cards.

To upgrade, replace the `hive_local` folder with this version, restart Home Assistant and refresh the browser. Keep your existing integration entry and dashboard card. Upgrading from a version earlier than 0.3.0 changes the old 19°C boost default to 30°C once; other saved integration targets are preserved. You can choose any supported boost temperature afterwards, including 19°C.

The default boost is **10 minutes at 30°C**. Choose the duration on the Heating tab; change the saved boost temperature in the control's **Settings** tab. This setting applies to future boosts from every card for that installation and survives restarts. The visual card editor can override the quick-boost duration. Legacy per-card `boost_temperature` overrides are ignored so Settings remains the source of the boost target.

The card places **Current** and **Target** to the right of their values, using the same small font for both labels. The Heating tab shows the current temperature, then heat boost, then **Turn off**, **Use schedule** and **Use manual**. Only manual mode has a target input there; schedule changes belong on the Schedule tab. Boost uses Hive's normal temperature regulation at its saved target.

One **refresh icon** sits beside the close button in the dialog header. It refreshes the active tab: heating readings, the week, holiday settings or the clock difference. Unsaved schedule edits must be saved or discarded first. Refreshing preserves unfinished heating, holiday and Settings inputs when the corresponding form remains available.

If using a YAML dashboard, the card is simply:

```yaml
type: custom:hive-local-card
entity: sensor.heating  # Select the sensor created by this integration; its ID may differ.
# name: Living room
# boost_minutes: 30
```

## Controls and limits

| Control | Included behaviour |
|---|---|
| Temperature / heating state | Fresh receiver readings every 30 seconds; unavailable readings are not displayed as current |
| Unreachable thermostat | Shows **Thermostat unreachable**, hides current/target readings and the boost countdown, disables heating actions and recovers automatically |
| Heat boost | One combined native boost command; repeated clicks are blocked while pending |
| End boost / Use schedule | One combined command returning to the onboard schedule; does not restore a previous Manual or Off mode |
| Turn off | Selects Off using one combined command |
| Use manual | Holds the manual temperature until you choose another mode |
| Weekly schedule | Groups identical days into shared patterns; create a new pattern for any days, copy existing times, and add or remove periods |
| Holiday settings | Shows dates only for an enabled holiday, with one away-temperature input and a cancellation control |
| Create holiday | Available when no holiday is enabled; saves and verifies a future interval and away temperature, then enables it |
| Boost temperature | Saves the target for future boosts without changing the current heating state |
| Clock difference | Refreshes on opening Settings; shows how far the thermostat is ahead of or behind Home Assistant |
| Set a manual date and time | Sets the chosen date/time using the adjacent Set button; Sync with Home Assistant synchronizes automatically |

## Edit shared schedules

The Schedule tab reads all seven days and groups days whose complete transition lists match. Common groups are labelled **Weekdays**, **Weekend** or **Every day**; other combinations list their days. A timeline and heating-period summary make the different patterns easy to compare. The striped part before the first change depends on the preceding day's schedule.

1. Click an existing pattern to edit it, or **New pattern** to create a separate schedule.
2. Choose which days should receive that pattern using the day buttons, or **Weekdays**, **Weekend** and **Every day** shortcuts. You can select just one day to give it its own schedule.
3. For a new pattern, **Start with** a blank all-day-Off schedule or copy the times from an existing pattern. No days are selected automatically.
4. Edit the times and temperatures, including Off periods. **Add period** and the remove icons let you use between one and six periods. Enter times in increasing order, then save.

For example, choose **New pattern → Sunday → Copy Weekend**, change Sunday's times and save. Sunday then appears separately, while Saturday and the weekdays keep their schedules. To create a new block of days, select several days instead. Saving moves only those days into the new pattern; days with identical times and temperatures automatically appear together, so duplicate patterns are merged.

Saving replaces the full schedule on the selected days. Every selected day is checked against a fresh read before any write; each is then saved and read back individually. No combined Zigbee day-mask writes are used. A partial save identifies confirmed days and stops before sending later days. Choose **Discard changes**, then use the header refresh icon before editing again. Days that could not be read are shown separately and cannot be selected. Incoming temperature updates preserve an open schedule draft.

## Holiday and clock settings

An enabled holiday may be in the future; the card does not claim it is currently active. Cancel it before planning another: both the form and the backend enforce this. Disabled holidays do not display their old dates. Holiday dates use Home Assistant's configured time zone as local wall-clock fields. Ambiguous/nonexistent clock-change times and intervals crossing daylight-saving changes are rejected. Holiday intervals are limited to one year. The 5–32°C input bounds are application bounds; heating commands also respect the receiver's reported target limits.

Opening Settings automatically reads the receiver clock and calculates its difference from Home Assistant's server clock. The difference is **green up to and including 2 minutes**, **yellow above 2 and up to 5 minutes**, and **red over 5 minutes**, whether ahead or behind. Failed reads show an unavailable status. There is no static clock display or Get time button.

**Sync with Home Assistant** synchronizes the clock. **Set a manual date and time** offers a compact input with **Set** beside it; input uses Home Assistant's configured time zone, independent of the browser's time zone. The action writes only the receiver's UTC Time attribute and preserves its existing timezone, daylight-saving and time-server flags. It uses seconds since 1 January 2000, following the [Zigbee Time cluster specification](https://zigbeealliance.org/wp-content/uploads/2021/10/07-5123-08-Zigbee-Cluster-Library.pdf). A receiver that rejects a clock write or fails readback produces an error and clears the previous difference.

The compact card stays quiet after successful operations and retains errors or unconfirmed outcomes. Receiver readback confirms stored attributes; it does not prove physical boiler operation. State is not optimistically changed after clicking a control. Other ZHA entities may still show generic modes; this card uses Hive's mode/hold/duration combination.

## When the thermostat is unreachable

The card shows **Thermostat unreachable** with dashes for the current and target temperatures. It does not display cached readings, a stale boost countdown or a heating indicator. The dialog also shows the connection status; heating buttons are disabled while the header refresh remains available. Fresh readings restore the controls automatically and preserve any manual-temperature draft.

The integration creates its sensor even if the first read fails, so an offline start does not become a missing-sensor configuration error. Failed receiver polls clear published readings. Wall-thermostat availability follows [ZHA's device availability](https://github.com/zigpy/zha/blob/2.3.1/zha/zigbee/device.py), including its timeout for battery devices; this control does not wake the wall thermostat to probe it. A lost Home Assistant connection, restored sensor state or a temporarily missing configured sensor also hides live readings.

## Troubleshooting

- **Integration not listed:** confirm the folder is not nested one level too deep, restart HA and hard-refresh the browser.
- **Card not listed:** finish integration setup, then reload the dashboard. As a fallback, add `/hive_local/hive-local-card.js?v=0.5.0` as a JavaScript module in Dashboard resources. Do not add it more than once.
- **Thermostat unreachable:** check receiver power, thermostat batteries, the configured IEEE addresses and availability of both devices in ZHA. The integration keeps polling after failed startup or later reads. Use the dialog's header refresh to retry; returning readings restore the card automatically. See the supplied protocol reference for the receiver-first pairing procedure; the integration never resets, re-pairs, binds or changes reporting automatically.
- **Schedule write timed out:** the integration reads the day back before deciding whether it persisted. An unknown outcome or mismatch is shown as an error. Reload the week before retrying; do not repeatedly press Save.
- **A stale edit was refused:** someone or something changed a selected day after it was loaded. Discard the draft, reload the week and reapply your edit.
- **Only some days were saved:** the message lists confirmed saves and where the operation stopped. Use **Discard changes**, then the header refresh icon to inspect the actual week before applying the remaining changes.
- **Holiday create failed:** cancel an enabled holiday before creating another. A failed creation may leave some new fields written; reload the holiday and inspect the thermostat before retrying.
- **ZHA was reloaded:** device references are resolved for every request, so the next successful receiver poll should recover automatically.

## Actions and automations

All controls are also available as `hive_local.*` actions in Developer Tools. Choose the installation using the provided selector. Every action supports response data; `read_schedule` returns `day`, `transitions`, `revision` and `read_at`.

```yaml
action: hive_local.boost
data:
  entry_id: YOUR_HIVE_CONFIG_ENTRY_ID
  minutes: 10
response_variable: boost_result
```

The config entry ID is also an attribute of the integration's heating sensor. `set_schedule` requires the revision returned by `read_schedule`, a single day mask, and the complete list of transitions. `read_week` returns individual day snapshots and any read failures; `set_schedule_group` accepts `days`, a full `transitions` list, and a `revisions` map keyed by each selected day mask as a string. Use `temperature: null` for Off. The integration serializes its own operations per receiver; it cannot lock out changes made at the physical thermostat or through another integration between its pre-write read and write. Multi-day writes are not atomic, and a response with `complete: false` reports a partial result.

Omitting `temperature` in a boost action uses the saved boost target. `set_boost_temperature` saves a new default; explicitly supplying `temperature` on a boost action overrides it for that action only. `set_target` remains available for automations that deliberately change the target in the current mode.

`read_time` returns the receiver's clock, the HA `server_time` and signed `clock_delta_seconds` (positive means the device is ahead). `set_time` accepts an optional `time: "2030-11-10T12:34:56"` in Home Assistant's time zone; omit `time` to use the HA server's current time.

## Development and validation

The backend uses the ZHA gateway helper and zigpy's public raw attribute APIs. Home Assistant **2026.10.4** source was used for API compatibility checks; protocol and wire-format tests use **zigpy 2.3.0**, matching the investigation. This package has **not been installed in a live Home Assistant instance or tested against the physical devices** during this implementation. See [validation notes](docs/VALIDATION.md) for exact coverage and the remaining live checks.

Use Python **3.14**, Node.js **24**, npm and Git. Create a virtual environment and activate it (`source .venv/bin/activate` on Linux/macOS, or `.\.venv\Scripts\Activate.ps1` in PowerShell):

```sh
python -m venv .venv
```

With the environment activated:

```sh
python -m pip install -r requirements-dev.txt
npm ci
npx playwright-core install chromium
python -m ruff check custom_components tests scripts
python -m ruff format --check custom_components tests scripts
node --check custom_components/hive_local/frontend/hive-local-card.js
node --check preview/demo.js
python -m pytest -q
npm test
python scripts/build.py
node scripts/check_preview.mjs
```

Browser tests prefer the Chromium installed by Playwright, then an installed Chrome/Edge/Chromium executable. Set `BROWSER_PATH` to choose another executable. On Linux, use `npx playwright-core install --with-deps chromium` to install the required system libraries too. No Node dependencies are included in the installation archive.

The build overwrites **`dist/hive-local-control.zip`** and **`dist/preview.html`**. These are the only distribution files tracked in Git; there are no versioned ZIP copies. ZIP entries have stable ordering, timestamps and line endings so an unchanged build does not create another binary diff.

Open [dist/preview.html](dist/preview.html) directly in a browser for an interactive simulated preview. For development, run `python -m http.server 8765 --bind 127.0.0.1` in this folder and open `http://127.0.0.1:8765/preview/`. Preview actions use fictional devices and never connect to your heating.

## GitHub Actions

The workflows are separated by trigger:

- [Pull request checks](.github/workflows/pull-request.yml) runs on **every pull request**, with read-only repository permissions.
- [Main tests and distribution](.github/workflows/push-main.yml) runs on **every push to `main`**, then updates the distribution after the checks pass. It can also be run manually.

Both run Python lint, JavaScript syntax checks, every Python and browser test, the build, and the standalone-preview check. Each successful run also makes its tested ZIP and preview available as a workflow artifact.

After a successful run on `main`, a separate job commits the tested **`dist/hive-local-control.zip`** and **`dist/preview.html`** back to `main` if they changed. It skips outdated builds when newer commits arrive and never force-pushes. Commits made with GitHub's built-in `GITHUB_TOKEN` [do not start another push workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow), so the update does not loop. You can also run the workflow manually on `main`.

Enable GitHub Actions for your repository and allow the publishing job's **`contents: write`** permission. If repository or organization rules restrict token permissions, adjust them in **Settings → Actions → General → Workflow permissions**. Branch protection/rulesets must also allow the bot's distribution commit to `main`; otherwise tests still run, but the publishing job reports that it cannot push. No personal access token or repository secrets are required.

Implementation references: [Home Assistant custom cards](https://contributors.home-assistant.io/frontend/custom-ui/card/), [ZHA gateway access](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/components/zha/helpers.py), [frontend module registration](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/components/frontend/__init__.py), [zigpy Thermostat schemas](https://github.com/zigpy/zigpy/blob/dev/zigpy/zcl/clusters/hvac.py), and the supplied [protocol investigation](hive_zigbee_protocol_reference.md).

