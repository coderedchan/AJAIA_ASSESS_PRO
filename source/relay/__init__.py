"""Relay Docs: a small document editor with explicit handoffs between teammates."""

import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from . import db
from .api import api
from .importers import MAX_UPLOAD_BYTES


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    data_dir = os.environ.get("RELAY_DATA_DIR", os.path.join(app.root_path, "..", "data"))
    app.config.update(
        DATABASE=os.path.join(data_dir, "relay.sqlite3"),
        SECRET_KEY=os.environ.get("RELAY_SECRET_KEY", "dev-only-secret-change-me"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 64 * 1024,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
    )
    if config:
        app.config.update(config)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    db.init_db(app.config["DATABASE"], seed=app.config.get("SEED", True))
    app.teardown_appcontext(db.close_db)
    app.register_blueprint(api)

    @app.get("/")
    @app.get("/d/<doc_id>")
    def shell(doc_id=None):
        return render_template("index.html")

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_err):
        return jsonify({"error": "Files can be up to 2 MB."}), 413

    @app.errorhandler(HTTPException)
    def http_error(err):
        if request.path.startswith("/api/"):
            return jsonify({"error": err.description}), err.code
        return err

    @app.cli.command("reset-demo")
    def reset_demo():
        """Delete all data and restore the seeded users and demo document."""
        conn = db.connect(app.config["DATABASE"])
        db.seed_demo(conn, reset=True)
        conn.commit()
        conn.close()
        print("Demo data restored.")

    return app
