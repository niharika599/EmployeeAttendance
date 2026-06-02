import face_recognition
from flask import Blueprint, jsonify, request

from stores import store
from utils import decode_image

validate_bp = Blueprint("validate", __name__)


@validate_bp.post("/validate")
def validate_face():
    """
    Check whether a face in the uploaded image belongs to the allowed set.
    Form field: image (file)
    """
    if "image" not in request.files:
        return jsonify({"error": "image file is required"}), 400

    img_array = decode_image(request.files["image"].read())
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
