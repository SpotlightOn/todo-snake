# TODO

What's next for a fast-moving alpha: sync robustness, a leaner code structure,
and a clean test suite. The data model is still flexible — we can change it
freely before compatibility locks anything in.

## Features

- [ ] **Subtasks**
      Child tasks linked via `RELATED-TO` (parent UID). Needs a tree/indent
      view, a parent picker in the dialog, and completion cascades.
- [ ] **Tags / categories (`CATEGORIES`)**
      UI to add/remove tags and a filter/sidebar. Currently preserved on sync
      but not editable in Todo Snake.
- [ ] **Multiple lists (`projects`)**
      In Nextcloud Tasks, calendars are lists. Today an account syncs exactly
      one calendar; a "lists" concept would map several calendars to several
      lists and allow moving tasks between them.
- [ ] **Location (`LOCATION`, `GEO`)**
      Optional free-text location / coordinates.
- [ ] **Percent complete (`PERCENT-COMPLETE`)**
      Partial progress independent of the status.
- [ ] **Finer priority (0–9)**
      Currently rounded to low / medium / high; expose the full iCalendar
      range if needed.
- [ ] **Multiple reminders per task**
      Right now one reminder lead per task (`VALARM`). Support several
      (e.g. 1 day and 10 minutes before).
- [ ] **Recurrence beyond the basics**
      The UI offers daily/weekly/monthly/yearly + interval. `BYDAY` (e.g.
      "every 2nd Tuesday") and `COUNT` are parsed but not offered/advanced.

## Sync robustness

- [ ] **`sync-collection` + `sync-token` (RFC 6578)** — *optional optimisation*
      Replace the full `calendar-query` (+ "known UID diff" for deletions) with
      WebDAV Sync, so the server reports changed/deleted resources directly.
      Deliberately **not** done yet: the current approach is simple, correct
      (deletions already propagate) and proven by tests; a sync-collection
      rewrite touches the core sync model (needs a persisted remote snapshot)
      and risks the working sync for a modest efficiency gain. Decide whether
      the gain is worth the rewrite before doing it.

## Code structure (optional follow-ups)

- [ ] **`ui/main_window.py` (≈670 lines)** mixes toolbar, actions, reminders,
      the sync animation and selection handling. Extract reminders and the sync
      spinner into helpers; the window should only wire them together.
- [ ] **`ui/settings_dialog.py` (≈460 lines)** holds the accounts tab, the
      behaviour tab and the orphan cleanup. Split into a small package.
- [ ] **`sync/icalendar.py` (≈440 lines)** is a hand-written RFC 5545 subset.
      Fine while it is tested, but if parser edge cases keep appearing, the
      `icalendar` library (BSD, pure Python) is the one swap worth making.
- [ ] **Quiet test suite:** the suite emits `ResourceWarning: unclosed socket/file`
      (fake HTTP servers, log files).
- [ ] **Every sync re-uploads every task** (`pushed: 5/6` in the log, also
      before attachments existed). The merge never converges — worth finding
      out why; it is not just cosmetic.

## Decisions (resolved, no code needed)

- **The Nextcloud Tasks web UI never shows attachments.** The feature is not
  implemented there: issue
  [#91 “Possibility of attaching file, note or event”](https://github.com/nextcloud/tasks/issues/91)
  is still open, and #208, #1303, #1470, #2961 and #2976 were all closed as
  duplicates of it. Todo Snake therefore keeps the standard `ATTACH` property
  (visible in Files and in CalDAV clients that render attachments) and does
  **not** mirror the link into the task description — with several accounts that
  would fight over one description field.
- **Calendar auto-create stays.** A `404` on the chosen task calendar creates
  it, so a user can just paste a URL/name for a list that does not exist yet.
  Deleting the calendar in Nextcloud therefore re-creates it on the next sync —
  intended, because the account is bound to that calendar.
- **Last-write-wins** stays the conflict model. Conditional `PUT`/`If-Match`
  (see below) now detects concurrent edits instead of silently overwriting
  them; sub-second collisions and host clock skew remain inherent to LWW and
  are accepted for a single-user app.

## Recently done (for context)

- **Attachments** (`ATTACH`): files attach to a task, stored locally as BLOBs
  (10 MB cap) and opened with one click. On **Nextcloud** accounts the file is
  uploaded to each account separately (`Todo Snake/Attachments/<task>/`), so
  every server carries its own copy and its own `ATTACH` URL; files attached
  elsewhere show up as link-only entries. Non-Nextcloud providers keep
  attachments local. Removing an attachment (or a whole task) also deletes the
  uploaded file from every account on the next sync; every sync additionally
  **sweeps the task folders** and removes files nothing references any more, so
  leftovers from earlier versions clean themselves up. **Settings → Sync
  accounts → “Clean up orphaned files…”** does the same for the whole folder on
  demand, after a confirmation.
  Visible in the UI: a **Files** column (count + file names in the tooltip), an
  **Attachments…** button in the task dialog, and 48×48 previews (images) or
  type icons (PDF, text, spreadsheet, archive, audio, video, unknown).
- Nextcloud Tasks sync (CalDAV / `VTODO`), one calendar chosen by full URL,
  created on demand.
- Browser login via Login Flow v2 (SSO / 2FA), no shell needed.
- Raw-`VTODO` preservation: editing only rewrites owned fields, so foreign
  properties (categories, recurrence, custom fields, foreign alarms) survive.
- Server-side deletion tracking (known UIDs + ETags); deletions propagate
  instead of resurrecting.
- **Recurring tasks (`RRULE`)** with UI (daily/weekly/monthly/yearly + every N);
  completing a recurring task advances it to the next occurrence instead of
  marking it done.
- Task status (open / in progress / done), start date, all-day due dates and a
  per-task reminder lead time.
- **Conditional writes**: `PUT` sends `If-Match: <etag>` and surfaces a
  concurrent edit (HTTP 412) instead of overwriting it.
- **Keyring**: app passwords go to the OS Secret Service (`secret-tool`) when
  available, with a `QSettings` fallback.
- Bidirectional sync fixes: first-sync 404, `LAST-MODIFIED` vs
  `X-TODO-SNAKE-UPDATED` precedence.
- "Sync now" toolbar button (right-aligned, green + spinning while active,
  disabled without enabled accounts); periodic or manual sync.
