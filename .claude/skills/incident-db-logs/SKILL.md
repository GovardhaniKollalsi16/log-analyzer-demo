---
name: incident-db-logs
description: How to fetch database logs for an incident investigation - logging in via the user's SSO, the required inputs (DB host and database name from the incident, time window from the seed), searching by time window and app, and what to look for. Used by the incident-logs coordinator for step 5, only when the incident names a database. All data is synthetic (MOCK).
---

# incident-db-logs (v0.1)

> Part of the `incident-logs` investigation. Read that coordinator's hard rules first; they apply here.
> Example values are deliberately neutral and match no scenario. Output samples are illustrative until `mocklogs` exists.

## 1. Logging in

- DB logs are read with the **user's SSO session**. **You never run `mocklogs sso login`**, and you never use database passwords.
- SSO missing or expired (exit code **3**): stop, ask the user, retry **once**. If the user declines → record `auth_required`.
- Not entitled (exit code **4**):
  ```
  # MOCK DATA — synthetic, not from any real system
  error: permission denied: user cannot read logs for database "example-db" on host "example-db-host"
  ```
  Record `access_denied`. Don't retry.

## 2. Required inputs

| Input | Required? | Where it must come from |
|---|---|---|
| `--host` (DB cluster) | **Required** | The incident's `db: host=` line |
| `--db` (database name) | **Required** | The incident's `db: name=` line |
| time window | **Required** | Derived from the seed line's `ts` |
| `--grep <app>` | Optional | The seed line's `app`. DB sessions are tagged `app=<name>` |

**If any required input is missing, don't run any command from this skill.** Record a `missing_input` gap that names what's missing (e.g. `missing_input: db host`) and continue with the next step. Never guess or substitute a value, and never reuse another app's or another source's value.

If the incident has no `db:` line, there is no DB step. Say so in the report; it isn't an error.

## 3. Commands

**Search by time + app** (the main search):
```
mocklogs db logs --host <db-host> --db <name> \
    --since-time=<rfc3339> --until-time=<rfc3339> --grep <app> --save-dir <workdir>
```

**Search by time only** (when the app-filtered search is empty, or you need to see whether other apps were affected too):
```
mocklogs db logs --host <db-host> --db <name> \
    --since-time=<rfc3339> --until-time=<rfc3339> --save-dir <workdir>
```
`--grep` and `--until-time` are mock extensions.

## 4. Output format (illustrative)

The first line is the MOCK banner. Then a postgres-style `log_line_prefix`, then the message:
```
# MOCK DATA — synthetic, not from any real system
2026-01-01 00:00:02.000 UTC [1001] app=example-app user=example db=example-db LOG:  connection authorized: user=example database=example-db
```
Prefix fields: timestamp with zone, `[pid]` (one DB session), `app=`, `user=`, `db=`, then the severity (`LOG`/`WARNING`/`ERROR`/`FATAL`/`PANIC`) and the message.

## 5. What to look for

You don't classify (`investigator` does). These signals help you decide whether to widen the search:
- `ERROR`/`FATAL`/`PANIC` lines;
- connections refused, or "too many connections";
- authentication failures;
- deadlocks; statements cancelled by a timeout; aborted transactions;
- slow statements or long lock waits;
- the connection count approaching the limit;
- whether problems are limited to the seed app's sessions (`app=`) or hit every app, which points to the DB itself vs. the app's use of it.
