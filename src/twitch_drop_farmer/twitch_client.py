from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

try:
    import requests
except ModuleNotFoundError as exc:
    if exc.name == "requests":
        raise SystemExit(
            "Falta a dependência 'requests'. "
            "Instala tudo com `python -m pip install -r requirements.txt` "
            "e arranca a app com `$env:PYTHONPATH='src'; python -m twitch_drop_farmer` "
            "na raiz do repositório."
        ) from exc
    raise

if __package__ in {None, ""}:
    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from twitch_drop_farmer.config import COOKIE_FILE, CONFIG_DIR
    from twitch_drop_farmer.models import DropCampaign, StreamCandidate
else:
    from .config import COOKIE_FILE, CONFIG_DIR
    from .models import DropCampaign, StreamCandidate


GQL_URL = "https://gql.twitch.tv/gql"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


@dataclass(slots=True)
class LoginState:
    oauth_token: str = ""

    @property
    def logged_in(self) -> bool:
        return bool(self.oauth_token)


class TwitchClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Client-ID": CLIENT_ID})
        self.login_state = LoginState()
        self._load_cookies()

    def _load_cookies(self) -> None:
        if not COOKIE_FILE.exists():
            return
        payload = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        for cookie in payload.get("cookies", []):
            self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))
        self.login_state.oauth_token = payload.get("oauth_token", "")

    def save_cookies(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        serialized = [
            {"name": c.name, "value": c.value, "domain": c.domain}
            for c in self.session.cookies
        ]
        COOKIE_FILE.write_text(
            json.dumps({"cookies": serialized, "oauth_token": self.login_state.oauth_token}, indent=2),
            encoding="utf-8",
        )

    def set_oauth_token(self, token: str) -> None:
        token = token.replace("OAuth ", "").strip()
        self.login_state.oauth_token = token
        self.session.headers["Authorization"] = f"OAuth {token}"
        self.save_cookies()

    def fetch_campaigns(self) -> list[DropCampaign]:
        """Best-effort GraphQL request for active drop campaigns."""
        query = {
            "operationName": "ViewerDropsDashboard",
            "variables": {"fetchRewardCampaigns": True},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "9a62a09b1f8f0f4df7142f2f2b1766fa0fe58f3d82405463e99e36fcff7bcbb8",
                }
            },
        }
        response = self.session.post(GQL_URL, json=query, timeout=20)
        response.raise_for_status()
        data = response.json()
        campaigns: list[DropCampaign] = []

        # Schema changes often. We keep parsing defensive.
        nodes: list[dict[str, Any]] = (
            data.get("data", {})
            .get("currentUser", {})
            .get("dropCampaignsInProgress", [])
        )
        for node in nodes:
            time_based = node.get("timeBasedDrops", [])
            req = 0
            progress = 0
            if time_based:
                req = int(time_based[0].get("requiredMinutesWatched", 0))
                progress = int(time_based[0].get("self", {}).get("currentMinutesWatched", 0))
            campaigns.append(
                DropCampaign(
                    id=node.get("id", ""),
                    game_name=node.get("game", {}).get("displayName", "Unknown"),
                    title=node.get("name", "Campaign"),
                    ends_at=datetime.fromisoformat(node.get("endAt", datetime.utcnow().isoformat()).replace("Z", "+00:00")),
                    progress_minutes=progress,
                    required_minutes=req,
                )
            )
        return campaigns

    def fetch_streams(self, game_name: str) -> list[StreamCandidate]:
        query = [{
            "operationName": "DirectoryPage_Game",
            "variables": {"name": game_name, "options": {"sort": "VIEWER_COUNT"}},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "1f0300090f8d6a3f3cce7f0ecad0fb3f29e6f732f95c98d5f7e6d2f9f15e9cc3",
                }
            },
        }]
        response = self.session.post(GQL_URL, json=query, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0]
        edges = (
            payload.get("data", {})
            .get("game", {})
            .get("streams", {})
            .get("edges", [])
        )
        output: list[StreamCandidate] = []
        for edge in edges:
            node = edge.get("node", {})
            output.append(
                StreamCandidate(
                    login=node.get("broadcaster", {}).get("login", ""),
                    display_name=node.get("broadcaster", {}).get("displayName", ""),
                    game_name=game_name,
                    viewer_count=int(node.get("viewersCount", 0)),
                    drops_enabled=bool(node.get("tags")),
                )
            )
        return output


if __name__ == "__main__":
    raise SystemExit(
        "Este ficheiro e um modulo interno. "
        "Arranca a aplicacao com `$env:PYTHONPATH='src'; python -m twitch_drop_farmer` "
        "depois de instalares as dependências com `python -m pip install -r requirements.txt`."
    )
