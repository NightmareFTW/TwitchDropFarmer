# Twitch Drop Farmer

[PT-PT](README.md) | [EN](README.en.md)

A Python + PySide6 desktop app to automate Twitch Drops farming with local control, campaign filters, and automatic channel rotation.

## Highlights

- Automatic campaign discovery (active and upcoming)
- Best-target farming selection logic
- Auto-switch between channels
- Whitelist and blacklist filters (games and channels)
- Manual and automatic drop redemption
- Real-time farming status (game, campaign, channel, progress, ETA)

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

## Authentication

Use your Twitch auth-token cookie value inside the app (Account tab).

- Paste only the cookie value
- Do not include the cookie name
- Do not include the OAuth prefix

## Screenshots

### Dashboard

![Dashboard](docs/images/ui-dashboard.png)

### Farming View

![Farming View](docs/images/ui-farming.png)

### Campaigns View

![Campaigns View](docs/images/ui-campaigns.png)

### Settings View

![Settings View](docs/images/ui-settings.png)

## Notes

- Twitch APIs and GraphQL behavior may change over time.
- If endpoints change, query hashes and parsing logic may need updates.

## License

This project is licensed under the MIT License. See LICENSE for details.
