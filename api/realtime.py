from flask import Blueprint, jsonify

from stores import camera

realtime_bp = Blueprint("realtime", __name__, url_prefix="/realtime")


@realtime_bp.get("/status")
def realtime_status():
    """
    Return the latest recognition result from the live camera feed.
    Updated every 0.5s by the background camera thread.
    """
    return jsonify(camera.state)
