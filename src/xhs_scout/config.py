from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    db_path: Path
    capture_dir: Path
    reports_dir: Path
    emulator_config_path: Path

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        base = (root or Path(__file__).resolve().parents[2]).resolve()
        data_dir = base / "data"
        settings = cls(
            root=base,
            data_dir=data_dir,
            db_path=data_dir / "xhs_scout.sqlite3",
            capture_dir=data_dir / "captures",
            reports_dir=data_dir / "reports",
            emulator_config_path=base / "config" / "emulator.json",
        )
        for path in (settings.data_dir, settings.capture_dir, settings.reports_dir):
            path.mkdir(parents=True, exist_ok=True)
        settings.emulator_config_path.parent.mkdir(parents=True, exist_ok=True)
        return settings

    def emulator_config(self) -> dict:
        if not self.emulator_config_path.exists():
            return {}
        return json.loads(self.emulator_config_path.read_text(encoding="utf-8"))

    def vision_fields_config(self) -> dict:
        path = self.root / "config" / "vision_fields.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("config/vision_fields.json 顶层必须是对象")
        return payload
