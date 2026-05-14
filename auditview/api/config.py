from flask import Blueprint, jsonify, current_app

bp = Blueprint("config", __name__)


@bp.route("/config", methods=["GET"])
def get_config():
    return jsonify({
        "root_path": current_app.config["ROOT_PATH"],
        "db_path": current_app.config["DB_PATH"],
    })
