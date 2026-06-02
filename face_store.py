import json
import threading
import uuid
from pathlib import Path

import face_recognition
import numpy as np

STORE_FILE = Path("faces_db.json")


class FaceStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.faces: dict = {}  # {id: {"name": str, "encoding": list[float]}}
        self._load()

    def _load(self):
        if STORE_FILE.exists():
            with open(STORE_FILE) as f:
                self.faces = json.load(f)

    def _save(self):
        with open(STORE_FILE, "w") as f:
            json.dump(self.faces, f)

    def add(self, name: str, encoding: np.ndarray, employee_id: str | None = None) -> str:
        face_id = str(uuid.uuid4())
        with self._lock:
            self.faces[face_id] = {
                "name": name,
                "employee_id": employee_id,
                "encoding": encoding.tolist(),
            }
            self._save()
        return face_id

    def remove(self, face_id: str) -> bool:
        with self._lock:
            if face_id not in self.faces:
                return False
            del self.faces[face_id]
            self._save()
        return True

    def list_faces(self) -> dict:
        with self._lock:
            return {
                fid: {
                    "id": fid,
                    "name": data["name"],
                    "employee_id": data.get("employee_id"),
                }
                for fid, data in self.faces.items()
            }

    def find_match(self, unknown_encoding: np.ndarray, tolerance: float = 0.6):
        with self._lock:
            if not self.faces:
                return None, None, None

            known_ids = list(self.faces.keys())
            known_encodings = [np.array(self.faces[fid]["encoding"]) for fid in known_ids]

            distances = face_recognition.face_distance(known_encodings, unknown_encoding)
            best_idx = int(np.argmin(distances))
            best_distance = float(distances[best_idx])

            if best_distance <= tolerance:
                fid = known_ids[best_idx]
                return fid, self.faces[fid]["name"], round(1 - best_distance, 3)

            return None, None, None
