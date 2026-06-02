import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

ATTENDANCE_FILE = Path("attendance_db.json")
DEFAULT_COOLDOWN_MINUTES = 5  # ignore re-entries for same person within this window


class AttendanceStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.records: list[dict] = []
        self._load()

    def _load(self):
        if ATTENDANCE_FILE.exists():
            with open(ATTENDANCE_FILE) as f:
                self.records = json.load(f)

    def _save(self):
        with open(ATTENDANCE_FILE, "w") as f:
            json.dump(self.records, f, indent=2)

    # ── Write ──────────────────────────────────────────────────────────────────

    def mark(self, face_id: str, name: str, cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES) -> dict | None:
        """
        Record an attendance entry for face_id/name.
        Returns the new record, or None if the same person was seen within cooldown_minutes.
        """
        now = datetime.now()
        with self._lock:
            # Check cooldown: scan backwards for the last entry of this person
            for record in reversed(self.records):
                if record["face_id"] == face_id:
                    last_seen = datetime.fromisoformat(record["timestamp"])
                    if (now - last_seen).total_seconds() < cooldown_minutes * 60:
                        return None
                    break

            record = {
                "id": str(uuid.uuid4()),
                "face_id": face_id,
                "name": name,
                "timestamp": now.isoformat(),
                "date": now.date().isoformat(),
                "time": now.strftime("%H:%M:%S"),
            }
            self.records.append(record)
            self._save()
            return record

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_today(self) -> list[dict]:
        today = date.today().isoformat()
        with self._lock:
            return [r for r in self.records if r["date"] == today]

    def get_by_date(self, date_str: str) -> list[dict]:
        with self._lock:
            return [r for r in self.records if r["date"] == date_str]

    def get_by_employee(self, face_id: str) -> list[dict]:
        with self._lock:
            return sorted(
                [r for r in self.records if r["face_id"] == face_id],
                key=lambda r: r["timestamp"],
                reverse=True,
            )

    def get_report(self, date_str: str | None = None) -> list[dict]:
        """
        Returns one summary row per employee for the given date (default: today).
        Each row has check_in (first seen), last_seen, and total_entries.
        """
        target = date_str or date.today().isoformat()
        with self._lock:
            day_records = [r for r in self.records if r["date"] == target]

        employees: dict[str, dict] = {}
        for r in day_records:
            fid = r["face_id"]
            if fid not in employees:
                employees[fid] = {"name": r["name"], "face_id": fid, "timestamps": []}
            employees[fid]["timestamps"].append(r["timestamp"])

        report = []
        for fid, data in employees.items():
            timestamps = sorted(data["timestamps"])
            report.append({
                "face_id": fid,
                "name": data["name"],
                "date": target,
                "check_in": timestamps[0],
                "last_seen": timestamps[-1],
                "total_entries": len(timestamps),
            })

        return sorted(report, key=lambda r: r["check_in"])
