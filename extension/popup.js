// Draws the alert card from what background.js saved, and handles Check now / Settings.
const $ = id => document.getElementById(id);
const TYPE_LABEL = { added: "Added", deleted: "Removed", renumbered: "Renumbered", split: "Split",
  possible_split: "Possible split", desc_changed: "Reworded", rate_changed: "Rate change",
  units_changed: "Units change", footnote_changed: "Footnote change" };
const LINEAGE = ["split", "possible_split", "renumbered"];
const SHOWN = 4;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v; else if (k === "text") node.textContent = v; else node.setAttribute(k, v);
  }
  node.append(...children.filter(Boolean));
  return node;
}

function ago(iso) {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "Checked just now";
  if (min < 60) return `Checked ${min} min ago`;
  const h = Math.round(min / 60);
  return h < 24 ? `Checked ${h} h ago` : `Checked ${new Date(iso).toLocaleDateString()}`;
}

function lineage(change) {
  const to = (change.related_codes || "").split("; ").filter(Boolean);
  if (!LINEAGE.includes(change.change_type) || !to.length) return null;
  return el("div", { class: "lineage", role: "img", "aria-label": `${change.code} replaced by ${to.join(", ")}` },
    el("div", { class: "from", text: change.code }),
    el("div", { class: "branch", "aria-hidden": "true" }),
    el("ul", { class: "to" }, ...to.map(c => el("li", { text: c }))));
}

function renderCard(alert) {
  const card = $("card");
  card.dataset.urgency = alert.urgency || "grey";
  $("releases").textContent = `HTS ${alert.to_release}, compared with ${alert.from_release}`;
  $("headline").textContent = alert.headline;
  $("overview").textContent = alert.overview || "";

  const counts = alert.tier_counts;
  $("strip").replaceChildren(...TIERS.filter(t => counts[t]).map(t => {
    const s = el("span", { class: "t" + t, title: `${TIER_LABEL[t]}: ${counts[t]}` });
    s.style.flex = `${counts[t]} 1 0`;
    return s;
  }));
  $("legend").replaceChildren(...TIERS.filter(t => counts[t]).map(t =>
    el("li", {}, el("span", { class: "swatch t" + t }), TIER_LABEL[t] + " ", el("strong", { text: String(counts[t]) }))));

  const top = alert.top_changes.slice(0, SHOWN);
  const items = top.map(c => el("li", { class: "change", "data-tier": c.tier },
    el("div", { class: "change-head" }, (TYPE_LABEL[c.change_type] || c.change_type) + " ",
      el("span", { class: "code", text: c.code })),
    el("p", { text: c.summary }),
    lineage(c)));
  $("changes").replaceChildren(...items);
  const relevant = (counts["1"] || 0) + (counts.needs_review || 0) + (counts["2"] || 0) + (counts["3"] || 0);
  if (relevant > top.length) {
    $("changes").after(el("p", { class: "more", id: "more", text: `${relevant - top.length} more in the full report.` }));
  }
  card.hidden = false;
}

async function render() {
  const { alertUrl } = await chrome.storage.sync.get("alertUrl");
  const { alert, lastChecked, error } = await chrome.storage.local.get(["alert", "lastChecked", "error"]);
  $("more")?.remove();
  $("checked").textContent = ago(lastChecked);
  $("open").onclick = () => chrome.tabs.create({ url: reportUrlFor(alertUrl) });

  const needsSetup = !alertUrl;
  if (alert && validAlert(alert) && !needsSetup) renderCard(alert); else $("card").hidden = true;
  showSetup(needsSetup, alertUrl);

  const err = $("error");
  err.hidden = !error || error === "setup";
  if (!err.hidden) {
    err.textContent = alert ? `Couldn't refresh the alert (${error}). Showing the last one received. Check the address in Settings.`
                            : `Couldn't load the alert: ${error}. Check the address in Settings.`;
  }
  $("check").disabled = needsSetup;
}

function showSetup(show, current = "") {
  $("setup").hidden = !show;
  $("url").value = current || "";
  $("cancel").hidden = !current;
  if (show) $("url").focus();
}

async function checkNow() {
  const btn = $("check");
  btn.disabled = true;
  btn.textContent = "Checking\u2026";
  await chrome.runtime.sendMessage({ type: "check" });
  btn.textContent = "Check now";
  await render();
}

$("check").addEventListener("click", checkNow);
$("settings").addEventListener("click", async () => {
  const { alertUrl } = await chrome.storage.sync.get("alertUrl");
  showSetup($("setup").hidden, alertUrl);
});
$("cancel").addEventListener("click", () => showSetup(false));
$("setup-form").addEventListener("submit", async e => {
  e.preventDefault();
  let url;
  try { url = new URL($("url").value.trim()).href; } catch { $("url").setCustomValidity("Enter a full web address"); $("url").reportValidity(); return; }
  await chrome.storage.sync.set({ alertUrl: url });
  await chrome.storage.local.remove("lastSeenRelease");   // treat the new address's alert as new
  showSetup(false);
  await checkNow();
});
$("url").addEventListener("input", () => $("url").setCustomValidity(""));

render();
