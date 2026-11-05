import test, { before, after, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve, extname } from "node:path";
import { launchBrowser } from "../scripts/browser.mjs";

let browser, server, base, page;
before(async () => {
  const root = resolve(".");
  server = createServer(async (req, res) => {
    const name = new URL(req.url, "http://localhost").pathname;
    const path = resolve(root, `.${decodeURIComponent(name)}`);
    if (!path.startsWith(root + "/") && !path.startsWith(root + "\\")) { res.writeHead(403).end(); return; }
    try {
      const file = await readFile(path);
      res.setHeader("Content-Type", { ".html": "text/html", ".js": "text/javascript" }[extname(path)] || "text/plain");
      res.end(file);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await launchBrowser();
  await mkdir("artifacts", { recursive: true });
});
after(async () => { await browser?.close(); await new Promise((resolve) => server?.close(resolve)); });
beforeEach(async () => {
  page = await browser.newPage({ viewport: { width: 1000, height: 850 } });
  await page.goto(`${base}/preview/index.html`);
  await page.locator("hive-local-card .open").waitFor();
});
afterEach(async () => { await page.close(); });
const open = () => page.locator("hive-local-card .open").click();
const tab = (name) => page.getByRole("tab", { name, exact: true }).click();
const requests = () => page.evaluate(() => window.calls);
const editWeekdays = async () => { await open(); await tab("Schedule"); await page.getByRole("button", { name: "Edit Weekdays", exact: true }).click(); };

test("quick boost uses the configured receiver and ends to schedule", async () => {
  await page.getByRole("button", { name: "Heat boost", exact: true }).click();
  await page.getByRole("button", { name: "End boost", exact: true }).waitFor();
  assert.deepEqual((await requests())[0], { type: "call_service", domain: "hive_local", service: "boost", service_data: { entry_id: "demo-entry", minutes: 10 }, return_response: true });
  assert.equal(await page.evaluate(() => window.demoHass.states["sensor.heating"].attributes.target_temperature), 30);
  assert.equal(await page.locator("hive-local-card .card-message").count(), 0);
  await page.getByRole("button", { name: "End boost", exact: true }).click();
  assert.equal((await requests())[1].service, "resume_schedule");
  assert.equal(await page.locator("hive-local-dialog").count(), 0);
});

test("only one write can be pending and service errors remain visible", async () => {
  await page.evaluate(() => { window.demoDelay = 200; window.demoFailure = "Receiver unavailable"; });
  await page.getByRole("button", { name: "Heat boost", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Working…" }).isDisabled(), true);
  await page.locator(".card-message.error").waitFor();
  assert.match(await page.locator(".card-message").textContent(), /Receiver unavailable/);
  assert.equal((await requests()).length, 1);
});

test("identical days are grouped into readable patterns", async () => {
  await open(); await tab("Schedule");
  await page.getByRole("button", { name: "Edit Weekdays", exact: true }).waitFor();
  assert.equal(await page.locator(".pattern").count(), 2);
  assert.equal(await page.getByRole("button", { name: "Edit Weekend", exact: true }).count(), 1);
  assert.match(await page.locator(".pattern").first().textContent(), /06:30–08:30/);
  await page.screenshot({ path: "artifacts/schedule-patterns-desktop.png" });
});

test("group edits survive state updates and include every Off period", async () => {
  await editWeekdays();
  const evening = page.getByRole("spinbutton", { name: "Period 5 target temperature" });
  await evening.fill("18.5");
  await page.evaluate(() => { window.demoHass.states["sensor.heating"].attributes.current_temperature = 20; window.updateDemo(); });
  assert.equal(await evening.inputValue(), "18.5");
  await page.getByRole("button", { name: "Save 5 days", exact: true }).click();
  await page.locator("hive-local-dialog .message").filter({ hasText: "5 days saved" }).waitFor();
  const save = (await requests()).find((r) => r.service === "set_schedule_group").service_data;
  assert.deepEqual(save.days, [2, 4, 8, 16, 32]);
  assert.deepEqual(Object.values(save.revisions), Array(5).fill("1".repeat(64)));
  assert.equal(save.transitions.length, 6);
  assert.deepEqual(save.transitions[4], { time: "17:00", temperature: 18.5 });
  assert.equal(save.transitions[1].temperature, null);
  await page.screenshot({ path: "artifacts/schedule-desktop.png" });
});

test("returning to the week cannot silently discard edits", async () => {
  await editWeekdays();
  await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).fill("18.5");
  await page.getByRole("button", { name: "Back to week" }).click();
  assert.equal(await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).inputValue(), "18.5");
  assert.match(await page.locator("hive-local-dialog .message").textContent(), /Save your edits/);
  await page.getByRole("button", { name: "Discard changes" }).click();
  await page.getByRole("button", { name: "Edit Weekdays", exact: true }).waitFor();
  assert.equal(await page.locator("#schedule").count(), 0);
});

test("schedule error preserves the draft without claiming a save", async () => {
  await editWeekdays();
  await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).fill("18.5");
  await page.evaluate(() => { window.demoFailure = "This day changed since it was loaded. Reload the day before editing."; });
  await page.getByRole("button", { name: "Save 5 days", exact: true }).click();
  await page.locator("hive-local-dialog .message.error").waitFor();
  assert.equal(await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).inputValue(), "18.5");
});

test("one pattern can be applied to every day and regroups the week", async () => {
  await editWeekdays();
  await page.getByRole("button", { name: "Every day", exact: true }).click();
  await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).fill("20");
  await page.getByRole("button", { name: "Save 7 days", exact: true }).click();
  await page.getByRole("button", { name: "Edit Every day", exact: true }).waitFor();
  assert.equal(await page.locator(".pattern").count(), 1);
  const save = (await requests()).find((r) => r.service === "set_schedule_group").service_data;
  assert.deepEqual(save.days, [2, 4, 8, 16, 32, 64, 1]);
});

