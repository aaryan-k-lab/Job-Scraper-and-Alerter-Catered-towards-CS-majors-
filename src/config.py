from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"


def load_settings(path: Path = CONFIG_DIR / "settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_targets(path: Path = CONFIG_DIR / "target_companies.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {"tier1": data.get("tier1") or [], "tier2": data.get("tier2") or []}
