# Relay Docs

Relay Docs lets teammates write documents, share them, and request a review.

Choose someone who already has access, add a note about what to check, and send the request. They can edit the document and send it back with a reply. Requests move through Draft, Awaiting response, and Returned. The person who created the document keeps control of sharing throughout.

Live application and walkthrough links are in `LIVE_URL.txt` and `WALKTHROUGH_URL.txt`.

## What works

- Create a document, rename it, and edit it in the browser with bold, italic, underline, two heading levels, bulleted lists, and numbered lists.
- Changes save automatically about one second after you stop typing. The status next to the Share button shows "Saving…", the time of the last save, or the reason a save failed with a Retry button. Ctrl+S or Cmd+S saves at once.
- If two people edit the same document and one saves first, the second save is refused instead of silently overwriting. This holds even when both saves reach the server at the same moment, because the version check is part of the database update. A banner offers "Load their version" or "Keep my version".
- Review buttons wait until your edits are saved. If saving fails, the handoff does not change, your edits stay in the editor, and a message explains why. Text typed into the review request is kept when the page refreshes its data.
- Import a .txt, .md, or .docx file of up to 2 MB. The file becomes a new document owned by the person who uploaded it. Other file types, and files whose text would exceed the 1 MB limit for one document, are refused with a message, and no document is created.
- The person who created a document can add or remove people in Share. Anyone added can read and edit it.
- The dashboard lists "Needs your attention", "Created by you", and "Shared with you" as separate sections.
- Documents, formatting, sharing, and handoffs are stored in SQLite. They survive a page refresh everywhere. They survive a server restart wherever the SQLite file is on persistent storage, which is the case for local runs and for Docker with a volume. The free Render plan described under Deploy does not keep the file across restarts.

## Demo accounts

Sign-in is mocked. The first screen lists three seeded accounts, and the "Signed in as" menu in the top bar switches between them at any time.

| Account | Role in the demo |
| --- | --- |
| Alex Morgan | Owns "Northwind delivery proposal", which is shared with Sam and handed to Sam with the instruction "Check the delivery dates." |
| Sam Rivera | Has edit access to Alex's proposal and sees it under "Needs your attention". |
| Jordan Lee | Has no access to Alex's proposal. Opening its link as Jordan shows "This document is not available". |

A short review path: sign in as Sam, open the proposal from "Needs your attention", change a delivery date, add a note, and click "Send back to Alex Morgan". Then switch to Alex. The proposal now appears under "Needs your attention" as "Returned to you", with Sam's note.

## Run locally

Prerequisites: Python 3.10 or newer. Node is not needed, because the editor bundle is already built and committed.

```bash
cd source
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
flask --app relay run --port 5000
```

Open http://127.0.0.1:5000. The database file is created and seeded on first start at `source/data/relay.sqlite3`.

To restore the seeded demo data at any time, stop the server and run `flask --app relay reset-demo`.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `RELAY_DATA_DIR` | `source/data` | Folder that holds the SQLite file. Point it at a persistent volume in production. |
| `RELAY_SECRET_KEY` | a development value | Signs the session cookie that remembers the selected demo account. Set a random value in production. |

### Run with Docker

```bash
cd source
docker build -t relay-docs .
docker run -p 8000:8000 -e RELAY_SECRET_KEY=change-me -v relay-data:/data relay-docs
```

The named volume `relay-data` keeps documents when the container restarts.

## Tests

```bash
cd source
pytest
```

The suite has 19 tests and runs in under a second. The test the brief asks for is `test_handoff_preserves_ownership_and_access` in `tests/test_handoff.py`. It follows the Alex and Sam example through Draft, Awaiting response, Returned, and back to Draft. After each step it reads the database directly and checks that the owner is still Alex and that the access list is still exactly Sam. It also checks that both Alex and Sam can still save edits, and that Jordan still gets a 404. The other tests cover the allowed status changes, access control for unshared users, persistence across an app restart, save conflicts (including two saves that arrive at the same moment), HTML sanitising, each upload type, and the shared content limit for imports and saves.

There is also a browser check that drives the full flow in Chromium and saves the screenshots in `../screenshots`. Besides the main flow, it checks that typed handoff text survives a data refresh and that "Send back to Alex Morgan" is blocked while saving fails. Any failed HTTP response fails the run unless the step expects it, such as the 404 for Jordan.

```bash
pip install playwright && python -m playwright install chromium
flask --app relay reset-demo && flask --app relay run --port 5000   # in one terminal
python scripts/e2e_smoke.py http://127.0.0.1:5000 ../screenshots     # in another
```

## Deploy

`render.yaml`, at the root of this folder, is a Render Blueprint that builds `source/Dockerfile` on the free plan. In Render, choose New, then Blueprint, and select the repository. Render generates `RELAY_SECRET_KEY` and checks `/healthz`.

Persistence limit on the free plan: Render's free web services have no persistent disk, so the SQLite file is reset to the seeded demo data when the service restarts, redeploys, or wakes after about 15 minutes idle. Within a session, documents, sharing, and handoffs persist across page refreshes and between accounts. For durable storage, attach a Render persistent disk at `/data` on a paid instance. No code changes are needed for that.

## Supported uploads

| Type | Result |
| --- | --- |
| .txt | Blank lines start new paragraphs. Single line breaks are kept. |
| .md | Headings, bold, italic, lists, quotes, and code are converted. Links keep their text but not the link, because the editor has no link tool. |
| .docx | Headings, paragraphs, bold, italic, underline, and lists are converted with Mammoth. Images are dropped, and table text is kept without the table layout. |

Files must be 2 MB or smaller, and .txt and .md files must be UTF-8. After conversion, the text must fit the 1 MB limit for one document. That is the same limit applied on every save, so any imported document can be edited and saved again. A .docx file with pictures can be larger than its text, which is why the file limit is higher than the content limit. These limits are shown under the "Import a file" button.

## Known limits

The editor saves whole documents and does not merge two people's edits made at the same moment. Instead it detects the conflict and lets the second person choose. There is no real authentication, no document deletion, and no view-only role. These cuts and the next steps are explained in `ARCHITECTURE.md`.
