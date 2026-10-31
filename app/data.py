from __future__ import annotations
import csv
from pathlib import Path
from typing import Any
from app.config import settings

TABLES = {
    "products": "products.csv",
    "customers": "customers.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "pincodes": "pincodes.csv",
    "holidays": "holidays.csv",
    "support_logs": "support_logs.csv",
}
EXPECTED_COUNTS = {
    "products": 70, "customers": 300, "orders": 1000, "order_items": 1783,
    "pincodes": 36, "holidays": 4, "support_logs": 244,
}

def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]

class Dataset:
    """Read-only CSV repository. All cells remain strings to preserve IDs and pincodes."""
    def __init__(self, root: Path | None = None):
        self.root = Path(root or settings.dataset_dir)
        self._cache: dict[str, list[dict[str, str]]] = {}

    def table(self, name: str) -> list[dict[str, str]]:
        if name not in TABLES:
            raise ValueError(f"Unsupported table: {name}")
        if name not in self._cache:
            path = self.root / "data" / TABLES[name]
            if not path.is_file():
                raise FileNotFoundError(f"Required dataset file is missing: {path}")
            self._cache[name] = read_csv_rows(path)
        return [dict(row) for row in self._cache[name]]

    def products(self) -> list[dict[str, str]]:
        return self.table("products")

    def holidays(self) -> set[str]:
        return {r["date"] for r in self.table("holidays") if r.get("date")}

    def health(self) -> dict[str, Any]:
        missing = [f"data/{filename}" for filename in TABLES.values()
                   if not (self.root / "data" / filename).is_file()]
        kb = self.root / "kb"
        return {"available": not missing and kb.is_dir(), "missing_files": missing,
                "knowledge_base_available": kb.is_dir()}

dataset = Dataset()
