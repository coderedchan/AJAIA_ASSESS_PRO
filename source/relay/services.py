"""Document, sharing and handoff rules.

Every protected operation goes through `load_for(...)`, which is the single place
where read/write access is decided. Ownership (documents.owner_id), access grants
(document_access) and the handoff (handoffs) are three separate records, and no
handoff action writes to the first two.
"""

import uuid

from .db import now_iso
from .sanitize import clean_html, html_to_excerpt

TITLE_MAX = 120
INSTRUCTION_MAX = 200
NOTE_MAX = 500
# One limit for document content, applied when a file is imported and on every save,
# so an imported document can always be saved again after editing.
CONTENT_MAX_BYTES = 1_000_000
TOO_LARGE = "This document has more than 1 MB of content, which is the limit for one document."
DEFAULT_TITLE = "Untitled document"


class ServiceError(Exception):
    status = 400

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra


class NotFound(ServiceError):
    status = 404


class Forbidden(ServiceError):
    status = 403


class Conflict(ServiceError):
    status = 409


# ---------------------------------------------------------------- helpers


def _user(conn, user_id):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY rowid")]


def require_user(conn, user_id):
    user = _user(conn, user_id) if user_id else None
    if not user:
        raise ServiceError("Choose a user to continue.", code="signed_out")
    return user


def clean_title(raw) -> str:
    title = " ".join(str(raw or "").split())
    if not title:
        raise ServiceError("The title cannot be empty.")
    if len(title) > TITLE_MAX:
        raise ServiceError(f"Titles can be up to {TITLE_MAX} characters.")
    return title