test("a single day can be split from a shared pattern", async () => {
  await editWeekdays();
  for (const name of ["Monday", "Tuesday", "Thursday", "Friday"]) await page.getByRole("button", { name, exact: true }).click();
  await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).fill("21");
  await page.getByRole("button", { name: "Save Wednesday", exact: true }).click();
  await page.getByRole("button", { name: "Edit Wednesday", exact: true }).waitFor();
  assert.deepEqual((await requests()).find((r) => r.service === "set_schedule_group").service_data.days, [8]);
  assert.equal(await page.locator(".pattern").count(), 3);
});

test("partial reads cannot invent or overwrite missing days", async () => {
  await page.evaluate(() => { window.demoReadErrors = { 8: "No response" }; });
  await open(); await tab("Schedule");
  await page.locator(".pattern").first().click();
  assert.equal(await page.getByRole("button", { name: "Wednesday", exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Every day", exact: true }).click();
  await page.getByRole("button", { name: "Save 6 days", exact: true }).click();
  await page.locator("hive-local-dialog .message").filter({ hasText: "6 days saved" }).waitFor();
  assert.equal((await requests()).find((r) => r.service === "set_schedule_group").service_data.days.includes(8), false);
});

test("partial saves stay visible and cannot be blindly resubmitted", async () => {
  await editWeekdays();
  await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).fill("20");
  await page.evaluate(() => { window.demoPartialDay = 8; });
  await page.getByRole("button", { name: "Save 5 days", exact: true }).click();
  await page.locator("hive-local-dialog .message.error").waitFor();
  assert.equal(await page.getByRole("button", { name: "Save 5 days", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).inputValue(), "20");
  await page.locator("#schedule").evaluate((form) => form.requestSubmit());
  assert.equal((await requests()).filter((r) => r.service === "set_schedule_group").length, 1);
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "New pattern", exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.locator(".pattern").first().waitFor();
  assert.equal(await page.locator(".pattern").count(), 3);
});

test("no selected days means no save, including implicit form submission", async () => {
  await editWeekdays();
  for (const name of ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]) await page.getByRole("button", { name, exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Save pattern", exact: true }).isDisabled(), true);
  await page.locator("#schedule").evaluate((form) => form.requestSubmit());
  assert.equal((await requests()).filter((r) => r.service === "set_schedule_group").length, 0);
});

test("new pattern creates a separate group and leaves every other day untouched", async () => {
  const original = await page.evaluate(() => structuredClone(window.demoSchedules));
  await open(); await tab("Schedule");
  await page.getByRole("button", { name: "New pattern", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Save pattern", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Remove period 1", exact: true }).isDisabled(), true);
  for (const name of ["Tuesday", "Thursday"]) await page.getByRole("button", { name, exact: true }).click();
  await page.getByRole("button", { name: "Add period", exact: true }).click();
  await page.getByLabel("Period 2 start time", { exact: true }).fill("07:15");
  await page.getByRole("spinbutton", { name: "Period 2 target temperature" }).fill("19.5");
  await page.getByRole("button", { name: "Add period", exact: true }).click();
  await page.getByLabel("Period 3 start time", { exact: true }).fill("18:00");
  await page.getByRole("checkbox", { name: "Period 3 off", exact: true }).check();
  await page.screenshot({ path: "artifacts/new-pattern-desktop.png" });
  await page.getByRole("button", { name: "Save 2 days", exact: true }).click();
  await page.getByRole("button", { name: "Edit Tue, Thu", exact: true }).waitFor();
  const save = (await requests()).find((r) => r.service === "set_schedule_group").service_data;
  assert.deepEqual(save.days, [4, 16]);
  assert.deepEqual(save.revisions, { 4: "1".repeat(64), 16: "1".repeat(64) });
  assert.deepEqual(save.transitions, [{ time: "00:00", temperature: null }, { time: "07:15", temperature: 19.5 }, { time: "18:00", temperature: null }]);
  const updated = await page.evaluate(() => window.demoSchedules);
  for (const day of [2, 8, 32, 64, 1]) assert.deepEqual(updated[day], original[day]);
  assert.equal(await page.locator(".pattern").count(), 3);
});

test("a new single-day pattern can copy existing times and become independent", async () => {
  await open(); await tab("Schedule");
  await page.getByRole("button", { name: "New pattern", exact: true }).click();
  await page.getByRole("button", { name: "Sunday", exact: true }).click();
  await page.getByLabel("Start with", { exact: true }).selectOption({ label: "Copy Weekend" });
  assert.equal(await page.getByLabel("Period 1 start time", { exact: true }).inputValue(), "08:00");
  await page.getByLabel("Period 1 start time", { exact: true }).fill("09:00");
  await page.getByRole("button", { name: "Save Sunday", exact: true }).click();
  await page.getByRole("button", { name: "Edit Sunday", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Edit Saturday", exact: true }).count(), 1);
  const save = (await requests()).find((r) => r.service === "set_schedule_group").service_data;
  assert.deepEqual(save.days, [1]);
  assert.equal(save.transitions.length, 6);
  assert.equal(save.transitions[0].time, "09:00");
  assert.equal(await page.evaluate(() => window.demoSchedules[64].transitions[0].time), "08:00");
});

test("new pattern periods respect the six-period limit and require valid input before saving", async () => {
  await open(); await tab("Schedule");
  await page.getByRole("button", { name: "New pattern", exact: true }).click();
  await page.getByRole("button", { name: "Monday", exact: true }).click();
  for (let i = 0; i < 5; i++) await page.getByRole("button", { name: "Add period", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Add period", exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Save Monday", exact: true }).click();
  assert.equal((await requests()).filter((r) => r.service === "set_schedule_group").length, 0);
  for (let i = 6; i > 1; i--) await page.getByRole("button", { name: `Remove period ${i}`, exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Remove period 1", exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Save Monday", exact: true }).click();
  await page.getByRole("button", { name: "Edit Monday", exact: true }).waitFor();
  assert.deepEqual((await requests()).find((r) => r.service === "set_schedule_group").service_data.transitions, [{ time: "00:00", temperature: null }]);
});

test("one header refresh reloads the active tab and retains unfinished form inputs", async () => {
  await open();
  const refresh = page.getByRole("button", { name: "Refresh", exact: true });
  assert.equal(await page.locator(".heading").getByRole("button", { name: "Refresh", exact: true }).count(), 1);
  await page.getByLabel("Manual temperature", { exact: false }).fill("21.5");
  await page.getByLabel("Minutes", { exact: true }).fill("25");
  await refresh.click();
  assert.equal((await requests()).at(-1).service, "refresh");
  assert.equal(await page.getByLabel("Manual temperature", { exact: false }).inputValue(), "21.5");
  assert.equal(await page.getByLabel("Minutes", { exact: true }).inputValue(), "25");
  await tab("Schedule"); await page.locator(".pattern").first().waitFor();
  await refresh.click();
  assert.equal((await requests()).filter((r) => r.service === "read_week").length, 2);
  assert.equal(await page.getByRole("button", { name: /reload/i }).count(), 0);
  await tab("Holiday"); await page.locator("#create-holiday").waitFor();
  await page.locator('#create-holiday [name="start"]').fill("2030-11-10T22:30");
  await page.getByLabel("Away temperature", { exact: false }).fill("8");
  await refresh.click();
  assert.equal((await requests()).filter((r) => r.service === "read_holiday").length, 2);
  assert.equal(await page.locator('#create-holiday [name="start"]').inputValue(), "2030-11-10T22:30");
  assert.equal(await page.getByLabel("Away temperature", { exact: false }).inputValue(), "8");
  assert.equal(await page.getByRole("button", { name: /reload/i }).count(), 0);
  await tab("Settings"); await page.locator(".clock.good").waitFor();
  await page.getByLabel("Boost temperature", { exact: false }).fill("28");
  await page.locator('#set-time [name="time"]').fill("2030-11-10T12:34:56");
  await page.evaluate(() => { window.demoClockDelta = 301; window.demoDelay = 250; });
  await refresh.click();
  assert.equal(await refresh.isDisabled(), true);
  assert.equal(await refresh.getAttribute("aria-busy"), "true");
  assert.equal(await page.locator(".clock.good").count(), 0);
  await page.locator(".clock.bad").waitFor();
  assert.equal(await refresh.isDisabled(), false);
  assert.equal(await page.getByLabel("Boost temperature", { exact: false }).inputValue(), "28");
  assert.equal(await page.locator('#set-time [name="time"]').inputValue(), "2030-11-10T12:34:56");
  assert.equal((await requests()).filter((r) => r.service === "read_time").length, 2);
  assert.equal((await requests()).filter((r) => r.service.startsWith("set_")).length, 0);
});

test("refresh cannot silently discard an edited schedule", async () => {
  await editWeekdays();
  await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).fill("18.5");
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  assert.match(await page.locator("hive-local-dialog .message.error").textContent(), /Save or discard/);
  assert.equal((await requests()).filter((r) => r.service === "read_week").length, 1);
  assert.equal(await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).inputValue(), "18.5");
  await page.getByRole("button", { name: "Discard changes", exact: true }).click();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  assert.equal((await requests()).filter((r) => r.service === "read_week").length, 2);
});

test("heating shows current temperature, boost duration, then the three explicit modes", async () => {
  await open();
  assert.match(await page.locator(".live").textContent(), /Current temperature.*19\.4/);
  assert.equal(await page.locator("#panel section h3").first().textContent(), "Heat boost");
  assert.equal(await page.locator('#boost [name="temperature"]').count(), 0);
  assert.equal(await page.locator('#manual-mode [name="temperature"]').inputValue(), "20");
  assert.equal(await page.getByRole("button", { name: "Turn off", exact: true }).count(), 1);
  assert.equal(await page.getByRole("button", { name: "Use schedule", exact: true }).count(), 1);
  await page.locator('#manual-mode [name="temperature"]').fill("21");
  await page.getByRole("button", { name: "Use manual", exact: true }).click();
  assert.equal((await requests())[0].service, "manual");
  assert.equal((await requests())[0].service_data.temperature, 21);
  assert.equal(await page.getByRole("button", { name: "Use manual" }).getAttribute("aria-pressed"), "true");
  await page.getByRole("button", { name: "Turn off", exact: true }).click();
  await page.getByRole("button", { name: "Use schedule", exact: true }).click();
  assert.deepEqual((await requests()).map((r) => r.service), ["manual", "off", "resume_schedule"]);
  assert.doesNotMatch(await page.locator("hive-local-dialog .dialog-body").textContent(), /experimental|your home, just right|Adjust the target|Set target/i);
  await page.screenshot({ path: "artifacts/heating-desktop.png" });
});

test("holiday has one away input and requires cancellation before planning another", async () => {
  await page.evaluate(() => { window.demoHass.states["sensor.heating"].attributes.experimental_controls = false; window.updateDemo(); });
  await open(); await tab("Holiday");
  await page.getByRole("button", { name: "Set holiday", exact: true }).waitFor();
  const status = await page.locator(".holiday-status").boundingBox();
  const heading = await page.getByRole("heading", { name: "Plan a holiday", exact: true }).boundingBox();
  assert.ok(heading.y - status.y - status.height >= 24);
  await page.screenshot({ path: "artifacts/holiday-disabled.png" });
  assert.doesNotMatch(await page.locator("#panel").textContent(), /experimental|unverified|wall thermostat|stored interval|2030-01-10/i);
  assert.equal(await page.getByLabel("Away temperature", { exact: false }).count(), 1);
  await page.locator('#create-holiday [name="start"]').fill("2030-11-10T22:30");
  await page.locator('#create-holiday [name="end"]').fill("2030-12-17T09:13");
  await page.getByRole("button", { name: "Set holiday", exact: true }).click();
  await page.getByRole("button", { name: "Cancel holiday", exact: true }).waitFor();
  assert.equal((await requests()).find((r) => r.service === "create_holiday").service_data.start, "2030-11-10T22:30");
  assert.equal(await page.getByRole("button", { name: "Set holiday", exact: true }).count(), 0);
  assert.equal(await page.getByLabel("Away temperature", { exact: false }).count(), 1);
  await page.locator('#holiday-temperature [name="temperature"]').fill("8");
  await page.getByRole("button", { name: "Save temperature", exact: true }).click();
  await page.locator('#holiday-temperature input[value="8"]').waitFor();
  await page.screenshot({ path: "artifacts/holiday-enabled.png" });
  await page.getByRole("button", { name: "Cancel holiday", exact: true }).click();
  await page.getByRole("button", { name: "Set holiday", exact: true }).waitFor();
  assert.equal(await page.getByLabel("Away temperature", { exact: false }).count(), 1);
  assert.doesNotMatch(await page.locator("#panel").textContent(), /2030-11-10|Stored interval/);
  assert.equal((await requests()).filter((r) => r.service === "read_holiday").length, 3);
});

test("holiday creation stays hidden when receiver settings cannot be read", async () => {
  await page.evaluate(() => { window.demoFailure = "Receiver unavailable"; });
  await open(); await tab("Holiday");
  await page.locator("hive-local-dialog .message.error").waitFor();
  assert.equal(await page.getByRole("button", { name: "Set holiday", exact: true }).count(), 0);
  await page.evaluate(() => { window.demoFailure = null; window.demoHoliday.enabled = true; });
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.getByRole("button", { name: "Cancel holiday", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Set holiday", exact: true }).count(), 0);
});

test("settings fetches the clock difference on entry, with working sync and manual controls", async () => {
  await open(); await tab("Settings");
  await page.locator(".clock.good").waitFor();
  assert.match(await page.locator(".clock").textContent(), /42 sec behind/);
  assert.equal(await page.getByRole("button", { name: "Get time", exact: true }).count(), 0);
  assert.equal(await page.locator('#set-time [name="time"]').inputValue(), "");
  assert.doesNotMatch(await page.locator("#panel").textContent(), /frost|child lock|battery|experimental|target limits|Connection details/i);
  assert.equal((await requests())[0].service, "read_time");
  await page.screenshot({ path: "artifacts/clock-settings.png" });
  await page.getByRole("button", { name: "Sync with Home Assistant", exact: true }).click();
  const sync = (await requests()).find((r) => r.service === "set_time");
  assert.deepEqual(sync.service_data, { entry_id: "demo-entry" });
  assert.match(await page.locator(".clock.good").textContent(), /In sync/);
  await page.locator('#set-time [name="time"]').fill("2030-11-10T12:34:56");
  await page.getByRole("button", { name: "Set", exact: true }).click();
  await page.locator("hive-local-dialog .message").filter({ hasText: "Time set" }).waitFor();
  assert.equal((await requests()).at(-1).service_data.time, "2030-11-10T12:34:56");
  assert.equal(await page.locator('#set-time [name="time"]').inputValue(), "2030-11-10T12:34:56");
  await tab("Heating"); await tab("Settings");
  await page.locator(".clock.bad").waitFor();
  assert.equal((await requests()).filter((r) => r.service === "read_time").length, 2);
});

test("clock colours use absolute server deltas at inclusive two and five minute boundaries", async () => {
  await open();
  for (const [delta, colour, direction] of [[0, "good", "In sync"], [120, "good", "ahead"], [-120, "good", "behind"], [120.1, "warning", "ahead"], [-121, "warning", "behind"], [300, "warning", "ahead"], [-300, "warning", "behind"], [300.1, "bad", "ahead"], [-301, "bad", "behind"]]) {
    await page.evaluate((value) => { window.demoClockDelta = value; }, delta);
    await tab("Settings");
    await page.locator(`.clock.${colour}`).waitFor();
    assert.match(await page.locator(".clock").textContent(), new RegExp(direction));
    await tab("Heating");
  }
});

test("clock failures and missing deltas cannot leave a stale green status", async () => {
  await open(); await tab("Settings");
  await page.locator(".clock.good").waitFor();
  await tab("Heating");
  await page.evaluate(() => { window.demoFailure = "Clock read failed"; });
  await tab("Settings");
  await page.locator("hive-local-dialog .message.error").waitFor();
  assert.equal(await page.locator(".clock.good,.clock.warning,.clock.bad").count(), 0);
  assert.match(await page.locator(".clock").textContent(), /unavailable/);
  assert.equal((await requests()).filter((r) => r.service === "read_time").length, 2);
  await tab("Heating");
  await page.evaluate(() => { window.demoFailure = null; window.demoClockDelta = null; });
  await tab("Settings");
  await page.locator(".clock").filter({ hasText: "unavailable" }).waitFor();
  assert.equal(await page.locator(".clock.good,.clock.warning,.clock.bad").count(), 0);
});

test("boost temperature is saved in Settings and used by both boost buttons", async () => {
  await page.evaluate(() => window.card.setConfig({ type: "custom:hive-local-card", entity: "sensor.heating", boost_temperature: 19 }));
  await open(); await tab("Settings");
  await page.locator(".clock.good").waitFor();
  assert.equal(await page.getByLabel("Boost temperature", { exact: false }).inputValue(), "30");
  await page.getByLabel("Boost temperature", { exact: false }).fill("29");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.locator("hive-local-dialog .message").filter({ hasText: "Boost temperature saved" }).waitFor();
  assert.equal((await requests()).find((r) => r.service === "set_boost_temperature").service_data.temperature, 29);
  assert.equal(await page.evaluate(() => window.demoHass.states["sensor.heating"].attributes.target_temperature), 18);
  await tab("Heating");
  assert.equal(await page.locator('#manual-mode [name="temperature"]').inputValue(), "20");
  await page.getByRole("button", { name: "Start boost", exact: true }).click();
  assert.equal(await page.evaluate(() => window.demoHass.states["sensor.heating"].attributes.target_temperature), 29);
  assert.deepEqual((await requests()).at(-1).service_data, { entry_id: "demo-entry", minutes: 10 });
  await page.getByRole("button", { name: "Close controls" }).click();
  await page.getByRole("button", { name: "End boost", exact: true }).click();
  await page.getByRole("button", { name: "Heat boost", exact: true }).click();
  assert.equal(await page.evaluate(() => window.demoHass.states["sensor.heating"].attributes.target_temperature), 29);
  await open(); await tab("Settings");
  await page.locator(".clock.good").waitFor();
  assert.equal(await page.getByLabel("Boost temperature", { exact: false }).inputValue(), "29");
});

test("an unconfirmed clock write clears the old delta and preserves the manual input", async () => {
  await open(); await tab("Settings");
  await page.locator(".clock.good").waitFor();
  await page.locator('#set-time [name="time"]').fill("2030-11-10T12:34:56");
  await page.evaluate(() => { window.demoFailure = "Time was sent, but could not be read back. Reopen Settings to check."; });
  await page.getByRole("button", { name: "Set", exact: true }).click();
  await page.locator("hive-local-dialog .message.error").waitFor();
  assert.equal(await page.locator(".clock.good,.clock.warning,.clock.bad").count(), 0);
  assert.match(await page.locator(".clock").textContent(), /unavailable/);
  assert.equal(await page.locator('#set-time [name="time"]').inputValue(), "2030-11-10T12:34:56");
  assert.equal((await requests()).filter((r) => r.service === "set_time").length, 1);
});

test("mobile heating and settings fit, with manual Set beside a compact date input", async () => {
  await page.setViewportSize({ width: 375, height: 760 });
  await page.screenshot({ path: "artifacts/card-mobile.png" });
  await open();
  assert.equal(await page.locator("dialog").evaluate((d) => d.scrollWidth <= d.clientWidth), true);
  await page.screenshot({ path: "artifacts/heating-mobile.png" });
  await tab("Settings");
  await page.locator(".clock.good").waitFor();
  await page.locator('#set-time [name="time"]').fill("2030-11-10T12:34:56");
  const input = await page.locator('#set-time [name="time"]').boundingBox();
  const button = await page.getByRole("button", { name: "Set", exact: true }).boundingBox();
  assert.ok(input.width <= 240 && button.x > input.x + input.width && Math.abs(button.y - input.y) < 2);
  assert.equal(await page.locator("dialog").evaluate((d) => d.scrollWidth <= d.clientWidth), true);
  await page.screenshot({ path: "artifacts/settings-mobile.png" });
});

test("mobile dialog fits viewport, supports keyboard close and theme", async () => {
  await page.setViewportSize({ width: 375, height: 760 });
  await page.locator("#theme").click();
  await open(); await tab("Schedule");
  await page.getByRole("button", { name: "Edit Weekdays", exact: true }).waitFor();
  await page.screenshot({ path: "artifacts/schedule-patterns-mobile.png" });
  await page.getByRole("button", { name: "Edit Weekdays", exact: true }).click();
  await page.getByRole("button", { name: "Save 5 days", exact: true }).waitFor();
  const bounds = await page.locator("dialog").boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 375);
  assert.equal(await page.locator("dialog").evaluate((d) => d.scrollWidth <= d.clientWidth), true);
  await page.screenshot({ path: "artifacts/schedule-mobile-dark.png" });
  await page.getByRole("button", { name: "Back to week", exact: true }).click();
  await page.getByRole("button", { name: "New pattern", exact: true }).click();
  await page.getByRole("button", { name: "Sunday", exact: true }).click();
  await page.getByLabel("Start with", { exact: true }).selectOption({ label: "Copy Weekend" });
  assert.equal(await page.locator("dialog").evaluate((d) => d.scrollWidth <= d.clientWidth), true);
  await page.screenshot({ path: "artifacts/new-pattern-mobile.png" });
  await page.keyboard.press("Escape");
  await page.locator("hive-local-dialog").waitFor({ state: "detached" });
  assert.equal(await page.locator("hive-local-dialog").count(), 0);
  assert.equal(await page.locator("hive-local-card .open").evaluate((b) => b === b.getRootNode().activeElement), true);
});

test("unavailable state hides cached temperatures, boost countdown and heating indication", async () => {
  await page.evaluate(() => {
    const state = window.demoHass.states["sensor.heating"];
    state.state = "boost"; state.attributes.remaining_minutes = 8; state.attributes.heating = true; window.updateDemo();
  });
  await open();
  await page.evaluate(() => { window.demoHass.states["sensor.heating"].state = "unavailable"; window.updateDemo(); });
  assert.equal(await page.getByRole("button", { name: "Heat boost", exact: true }).isDisabled(), true);
  assert.equal(await page.locator("hive-local-card .unreachable").textContent(), "Thermostat unreachable");
  assert.doesNotMatch(await page.locator("hive-local-card ha-card").textContent(), /19\.4|18 °C|8 min left|Configuration error/i);
  assert.equal(await page.locator("hive-local-card .dot.heating").count(), 0);
  assert.match(await page.locator("[data-live-temperature]").textContent(), /—/);
  assert.equal(await page.getByRole("button", { name: "Start boost", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Use manual", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Refresh", exact: true }).isDisabled(), false);
  await page.locator("#boost").evaluate((form) => form.requestSubmit());
  assert.equal((await requests()).length, 0);
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 375, height: 760 });
  await page.screenshot({ path: "artifacts/card-unreachable.png" });
});

test("unavailable card handles initial startup, a missing sensor and restored state without configuration errors", async () => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const reason of ["missing", "unavailable", "unknown", "restored", "no-read", "wall-offline", "ha-disconnected"]) {
    await page.evaluate((reason) => {
      window.demoHass.connected = reason !== "ha-disconnected";
      if (reason === "missing") { delete window.demoHass.states["sensor.heating"]; }
      else window.demoHass.states["sensor.heating"] = {
        entity_id: "sensor.heating", state: ["unavailable", "unknown"].includes(reason) ? reason : "schedule",
        attributes: { hive_local_control: true, entry_id: "demo-entry", current_temperature: 19.4, target_temperature: 18,
          read_at: reason === "no-read" ? null : new Date().toISOString(), restored: reason === "restored", ...(reason === "wall-offline" ? { reachable: false } : {}) },
      };
      window.updateDemo();
    }, reason);
    await page.locator("hive-local-card .unreachable").waitFor();
    assert.equal(await page.getByRole("button", { name: "Heat boost", exact: true }).isDisabled(), true, reason);
    assert.doesNotMatch(await page.locator("hive-local-card ha-card").textContent(), /19\.4|18 °C|Configuration error|Select a Hive/i, reason);
    await open();
    assert.match(await page.locator(".connection-status").textContent(), /Thermostat unreachable/);
    await page.keyboard.press("Escape");
  }
  assert.deepEqual(errors, []);
});

