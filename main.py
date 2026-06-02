from contextlib import asynccontextmanager
from io import BytesIO

import face_recognition
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

from camera_worker import CameraWorker
from face_store import FaceStore

store = FaceStore()
camera = CameraWorker(store)


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

    The camera worker runs asynchronously every 0.5 s and updates this state.
    Fields:
      - camera_available : whether a camera was found
      - face_detected    : whether a face is currently visible
      - recognized       : whether that face is in the allowed set
      - name / face_id   : identity if recognized
      - confidence       : 0-1 similarity score (1 = perfect match)
    """
    return camera.state
