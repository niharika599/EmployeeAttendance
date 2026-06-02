import threading
import time

from flask import Flask, jsonify

from api.attendance import attendance_bp
from api.employees import employees_bp
from api.faces import faces_bp
from api.realtime import realtime_bp
from api.validate import validate_bp
from stores import camera, employees


def _notice_period_checker():
    """Daemon thread — revokes face access once 60-day notice periods expire."""
    while True:
        expired = employees.expire_notice_periods()
        for emp_id in expired:
            print(f"[NoticeChecker] Notice period ended — access revoked for {emp_id}")
        time.sleep(3600)


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Blueprints ─────────────────────────────────────────────────────────────
    app.register_blueprint(faces_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(validate_bp)
    app.register_blueprint(realtime_bp)

    # ── Centralised error handlers ─────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request", "detail": str(e)}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


# ── Background threads (start once at process boot) ────────────────────────────
camera.start()
threading.Thread(target=_notice_period_checker, daemon=True).start()

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
