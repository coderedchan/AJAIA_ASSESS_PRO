# AI workflow

## Tools used

- **Claude Code (Claude Opus 5.5) in VS Code.** It was the main tool. It read the assignment pack, proposed the stack and scope, wrote the server, client, tests, and documents, and ran every check listed below in the terminal.
- **Playwright with Chromium.** Claude Code wrote and ran a browser script (`source/scripts/e2e_smoke.py`) that drives the full flow and saves screenshots. Reviewing those screenshots found most of the interface bugs listed below.
- **Docker.** It was used to build the TipTap bundle without installing Node, and to run the production image locally before deployment.

I set the product direction: Relay Docs, the handoff card and its rules, the editorial style, and the instruction to finish the core requirements before the handoff feature. I also gave Claude Code a style guide on machine-sounding prose, and every piece of user-facing text was written against it.

## Where AI materially accelerated the work

- **Turning the brief into decisions.** Claude Code read the guideline, the seven-part assignment pack, and my feature brief, and checked which tools were installed (Python and Docker, no Node). It then proposed a stack that fit the machine and the hosting constraint. That replaced a round of manual research.
- **Writing the whole first version.** It wrote the schema, the service layer with a single access check, the JSON API, the client with autosave and conflict handling, and the handoff card in one pass, all following the separation rule from the brief.
- **Tests that check the right thing.** It wrote the required handoff test so that it reads ownership and access straight from the database after every step, not through the API. It then proved the test can fail, by running it against a copy of the code where sending a handoff changes the owner. The test failed with `changed after send`.
- **Browser verification.** The Playwright script covers sign-in, formatting, reload, sharing, handoff, return, the refused user, import, a save conflict between two browser sessions, and a phone-width layout. The same script ran against the local server and against the Docker image.

## Output that was changed or rejected

| What the AI produced | What happened | Change |
| --- | --- | --- |
| Editor build with TipTap pinned to 2.11.5 | esbuild failed because StarterKit pulled newer 2.x extensions than the pinned core. | Aligned every TipTap package on the same 2.x range and committed the lockfile. |
| SQLite start-up code | Starting Gunicorn with several workers on a new database crashed with "database is locked". | Added a lock timeout, a retry for the WAL switch, a single write transaction for seeding, and `--preload` in the Dockerfile. Then confirmed four workers boot cleanly. |
| First fix for the lock: switch connections to autocommit | Rejected. Multi-step operations such as removing access and resetting a handoff would no longer be atomic. | Kept the default transactions and fixed only start-up. |
| Handoff card rendering | A screenshot showed the word "null" under the form, because `replaceChildren()` prints a null argument as text. | Filtered out empty parts before rendering. |
| Card and dashboard styles | Screenshots showed unstyled field labels (the CSS selector was too narrow), a wrapped "Signed in as" label, a stray space in excerpts ("before tax ."), and "Awaiting Sam Rivera" shown to Sam. | Fixed each one and re-ran the browser check. |
| README claims about imports | Checking the claims against the code showed that Mammoth drops underline by default, and that the editor has no link tool. | Mapped underline in the .docx import and added a test for it. Corrected the README to say that links keep their text only. |
| Handoff API | The API accepted "Hand off" from Returned, which the interface never offers. | Restricted sending to Draft and added a test for the allowed status changes. |
| A browser test that typed into the wrong place | Sam's edit landed at the top of the document. Logging showed no reload and no second editor. ProseMirror reads a click's cursor position on the next `selectionchange` event, and the script typed before that event. | Fixed the test with a short pause after the click. The application was not changed, because a person cannot type within the same few milliseconds as a click. |

## Review of the finished package, and the fixes it led to

After the first version was complete, the package was reviewed separately against the requirements (`docs/SUBMISSION_REVIEW.md`, outside this folder). The review reproduced four defects that the original tests and browser script had missed, and it found a gap in the browser script itself. Claude Code fixed each one and added a check that fails without the fix. Each check was confirmed to fail on a copy of the code with the fix removed.

| Defect found in review | Cause | Fix | Check that now covers it |
| --- | --- | --- | --- |
| Two saves arriving at the same moment could both succeed, and one person's text replaced the other's. | The version was checked before a separate `UPDATE ... WHERE id = ?`. | The version condition is now part of the `UPDATE`. A save that matches no row is refused with 409. | `test_simultaneous_saves_cannot_both_succeed` holds two threads after their version check, then lets both write. Without the fix, both saves succeed. |
| "Return to owner" could succeed while the contributor's edits had failed to save. | The handoff action awaited `save()`, but `save()` did not report failure. | A new `flush()` method reports whether every change is stored. Handoff actions and leaving a document only go ahead when it does. | The browser script makes saves fail with a simulated 503, clicks "Return to owner", and checks that the status stays Awaiting response. |
| Text typed into the handoff card disappeared when the window regained focus. | The focus refresh redrew the card from server data and dropped unsaved form input. | Typed text is kept in the page's own state, and the card is only redrawn when server data changed. | The browser script types an instruction and a return note, fires the focus event, and checks both values. |
| A file between 1 MB and 2 MB could be imported but not saved after one edit. | The import limit was 2 MB of file, and the save limit was 1 MB of content. | The 1 MB content limit is now checked on the converted text at import, as well as on save. | `test_import_and_save_share_one_content_limit`. |
| The browser script ignored failed API responses. | Its response check skipped every `fetch` request, so it could not see API errors. | Every response of 400 or above now fails the run, unless the step that causes it declares it. | The script itself. The second browser session also waits for sign-in to finish before it navigates. |

The lesson for the AI-written tests was that they only covered the paths that were expected to work. The new checks simulate failure and timing: a failed save, two saves at once, and a refresh during typing.

## Verification

- **Automated tests:** `pytest` in `source/` runs 19 tests, and all 19 pass. They cover the handoff rules, access control, persistence across an app restart, save conflicts including simultaneous saves, sanitising, all three upload types, and the shared content limit.
- **Browser check:** `scripts/e2e_smoke.py` passed against the local Gunicorn server and against a freshly built Docker image, both after the review fixes. It fails on any script error, console error, or failed HTTP response that the current step did not declare. The declared ones are the 404 for Jordan, the 409 in the save-conflict step, and the simulated 503 in the failed-save step.
- **Persistence:** after the browser run, the Docker container was restarted with a mounted volume, and the documents created during the run were still listed for Alex.
- **Visual review:** the 12 screenshots in `screenshots/` were regenerated after the fixes and checked at desktop width and phone width.
- **Prose check:** `scripts/check_prose.py` scans every document, template, script, and Python file for em dashes, "X is X" sentences, inflated verbs, negative parallelism, and runs of near-identical bullets. It reports 0 issues. A pattern scan does not catch everything, so the text was also read through.
- **Live deployment:** the same browser check passed against https://relay-docs-w94c.onrender.com on Render's free plan. Restarting the service afterwards returned the data to the seeded state, which confirms the documented reset behaviour.
- **Not verified here:** the Google Drive folder and the walkthrough video, which are prepared separately before submitting.
- **Remaining limits:** there is no live merging of simultaneous edits, and the free Render plan resets the data on restart. Both are explained in `ARCHITECTURE.md`.

## Follow-up wording review

Codex reviewed the updated source and simplified the interface copy: Send to, named Send back buttons, Review request, and My documents. Owner is shown in Share, where it explains access management. The review retained the existing data model and access rules, updated the browser selectors and documentation, and regenerated the screenshots. The 19 backend tests and the complete browser check passed locally. Deployment, the video recording, and the Google Drive upload are still pending.
