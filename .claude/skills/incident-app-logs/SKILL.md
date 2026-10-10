---
name: incident-app-logs
description: How to fetch application logs for an incident investigation (kubectl logs shape) - logging in via the user's SSO, the required inputs (cluster and namespace from the incident, app and time from the seed), searching by time window, correlation ID, and thread, and what to look for. Used by the incident-logs coordinator for steps 1 and 4. All data is synthetic (MOCK).
---

# incident-app-logs (v0.1)

> Part of the `incident-logs` investigation. Read that coordinator's hard rules first; they apply here.
> Example values are deliberately neutral and match no scenario. Output samples are illustrative until `mocklogs` exists.

## 1. Logging in

- There are no agent credentials. App logs are read with the **user's SSO session**. **You never run `mocklogs sso login`**; the user does.
- If the session is missing or expired (exit code **3**):
  ```
  # MOCK DATA — synthetic, not from any real system
  error: SSO session expired or missing. Ask the user to run: mocklogs sso login
  ```
  Stop and ask the user to log in, then retry the same command **once**. If the user declines → record `auth_required` for this app and continue.
- If the user isn't entitled to this app's logs (exit code **4**):
  ```
  # MOCK DATA — synthetic, not from any real system
  Error from server (Forbidden): pods "example-app-5c6d7-0" is forbidden: user cannot get logs in namespace "apps" on cluster "example-cluster"
  ```
  Record `access_denied` for this app. Don't retry.

## 2. Required inputs

| Input | Required? | Where it must come from |
|---|---|---|
| `cluster` (kube context) | **Required** | Seed app: the incident's `app:` line. Related app: the incident's `app[<name>]:` line |
| `namespace` | **Required** | Same as `cluster` |
| `app` | **Required** | Seed app: the seed line's `app`. Related apps: the app name from Kafka output (`producer_app` header = upstream, `CLIENT-ID` = downstream) |
| time window | **Required** | Derived from the seed line's `ts` (default −10 min / +2 min) |
| `correlation_id` | Optional | The seed line. If absent, use the thread search or the time-only search |
| `instance` + `thread` | Optional (both or neither) | The seed line. Only for the **seed app's** own thread segment |

**If any required input is missing, don't run any command from this skill.** Record a `missing_input` gap that names what's missing (e.g. `missing_input: app cluster`) and continue with the next step. Never guess or substitute a value, and never reuse another app's or another source's value.

**Related apps need their own location.** Use an `app[<name>]: cluster=… namespace=…` line from the incident for that app. If the incident has no such line, record `missing_input: cluster/namespace for <name>` and **don't fetch** that app's logs. Never reuse the seed app's cluster for another app *(pending user confirmation: see the coordinator, §2)*.

## 3. Commands

**Search by time + correlation ID** (the main search, for the seed app and for related apps):
```
mocklogs kubectl logs deploy/<app> --context <cluster> -n <namespace> --timestamps \
    --since-time=<rfc3339> --until-time=<rfc3339> \
    --grep <correlation-id> --save-dir <workdir>
```

**Search by time + thread** (the seed's thread segment: ID-less lines from the same unit of work, such as retries and stack traces):
```
mocklogs kubectl logs deploy/<app> --context <cluster> -n <namespace> --timestamps \
    --since-time=<rfc3339> --until-time=<rfc3339> \
    --instance <pod> --thread <thread> --save-dir <workdir>
```

**Search by time only** (when the seed has no correlation ID, or the narrower searches found nothing):
```
mocklogs kubectl logs deploy/<app> --context <cluster> -n <namespace> --timestamps \
    --since-time=<rfc3339> --until-time=<rfc3339> --save-dir <workdir>
```

Notes:
- `--since-time` / `--until-time` are RFC 3339 UTC, e.g. `2026-01-01T00:00:00Z`.
- `--grep` and `--until-time` are **mock extensions** (the real tool would need a pipe, which isn't allowed).
- **Thread names are only meaningful within one app on one instance.** Never compare thread names across apps or pods. `investigator` limits thread links to a 1-minute window and stops them at a different correlation ID.

## 4. Output format (illustrative)

The first line is the MOCK banner. Then each line is an RFC 3339 prefix followed by one JSON object:
```
# MOCK DATA — synthetic, not from any real system
2026-01-01T00:00:01.250000000Z {"ts":"2026-01-01T00:00:01.250Z","level":"ERROR","cluster":"example-cluster","namespace":"apps","app":"example-app","instance":"example-app-5c6d7-0","thread":"worker-2","logger":"example.Handler","correlation_id":"c-0000","msg":"Request failed","error":{"type":"ExampleException","message":"example failure"}}
```
Fields: `ts`, `level`, `cluster`, `namespace`, `app`, `instance`, `thread`, `logger`, `correlation_id` (may be missing), `msg`, optional `error{type, message, stack}`.

Kafka **client** activity (producer sends, consumer processing) is logged here too, under a `logger` naming the Kafka client.

## 5. What to look for

You don't classify (`investigator` does). These signals just help you choose filters and decide whether to widen the window:
- `level` ERROR/FATAL, or an `error` object with a stack trace;
- retry wording ("retrying", "attempt n/N", "retries exhausted", "giving up");
- timeouts and waits that expire;
- Kafka client warnings and errors under a Kafka-client `logger`;
- circuit breaker opened, thread pool or queue saturation;
- the **first** error for the correlation ID, and what the same thread logged just before it.

If a correlation-ID search returns only the seed line, run the thread search next. If both are empty, widen the window once before moving on.
