from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os

from recommendation import get_recommendations, load_products, load_profiles

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/api/products", methods=["GET"])
def api_products():
    return jsonify(load_products())


@app.route("/api/profiles", methods=["GET"])
def api_profiles():
    return jsonify(load_profiles())


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    """
    Body: {"query": "free text request"} OR {"profile_id": "U01"} OR {} for cold start.
    Optional: {"category": "laptop"} to hint/restrict category.
    """
    body = request.get_json(silent=True) or {}
    query = body.get("query", "")
    category_hint = body.get("category")

    if not query and body.get("profile_id"):
        profiles = load_profiles()
        match = next((p for p in profiles if p["id"] == body["profile_id"]), None)
        if match:
            query = match["query"]

    try:
        result = get_recommendations(query, category_hint=category_hint, top_n=5)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)




# from flask import Flask, jsonify, request, send_from_directory
# from flask_cors import CORS
# import os

# from recommendation import get_recommendations, load_products, load_profiles

# FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

# app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
# CORS(app)


# @app.route("/")
# def index():
#     return send_from_directory(FRONTEND_DIR, "index.html")


# @app.route("/api/products", methods=["GET"])
# def api_products():
#     return jsonify(load_products())


# @app.route("/api/profiles", methods=["GET"])
# def api_profiles():
#     return jsonify(load_profiles())


# @app.route("/api/recommend", methods=["POST"])
# def api_recommend():
#     """
#     Body: {"query": "free text request"} OR {"profile_id": "U01"} OR {} for cold start.
#     Optional: {"category": "laptop"} to hint/restrict category.
#     """
#     body = request.get_json(silent=True) or {}
#     query = body.get("query", "")
#     category_hint = body.get("category")

#     if not query and body.get("profile_id"):
#         profiles = load_profiles()
#         match = next((p for p in profiles if p["id"] == body["profile_id"]), None)
#         if match:
#             query = match["query"]

#     try:
#         result = get_recommendations(query, category_hint=category_hint, top_n=5)
#         return jsonify(result)
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


# if __name__ == "__main__":
#     app.run(debug=True, port=5000)
