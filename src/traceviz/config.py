import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    geo_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "traceviz.db"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("TRACEVIZ_DATA_DIR") or Path.home() / ".local/share/traceviz")
        geo_dir = Path(os.environ.get("TRACEVIZ_GEO_DIR") or data_dir / "geo")
        return cls(data_dir=data_dir, geo_dir=geo_dir)
