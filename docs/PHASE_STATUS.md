# Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: project, custom user, roles, auth, base UI, admin, tests | Done |
| 2 | Academic management | Not started |
| 3 | Reminders | Not started |
| 4 | Attendance and performance | Not started |
| 5 | Research study | Not started |
| 6 | Questionnaires | Not started |
| 7 | Analytics and exports | Not started |
| 8 | Final verification and documentation | Not started |

## Phase 1 design decisions / assumptions
- One primary role per user (`User.role`), exclusive; roles are not stacked.
- `is_staff` (Django Admin access) is derived: true only for administrators and superusers.
- Role groups ("System Administrator", "Lecturer", "Student", "Researcher") are created after migrate. Only the
  administrator group has model permissions so far; later phases extend `ROLE_PERMISSIONS` in
  `apps/accounts/signals.py`.
- `AuditLog` is append-only (no add/change/delete in Django Admin). It records logins, logouts, failed login
  usernames (never passwords), and user create/update events.
- An administrator cannot demote or deactivate their own account (lock-out protection).
- Ambiguity: the brief did not say how accounts are created. Default chosen: administrators create accounts;
  there is no public self-registration.
