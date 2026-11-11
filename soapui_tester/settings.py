# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferences utilisateur persistees sur disque, independantes du projet
SoapUI charge (ex : historique des valeurs deja utilisees pour chaque
propriete de projet, pour pouvoir re-selectionner par ex. plusieurs
baseUrl differents sans les retaper)."""
import json
from pathlib import Path

_SETTINGS_DIR = Path.home() / ".soapui_tester"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"
_MAX_PROPERTY_HISTORY = 15


def _load() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_property_history() -> dict:
    return dict(_load().get("property_history", {}))


def remember_property_value(name: str, value: str) -> None:
    name = name.strip()
    value = value.strip()
    if not name or not value:
        return
    data = _load()
    histories = data.setdefault("property_history", {})
    history = [v for v in histories.get(name, []) if v != value]
    history.insert(0, value)
    histories[name] = history[:_MAX_PROPERTY_HISTORY]
    _save(data)
