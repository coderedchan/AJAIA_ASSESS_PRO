# Architecture note

## Priorities

I built the core requirements first, as one working path: create, edit, save, reopen, share, open as the recipient, and import. The handoff card came after that path worked end to end. The order of priority was:

1. Access rules that are enforced in one place on the server and covered by tests.
2. Saving that cannot lose work without telling the user, including when two people edit the same document.
3. The handoff feature, kept separate from ownership and access in the data model, so that the separation is a property of the schema and not only of the UI.
4. A calm editorial interface, with one accent colour reserved for handoff actions and handoff status.

## Stack

| Part | Choice | Reason |
| --- | --- | --- |
| Server | Python 3, Flask, Gunicorn | Small, familiar, and easy to test with Flask's test client. |
| Storage | SQLite, one file | No paid service for reviewers. Easy to inspect and to reset. |
| Editor | TipTap 2 (ProseMirror) with StarterKit, Underline, and Placeholder | A proper document model with lists and headings, instead of `contentEditable` with `execCommand`. |
| Client | Plain JavaScript modules, no build step for the app | The editor is the only dependency. It is bundled once with esbuild inside a Node container (`scripts/build-editor.sh`) and committed, so neither reviewers nor the server need Node. |
| Sanitising | nh3 allowlist | Every save and every import is cleaned on the server before storage. |
| Import | Python-Markdown for .md, Mammoth for .docx | Both produce HTML that goes through the same allowlist. |

## Code layout

| File | Responsibility |
| --- | --- |
| `relay/db.py` | Schema, connections, and seed data. |
| `relay/services.py` | Every rule about documents, sharing, and handoffs. All access checks go through `load_for()`. |
| `relay/api.py` | JSON routes. Each route resolves the signed-in user and calls the service layer. It makes no access decisions of its own. |
| `relay/importers.py` | Converts uploads to HTML and enforces type and size limits. |
| `relay/sanitize.py` | The HTML allowlist and the plain-text excerpt used on the dashboard. |
| `relay/static/app.js` | Client routing, dashboard, editor, autosave, sharing panel, and the handoff card. |

## Data model

```
users(id, name, email, title)
documents(id, title, content_html, owner_id, version, source_filename, created_at, updated_at, updated_by)
document_access(document_id, user_id, granted_by, granted_at)        -- people the owner shared with
handoffs(document_id, contributor_id, instruction, status, return_note, updated_at, updated_by)
handoff_events(id, document_id, actor_id, action, detail, created_at)
```

Ownership, access, and the handoff are three separate tables. Ownership is `documents.owner_id`. Access is the set of rows in `document_access`, and the owner is never stored there. The handoff is one row per document in `handoffs`. No handoff function writes to `documents.owner_id` or to `document_access`. Removing someone's access is the only place where sharing affects a handoff: if the owner removes the person a handoff is waiting on, that handoff goes back to Draft, because that person can no longer open the document to respond.

## Identity and access

Sign-in is mocked. The session cookie stores the id of a seeded user, and the "Signed in as" menu changes it. Every API call reads that id and passes it to the service layer.

`services.load_for(doc_id, user_id, owner_only=False)` is the single access check. A user who is neither the owner nor in `document_access` gets 404 for every operation, so the API does not reveal which document ids exist. Owner-only operations (sharing, removing access, sending, withdrawing, and reviewing a handoff) return 403 to people who have access but do not own the document.

Recipients can read and edit content and the title. Only the owner manages access. I chose edit access for recipients because the handoff example has Sam editing Alex's document.

## Handoff states

| From | Action | Who can do it | To |
| --- | --- | --- | --- |
| Draft | Save draft (choose contributor and instruction) | Owner | Draft |
| Draft | Hand off | Owner | Awaiting response |
| Awaiting response | Withdraw handoff | Owner | Draft |
| Awaiting response | Send back to the person who created it, with an optional note | The selected person only | Returned |
| Returned | Finish review | Owner | Draft, with the contributor and instruction cleared |
| Awaiting response | Owner removes the contributor's access | Owner | Draft, with the contributor cleared |

