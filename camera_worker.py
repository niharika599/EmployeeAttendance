import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import cv2
import face_recognition

from attendance_store import AttendanceStore
from face_store import FaceStore

_IDLE = {
    "camera_available": False,
    "face_detected": False,
    "recognized": False,
    "name": None,
    "face_id": None,
    "confidence": None,
    "attendance_marked": False,
}


class CameraWorker:
    """Background async worker that continuously reads the camera and runs face recognition."""

    def __init__(
        self,
        store: FaceStore,
        attendance: Optional[AttendanceStore] = None,
        camera_index: int = 0,
        interval: float = 0.5,
    ):
        self.store = store
        self.attendance = attendance
        self.camera_index = camera_index
        self.interval = interval
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._task: asyncio.Task | None = None
        self.running = False
        self._lock = threading.Lock()
        self._state: dict = dict(_IDLE)

    # ── blocking capture (runs in thread pool) ─────────────────────────────────

    def _capture_and_recognize(self) -> dict:
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            return dict(_IDLE)

        ret, frame = cap.read()
        cap.release()

        if not ret:
            return {**_IDLE, "camera_available": True}

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")

        if not locations:
            return {**_IDLE, "camera_available": True}

        encodings = face_recognition.face_encodings(rgb, locations)
        if not encodings:
            return {**_IDLE, "camera_available": True, "face_detected": True}

        face_id, name, confidence = self.store.find_match(encodings[0])

        attendance_marked = False
        if face_id and self.attendance:
            record = self.attendance.mark(face_id, name)
            attendance_marked = record is not None

        return {
            "camera_available": True,
            "face_detected": True,
            "recognized": face_id is not None,
            "name": name,
            "face_id": face_id,
            "confidence": confidence,
            "attendance_marked": attendance_marked,
        }

    # ── async loop ─────────────────────────────────────────────────────────────

    async def _loop(self):
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                result = await loop.run_in_executor(self._executor, self._capture_and_recognize)
                with self._lock:
                    self._state = result
            except Exception as exc:
                print(f"[CameraWorker] {exc}")
            await asyncio.sleep(self.interval)

    async def start(self):
        self.running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @property
    def state(self) -> dict:
        with self._lock:
            return dict(self._state)