test("fresh readings restore an unreachable card and open dialog automatically", async () => {
  await page.evaluate(() => { window.demoHass.states["sensor.heating"].attributes.reachable = false; window.updateDemo(); });
  await open();
  await page.getByLabel("Manual temperature", { exact: false }).fill("22");
  await page.evaluate(() => {
    Object.assign(window.demoHass.states["sensor.heating"].attributes, { reachable: true, current_temperature: 20.5, target_temperature: 21, read_at: new Date().toISOString() });
    window.updateDemo();
  });
  assert.equal(await page.locator("hive-local-card .unreachable").count(), 0);
  assert.equal(await page.locator(".connection-status").isVisible(), false);
  assert.match(await page.locator("hive-local-card .temperature").textContent(), /20\.5/);
  assert.match(await page.locator("[data-live-temperature]").textContent(), /20\.5/);
  assert.equal(await page.getByRole("button", { name: "Start boost", exact: true }).isDisabled(), false);
  assert.equal(await page.getByLabel("Manual temperature", { exact: false }).inputValue(), "22");
  assert.equal((await requests()).length, 0);
});

test("an auto-selected card remembers its installation while the sensor is missing", async () => {
  await page.evaluate(() => {
    window.card.setConfig({ type: "custom:hive-local-card" });
    window.savedSensor = window.demoHass.states["sensor.heating"];
    delete window.demoHass.states["sensor.heating"];
    window.updateDemo();
  });
  assert.equal(await page.locator("hive-local-card .unreachable").textContent(), "Thermostat unreachable");
  assert.equal(await page.locator("hive-local-card .empty").count(), 0);
  await page.evaluate(() => { window.demoHass.states["sensor.heating"] = window.savedSensor; window.updateDemo(); });
  assert.equal(await page.locator("hive-local-card .unreachable").count(), 0);
  assert.equal(await page.getByRole("button", { name: "Heat boost", exact: true }).isDisabled(), false);
});