def has_access(conn, doc_id, user_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM documents d WHERE d.id = ? AND (d.owner_id = ? OR EXISTS ("
        " SELECT 1 FROM document_access a WHERE a.document_id = d.id AND a.user_id = ?))",
        (doc_id, user_id, user_id),
    ).fetchone()
    return row is not None


def load_for(conn, doc_id, user_id, owner_only=False):
    """Return the document row if the user may act on it.

    Users without access get NotFound rather than Forbidden, so the API does not
    reveal which document ids exist.
    """
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None or not has_access(conn, doc_id, user_id):
        raise NotFound("This document does not exist or has not been shared with you.")
    if owner_only and doc["owner_id"] != user_id:
        raise Forbidden("Only the document owner can do this.")
    return doc


def _log(conn, doc_id, actor_id, action, detail=""):
    conn.execute(
        "INSERT INTO handoff_events (document_id, actor_id, action, detail, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (doc_id, actor_id, action, detail, now_iso()),
    )


# ---------------------------------------------------------------- documents


def create_document(conn, user_id, title=None, content_html="", source_filename=None):
    title = clean_title(title) if title else DEFAULT_TITLE
    content = clean_html(content_html)
    if len(content.encode("utf-8")) > CONTENT_MAX_BYTES:
        raise ServiceError(TOO_LARGE)
    doc_id = uuid.uuid4().hex[:12]
    ts = now_iso()
    conn.execute(
        "INSERT INTO documents (id, title, content_html, owner_id, source_filename,"
        " created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (doc_id, title, content, user_id, source_filename, ts, ts, user_id),
    )
    conn.commit()
    return get_document(conn, doc_id, user_id)


def update_document(conn, doc_id, user_id, *, base_version, title=None, content_html=None, force=False):
    """Save title and/or content. Owner and shared users can edit.

    `base_version` is the version the client loaded. If someone saved in between,
    the save is refused with Conflict unless the client chose to overwrite.
    """
    doc = load_for(conn, doc_id, user_id)
    if not force and base_version != doc["version"]:
        _raise_conflict(conn, doc_id, user_id)
    fields, values = [], []
    if title is not None:
        fields.append("title = ?")
        values.append(clean_title(title))
    if content_html is not None:
        if len(content_html.encode("utf-8")) > CONTENT_MAX_BYTES:
            raise ServiceError(TOO_LARGE)
        fields.append("content_html = ?")
        values.append(clean_html(content_html))
    if not fields:
        raise ServiceError("Nothing to save.")
    fields += ["version = version + 1", "updated_at = ?", "updated_by = ?"]
    values += [now_iso(), user_id, doc_id]
    # The version check is repeated inside the UPDATE. Two requests can both pass the
    # check above before either writes; only the first matches this predicate, and the
    # second gets Conflict instead of silently replacing the first person's text.
    sql = f"UPDATE documents SET {', '.join(fields)} WHERE id = ?"
    if not force:
        sql += " AND version = ?"
        values.append(base_version)
    cur = conn.execute(sql, values)
    conn.commit()
    if cur.rowcount == 0:
        _raise_conflict(conn, doc_id, user_id)
    return get_document(conn, doc_id, user_id)


def _raise_conflict(conn, doc_id, user_id):
    latest = get_document(conn, doc_id, user_id)
    raise Conflict(
        f"{latest['updated_by_name']} saved a newer version while you were editing.",
        latest=latest,
    )


def get_document(conn, doc_id, user_id):
    doc = dict(load_for(conn, doc_id, user_id))
    owner = _user(conn, doc["owner_id"])
    doc["owner"] = owner
    doc["updated_by_name"] = _user(conn, doc["updated_by"])["name"]
    doc["role"] = "owner" if doc["owner_id"] == user_id else "editor"
    doc["shared_with"] = shared_users(conn, doc_id)
    doc["handoff"] = get_handoff(conn, doc_id)
    return doc


def shared_users(conn, doc_id):
    rows = conn.execute(
        "SELECT u.*, a.granted_at FROM document_access a JOIN users u ON u.id = a.user_id"
        " WHERE a.document_id = ? ORDER BY u.name",
        (doc_id,),
    )
    return [dict(r) for r in rows]


def dashboard(conn, user_id):
    rows = conn.execute(
        "SELECT d.*, u.name AS owner_name, ub.name AS updated_by_name,"
        " h.status AS h_status, h.contributor_id AS h_contributor, h.instruction AS h_instruction,"
        " h.return_note AS h_note, hc.name AS h_contributor_name, h.updated_at AS h_updated_at"
        " FROM documents d"
        " JOIN users u ON u.id = d.owner_id"
        " JOIN users ub ON ub.id = d.updated_by"
        " LEFT JOIN handoffs h ON h.document_id = d.id"
        " LEFT JOIN users hc ON hc.id = h.contributor_id"
        " WHERE d.owner_id = ? OR d.id IN (SELECT document_id FROM document_access WHERE user_id = ?)"
        " ORDER BY d.updated_at DESC",
        (user_id, user_id),
    ).fetchall()

    owned, shared, actions = [], [], []
    for r in rows:
        item = {
            "id": r["id"],
            "title": r["title"],
            "excerpt": html_to_excerpt(r["content_html"]),
            "owner_name": r["owner_name"],
            "updated_at": r["updated_at"],
            "updated_by_name": r["updated_by_name"],
            "handoff_status": r["h_status"],
            "handoff_contributor": r["h_contributor_name"],
        }
        is_owner = r["owner_id"] == user_id
        (owned if is_owner else shared).append(item)

        # "Your next actions": what this user is responsible for right now.
        if r["h_status"] == "awaiting" and r["h_contributor"] == user_id:
            actions.append({**item, "kind": "respond", "from_name": r["owner_name"],
                            "instruction": r["h_instruction"], "since": r["h_updated_at"]})
        elif r["h_status"] == "returned" and is_owner:
            actions.append({**item, "kind": "review", "from_name": r["h_contributor_name"],
                            "instruction": r["h_instruction"], "note": r["h_note"],
                            "since": r["h_updated_at"]})
        elif r["h_status"] == "draft" and is_owner and r["h_contributor"]:
            actions.append({**item, "kind": "send", "from_name": None,
                            "instruction": r["h_instruction"], "since": r["h_updated_at"]})

    order = {"respond": 0, "review": 1, "send": 2}
    actions.sort(key=lambda a: (order[a["kind"]], a["since"]), reverse=False)
    return {"actions": actions, "owned": owned, "shared": shared}


# ---------------------------------------------------------------- sharing


def share(conn, doc_id, owner_id, recipient_id):
    doc = load_for(conn, doc_id, owner_id, owner_only=True)
    recipient = _user(conn, recipient_id)
    if not recipient:
        raise ServiceError("That user does not exist.")
    if recipient_id == doc["owner_id"]:
        raise ServiceError("The owner already has access.")
    cur = conn.execute(
        "INSERT OR IGNORE INTO document_access (document_id, user_id, granted_by, granted_at)"
        " VALUES (?, ?, ?, ?)",
        (doc_id, recipient_id, owner_id, now_iso()),
    )
    if cur.rowcount:
        _log(conn, doc_id, owner_id, "shared", recipient["name"])
    conn.commit()
    return shared_users(conn, doc_id)


def unshare(conn, doc_id, owner_id, recipient_id):
    """Remove access. If the person loses access while a handoff waits on them,
    the handoff goes back to Draft, because they can no longer respond."""
    load_for(conn, doc_id, owner_id, owner_only=True)
    cur = conn.execute(
        "DELETE FROM document_access WHERE document_id = ? AND user_id = ?", (doc_id, recipient_id)
    )
    if cur.rowcount:
        name = _user(conn, recipient_id)["name"]
        _log(conn, doc_id, owner_id, "unshared", name)
        h = conn.execute("SELECT * FROM handoffs WHERE document_id = ?", (doc_id,)).fetchone()
        if h and h["contributor_id"] == recipient_id:
            conn.execute(
                "UPDATE handoffs SET contributor_id = NULL, status = 'draft', return_note = '',"
                " updated_at = ?, updated_by = ? WHERE document_id = ?",
                (now_iso(), owner_id, doc_id),
            )
            if h["status"] == "awaiting":
                _log(conn, doc_id, owner_id, "withdrawn", f"{name} no longer has access")
    conn.commit()
    return shared_users(conn, doc_id)


# ---------------------------------------------------------------- handoffs


def get_handoff(conn, doc_id):
    h = conn.execute(
        "SELECT h.*, u.name AS contributor_name FROM handoffs h"
        " LEFT JOIN users u ON u.id = h.contributor_id WHERE h.document_id = ?",
        (doc_id,),
    ).fetchone()
    events = conn.execute(
        "SELECT e.action, e.detail, e.created_at, u.name AS actor_name FROM handoff_events e"
        " JOIN users u ON u.id = e.actor_id WHERE e.document_id = ? ORDER BY e.id DESC LIMIT 6",
        (doc_id,),
    ).fetchall()
    base = dict(h) if h else {
        "document_id": doc_id, "contributor_id": None, "contributor_name": None,
        "instruction": "", "status": "draft", "return_note": "", "updated_at": None,
    }
    base["events"] = [dict(e) for e in events]
    return base


def _validate_plan(conn, doc, contributor_id, instruction):
    instruction = " ".join(str(instruction or "").split())
    if len(instruction) > INSTRUCTION_MAX:
        raise ServiceError(f"Keep the instruction under {INSTRUCTION_MAX} characters.")
    if contributor_id:
        if contributor_id == doc["owner_id"]:
            raise ServiceError("Choose someone else to review this document.")
        granted = conn.execute(
            "SELECT 1 FROM document_access WHERE document_id = ? AND user_id = ?",
            (doc["id"], contributor_id),
        ).fetchone()
        if not granted:
            raise ServiceError("Choose someone the document is already shared with.")
    return contributor_id or None, instruction


def _upsert_handoff(conn, doc_id, actor_id, **fields):
    current = conn.execute("SELECT 1 FROM handoffs WHERE document_id = ?", (doc_id,)).fetchone()
    fields["updated_at"] = now_iso()
    fields["updated_by"] = actor_id
    if current:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE handoffs SET {sets} WHERE document_id = ?", [*fields.values(), doc_id])
    else:
        fields["document_id"] = doc_id
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        conn.execute(f"INSERT INTO handoffs ({cols}) VALUES ({marks})", list(fields.values()))


def save_handoff_draft(conn, doc_id, user_id, contributor_id, instruction):
    """Owner prepares the next handoff without sending it."""
    doc = load_for(conn, doc_id, user_id, owner_only=True)
    status = get_handoff(conn, doc_id)["status"]
    if status == "awaiting":
        raise Conflict("Withdraw the current handoff before changing it.")
    if status == "returned":
        raise Conflict("Mark the returned handoff as reviewed before starting a new one.")
    contributor_id, instruction = _validate_plan(conn, doc, contributor_id, instruction)
    _upsert_handoff(conn, doc_id, user_id, contributor_id=contributor_id,
                    instruction=instruction, status="draft", return_note="")
    conn.commit()
    return get_handoff(conn, doc_id)


def send_handoff(conn, doc_id, user_id, contributor_id, instruction):
    """Owner hands the next action to a contributor: Draft -> Awaiting response."""
    doc = load_for(conn, doc_id, user_id, owner_only=True)
    status = get_handoff(conn, doc_id)["status"]
    if status == "awaiting":
        raise Conflict("This document is already waiting on a response.")
    if status == "returned":
        raise Conflict("Mark the returned handoff as reviewed before sending a new one.")
    contributor_id, instruction = _validate_plan(conn, doc, contributor_id, instruction)
    if not contributor_id:
        raise ServiceError("Choose someone to send this to.")
    if not instruction:
        raise ServiceError("Add a short instruction so they know what to do.")
    _upsert_handoff(conn, doc_id, user_id, contributor_id=contributor_id,
                    instruction=instruction, status="awaiting", return_note="")
    _log(conn, doc_id, user_id, "sent", f"to {_user(conn, contributor_id)['name']}: {instruction}")
    conn.commit()
    return get_handoff(conn, doc_id)


def withdraw_handoff(conn, doc_id, user_id):
    """Owner takes the handoff back before it is answered: Awaiting -> Draft."""
    load_for(conn, doc_id, user_id, owner_only=True)
    if get_handoff(conn, doc_id)["status"] != "awaiting":
        raise Conflict("There is no handoff waiting on a response.")
    _upsert_handoff(conn, doc_id, user_id, status="draft")
    _log(conn, doc_id, user_id, "withdrawn")
    conn.commit()
    return get_handoff(conn, doc_id)


def return_handoff(conn, doc_id, user_id, note=""):
    """The current contributor hands the document back: Awaiting -> Returned."""
    load_for(conn, doc_id, user_id)
    h = get_handoff(conn, doc_id)
    if h["status"] != "awaiting":
        raise Conflict("This document is not waiting on a response.")
    if h["contributor_id"] != user_id:
        raise Forbidden(f"Only {h['contributor_name']} can return this handoff.")
    note = " ".join(str(note or "").split())
    if len(note) > NOTE_MAX:
        raise ServiceError(f"Keep the note under {NOTE_MAX} characters.")
    _upsert_handoff(conn, doc_id, user_id, status="returned", return_note=note)
    _log(conn, doc_id, user_id, "returned", note)
    conn.commit()
    return get_handoff(conn, doc_id)


def start_new_handoff(conn, doc_id, user_id):
    """Owner acknowledges a returned handoff and starts a fresh draft: Returned -> Draft."""
    load_for(conn, doc_id, user_id, owner_only=True)
    if get_handoff(conn, doc_id)["status"] != "returned":
        raise Conflict("Only a returned handoff can be closed.")
    _upsert_handoff(conn, doc_id, user_id, contributor_id=None, instruction="",
                    status="draft", return_note="")
    _log(conn, doc_id, user_id, "closed")
    conn.commit()
    return get_handoff(conn, doc_id)
