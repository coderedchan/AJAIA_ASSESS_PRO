"""Browser check of the main flow, using Playwright.

Usage:
    pip install playwright && python -m playwright install chromium
    python scripts/e2e_smoke.py http://127.0.0.1:5000 ../screenshots

Run it against a freshly seeded database. It signs in as Alex, writes a formatted
document, reloads it, shares it with Sam, hands it off, returns it as Sam, checks
that Jordan is refused, imports files, checks a save conflict between two
sessions, and saves a screenshot at each step.

Every HTTP response of 400 or above fails the run, including API calls, unless the
step that causes it declares it with `allow(status, path)`. Script errors and
console errors also fail the run.
"""

import json
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5000"
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

errors = []
allowed = []  # (status, path substring, method or None) declared by the current step


@contextmanager
def allow(status, path, method=None):
    entry = (status, path, method)
    allowed.append(entry)
    try:
        yield
    finally:
        allowed.remove(entry)


def watch(page):
    # The browser also logs failed requests as console errors. Those are judged by
    # the response handler below, so the console handler skips them.
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text
            and errors.append(f"console: {m.text}"))
    page.on("pageerror", lambda e: errors.append(f"script error: {e}"))

    def on_response(r):
        if r.status < 400:
            return
        for status, path, method in allowed:
            if r.status == status and path in r.url and method in (None, r.request.method):
                return
        errors.append(f"unexpected {r.status} for {r.request.method} {r.url}")

    page.on("response", on_response)


def shot(page, name):
    # Full-page captures of a scrolled page draw the sticky top bar mid-page.
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    print("saved", name)


def switch_user(page, name):
    page.select_option("#identity select", label=name)
    expect(page.locator("#identity select")).to_have_value(name.split()[0].lower())
    page.wait_for_timeout(300)


def sign_in(page, name):
    page.goto(BASE)
    page.get_by_role("button", name=name).click()
    expect(page.get_by_role("heading", name="Needs your attention")).to_be_visible()


def focus_refresh(page, doc_id):
    """Fire the window focus event and wait for the document refresh it triggers."""
    with page.expect_response(lambda r: r.url.endswith(f"/api/documents/{doc_id}") and r.request.method == "GET"):
        page.evaluate("window.dispatchEvent(new Event('focus'))")
    page.wait_for_timeout(100)


