from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from twitch_drop_farmer.twitch_client import TwitchClient


def _load_from_config(config_path: Path) -> tuple[str, str]:
    if not config_path.exists():
        return "", ""
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Config inválida em {config_path}: {exc}") from exc

    token = str(payload.get("oauth_token", "") or "").strip()
    session_json = json.dumps({
        "cookies": payload.get("cookies", []),
        "user_id": payload.get("user_id", ""),
        "login_name": payload.get("login_name", ""),
        "device_id": payload.get("device_id", ""),
        "session_id": payload.get("session_id", ""),
    })
    return token, session_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduz o fetch real de campanhas da Twitch usando sessão autenticada.")
    parser.add_argument("--token", help="Valor do cookie auth-token da Twitch.")
    parser.add_argument("--session-json", help="JSON exportado pela app, com a sessão autenticada.")
    parser.add_argument("--config", type=Path, default=Path.home() / ".twitch-drop-farmer" / "cookies.json", help="Caminho para config.json/cookies.json local da app.")
    args = parser.parse_args()

    client = TwitchClient()

    token = (args.token or "").strip()
    session_json = (args.session_json or "").strip()

    if not token and not session_json:
        token, session_json = _load_from_config(args.config)

    if token:
        client.set_oauth_token(token)
    elif session_json:
        client.import_session_json(session_json)
    else:
        print("Nenhum token nem sessão foram fornecidos.")
        print("Use --token, --session-json ou active a app para exportar a sessão.")
        return 2

    try:
        client.validate_oauth_token()
    except Exception as exc:  # noqa: BLE001
        print(f"VALIDACAO OAuth falhou: {exc}")
        return 3

    print("Autenticado como:", client.login_state.login_name or "unknown")
    print("user_id:", client.login_state.user_id or "unknown")

    try:
        campaigns = client.fetch_campaigns(allow_browser_fallback=True)
    except Exception as exc:  # noqa: BLE001
        print(f"fetch_campaigns() falhou com exceção: {exc}")
        raise

    print(f"Campanhas retornadas: {len(campaigns)}")
    for campaign in campaigns[:10]:
        status = getattr(campaign, "status", "")
        print(f"- {campaign.id} | {campaign.title} | {status} | active={campaign.active} | eligible={campaign.eligible}")

    diags = client.consume_diagnostics()
    if diags:
        print("\nDIAGNOSTICOS:")
        for item in diags:
            print("-", item)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
