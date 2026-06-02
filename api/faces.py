from flask import Blueprint, jsonify

from stores import store

faces_bp = Blueprint("faces", __name__, url_prefix="/faces")


@faces_bp.get("/")
def list_faces():
    """Return all registered faces with their employee_id references."""
    return jsonify(store.list_faces())


@faces_bp.delete("/<face_id>")
def delete_face(face_id):
    """Remove a face encoding directly by face_id."""
    if not store.remove(face_id):
        return jsonify({"error": "Face not found"}), 404
    return jsonify({"deleted": face_id})
