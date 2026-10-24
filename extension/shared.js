// Shared by background.js and popup.js.
const CHECK_EVERY_MINUTES = 30;
const URGENCY_COLOR = { red: "#B42318", amber: "#B54708", grey: "#5D6B7A" };
const TIERS = ["1", "needs_review", "2", "3", "not_relevant"];
const TIER_LABEL = { "1": "Covered", needs_review: "Needs a decision", "2": "Near a watched rule",
                     "3": "Similar wording", not_relevant: "Not relevant" };

// The report sits next to alert.json on the published site.
function reportUrlFor(alertUrl) {
  try { return new URL("report.html", alertUrl).href; } catch (e) { return ""; }
}

// Check that a downloaded alert has what the extension needs.
function validAlert(a) {
  return a && typeof a.headline === "string" && typeof a.to_release === "string" &&
         a.tier_counts && typeof a.tier_counts === "object" && Array.isArray(a.top_changes);
}

// Badge text: Tier 1 count when red; count of possible changes when amber; empty when grey.
function badgeFor(a) {
  const t = a.tier_counts;
  if (a.urgency === "red") return String(t["1"] || "");
  if (a.urgency === "amber") return String((t.needs_review || 0) + (t["2"] || 0) + (t["3"] || 0));
  return "";
}
