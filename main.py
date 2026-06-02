from contextlib import asynccontextmanager
from io import BytesIO

import face_recognition
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from PIL import Image

from attendance_store import AttendanceStore
from camera_worker import CameraWorker
from face_store import FaceStore

store = FaceStore()
attendance = AttendanceStore()
camera = CameraWorker(store, attendance=attendance)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await camera.start()
    yield
    await camera.stop()


app = FastAPI(title="Face Recognition Door System", lifespan=lifespan)


def _decode_image(data: bytes) -> np.ndarray:
    return np.array(Image.open(BytesIO(data)).convert("RGB"))


# ── Face management ────────────────────────────────────────────────────────────

@app.post("/faces", status_code=201)
async def add_face(name: str = Form(...), image: UploadFile = File(...)):
    """
    Register a face in the allowed set.

    Body (multipart/form-data):
      - name  : display name for this person
      - image : photo file containing exactly one face
    """
    img_array = _decode_image(await image.read())
    locations = face_recognition.face_locations(img_array, model="hog")

    if not locations:
        raise HTTPException(400, "No face detected in the uploaded image")
    if len(locations) > 1:
        raise HTTPException(400, "Multiple faces found; upload a photo with one face only")

    encoding = face_recognition.face_encodings(img_array, locations)[0]
    face_id = store.add(name, encoding)
    return {"face_id": face_id, "name": name}


@app.get("/faces")
async def list_faces():
    """Return all registered (allowed) faces."""
    return store.list_faces()


@app.delete("/faces/{face_id}")
async def delete_face(face_id: str):
    """Remove a face from the allowed set by its ID."""
    if not store.remove(face_id):
        raise HTTPException(404, "Face not found")
    return {"deleted": face_id}


# ── Validate an uploaded image ─────────────────────────────────────────────────

@app.post("/validate")
async def validate_face(image: UploadFile = File(...)):
    """
    Check whether a face in the uploaded image belongs to the allowed set.

    Returns access=granted with name/confidence on match, access=denied otherwise.
    """
    img_array = _decode_image(await image.read())
    locations = face_recognition.face_locations(img_array, model="hog")

    if not locations:
        raise HTTPException(400, "No face detected in the uploaded image")

    encoding = face_recognition.face_encodings(img_array, locations)[0]
    face_id, name, confidence = store.find_match(encoding)

    return {
        "access": "granted" if face_id else "denied",
        "recognized": face_id is not None,
        "face_id": face_id,
        "name": name,
        "confidence": confidence,
    }


# ── Real-time camera feed ──────────────────────────────────────────────────────

@app.get("/realtime/status")
async def realtime_status():
    """
    Return the latest recognition result from the live camera feed.

    Fields:
      - camera_available   : whether a camera was found
      - face_detected      : whether a face is currently visible
      - recognized         : whether that face is in the allowed set
      - name / face_id     : identity if recognized
      - confidence         : 0-1 similarity score (1 = perfect match)
      - attendance_marked  : True if a new attendance record was just created
    """
    return camera.state


# ── Attendance ─────────────────────────────────────────────────────────────────

@app.get("/attendance/today")
async def attendance_today():
    """Return every attendance entry recorded today."""
    return attendance.get_today()


@app.get("/attendance/report")
async def attendance_report(date: str = Query(default=None, description="YYYY-MM-DD (default: today)")):
    """
    Return one summary row per employee for the given date.
    Each row includes check_in time, last_seen time, and total_entries.
    """
    return attendance.get_report(date)


@app.get("/attendance/employee/{face_id}")
async def attendance_by_employee(face_id: str):
    """Return full attendance history for a specific employee."""
    records = attendance.get_by_employee(face_id)
    if not records:
        raise HTTPException(404, "No attendance records found for this employee")
    return records


@app.get("/attendance/date/{date_str}")
async def attendance_by_date(date_str: str):
    """Return all attendance entries for a specific date (YYYY-MM-DD)."""
    records = attendance.get_by_date(date_str)
    if not records:
        raise HTTPException(404, f"No attendance records found for {date_str}")
    return records
