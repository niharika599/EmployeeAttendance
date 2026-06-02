import face_recognition
from flask import Blueprint, jsonify, request

from stores import employees, store
from utils import decode_image

employees_bp = Blueprint("employees", __name__, url_prefix="/employees")


@employees_bp.post("/")
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

    img_array = decode_image(request.files["image"].read())
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
        store.remove(face_id)
        return jsonify({"error": str(e)}), 409

    return jsonify({**employee, "face_encoding_size": len(encoding)}), 201


@employees_bp.get("/")
def list_employees():
    """List all employees. Query param: status=active|notice_period|resigned"""
    return jsonify(employees.list(status=request.args.get("status")))


@employees_bp.get("/<employee_id>")
def get_employee(employee_id):
    """Get details for a specific employee."""
    emp = employees.get(employee_id)
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    return jsonify(emp)


@employees_bp.post("/<employee_id>/resign")
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
