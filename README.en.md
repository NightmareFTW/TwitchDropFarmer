# Twitch Drop Farmer

[PT-PT](README.md) | [EN](README.en.md)

A Python + PySide6 desktop app to automate Twitch Drops farming with local control, campaign filters, and automatic channel rotation.

Current version: `2.2.41`

## About the project

Twitch Drop Farmer has evolved into a more resilient and predictable farming client:

- Dashboard states now reflect real campaign outcomes (Active, Not started, No stream, Completed, Lost, Subscription required).
- Manual game targeting is now sticky and avoids unexpected automatic switches.
- Filters are reorganized into sub-tabs with search and bulk actions (select/clear all and visible).
- Farming context remains clearer even when a valid stream is temporarily unavailable.
- Automation is designed for stable local operation without external service dependencies.
- Diagnostics and update checks provide clearer status and compact test reporting.

## Highlights

- Automatic campaign discovery (active and upcoming)
- Best-target farming selection logic
- Auto-switch between channels
- Whitelist and blacklist filters (games and channels)
- Manual and automatic drop redemption
- Real-time farming status (game, campaign, channel, progress, ETA)
- Durable session JSON import/export mode

## What's new in 2.2.41

- Fixed the Filters whitelist hiding already-selected games with no active campaign — it now shows all configured games.
- New field to add games to the whitelist manually, even when Twitch withholds the full catalog.

## What's new in 2.2.40

- Fixed the Filters tab only showing games already in the whitelist.
- Disk-persisted campaign cache: the full game catalog now survives app restarts.

## What's new in 2.2.39

- Dashboard notice + "Refresh dashboard" tooltip explaining what to do when a game's drops don't load.
- Full PT-PT (pre-1990 orthography) and EN translation review, with fixed accents.
- Fixed the "About" dialog showing literal `\n-` instead of line breaks; text rewritten and refreshed.

## What's new in 2.2.38

- New "Showing X/Y whitelisted games" counter on the dashboard.

## What's new in 2.2.37

- "Refresh dashboard" button now runs a full whitelist detail scan instead of just 8 campaigns per cycle.

## What's new in 2.2.36

- Per-drop detail fetching now prioritizes the selected/active farm target instead of just soonest-ending order.

## What's new in 2.2.35

- Fixed a 2.2.34 regression: the on-disk persistent profile made the browser fallback stop finding campaigns after many restarts. Reverted to an in-memory profile (reused within a single run).

## What's new in 2.2.34

- Persistent, shared browser profile across fallback calls instead of a fresh one every time.
- Client-Integrity token harvested from the browser is reused on direct requests for a few minutes.
- Circuit breaker skips redundant DropCampaignDetails retries when integrity is already confirmed blocked for the cycle.

## What's new in 2.2.33

- `[HH:MM:SS]` timestamps on every log line.
- Campaign cache now merges instead of replacing — whitelisted games outside the actively farmed one fill in over time.

## What's new in 2.2.32

- Fixed browser-fallback log spam from overlapping async calls, and reduced the per-campaign detail fetch cost so it no longer delays the streamless heartbeat.

## What's new in 2.2.31

- The invisible browser fallback (no window, ever) now also visits each active campaign's detail page, capturing real per-drop progress instead of only summary data.

## What's new in 2.2.30

- **[CRITICAL]** Fixed an empty `Client-Id` on every direct GraphQL request (Inventory, ViewerDropsDashboard, DropCampaignDetails), which made Twitch's integrity check always fail and forced the slow browser fallback. Restored Twitch's real public Client-IDs — the app should now work without opening any browser.

## What's new in 2.2.29

- Fixed the "Active drops" panel showing "No active drops to display" even while a campaign is being actively farmed — it now shows aggregate progress when Twitch doesn't return per-drop detail.

## What's new in 2.2.28

- Fixed a global false-positive "subscription required" warning on the dashboard, active-drops list, and hide-sub-only checkbox count — campaigns with missing per-drop metadata (browser fallback) are no longer confused with subscription-only ones.

## What's new in 2.2.27

- Fixed false critical OAuth diagnostic failures for durable session users.
- Diagnostics now run in a safe mode without rendered browser fallback in worker threads.
- Added compact diagnostic report table (`Test | Status | Time | Message`).
- Improved subscription-only hiding logic for campaigns with missing actionable metadata.
- Dashboard grid now compacts correctly after hidden-game filtering.
- Fixed manual target behavior so selected games stay selected reliably.

## Quick Start

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:PYTHONPATH="src"
python -m twitch_drop_farmer
```

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m twitch_drop_farmer
```

## Build EXE (Windows)

```powershell
.\build_exe.ps1
```

Generated binary:

- dist\TwitchDropFarmer\TwitchDropFarmer.exe
- dist\TwitchDropFarmer-win64.zip

Notes:

- The build now uses `onedir` to avoid an oversized single-file executable with Qt WebEngine.
- The generated ZIP is the recommended release artifact for distribution.

## GitHub Releases

- `v*` tags can now trigger an automated Windows release build through GitHub Actions.
- The release publishes `TwitchDropFarmer-win64.zip` as an asset.
- Release notes for this version: `docs/releases/v2.2.41.en.md` and `docs/releases/v2.2.41.pt-PT.md`.

## Authentication

Use your Twitch auth-token cookie value inside the app (Account tab).

- Paste only the cookie value
- Do not include the cookie name
- Do not include the OAuth prefix

Durable session alternative:

- Import session JSON in the Account tab.
- Save and refresh.

## Privacy and Security

- Credentials and session artifacts are stored locally.
- Sensitive data must never be published in issues or commits.
- The repository includes ignore rules to prevent common local data leaks.
- Responsible disclosure policy: `SECURITY.md`.

## Screenshots

### Dashboard

![Dashboard](docs/images/ui-dashboard.png)

### Farming View

![Farming View](docs/images/ui-farming.png)

### Campaigns View

![Campaigns View](docs/images/ui-campaigns.png)

### Settings View

![Settings View](docs/images/ui-settings.png)

## Troubleshooting

- App icon still looks stale on Windows:
	- Run `tools\\refresh_icon_cache.ps1` in PowerShell to clear icon cache and restart Explorer.
	- Non-interactive alternative: `powershell -ExecutionPolicy Bypass -File .\\tools\\refresh_icon_cache.ps1 -Force`

## Notes

- Twitch APIs and GraphQL behavior may change over time.
- If endpoints change, query hashes and parsing logic may need updates.

## License

This project is licensed under the MIT License. See LICENSE for details.
