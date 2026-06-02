from flask import Blueprint, jsonify, request

from stores import attendance

attendance_bp = Blueprint("attendance", __name__, url_prefix="/attendance")


@attendance_bp.get("/today")
def attendance_today():
    """Return every attendance entry recorded today."""
    return jsonify(attendance.get_today())


@attendance_bp.get("/report")
def attendance_report():
    """
    Return one summary row per employee for the given date.
    Query param: date=YYYY-MM-DD (default: today)
    """
    return jsonify(attendance.get_report(request.args.get("date")))


@attendance_bp.get("/employee/<face_id>")
def attendance_by_employee(face_id):
    """Return full attendance history for a specific employee."""
    records = attendance.get_by_employee(face_id)
    if not records:
        return jsonify({"error": "No attendance records found for this employee"}), 404
    return jsonify(records)


@attendance_bp.get("/date/<date_str>")
def attendance_by_date(date_str):
    """Return all attendance entries for a specific date (YYYY-MM-DD)."""
    records = attendance.get_by_date(date_str)
    if not records:
        return jsonify({"error": f"No attendance records found for {date_str}"}), 404
    return jsonify(records)
