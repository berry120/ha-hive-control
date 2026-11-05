// Prefer Playwright's pinned Chromium in CI; allow an installed browser locally.
import { existsSync } from "node:fs";
import { chromium } from "playwright-core";

export function launchBrowser() {
  const executablePath = process.env.BROWSER_PATH || [
    chromium.executablePath(),
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
  ].find(existsSync);
  if (!executablePath) throw new Error("Run npx playwright-core install chromium, or set BROWSER_PATH to a Chromium executable.");
  return chromium.launch({ executablePath, headless: true });
}
