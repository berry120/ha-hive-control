import "../custom_components/hive_local/frontend/hive-local-card.js";

window.calls = [];
window.demoDelay = 0;
window.demoFailure = null;
const card = document.querySelector("hive-local-card");
const demoTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
window.card = card;
const state = {
  entity_id: "sensor.heating", state: "schedule", attributes: {
    friendly_name: "Heating", name: "Heating", hive_local_control: true, entry_id: "demo-entry",
    current_temperature: 19.4, target_temperature: 18, heating: false, scheduled_off: false,
    boost_minutes: 10, boost_temperature: 30, remaining_minutes: null,
    receiver_ieee: "02:00:00:00:00:00:00:01", thermostat_ieee: "02:00:00:00:00:00:00:02",
    minimum_temperature: 5, maximum_temperature: 32, battery_percentage: 86,
    raw_system_mode: 4, hold: 0, hold_duration: 0, running_state: 0,
    timezone: demoTimezone, read_at: new Date().toISOString(),
  },
};
const schedules = {};
for (const day of [1, 2, 4, 8, 16, 32, 64]) schedules[day] = {
  day, revision: "1".repeat(64), transitions: [
    { time: [64, 1].includes(day) ? "08:00" : "06:30", temperature: 18 },
    { time: [64, 1].includes(day) ? "10:00" : "08:30", temperature: null },
    { time: "12:00", temperature: null }, { time: "14:00", temperature: null },
    { time: "17:00", temperature: [64, 1].includes(day) ? 18 : 17.5 }, { time: "20:00", temperature: null },
  ],
};
let holiday = { enabled: false, start: "2030-01-10T22:30", end: "2030-01-17T09:13", temperature: 7, timezone: demoTimezone };
window.demoClockDelta = -42;
window.demoHoliday = holiday;
window.demoSchedules = schedules;
window.demoReadErrors = {};
window.demoPartialDay = null;
const localTime = (date) => new Intl.DateTimeFormat("sv-SE", { timeZone: demoTimezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(date).replace(" ", "T");
const clockResponse = () => ({ time: localTime(new Date(Date.now() + (window.demoClockDelta || 0) * 1000)), timezone: demoTimezone, clock_delta_seconds: window.demoClockDelta, server_time: new Date().toISOString() });
window.demoHass = {
  states: { [state.entity_id]: state },
  async callWS(request) {
    window.calls.push(structuredClone(request));
    if (window.demoDelay) await new Promise((resolve) => setTimeout(resolve, window.demoDelay));
    if (window.demoFailure) throw new Error(window.demoFailure);
    const d = request.service_data, a = state.attributes;
    let response = { acknowledged: true, read_back: true, effective_on_device: false, message: "Receiver values confirmed." };
    switch (request.service) {
      case "boost": state.state = "boost"; a.remaining_minutes = d.minutes; a.target_temperature = d.temperature ?? a.boost_temperature; break;
      case "set_boost_temperature": a.boost_temperature = d.temperature; response = { temperature: d.temperature, message: "Boost temperature saved." }; break;
      case "resume_schedule": state.state = "schedule"; a.remaining_minutes = null; a.target_temperature = 18; break;
      case "off": state.state = "off"; break;
      case "set_target": a.target_temperature = d.temperature; break;
      case "manual": state.state = "manual"; a.target_temperature = d.temperature; break;
      case "read_schedule": response = structuredClone(schedules[d.day]); break;
      case "read_week": response = { days: Object.values(schedules).filter((s) => !window.demoReadErrors[s.day]).map((s) => structuredClone(s)), errors: { ...window.demoReadErrors } }; break;
      case "set_schedule_group": {
        for (const day of d.days) if (schedules[day].revision !== d.revisions[day]) throw new Error("A selected day changed. Reload the week before saving.");
        const saved = [];
        for (const [index, day] of d.days.entries()) {
          if (day === window.demoPartialDay) {
            response = { complete: false, days: saved, failed_day: day, remaining_days: d.days.slice(index), message: "Some days were saved. Reload the week before retrying." }; break;
          }
          schedules[day] = { day, transitions: structuredClone(d.transitions), revision: "2".repeat(64) };
          saved.push(structuredClone(schedules[day]));
          response = { ...response, complete: true, days: saved, message: `${saved.length} days saved and read back from the receiver.` };
        }
        break;
      }
      case "set_schedule":
        if (schedules[d.day].revision !== d.revision) throw new Error("This day changed since it was loaded. Reload the day before editing.");
        schedules[d.day] = { day: d.day, transitions: structuredClone(d.transitions), revision: "2".repeat(64) };
        response = { ...response, ...structuredClone(schedules[d.day]), message: "Day saved and read back from the receiver." }; break;
      case "read_holiday": response = structuredClone(holiday); break;
      case "set_holiday_temperature": holiday.temperature = d.temperature; break;
      case "cancel_holiday": holiday.enabled = false; break;
      case "create_holiday":
        if (holiday.enabled) throw new Error("Cancel the existing holiday before creating a new one.");
        Object.assign(holiday, d, { enabled: true }); response.holiday = structuredClone(holiday); break;
      case "read_time": response = clockResponse(); break;
      case "set_time": {
        const now = Date.now();
        const candidate = d.time ? Date.parse(`${d.time}Z`) : now;
        const zoneOffset = Date.parse(`${localTime(new Date(candidate))}Z`) - Math.floor(candidate / 1000) * 1000;
        window.demoClockDelta = d.time ? (candidate - zoneOffset - now) / 1000 : 0;
        response = { ...response, ...clockResponse(), message: "Time set and read back from the receiver." }; break;
      }
      case "refresh": response = { ...response, ...a }; break;
      default: throw new Error("Unknown demo service");
    }
    window.updateDemo();
    return { response };
  },
};
window.updateDemo = () => { card.hass = window.demoHass; };
card.setConfig({ type: "custom:hive-local-card", entity: "sensor.heating" });
window.updateDemo();
document.querySelector("#theme").onclick = () => document.documentElement.classList.toggle("dark");

