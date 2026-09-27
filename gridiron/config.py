"""설정 파일 로더. 모든 튜닝 값은 `config/` 아래 YAML에 둔다 (PRD N4)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


@lru_cache(maxsize=None)
def load(name: str) -> Any:
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
