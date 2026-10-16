"""Read-only release verification. Never outputs credentials or submits orders."""
import json
import urllib.request
from datetime import datetime, timezone

from app.core.config import settings


def main():
    request = urllib.request.Request(
        "http://127.0.0.1:8080/api/intraday-focus/snapshot",
        headers={"x-app-secret": settings.app_shared_secret or ""},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    assert data["mode"] == "PAPER" and data["real_orders_enabled"] is False
    assert data["initial_capital"] == 5_000_000
    assert len(data["strategies"]) == 5
    assert all(s["initial_capital"] == 1_000_000 for s in data["strategies"])
    assert data["started_at"] and data["engine"]["last_tick"], "Engine not initialized"
    tick = datetime.fromisoformat(data["engine"]["last_tick"].replace("Z", "+00:00"))
    assert 0 <= (datetime.now(timezone.utc) - tick).total_seconds() <= 90, "Stale heartbeat"
    print(json.dumps({
        "verified": True, "mode": data["mode"], "real_orders_enabled": False,
        "accounts": len(data["strategies"]), "capital": data["initial_capital"],
        "feed": data["feed"]["status"], "started_at": data["started_at"],
        "heartbeat": data["engine"]["last_tick"],
        "entries_enabled": data["engine"]["entries_enabled"],
    }))


if __name__ == "__main__":
    main()
