import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from face_store import FaceStore

EMPLOYEE_FILE = Path("employees_db.json")


class EmployeeStore:
    def __init__(self, face_store: FaceStore):
        self.face_store = face_store
        self._lock = threading.Lock()
        self.employees: dict = {}  # {employee_id: {...}}
        self._load()

    def _load(self):
        if EMPLOYEE_FILE.exists():
            with open(EMPLOYEE_FILE) as f:
                self.employees = json.load(f)

    def _save(self):
        with open(EMPLOYEE_FILE, "w") as f:
            json.dump(self.employees, f, indent=2)

    # ── Write ──────────────────────────────────────────────────────────────────

    def register(self, employee_id: str, name: str, face_id: str) -> dict:
        with self._lock:
            if employee_id in self.employees:
                raise ValueError(f"Employee ID '{employee_id}' already exists")
            record = {
                "employee_id": employee_id,
                "name": name,
                "face_id": face_id,
                "status": "active",
                "joined_at": datetime.now().isoformat(),
                "resigned_at": None,
            }
            self.employees[employee_id] = record
            self._save()
            return record

    def resign(self, employee_id: str) -> dict:
        """
        Mark employee as resigned and automatically remove their face
        from the allowed set so they can no longer be recognized.
        """
        with self._lock:
            if employee_id not in self.employees:
                raise KeyError(employee_id)
            emp = self.employees[employee_id]
            if emp["status"] == "resigned":
                raise ValueError(f"Employee '{employee_id}' is already resigned")

            self.face_store.remove(emp["face_id"])

            emp["status"] = "resigned"
            emp["resigned_at"] = datetime.now().isoformat()
            self._save()
            return dict(emp)

    # ── Read ───────────────────────────────────────────────────────────────────

    def get(self, employee_id: str) -> Optional[dict]:
        with self._lock:
            emp = self.employees.get(employee_id)
            return dict(emp) if emp else None

    def list(self, status: Optional[str] = None) -> list:
        with self._lock:
            records = list(self.employees.values())
        if status:
            records = [r for r in records if r["status"] == status]
        return records
