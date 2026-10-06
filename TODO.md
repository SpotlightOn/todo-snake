# TODO

Open items for Todo Snake, focused on the Nextcloud Tasks sync. The project is
young and the data model may still change freely — no backward-compatibility
constraints.

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
- [ ] **Attachments / links (`ATTACH`)**
      Attach URLs to a task (and open them).
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

## Decisions (resolved, no code needed)

- **Calendar auto-create stays.** A `404` on the chosen task calendar creates
  it, so a user can just paste a URL/name for a list that does not exist yet.
  Deleting the calendar in Nextcloud therefore re-creates it on the next sync —
  intended, because the account is bound to that calendar.
- **Last-write-wins** stays the conflict model. Conditional `PUT`/`If-Match`
  (see below) now detects concurrent edits instead of silently overwriting
  them; sub-second collisions and host clock skew remain inherent to LWW and
  are accepted for a single-user app.

## Recently done (for context)

- Nextcloud Tasks sync (CalDAV / `VTODO`), one calendar chosen by full URL,
  created on demand.
- Browser login via Login Flow v2 (SSO / 2FA), no shell needed.
- Raw-`VTODO` preservation: editing only rewrites owned fields, so foreign
  properties (categories, recurrence, attachments, custom fields, foreign
  alarms) survive.
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
