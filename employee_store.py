import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from face_store import FaceStore

EMPLOYEE_FILE = Path("employees_db.json")
NOTICE_PERIOD_DAYS = 60


class EmployeeStore:
    def __init__(self, face_store: FaceStore):
        self.face_store = face_store
        self._lock = threading.Lock()
        self.employees: dict = {}
        self._load()

    def _load(self):
        if EMPLOYEE_FILE.exists():
            with open(EMPLOYEE_FILE) as f:
                self.employees = json.load(f)

    def _save(self):
        with open(EMPLOYEE_FILE, "w") as f:
            json.dump(self.employees, f, indent=2)

    # ── Write ──────────────────────────────────────────────────────────────────

    def register(
        self,
        employee_id: str,
        name: str,
        face_id: str,
        email: Optional[str] = None,
        department: Optional[str] = None,
        phone: Optional[str] = None,
        designation: Optional[str] = None,
    ) -> dict:
        with self._lock:
            if employee_id in self.employees:
                raise ValueError(f"Employee ID '{employee_id}' already exists")
            record = {
                "employee_id": employee_id,
                "name": name,
                "email": email,
                "department": department,
                "phone": phone,
                "designation": designation,
                "face_id": face_id,
                "status": "active",
                "joined_at": datetime.now().isoformat(),
                "resigned_at": None,
                "notice_ends_at": None,
            }
            self.employees[employee_id] = record
            self._save()
            return record

    def resign(self, employee_id: str) -> dict:
        """
        Begin the resignation process. Sets status to notice_period and
        schedules face removal after NOTICE_PERIOD_DAYS days.
        The employee retains camera access until the notice period ends.
        """
        with self._lock:
            if employee_id not in self.employees:
                raise KeyError(employee_id)
            emp = self.employees[employee_id]
            if emp["status"] in ("notice_period", "resigned"):
                raise ValueError(f"Employee '{employee_id}' has already resigned")

            now = datetime.now()
            emp["status"] = "notice_period"
            emp["resigned_at"] = now.isoformat()
            emp["notice_ends_at"] = (now + timedelta(days=NOTICE_PERIOD_DAYS)).isoformat()
            self._save()
            return dict(emp)

    def expire_notice_periods(self) -> list:
        """
        Called hourly. Removes face access for employees whose notice period
        has ended and marks them as resigned.
        Returns list of expired employee_ids.
        """
        now = datetime.now()
        expired = []
        with self._lock:
            for emp_id, emp in self.employees.items():
                if emp["status"] == "notice_period":
                    if now >= datetime.fromisoformat(emp["notice_ends_at"]):
                        self.face_store.remove(emp["face_id"])
                        emp["status"] = "resigned"
                        expired.append(emp_id)
            if expired:
                self._save()
        return expired

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
