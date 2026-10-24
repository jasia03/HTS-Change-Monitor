// Checks the published alert.json on a timer, updates the badge, and shows a pop-up for new revisions.
importScripts("shared.js");

async function check() {
  const { alertUrl } = await chrome.storage.sync.get("alertUrl");
  const now = new Date().toISOString();
  if (!alertUrl) {
    await chrome.action.setBadgeText({ text: "" });
    await chrome.action.setTitle({ title: "HTS Change Monitor: add the alert address in the popup" });
    await chrome.storage.local.set({ lastChecked: now, error: "setup" });
    return { error: "setup" };
  }
  try {
    const res = await fetch(alertUrl, { cache: "no-store" });
    if (!res.ok) throw new Error(`the server answered ${res.status}`);
    const alert = await res.json();
    if (!validAlert(alert)) throw new Error("the file is not an alert.json made by report.py");

    const { lastSeenRelease } = await chrome.storage.local.get("lastSeenRelease");
    const isNew = lastSeenRelease !== alert.to_release;
    await chrome.storage.local.set({ alert, lastChecked: now, error: "", lastSeenRelease: alert.to_release });

    const text = badgeFor(alert);
    await chrome.action.setBadgeText({ text });
    await chrome.action.setBadgeBackgroundColor({ color: URGENCY_COLOR[alert.urgency] || URGENCY_COLOR.grey });
    await chrome.action.setTitle({ title: `HTS ${alert.to_release}: ${alert.headline}` });

    if (isNew) {
      chrome.notifications.create(`hts-${alert.to_release}`, {
        type: "basic",
        iconUrl: "icons/icon128.png",
        title: alert.headline,
        message: `HTS ${alert.to_release}, compared with ${alert.from_release}. Click to open the report.`,
        priority: alert.urgency === "red" ? 2 : 0,
      });
    }
    return { alert, isNew };
  } catch (e) {
    const error = e instanceof TypeError
      ? "the address could not be reached"          // network down, wrong address, or blocked
      : String(e.message || e);
    await chrome.storage.local.set({ lastChecked: now, error });
    await chrome.action.setBadgeText({ text: "!" });
    await chrome.action.setBadgeBackgroundColor({ color: URGENCY_COLOR.grey });
    await chrome.action.setTitle({ title: `HTS Change Monitor: couldn't load the alert (${error})` });
    return { error };
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("check", { periodInMinutes: CHECK_EVERY_MINUTES });
  check();
});
chrome.runtime.onStartup.addListener(check);
chrome.alarms.onAlarm.addListener(a => { if (a.name === "check") check(); });

chrome.notifications.onClicked.addListener(async () => {
  const { alertUrl } = await chrome.storage.sync.get("alertUrl");
  const url = reportUrlFor(alertUrl);
  if (url) chrome.tabs.create({ url });
});

// The popup asks for a check ("Check now", or after saving settings).
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "check") { check().then(reply); return true; }
});
