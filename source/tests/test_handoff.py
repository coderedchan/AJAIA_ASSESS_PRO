"""Handoff rules. The main test follows the Alex and Sam example from the brief
and checks after every step that ownership and access did not change."""


def ownership_and_access(conn, doc_id):
    owner = conn.execute("SELECT owner_id FROM documents WHERE id = ?", (doc_id,)).fetchone()[0]
    access = {
        r[0]
        for r in conn.execute("SELECT user_id FROM document_access WHERE document_id = ?", (doc_id,))
    }
    return owner, access


def edit(client, doc_id, text):
    version = client.get(f"/api/documents/{doc_id}").get_json()["version"]
    return client.patch(
        f"/api/documents/{doc_id}", json={"base_version": version, "content_html": f"<p>{text}</p>"}
    )


def next_actions(client):
    return {(a["id"], a["kind"]) for a in client.get("/api/documents").get_json()["actions"]}


def test_handoff_preserves_ownership_and_access(as_user, raw_db):
    alex, sam, jordan = as_user("alex"), as_user("sam"), as_user("jordan")

    doc = alex.post("/api/documents", json={"title": "Q1 proposal"}).get_json()
    doc_id = doc["id"]
    assert alex.post(f"/api/documents/{doc_id}/access", json={"user_id": "sam"}).status_code == 200
    expected = ("alex", {"sam"})
    assert ownership_and_access(raw_db, doc_id) == expected

    def check_unchanged(step):
        assert ownership_and_access(raw_db, doc_id) == expected, f"changed after {step}"
        # Editing is never locked: owner and recipient can both save at every status.
        assert edit(alex, doc_id, f"Alex edit after {step}").status_code == 200, step
        assert edit(sam, doc_id, f"Sam edit after {step}").status_code == 200, step
        # A user without access still has no access.
        assert jordan.get(f"/api/documents/{doc_id}").status_code == 404, step
        assert ownership_and_access(raw_db, doc_id) == expected, f"changed after edits at {step}"

    # Draft
    res = alex.put(f"/api/documents/{doc_id}/handoff",
                   json={"contributor_id": "sam", "instruction": "Check the delivery dates."})
    assert res.get_json()["status"] == "draft"
    check_unchanged("draft")

    # Alex hands over to Sam: Awaiting response, and it appears in Sam's next actions.
    res = alex.post(f"/api/documents/{doc_id}/handoff/send",
                    json={"contributor_id": "sam", "instruction": "Check the delivery dates."})
    assert res.get_json()["status"] == "awaiting"
    assert (doc_id, "respond") in next_actions(sam)
    assert (doc_id, "respond") not in next_actions(alex)
    check_unchanged("send")

    # Sam returns it: Returned, and it appears in Alex's next actions instead.
    res = sam.post(f"/api/documents/{doc_id}/handoff/return", json={"note": "Week 3 moved to week 4."})
    assert res.get_json()["status"] == "returned"
    assert (doc_id, "review") in next_actions(alex)
    assert not any(d == doc_id for d, _ in next_actions(sam))
    check_unchanged("return")

    # Alex marks it reviewed: back to Draft with nothing waiting on anyone.
    res = alex.post(f"/api/documents/{doc_id}/handoff/close")
    assert res.get_json()["status"] == "draft"
    assert not any(d == doc_id for d, _ in next_actions(alex) | next_actions(sam))
    check_unchanged("close")

    # The owner and recipient views still describe the same ownership.
    assert alex.get(f"/api/documents/{doc_id}").get_json()["role"] == "owner"
    assert sam.get(f"/api/documents/{doc_id}").get_json()["role"] == "editor"


def test_contributor_must_already_have_access(as_user):
    alex = as_user("alex")
    doc_id = alex.post("/api/documents", json={}).get_json()["id"]
    res = alex.post(f"/api/documents/{doc_id}/handoff/send",
                    json={"contributor_id": "jordan", "instruction": "Review this."})
    assert res.status_code == 400
    assert "shared with" in res.get_json()["error"]


def test_only_the_contributor_can_return_and_only_the_owner_can_send(as_user):
    alex, sam, jordan = as_user("alex"), as_user("sam"), as_user("jordan")
    doc_id = alex.post("/api/documents", json={}).get_json()["id"]
    for person in ("sam", "jordan"):
        alex.post(f"/api/documents/{doc_id}/access", json={"user_id": person})

    res = sam.post(f"/api/documents/{doc_id}/handoff/send",
                   json={"contributor_id": "jordan", "instruction": "Look at this."})
    assert res.status_code == 403

    alex.post(f"/api/documents/{doc_id}/handoff/send",
              json={"contributor_id": "sam", "instruction": "Review pricing."})
    assert jordan.post(f"/api/documents/{doc_id}/handoff/return", json={}).status_code == 403
    assert sam.post(f"/api/documents/{doc_id}/handoff/return", json={}).status_code == 200


def test_send_requires_contributor_and_instruction(as_user):
    alex = as_user("alex")
    doc_id = alex.post("/api/documents", json={}).get_json()["id"]
    alex.post(f"/api/documents/{doc_id}/access", json={"user_id": "sam"})
    url = f"/api/documents/{doc_id}/handoff/send"
    assert alex.post(url, json={"contributor_id": "sam", "instruction": "  "}).status_code == 400
    assert alex.post(url, json={"contributor_id": None, "instruction": "Review."}).status_code == 400
    assert alex.post(url, json={"contributor_id": "sam", "instruction": "x" * 201}).status_code == 400


def test_removing_access_withdraws_a_waiting_handoff(as_user, raw_db):
    alex, sam = as_user("alex"), as_user("sam")
    doc_id = alex.post("/api/documents", json={}).get_json()["id"]
    alex.post(f"/api/documents/{doc_id}/access", json={"user_id": "sam"})
    alex.post(f"/api/documents/{doc_id}/handoff/send",
              json={"contributor_id": "sam", "instruction": "Check the dates."})

    assert alex.delete(f"/api/documents/{doc_id}/access/sam").status_code == 200

    handoff = alex.get(f"/api/documents/{doc_id}").get_json()["handoff"]
    assert handoff["status"] == "draft"
    assert handoff["contributor_id"] is None
    assert sam.get(f"/api/documents/{doc_id}").status_code == 404
    assert ownership_and_access(raw_db, doc_id) == ("alex", set())


def test_status_changes_follow_one_path(as_user):
    """Draft -> Awaiting response -> Returned -> (reviewed) Draft. Other jumps are refused."""
    alex, sam = as_user("alex"), as_user("sam")
    doc_id = alex.post("/api/documents", json={}).get_json()["id"]
    alex.post(f"/api/documents/{doc_id}/access", json={"user_id": "sam"})
    url = f"/api/documents/{doc_id}/handoff"
    plan = {"contributor_id": "sam", "instruction": "Check the dates."}

    assert sam.post(f"{url}/return", json={}).status_code == 409          # nothing to return yet
    assert alex.post(f"{url}/close").status_code == 409                    # nothing returned yet
    assert alex.post(f"{url}/send", json=plan).status_code == 200
    assert alex.post(f"{url}/send", json=plan).status_code == 409          # already waiting
    assert alex.put(url, json=plan).status_code == 409                     # withdraw first
    assert sam.post(f"{url}/return", json={}).status_code == 200
    assert alex.post(f"{url}/send", json=plan).status_code == 409          # review the return first
    assert alex.post(f"{url}/close").status_code == 200
    assert alex.post(f"{url}/send", json=plan).status_code == 200
