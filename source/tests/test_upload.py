"""File import: .txt, .md, and .docx become new documents owned by the uploader."""

import io

import docx


def upload(client, name, data):
    return client.post(
        "/api/documents/import",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_markdown_import_keeps_structure(as_user):
    alex = as_user("alex")
    res = upload(alex, "delivery_notes.md", b"# Dates\n\nShip **Monday**.\n\n- Leeds\n- York\n\n1. Call\n2. Confirm\n")
    assert res.status_code == 201
    doc = res.get_json()
    assert doc["title"] == "delivery notes"
    assert doc["owner_id"] == "alex"
    assert doc["source_filename"] == "delivery_notes.md"
    for tag in ("<h1>Dates</h1>", "<strong>Monday</strong>", "<ul>", "<ol>"):
        assert tag in doc["content_html"]


def test_text_import_escapes_markup(as_user):
    res = upload(as_user("alex"), "notes.txt", b"First line\nsecond line\n\n<script>alert(1)</script>")
    assert res.status_code == 201
    html = res.get_json()["content_html"]
    assert html.startswith("<p>First line<br>second line</p>")
    assert "<script>" not in html


def test_docx_import(as_user):
    document = docx.Document()
    document.add_heading("Pricing review", level=1)
    para = document.add_paragraph("Total is ")
    para.add_run("£48,500").bold = True
    para.add_run(" before tax").underline = True
    buffer = io.BytesIO()
    document.save(buffer)

    res = upload(as_user("alex"), "pricing.docx", buffer.getvalue())
    assert res.status_code == 201
    html = res.get_json()["content_html"]
    assert "<h1>Pricing review</h1>" in html
    assert "<strong>£48,500</strong>" in html
    assert "<u> before tax</u>" in html


def test_rejected_uploads_create_no_document(as_user):
    alex = as_user("alex")
    before = len(alex.get("/api/documents").get_json()["owned"])

    bad_type = upload(alex, "photo.png", b"\x89PNG")
    assert bad_type.status_code == 400
    assert ".txt, .md, and .docx" in bad_type.get_json()["error"]
    assert upload(alex, "empty.md", b"").status_code == 400
    assert upload(alex, "broken.docx", b"not a zip file").status_code == 400
    assert upload(alex, "latin1.txt", "café".encode("latin-1")).status_code == 400
    assert upload(alex, "huge.txt", b"a" * (3 * 1024 * 1024)).status_code == 413

    assert len(alex.get("/api/documents").get_json()["owned"]) == before


def test_import_and_save_share_one_content_limit(as_user):
    """Anything that imports successfully can be edited and saved again."""
    alex = as_user("alex")
    before = len(alex.get("/api/documents").get_json()["owned"])

    too_big = upload(alex, "long.txt", b"a" * 1_100_000)  # under the 2 MB file limit
    assert too_big.status_code == 400
    assert "1 MB" in too_big.get_json()["error"]
    assert len(alex.get("/api/documents").get_json()["owned"]) == before

    near_limit = upload(alex, "near.txt", b"word " * 190_000)  # about 950 KB of content
    assert near_limit.status_code == 201
    doc = near_limit.get_json()
    edited = doc["content_html"] + "<p>One more line.</p>"
    res = alex.patch(f"/api/documents/{doc['id']}",
                     json={"base_version": doc["version"], "content_html": edited})
    assert res.status_code == 200
