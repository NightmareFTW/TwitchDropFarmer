# Twitch Drop Farmer

[PT-PT](README.md) | [EN](README.en.md)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-2ea44f)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Python + Tkinter desktop app to automate Twitch Drops farming with local control, campaign filters, and channel rotation.

## Highlights

- Automatic campaign discovery (active and upcoming)
- Best-target farming selection logic
- Auto-switch between channels
- Whitelist and blacklist filters (games and channels)
- Manual and automatic drop redemption
- Real-time farming status (game, campaign, channel, progress, ETA)

## Screenshots

![Farming View](docs/images/ui-farming.png)
![Campaigns View](docs/images/ui-campaigns.png)
![Settings View](docs/images/ui-settings.png)

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

- dist\TwitchDropFarmer.exe

## Authentication

Use your Twitch auth-token cookie value inside the app (Account tab).

- Paste only the cookie value
- Do not include the cookie name
- Do not include the OAuth prefix

## Notes

- Twitch APIs and GraphQL behavior may change over time.
- If endpoints change, query hashes and parsing logic may need updates.

## License

This project is licensed under the MIT License. See LICENSE for details.
