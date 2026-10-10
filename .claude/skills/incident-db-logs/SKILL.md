---
name: incident-db-logs
description: How to fetch database logs for an incident investigation - logging in via the user's SSO, picking the DB host (cluster) and database name from the app config, searching by time window and app, and what to look for. Used by the incident-logs coordinator for step 5, only when the seed app's config declares a database. All data is synthetic (MOCK).
---

# incident-db-logs (v0)

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

## 2. Where the inputs come from

| Input | Source |
|---|---|
| `--host` (DB cluster) | The seed app's config: `db.host` |
| `--db` | The seed app's config: `db.name` |
| `--grep <app>` | The seed app's name. DB sessions are tagged `app=<name>` |
| time window | Same window as the coordinator |

**Run this step only if the config declares a database** (`db.name` non-empty). Otherwise skip it and say so.

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
