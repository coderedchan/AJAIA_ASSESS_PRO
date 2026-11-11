"""JSON API. Each route resolves the signed-in user, then calls the service layer,
which makes every access decision."""

from flask import Blueprint, jsonify, request, session

from . import services as svc
from .db import get_db
from .importers import convert_upload

api = Blueprint("api", __name__, url_prefix="/api")


def current_user_id() -> str:
    return svc.require_user(get_db(), session.get("user_id"))["id"]


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise svc.ServiceError("The request body must be a JSON object.")
    return data


@api.errorhandler(svc.ServiceError)
def service_error(err: svc.ServiceError):
    status = 401 if err.extra.get("code") == "signed_out" else err.status
    return jsonify({"error": err.message, **err.extra}), status


# ---------------------------------------------------------------- session (mocked sign-in)


@api.get("/session")
def get_session():
    conn = get_db()
    user = svc._user(conn, session.get("user_id")) if session.get("user_id") else None
    return jsonify({"user": user, "users": svc.list_users(conn)})


@api.post("/session")
def sign_in():
    user = svc.require_user(get_db(), body().get("user_id"))
    session["user_id"] = user["id"]
    return jsonify({"user": user})


@api.delete("/session")
def sign_out():
    session.pop("user_id", None)
    return jsonify({"user": None})


# ---------------------------------------------------------------- documents


@api.get("/documents")
def list_documents():
    return jsonify(svc.dashboard(get_db(), current_user_id()))


@api.post("/documents")
def create_document():
    uid = current_user_id()
    data = request.get_json(silent=True) or {}
    return jsonify(svc.create_document(get_db(), uid, title=data.get("title"))), 201


@api.post("/documents/import")
def import_document():
    uid = current_user_id()
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise svc.ServiceError("Choose a file to import.")
    title, html = convert_upload(upload.filename, upload.read())
    doc = svc.create_document(get_db(), uid, title=title, content_html=html,
                              source_filename=upload.filename)
    return jsonify(doc), 201


@api.get("/documents/<doc_id>")
def get_document(doc_id):
    return jsonify(svc.get_document(get_db(), doc_id, current_user_id()))


@api.patch("/documents/<doc_id>")
def update_document(doc_id):
    uid = current_user_id()
    data = body()
    try:
        base_version = int(data.get("base_version"))
    except (TypeError, ValueError):
        raise svc.ServiceError("base_version is required.") from None
    doc = svc.update_document(
        get_db(), doc_id, uid,
        base_version=base_version,
        title=data.get("title"),
        content_html=data.get("content_html"),
        force=bool(data.get("force")),
    )
    return jsonify(doc)


# ---------------------------------------------------------------- sharing


@api.post("/documents/<doc_id>/access")
def share(doc_id):
    uid = current_user_id()
    shared = svc.share(get_db(), doc_id, uid, body().get("user_id"))
    return jsonify({"shared_with": shared})


@api.delete("/documents/<doc_id>/access/<user_id>")
def unshare(doc_id, user_id):
    uid = current_user_id()
    shared = svc.unshare(get_db(), doc_id, uid, user_id)
    return jsonify({"shared_with": shared})


# ---------------------------------------------------------------- handoff


@api.put("/documents/<doc_id>/handoff")
def save_handoff(doc_id):
    uid = current_user_id()
    data = body()
    h = svc.save_handoff_draft(get_db(), doc_id, uid, data.get("contributor_id"), data.get("instruction"))
    return jsonify(h)


@api.post("/documents/<doc_id>/handoff/<action>")
def handoff_action(doc_id, action):
    uid = current_user_id()
    conn = get_db()
    data = request.get_json(silent=True) or {}
    if action == "send":
        h = svc.send_handoff(conn, doc_id, uid, data.get("contributor_id"), data.get("instruction"))
    elif action == "withdraw":
        h = svc.withdraw_handoff(conn, doc_id, uid)
    elif action == "return":
        h = svc.return_handoff(conn, doc_id, uid, data.get("note"))
    elif action == "close":
        h = svc.start_new_handoff(conn, doc_id, uid)
    else:
        raise svc.NotFound("Unknown handoff action.")
    return jsonify(h)
