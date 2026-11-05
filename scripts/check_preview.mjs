// Smoke-check the generated, standalone preview in Chromium.
import assert from "node:assert/strict";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { launchBrowser } from "./browser.mjs";

const browser = await launchBrowser();
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(pathToFileURL(resolve("dist/preview.html")).href);
  await page.locator("hive-local-card .open").click();
  await page.getByRole("tab", { name: "Schedule", exact: true }).click();
  await page.getByRole("button", { name: "Edit Weekdays", exact: true }).click();
  await page.getByRole("button", { name: "Save 5 days", exact: true }).waitFor();
  assert.equal(await page.getByRole("spinbutton", { name: "Period 5 target temperature" }).inputValue(), "17.5");
  await page.getByRole("button", { name: "Back to week", exact: true }).click();
  await page.getByRole("button", { name: "New pattern", exact: true }).click();
  await page.getByLabel("Start with", { exact: true }).selectOption({ label: "Copy Weekend" });
  assert.equal(await page.getByLabel("Period 1 start time", { exact: true }).inputValue(), "08:00");
  await page.getByRole("tab", { name: "Settings", exact: true }).click();
  await page.locator(".clock.good").waitFor();
  assert.equal(await page.getByLabel("Boost temperature", { exact: false }).inputValue(), "30");
  assert.equal(await page.getByRole("button", { name: "Get time", exact: true }).count(), 0);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.locator(".clock.good").waitFor();
  assert.equal(await page.getByRole("button", { name: "Sync with Home Assistant", exact: true }).count(), 1);
  assert.deepEqual(errors, []);
  console.log("Standalone preview opens from disk with new schedule patterns and header refresh.");
} finally {
  await browser.close();
}