The selected person must already be in `document_access`. A handoff therefore cannot be used to grant access by accident. Any other status change returns 409 with a message saying what to do first. Each handoff action is logged in `handoff_events`, and the card shows the last six as "Recent activity".

"Needs your attention" on the dashboard is computed from the same tables. It lists documents awaiting the signed-in user's response, documents of theirs that were returned, and handoffs they drafted but have not sent.

## Saving and rich text

The editor stores HTML produced by TipTap. The server sanitises it with an allowlist of the tags the editor can produce (paragraphs, three heading levels, bold, italic, underline, strike, lists, quotes, and code) and stores the result. On reopen, TipTap parses the stored HTML back into its schema, so the formatting round-trips. A test saves formatted HTML, starts a new app instance on the same database file, and checks that every tag is still present.

The client saves about 0.9 seconds after the last change. Every save sends the `version` the client last loaded. The server checks it once when it loads the document, and again inside the `UPDATE` statement (`WHERE id = ? AND version = ?`). The second check matters when two saves arrive at the same moment: both can pass the first check, but only one matches the `UPDATE`, and the other is refused with 409 and the latest version. "Keep my version" sends `force`, which is the only save without the version condition. On a conflict, the client keeps the local text in the editor and shows a banner with "Load their version" and "Keep my version". This is not real-time co-editing, but it means two people working at once never overwrite each other silently.

The client has one method, `flush()`, that waits for any save in progress, saves anything still pending, and reports whether every change reached the server. Leaving a document and every handoff action go through it. A handoff tells the other person that the document is ready, so if saving fails, the handoff action is not sent: the status stays as it was, the edits stay in the editor, and a message points to the save error. Closing the tab with unsaved changes shows the browser's leave warning.

When the window regains focus, the page fetches the document again to pick up other people's changes. Text typed into the handoff card (the selected person, the request text, and the reply) is held in the page's own state, separate from the server data, so redrawing the card does not clear it. The card is only redrawn when the server's handoff or sharing data has actually changed.

## Uploads

Upload creates a new document owned by the uploader. Accepted types are .txt, .md, and .docx, up to 2 MB, and .txt and .md must be UTF-8. The client checks type and size before sending, and the server checks them again. Flask's request size limit stops larger bodies before they are read. Empty files, damaged .docx files, and non-UTF-8 text are refused with a message, and no document is created.

There are two separate limits. The 2 MB limit applies to the uploaded file. The 1 MB limit applies to document content, and it is checked on the converted HTML at import and again on every save. Conversion can make text larger, because it adds paragraph tags and escapes characters, so checking only the file size would let a document in that could not be saved after one edit. The file limit is higher because a .docx file with pictures is much larger than its text, and the pictures are not imported.

## Deployment and storage

The Dockerfile runs Gunicorn with two workers and `--preload`, so the database is created and seeded once before the workers start. Separately from that, `init_db` waits for the SQLite lock and retries the switch to WAL mode. Starting several workers on an empty database was the cause of a "database is locked" crash found during testing.

The Render Blueprint uses the free plan, which has no persistent disk. On that plan the database returns to the seeded state on every restart or redeploy, and after the service sleeps when idle. That is enough for a reviewer to follow the full flow in one sitting. Durable storage needs a persistent disk mounted at `/data`, which is a paid option on Render. A move to Postgres would change only `db.py` and the SQL in `services.py`.

## Deliberate cuts

- Real-time co-editing and presence. Conflict detection covers the safety side of two people editing at once. Merging their edits would need a CRDT or operational transformation, which is out of proportion for this scope.
- Real authentication, because the brief allows seeded users.
- Document deletion, a view-only role, comments, version history, and export.
- Handoff chains, where the contributor passes the document to a third person instead of back to the owner. The owner decides who acts next in this version.

## Next 2 to 4 hours

1. Deploy with a persistent disk, or with Render Postgres, so the live demo keeps data between visits.
2. Show what changed while a document was handed off: store the content at "Hand off" and show a simple diff when it comes back as Returned. This is the most useful addition for the owner reviewing a return.
3. Refresh the handoff card and dashboard every 20 to 30 seconds, so a returned document appears without switching tabs or reloading.
4. Add a view-only sharing role and document deletion, both with tests at the service layer.
