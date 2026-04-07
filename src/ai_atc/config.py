import json
import os
from pathlib import Path
from typing import Any, Dict

SETTINGS_FILE = Path("settings.json")

DEFAULT_SETTINGS = {
    "xplane_path": "",
    "simbrief_username": "",
    "callsign": "N12345",
    "theme": "dark",
}

class AIATCConfig:
    def __init__(self):
        self.settings: Dict[str, Any] = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r") as f:
                    loaded = json.load(f)
                    self.settings.update(loaded)
            except Exception:
                pass

    def save(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f, indent=4)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        self.settings[key] = value
        self.save()

# Global config instance
config = AIATCConfig()