test("visual card editor emits configuration and escapes user text", async () => {
  await page.evaluate(() => {
    const editor = document.createElement("hive-local-card-editor");
    editor.setConfig({ type: "custom:hive-local-card", entity: "sensor.heating" });
    editor.hass = window.demoHass;
    editor.addEventListener("config-changed", (e) => { window.editorConfig = e.detail.config; });
    document.querySelector("main").append(editor);
  });
  const name = page.locator('hive-local-card-editor [name="name"]');
  await name.fill('<img src=x onerror="window.injected=true">'); await name.blur();
  await page.evaluate(() => window.card.setConfig(window.editorConfig));
  assert.equal(await page.locator("hive-local-card img").count(), 0);
  assert.equal(await page.evaluate(() => window.injected), undefined);
});

test("multiple receivers require explicit selection, and removed cards clean up dialogs", async () => {
  await page.evaluate(() => {
    window.demoHass.states["sensor.second"] = { ...window.demoHass.states["sensor.heating"], entity_id: "sensor.second" };
    window.card.setConfig({ type: "custom:hive-local-card" }); window.updateDemo();
  });
  assert.match(await page.locator("hive-local-card").textContent(), /^$/); // Visible content lives in shadow DOM.
  assert.match(await page.locator("hive-local-card .empty").textContent(), /Select a Hive/);
  await page.evaluate(() => window.card.setConfig({ type: "custom:hive-local-card", entity: "sensor.heating" }));
  await open();
  await page.evaluate(() => window.card.remove());
  assert.equal(await page.locator("hive-local-dialog").count(), 0);
});

test("compact preview screenshot", async () => {
  assert.deepEqual(await page.locator("hive-local-card .reading-label").allTextContents(), ["Current", "Target"]);
  const readings = await page.locator("hive-local-card .reading").evaluateAll((rows) => rows.map((row) => {
    const [value, label] = row.children;
    return { gap: label.getBoundingClientRect().left - value.getBoundingClientRect().right, font: getComputedStyle(label).fontSize };
  }));
  assert.ok(readings.every((reading) => reading.gap >= 8));
  assert.equal(readings[0].font, readings[1].font);
  assert.equal(await page.locator("hive-local-card .quick .subtle").textContent(), "10 min");
  await page.screenshot({ path: "artifacts/card-desktop.png" });
});
