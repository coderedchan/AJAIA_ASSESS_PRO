"""Core document behaviour: create, rename, save, reopen, sharing and access."""

from relay import create_app

FORMATTED = (
    "<h1>Plan</h1><p><strong>Bold</strong> <em>italic</em> <u>underline</u></p>"
    "<ul><li><p>one</p></li></ul><ol><li><p>first</p></li></ol>"
)


def test_create_rename_save_and_reopen_after_restart(as_user, db_path):
    alex = as_user("alex")
    doc = alex.post("/api/documents", json={}).get_json()
    assert doc["title"] == "Untitled document"
    assert doc["owner_id"] == "alex"

    res = alex.patch(f"/api/documents/{doc['id']}", json={
        "base_version": doc["version"], "title": "  Launch   plan ", "content_html": FORMATTED,
    })
    assert res.status_code == 200
    assert res.get_json()["title"] == "Launch plan"

    # A fresh app instance on the same database file stands in for a server restart.
    restarted = create_app({"DATABASE": db_path, "SECRET_KEY": "test"}).test_client()
    restarted.post("/api/session", json={"user_id": "alex"})
    reopened = restarted.get(f"/api/documents/{doc['id']}").get_json()
    assert reopened["title"] == "Launch plan"
    for tag in ("<h1>", "<strong>", "<em>", "<u>", "<ul>", "<ol>"):
        assert tag in reopened["content_html"]


def test_dashboard_separates_owned_and_shared(as_user):
    alex, sam = as_user("alex"), as_user("sam")
    doc_id = alex.post("/api/documents", json={"title": "Budget"}).get_json()["id"]
    alex.post(f"/api/documents/{doc_id}/access", json={"user_id": "sam"})
    assert doc_id in {d["id"] for d in alex.get("/api/documents").get_json()["owned"]}
    sam_view = sam.get("/api/documents").get_json()
    assert doc_id in {d["id"] for d in sam_view["shared"]}
    assert doc_id not in {d["id"] for d in sam_view["owned"]}


def test_unshared_user_cannot_read_edit_or_share(as_user):
    alex, jordan = as_user("alex"), as_user("jordan")
    doc = alex.post("/api/documents", json={}).get_json()
    url = f"/api/documents/{doc['id']}"
    assert jordan.get(url).status_code == 404
    assert jordan.patch(url, json={"base_version": doc["version"], "title": "Mine"}).status_code == 404
    assert jordan.post(f"{url}/access", json={"user_id": "jordan"}).status_code == 404
    assert doc["id"] not in {d["id"] for d in jordan.get("/api/documents").get_json()["shared"]}


def test_recipient_can_edit_but_not_manage_access(as_user):
    alex, sam = as_user("alex"), as_user("sam")
    doc = alex.post("/api/documents", json={}).get_json()
    alex.post(f"/api/documents/{doc['id']}/access", json={"user_id": "sam"})
    res = sam.patch(f"/api/documents/{doc['id']}",
                    json={"base_version": doc["version"], "content_html": "<p>Sam was here</p>"})
    assert res.status_code == 200
    assert sam.post(f"/api/documents/{doc['id']}/access", json={"user_id": "jordan"}).status_code == 403


def test_stale_save_is_refused_with_the_latest_version(as_user):
    alex, sam = as_user("alex"), as_user("sam")
    doc = alex.post("/api/documents", json={}).get_json()
    alex.post(f"/api/documents/{doc['id']}/access", json={"user_id": "sam"})
    url = f"/api/documents/{doc['id']}"
    assert sam.patch(url, json={"base_version": doc["version"], "content_html": "<p>Sam</p>"}).status_code == 200

    stale = alex.patch(url, json={"base_version": doc["version"], "content_html": "<p>Alex</p>"})
    assert stale.status_code == 409
    assert stale.get_json()["latest"]["content_html"] == "<p>Sam</p>"

    forced = alex.patch(url, json={"base_version": doc["version"], "content_html": "<p>Alex</p>", "force": True})
    assert forced.status_code == 200


def test_validation_and_sanitising(as_user):
    alex = as_user("alex")
    doc = alex.post("/api/documents", json={}).get_json()
    url = f"/api/documents/{doc['id']}"
    assert alex.patch(url, json={"base_version": doc["version"], "title": "   "}).status_code == 400
    assert alex.patch(url, json={"base_version": doc["version"], "title": "x" * 121}).status_code == 400
    res = alex.patch(url, json={
        "base_version": doc["version"],
        "content_html": '<p onclick="steal()">Hi<script>alert(1)</script><a href="javascript:x()">link</a></p>',
    })
    saved = res.get_json()["content_html"]
    assert "script" not in saved and "onclick" not in saved and "javascript" not in saved
    assert "Hi" in saved


def test_signed_out_requests_are_rejected(app):
    assert app.test_client().get("/api/documents").status_code == 401


def test_simultaneous_saves_cannot_both_succeed(app, db_path, monkeypatch):
    """Two saves that both read version 1 before either writes: one must get a conflict.

    A barrier holds each save after its version check until both have checked, which
    is the interleaving that let the second save silently replace the first.
    """
    import threading

    from relay import services as svc
    from relay.db import connect

    setup = connect(db_path)
    doc = svc.create_document(setup, "alex")
    svc.share(setup, doc["id"], "alex", "sam")
    setup.close()

    barrier = threading.Barrier(2, timeout=5)
    local = threading.local()
    real_load_for = svc.load_for

    def load_then_wait(conn, doc_id, user_id, owner_only=False):
        row = real_load_for(conn, doc_id, user_id, owner_only)
        if not getattr(local, "waited", False):  # only the version check, not later reads
            local.waited = True
            barrier.wait()
        return row

    monkeypatch.setattr(svc, "load_for", load_then_wait)
    outcomes = {}

    def save(user_id, text):
        conn = connect(db_path)
        try:
            svc.update_document(conn, doc["id"], user_id, base_version=doc["version"],
                                content_html=f"<p>{text}</p>")
            outcomes[user_id] = "saved"
        except svc.Conflict:
            outcomes[user_id] = "conflict"
        finally:
            conn.close()

    threads = [threading.Thread(target=save, args=args) for args in (("alex", "Alex"), ("sam", "Sam"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes.values()) == ["conflict", "saved"]
    winner = next(u for u, o in outcomes.items() if o == "saved")
    check = connect(db_path)
    stored = check.execute("SELECT content_html, version FROM documents WHERE id = ?", (doc["id"],)).fetchone()
    check.close()
    assert stored["content_html"] == f"<p>{winner.capitalize()}</p>"
    assert stored["version"] == doc["version"] + 1
