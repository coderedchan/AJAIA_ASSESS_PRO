# Submission: Relay Docs

## Reviewer links

- Google Drive folder: TODO, add the folder link after uploading.
- Live application: see `LIVE_URL.txt`.
- Walkthrough video: see `WALKTHROUGH_URL.txt`.

## Demo accounts

There are no passwords. The first screen lists the seeded accounts, and the "Signed in as" menu in the top bar switches between them.

- **Alex Morgan** owns "Northwind delivery proposal", which is shared with Sam and handed to Sam.
- **Sam Rivera** has edit access and sees the proposal under "Needs your attention".
- **Jordan Lee** has no access, which shows the refused case.

## Included materials

| Path | Contents |
| --- | --- |
| `README.md` | What works, local setup, Docker, tests, deployment, upload types, and known limits. |
| `ARCHITECTURE.md` | Priorities, stack, data model, access rules, handoff states, saving, deployment, cuts, and the next 2 to 4 hours. |
| `AI_WORKFLOW.md` | Tools used, where AI helped, output that was changed or rejected, and how the work was verified. |
| `SUBMISSION.md` | This file. |
| `LIVE_URL.txt` | Deployed application URL. |
| `.gitignore` | Files kept out of the repository. |
| `WALKTHROUGH_URL.txt` | Walkthrough video URL. |
| `screenshots/` | Twelve screenshots from the automated browser run, numbered in the order of the review flow. |
| `source/relay/` | Application code: Flask app, service layer, API, importers, sanitiser, template, styles, client script, and the vendored TipTap bundle. |
| `source/tests/` | 19 pytest tests. The required handoff test is in `test_handoff.py`. |
| `source/scripts/` | `e2e_smoke.py` (browser check), `check_prose.py` (prose scan), and `build-editor.sh` (rebuilds the editor bundle with Docker). |
| `source/editor-build/` | `package.json`, lockfile, and entry file for the editor bundle. |
| `source/Dockerfile`, `render.yaml` | Container image, and the Render Blueprint at the repository root. |
| `source/requirements.txt`, `source/requirements-dev.txt`, `source/pytest.ini` | Python dependencies and test settings. |

## Review flow

1. Open the live URL and choose **Sam Rivera**. "Needs your attention" shows the Northwind proposal with Alex's instruction, "Check the delivery dates."
2. Open it. The review request shows that Alex sent it to Sam and is awaiting a response. Edit a delivery date, add a note, and click **Send back to Alex Morgan**.
3. Switch to **Alex Morgan**. The proposal is under "Needs your attention" as "Returned to you", with Sam's note. Open it, confirm that Alex is still the owner and Sam still has access, and click **Finish review**.
4. As Alex, click **New document**. Type a title and some text, and use bold, italic, underline, H1 or H2, and both list types. Wait for "Saved at", then refresh the page to confirm everything is still there.
5. Click **Share**, add Sam, then choose Sam under Send to, add what needs checking, and click **Send to Sam Rivera**.
6. Switch to **Jordan Lee** and open the same document URL. The page says the document is not available.
7. On the dashboard, use **Import a file** with a .txt, .md, or .docx file. Try another type, such as an image, to see the refusal message.

## Local setup

See `README.md`. The application is in `source/`. After installing, run `flask --app relay run` from `source/`.

## Verification

- `pytest` in `source/`: 19 passed.
- `python scripts/e2e_smoke.py <url> ../screenshots`: "all browser checks passed", against both the local Gunicorn server and a freshly built Docker image. The script fails on any failed HTTP response that a step does not expect.
- Docker container restarted with a volume: documents created before the restart were still listed.
- A separate review of the package (`docs/SUBMISSION_REVIEW.md`, not included in this folder) found four defects: simultaneous saves could overwrite each other, a handoff could be returned while edits had failed to save, a focus refresh cleared handoff text, and import and save used different size limits. All four are fixed, each with a check that fails without the fix. Details are in `AI_WORKFLOW.md`.
- `python scripts/check_prose.py ..`: 0 issues.
- Deployed checks: TODO, run the review flow above on the live URL after deployment.

## Completion status

- **Working:** every core requirement (create, rename, rich text, autosave and reopen, import, ownership, sharing with owned and shared views, and persistence) and the review request with "Needs your attention". Also working: save-conflict detection that holds for simultaneous saves, handoff actions that wait for edits to be saved, access removal, and a phone-width layout.
- **Not yet done:** deployment, the walkthrough recording, and the Drive upload. The TODO lines above and in the two URL files mark them.
- **Limits:** no merging of simultaneous edits (a conflict is detected and the user chooses a version), mocked sign-in, and no deletion or view-only role. Data survives restarts when the SQLite file is on persistent storage. On the free Render plan it is not, so the data resets to the seeded state when the service restarts.
- **Next 2 to 4 hours:** persistent hosting storage, a "changed since handoff" diff for the owner, periodic refresh of the card and dashboard, then a view-only role and deletion. Details are in `ARCHITECTURE.md`.