def click_end_of_last_item(page):
    page.locator(".ProseMirror li").last.click()
    # ProseMirror reads the click's cursor position on the next selectionchange
    # event. Without a short pause the script types before that, at the old cursor.
    page.wait_for_timeout(150)
    page.keyboard.press("End")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        watch(page)

        # 1. Sign in as Alex.
        page.goto(BASE)
        expect(page.get_by_text("Choose a demo account")).to_be_visible()
        shot(page, "01-sign-in")
        page.get_by_role("button", name="Alex Morgan").click()
        expect(page.get_by_role("heading", name="Needs your attention")).to_be_visible()
        shot(page, "02-dashboard-alex")

        # 2. Create, rename and format a document.
        page.get_by_role("button", name="New document").click()
        title = page.get_by_label("Document title")
        title.fill("Q1 pricing proposal")
        page.locator(".ProseMirror").click()
        page.get_by_role("button", name="Heading 2").click()
        page.keyboard.type("Pricing")
        page.keyboard.press("Enter")
        page.keyboard.type("The total is ")
        page.get_by_role("button", name="Bold").click()
        page.keyboard.type("£48,500")
        page.get_by_role("button", name="Bold").click()
        page.keyboard.type(" for ")
        page.get_by_role("button", name="Italic").click()
        page.keyboard.type("three")
        page.get_by_role("button", name="Italic").click()
        page.keyboard.type(" sites, ")
        page.get_by_role("button", name="Underline").click()
        page.keyboard.type("before tax")
        page.get_by_role("button", name="Underline").click()
        page.keyboard.type(".")
        page.keyboard.press("Enter")
        page.get_by_role("button", name="Bulleted list").click()
        page.keyboard.type("Leeds")
        page.keyboard.press("Enter")
        page.keyboard.type("York")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.get_by_role("button", name="Numbered list").click()
        page.keyboard.type("Confirm the rate card")
        expect(page.locator(".save-state")).to_contain_text("Saved at", timeout=5000)
        shot(page, "03-editor-formatting")

        # 3. Reload: title and formatting survive.
        doc_url = page.url
        doc_id = doc_url.rsplit("/", 1)[1]
        page.reload()
        expect(page.get_by_label("Document title")).to_have_value("Q1 pricing proposal")
        html = page.locator(".ProseMirror").inner_html()
        for tag in ("<h2>", "<strong>", "<em>", "<u>", "<ul>", "<ol>"):
            assert tag in html, f"{tag} missing after reload"
        print("reload check passed")

        # 4. Share with Sam and hand off. A focus refresh must not clear the typed instruction.
        page.get_by_role("button", name="Share", exact=True).click()
        page.get_by_label("Person to share with").select_option(label="Sam Rivera (sam@relay.test)")
        page.locator(".share-panel").get_by_role("button", name="Share").click()
        expect(page.locator(".doc-facts")).to_contain_text("Shared with Sam Rivera")
        page.mouse.click(5, 300)
        page.select_option("#handoff-to", "sam")
        page.fill("#handoff-instruction", "Review the pricing paragraph.")
        focus_refresh(page, doc_id)
        expect(page.locator("#handoff-to")).to_have_value("sam")
        expect(page.locator("#handoff-instruction")).to_have_value("Review the pricing paragraph.")
        print("handoff form kept its text after a focus refresh")
        page.get_by_role("button", name="Send to Sam Rivera").click()
        expect(page.locator(".handoff .pill")).to_have_text("Awaiting response")
        shot(page, "04-handoff-sent")

        # 5. Sam sees it in next actions and edits it.
        switch_user(page, "Sam Rivera")
        page.goto(BASE)
        action = page.locator(".action", has_text="Q1 pricing proposal")
        expect(action).to_contain_text("Review the pricing paragraph.")
        shot(page, "05-sam-next-actions")
        action.click()
        expect(page.get_by_role("button", name="Send back to Alex Morgan")).to_be_visible()

        # 5a. The note Sam is typing survives a focus refresh.
        note = "Pricing matches the rate card. I added a line at the end."
        page.fill("#return-note", note)
        focus_refresh(page, doc_id)
        expect(page.locator("#return-note")).to_have_value(note)
        print("return note kept its text after a focus refresh")

        # 5b. While saving fails, Send back to Alex Morgan must not change the handoff.
        def fail_saves(route):
            if route.request.method == "PATCH":
                route.fulfill(status=503, content_type="application/json",
                              body=json.dumps({"error": "The server is unavailable."}))
            else:
                route.continue_()

        doc_api = re.compile(rf".*/api/documents/{doc_id}$")
        with allow(503, f"/api/documents/{doc_id}", "PATCH"):
            page.route(doc_api, fail_saves)
            click_end_of_last_item(page)
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")
            page.keyboard.type("Sam: pricing checked against the March rate card.")
            expect(page.locator(".save-state")).to_contain_text("Not saved", timeout=5000)
            page.get_by_role("button", name="Send back to Alex Morgan").click()
            expect(page.locator("#toast")).to_contain_text("Save your latest edits before sending this request")
            expect(page.locator(".handoff .pill")).to_have_text("Awaiting response")
            expect(page.locator("#return-note")).to_have_value(note)
            page.unroute(doc_api)
        print("failed save blocked the return")

        # 5c. Once saving works again, the return goes through with the edit stored.
        page.get_by_role("button", name="Send back to Alex Morgan").click()
        expect(page.locator(".handoff .pill")).to_have_text("Returned")
        expect(page.locator(".save-state")).to_contain_text("Saved at")
        shot(page, "06-sam-returned")

        # 6. Jordan has no access.
        with allow(404, f"/api/documents/{doc_id}", "GET"):
            switch_user(page, "Jordan Lee")
            page.goto(doc_url)
            expect(page.get_by_text("This document is not available")).to_be_visible()
            shot(page, "07-jordan-no-access")

        # 7. Alex sees the return; ownership is unchanged.
        switch_user(page, "Alex Morgan")
        page.goto(BASE)
        returned = page.locator(".action", has_text="Q1 pricing proposal")
        expect(returned).to_contain_text("Returned to you")
        shot(page, "08-alex-returned-dashboard")
        returned.click()
        expect(page.locator(".doc-facts")).to_contain_text("Created by you")
        expect(page.locator(".ProseMirror")).to_contain_text("pricing checked against the March rate card")
        expect(page.locator(".handoff")).to_contain_text("Pricing matches the rate card.")
        shot(page, "09-alex-returned-document")
        page.get_by_role("button", name="Finish review").click()
        expect(page.locator(".handoff .pill")).to_have_text("Draft")

        # 8. Upload: a supported file becomes a document; an unsupported one is refused
        #    in the browser before any request is sent.
        page.goto(BASE)
        tmp = Path(tempfile.mkdtemp())
        good = tmp / "site_survey_notes.md"
        good.write_text("# Site survey\n\nLeeds dock is **ready**.\n\n- Power checked\n- Racking measured\n")
        bad = tmp / "photo.png"
        bad.write_bytes(b"\x89PNG")
        page.set_input_files("#import-file", str(bad))
        expect(page.locator("#toast")).to_contain_text("Only .txt, .md, and .docx")
        page.set_input_files("#import-file", str(good))
        expect(page.get_by_label("Document title")).to_have_value("site survey notes")
        expect(page.locator(".ProseMirror h1")).to_have_text("Site survey")
        shot(page, "10-imported-markdown")

        # 9. Two people editing at once: the later save is refused and both versions are offered.
        page.goto(doc_url)
        expect(page.locator(".ProseMirror")).to_be_visible()
        sam_context = browser.new_context()
        sam_page = sam_context.new_page()
        watch(sam_page)
        sign_in(sam_page, "Sam Rivera")
        sam_page.goto(doc_url)
        click_end_of_last_item(sam_page)
        sam_page.keyboard.type(" (Sam)")
        expect(sam_page.locator(".save-state")).to_contain_text("Saved at", timeout=5000)
        with allow(409, f"/api/documents/{doc_id}", "PATCH"):
            page.locator(".ProseMirror li").first.click()
            page.wait_for_timeout(150)
            page.keyboard.type(" (Alex)")
            expect(page.locator(".banner")).to_contain_text("Sam Rivera saved a newer version", timeout=5000)
            shot(page, "11-save-conflict")
        page.get_by_role("button", name="Keep my version").click()
        expect(page.locator(".save-state")).to_contain_text("Saved at", timeout=5000)
        sam_context.close()

        # 10. Narrow screen.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(doc_url)
        expect(page.locator(".handoff")).to_be_visible()
        shot(page, "12-mobile-document")

        browser.close()

    if errors:
        print("failures:", *errors, sep="\n  ")
        sys.exit(1)
    print("all browser checks passed")


if __name__ == "__main__":
    main()
