"""Local property watchlists: stored search criteria + new-listing diffing.

Watches are OUR feature, not Zameen's account feature: criteria are stored in
``data/watches.json`` and ``check`` simply re-runs the (read-only) search and
reports listings whose ids were not seen before. Nothing is written to
Zameen.com by this module.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

def _watches_file() -> Path:
    """Per-user watches store: $ZAMEEN_MCP_HOME if set, else ~/.zameen-mcp."""
    import os

    env = os.environ.get("ZAMEEN_MCP_HOME")
    base = Path(env) if env else Path.home() / ".zameen-mcp"
    return base / "watches.json"


WATCHES_FILE = _watches_file()


def _load(path: Optional[Path] = None) -> Dict[str, dict]:
    p = Path(path or WATCHES_FILE)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("unreadable watches file: %s", p)
        return {}
    return data if isinstance(data, dict) else {}


def _save(watches: Dict[str, dict], path: Optional[Path] = None) -> None:
    p = Path(path or WATCHES_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(watches, indent=2), encoding="utf-8")


def add(name: str, criteria: Dict[str, object],
        seed_ids: Optional[List[str]] = None,
        path: Optional[Path] = None) -> dict:
    """Create a watch; raises ValueError on duplicate or blank name."""
    name = (name or "").strip()
    if not name:
        raise ValueError("watch name must be non-empty")
    watches = _load(path)
    if name in watches:
        raise ValueError(f"watch {name!r} already exists; remove it first")
    entry = {
        "criteria": criteria,
        "last_ids": list(seed_ids or []),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_checked_at": None,
    }
    watches[name] = entry
    _save(watches, path)
    return dict(entry)


def remove(name: str, path: Optional[Path] = None) -> bool:
    watches = _load(path)
    if name not in watches:
        return False
    del watches[name]
    _save(watches, path)
    return True


def get(name: str, path: Optional[Path] = None) -> Optional[dict]:
    return _load(path).get(name)


def names(path: Optional[Path] = None) -> Dict[str, dict]:
    """Summary view: criteria + timestamps without the bulky id lists."""
    return {
        name: {
            "criteria": entry.get("criteria", {}),
            "created_at": entry.get("created_at"),
            "last_checked_at": entry.get("last_checked_at"),
            "known_listing_count": len(entry.get("last_ids", [])),
        }
        for name, entry in _load(path).items()
    }


def diff(previous_ids: List[str], current_ids: List[str]) -> List[str]:
    """Ids in *current_ids* that are not in *previous_ids*, order preserved."""
    seen = set(previous_ids or [])
    return [i for i in current_ids if i not in seen]


def record_check(name: str, current_ids: List[str],
                 path: Optional[Path] = None) -> None:
    watches = _load(path)
    if name in watches:
        watches[name]["last_ids"] = list(current_ids)
        watches[name]["last_checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save(watches, path)
