"""持久化配置读写"""
import json
from pathlib import Path
import sys as _sys

CONFIG_FILE = Path(_sys.argv[0]).parent / "topohelper.json"


def save(key: str, url: str, model: str):
    try:
        CONFIG_FILE.write_text(
            json.dumps({"key": key, "url": url, "model": model}), encoding="utf-8"
        )
    except Exception:
        pass


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
