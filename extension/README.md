# HTS Change Monitor: Chrome extension

Shows the latest HTS alert from your pipeline on the browser toolbar.

- **Badge:** the Tier 1 count on red, or the count of possible changes on amber. Empty when no change
  touches CPSC. `!` when the alert can't be loaded.
- **Popup:** the alert card (headline, overview, tier strip, top changes, splits drawn as old → new codes)
  and an **Open full report** button.
- **Desktop pop-up** when a new revision appears. Clicking it opens the report.
- Checks every 30 minutes. **Check now** in the popup checks right away.

## Install (no Chrome Web Store needed)

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose this `extension/` folder.
3. Pin it: click the puzzle-piece icon on the toolbar, then the pin next to HTS Change Monitor.
4. Click the icon, paste the address of your published `alert.json`, and click **Save and check**.

## Where alert.json comes from

`python report.py --latest --publish` copies `report.html` and `alert.json` into `docs/latest/`.
Commit and push, and turn on GitHub Pages for the repo's `docs/` folder once
(repo **Settings → Pages**). The address is then:

    https://<github-username>.github.io/<repo-name>/latest/alert.json

The report must sit next to `alert.json`; the extension opens `report.html` from the same folder.

## Testing on your own computer

    cd docs && python -m http.server 8765

Then use `http://localhost:8765/latest/alert.json` as the address. To see the pop-up again, publish a
newer alert, or change the address and save (saving resets "last seen").

## Files

| File | What it does |
| --- | --- |
| `manifest.json` | Name, permissions, and which files Chrome runs |
| `background.js` | Checks `alert.json` on a timer, sets the badge, shows pop-ups |
| `popup.html` / `popup.css` / `popup.js` | The card you see when you click the icon |
| `shared.js` | Small helpers both scripts use |
| `icons/` | Toolbar and pop-up icons |

The extension may only read GitHub Pages sites (`*.github.io`) and `localhost`. To host the alert
anywhere else, add that address to `host_permissions` in `manifest.json` and reload the extension.
