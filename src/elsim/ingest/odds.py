"""Takes one pre-game odds snapshot from The Odds API and saves it to disk.

Each snapshot costs one credit of the free plan and cannot be fetched again
later, so every snapshot is kept as its own file and never overwritten.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://api.the-odds-api.com/v4/sports/basketball_euroleague/odds"


def read_key() -> str:
    """Return ODDS_API_KEY from the environment or from the .env file."""
    key = os.environ.get("ODDS_API_KEY", "")
    env_file = Path(".env")
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ODDS_API_KEY":
                key = value
    key = key.strip().strip("\"'")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set. Copy .env.example to .env and put the key there.")
    return key


def take_snapshot(settings: dict) -> Path:
    query = urllib.parse.urlencode({"regions": "eu", "markets": "h2h", "apiKey": read_key()})
    request = urllib.request.Request(f"{URL}?{query}", headers={"User-Agent": settings["user_agent"]})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            events = json.loads(response.read())
            headers = response.headers
    except urllib.error.HTTPError as error:
        # The address contains the key, so only the status is reported.
        raise SystemExit(f"The Odds API answered HTTP {error.code}. No snapshot was saved.") from None

    now = datetime.now(timezone.utc)
    snapshot = {
        "snapshot_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "credits_used_by_this_request": headers.get("x-requests-last"),
        "credits_remaining": headers.get("x-requests-remaining"),
        "events": events,
    }
    path = Path(settings["raw_dir"]) / "odds" / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return path
