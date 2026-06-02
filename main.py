import threading
import time
from io import BytesIO

import face_recognition
import numpy as np
from flask import Flask, jsonify, request
from PIL import Image

from attendance_store import AttendanceStore
from camera_worker import CameraWorker
from employee_store import EmployeeStore
from face_store import FaceStore

app = Flask(__name__)

store = FaceStore()
attendance = AttendanceStore()
employees = EmployeeStore(store)
camera = CameraWorker(store, attendance=attendance)


def _notice_period_checker():
    """Runs every hour. Revokes face access for employees whose 60-day notice period has ended."""
    while True:
        expired = employees.expire_notice_periods()
        for emp_id in expired:
            print(f"[NoticeChecker] Notice period ended — access revoked for {emp_id}")
        time.sleep(3600)


# Start background threads when the module loads
camera.start()
threading.Thread(target=_notice_period_checker, daemon=True).start()


def _decode_image(data: bytes) -> np.ndarray:
    return np.array(Image.open(BytesIO(data)).convert("RGB"))


# ── Face utilities ─────────────────────────────────────────────────────────────

@app.get("/faces")
def list_faces():
    """Return all registered faces with their employee_id references."""
    return jsonify(store.list_faces())


@app.delete("/faces/<face_id>")
def delete_face(face_id):
    """Remove a face encoding directly by face_id."""
    if not store.remove(face_id):
        return jsonify({"error": "Face not found"}), 404
    return jsonify({"deleted": face_id})


# ── Validate an uploaded photo ─────────────────────────────────────────────────

@app.post("/validate")
def validate_face():
    """
    Check whether a face in the uploaded image belongs to the allowed set.
    Form field: image (file)
    """
    if "image" not in request.files:
        return jsonify({"error": "image file is required"}), 400

    img_array = _decode_image(request.files["image"].read())
    locations = face_recognition.face_locations(img_array, model="hog")

    if not locations:
        return jsonify({"error": "No face detected in the uploaded image"}), 400

    encoding = face_recognition.face_encodings(img_array, locations)[0]
    face_id, name, confidence = store.find_match(encoding)

    return jsonify({
        "access": "granted" if face_id else "denied",
        "recognized": face_id is not None,
        "face_id": face_id,
        "name": name,
        "confidence": confidence,
    })


# ── Real-time camera feed ──────────────────────────────────────────────────────

@app.get("/realtime/status")
def realtime_status():
    """
    Return the latest recognition result from the live camera feed.
    Updated every 0.5s by the background camera thread.
    """
    return jsonify(camera.state)


# ── Attendance ─────────────────────────────────────────────────────────────────

@app.get("/attendance/today")
def attendance_today():
    """Return every attendance entry recorded today."""
    return jsonify(attendance.get_today())


@app.get("/attendance/report")
def attendance_report():
    """
    Return one summary row per employee for the given date.
    Query param: date=YYYY-MM-DD (default: today)
    """
    return jsonify(attendance.get_report(request.args.get("date")))


@app.get("/attendance/employee/<face_id>")
def attendance_by_employee(face_id):
    """Return full attendance history for a specific employee."""
    records = attendance.get_by_employee(face_id)
    if not records:
        return jsonify({"error": "No attendance records found for this employee"}), 404
    return jsonify(records)


@app.get("/attendance/date/<date_str>")
def attendance_by_date(date_str):
    """Return all attendance entries for a specific date (YYYY-MM-DD)."""
    records = attendance.get_by_date(date_str)
    if not records:
        return jsonify({"error": f"No attendance records found for {date_str}"}), 404
    return jsonify(records)


# ── Employee management ────────────────────────────────────────────────────────

@app.post("/employees")
def create_employee():
    """
    Register a new employee with their details and face photo.

    Form fields:
      - employee_id  (required)
      - name         (required)
      - image        (required — file upload)
      - email        (optional)
      - department   (optional)
      - phone        (optional)
      - designation  (optional)
    """
    employee_id = request.form.get("employee_id")
    name = request.form.get("name")

    if not employee_id or not name:
        return jsonify({"error": "employee_id and name are required"}), 400
    if "image" not in request.files:
        return jsonify({"error": "image file is required"}), 400

    img_array = _decode_image(request.files["image"].read())
    locations = face_recognition.face_locations(img_array, model="hog")

    if not locations:
        return jsonify({"error": "No face detected in the uploaded image"}), 400
    if len(locations) > 1:
        return jsonify({"error": "Multiple faces found; upload a photo with one face only"}), 400

    encoding = face_recognition.face_encodings(img_array, locations)[0]
    face_id = store.add(name, encoding, employee_id=employee_id)

    try:
        employee = employees.register(
            employee_id=employee_id,
            name=name,
            face_id=face_id,
            email=request.form.get("email"),
            department=request.form.get("department"),
            phone=request.form.get("phone"),
            designation=request.form.get("designation"),
        )
    except ValueError as e:
        store.remove(face_id)   # rollback face if employee_id is duplicate
        return jsonify({"error": str(e)}), 409

    return jsonify({**employee, "face_encoding_size": len(encoding)}), 201


@app.get("/employees")
def list_employees():
    """List all employees. Query param: status=active|notice_period|resigned"""
    return jsonify(employees.list(status=request.args.get("status")))


@app.get("/employees/<employee_id>")
def get_employee(employee_id):
    """Get details for a specific employee."""
    emp = employees.get(employee_id)
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    return jsonify(emp)


@app.post("/employees/<employee_id>/resign")
def resign_employee(employee_id):
    """
    Begin the 60-day notice period. Face access is retained during this period
    and revoked automatically when it ends.
    """
    try:
        emp = employees.resign(employee_id)
    except KeyError:
        return jsonify({"error": "Employee not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    return jsonify({
        "message": f"{emp['name']} resignation recorded. Face access will be revoked on {emp['notice_ends_at'][:10]}.",
        "employee": emp,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
