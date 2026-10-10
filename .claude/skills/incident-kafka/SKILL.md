---
name: incident-kafka
description: How to fetch Kafka data for an incident investigation (kafka-consumer-groups, kafka-get-offsets, kafka-console-consumer and broker/client log shapes) - logging in via the user's SSO, picking the cluster (bootstrap servers) and topic, searching by time window and correlation ID, finding upstream producers and downstream consumers, and what to look for. Used by the incident-logs coordinator for step 3. All data is synthetic (MOCK).
---

# incident-kafka (v0)

> Part of the `incident-logs` investigation. Read that coordinator's hard rules first; they apply here.
> Example values are deliberately neutral and match no scenario. Output samples are illustrative until `mocklogs` exists.

## 1. Logging in

- Kafka is read with the **user's SSO session**. There are no agent credentials, and **you never run `mocklogs sso login`**.
- SSO missing or expired (exit code **3**):
  ```
  # MOCK DATA — synthetic, not from any real system
  error: SSO session expired or missing. Ask the user to run: mocklogs sso login
  ```
  Stop, ask the user, and retry **once**. If the user declines → record `auth_required` for the remaining Kafka steps.
- Not authorized for a topic or group (exit code **4**):
  ```
  # MOCK DATA — synthetic, not from any real system
  org.apache.kafka.common.errors.TopicAuthorizationException: Not authorized to access topics: [example.in]
  ```
  Record `access_denied` for that topic or group. Don't retry.

## 2. Where the inputs come from

| Input | Source |
|---|---|
| cluster = `--bootstrap-server` | The seed app's config: `kafka.bootstrap.servers` |
| topics | Config: `kafka.consumer.topics` (consumed → **upstream**), `kafka.producer.topics` (produced → **downstream**) |
| consumer group | Config: `kafka.consumer.group` |
| time window | Same window as the coordinator (default: seed `ts` − 10 min to + 2 min) |
| `correlation_id` | The seed line |

## 3. Commands

**Consumer-group lag, for the seed app's group** (is it falling behind?):
```
mocklogs kafka-consumer-groups --bootstrap-server <servers> --describe --group <group> \
    --samples 3 --save-dir <workdir>
```
`--samples N` (mock extension) prints N snapshots one minute apart, standing in for polling repeatedly. It shows whether lag is **growing** or steady.

**Who consumes a topic, to find downstream apps:**
```
mocklogs kafka-consumer-groups --bootstrap-server <servers> --describe --all-groups --save-dir <workdir>
```
Each group on one of the seed app's **produced** topics is a downstream consumer. Its `CLIENT-ID` is the app name.

**Search messages by time:** first find the offsets at the window start, then read from them.
```
mocklogs kafka-get-offsets --bootstrap-server <servers> --topic <topic> --time <epoch-ms> --save-dir <workdir>
mocklogs kafka-console-consumer --bootstrap-server <servers> --topic <topic> \
    --partition <p> --offset <o> --max-messages <n> \
    --property print.headers=true --property print.timestamp=true \
    --property print.partition=true --property print.offset=true \
    --grep <correlation-id> --save-dir <workdir>
```
- Run the consumer once per partition that `kafka-get-offsets` returned.
- `--grep` is a mock extension (the real tool would be piped to grep).
- On a topic the seed app **consumes**, the `producer_app` header names the **upstream** app.

**Broker and client logs for a topic, by time:**
```
mocklogs kafka logs --bootstrap-server <servers> --component broker|producer|consumer --topic <topic> \
    --since-time=<rfc3339> --until-time=<rfc3339> --save-dir <workdir>
```

## 4. Output formats (illustrative)

Each output starts with the MOCK banner line.

Lag (`--samples` puts `# sample k/N at <rfc3339>` before each snapshot):
```
GROUP              TOPIC       PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG  CONSUMER-ID       HOST        CLIENT-ID
example-app-group  example.in  0          1200            1200            0    consumer-1-0000   /10.0.0.1   example-app
```

Offsets at a time (`topic:partition:offset`):
```
example.in:0:1180
example.in:1:977
```

Messages (tab-separated timestamp, partition, offset, headers, value):
```
CreateTime:1767225600000	Partition:0	Offset:1199	correlation_id:c-0000,producer_app:example-upstream	{"id":"x-1","payload":"..."}
```

Broker and client logs (log4j style):
```
[2026-01-01 00:00:00,500] INFO [Consumer clientId=example-app-1, groupId=example-app-group] Setting offset for partition example.in-0 to the committed offset 1200 (org.apache.kafka.clients.consumer.internals.ConsumerCoordinator)
```

## 5. What to look for

You don't classify (`investigator` does). These signals help you choose what to fetch next:
- **Lag:** growing across samples, or one partition whose `CURRENT-OFFSET` doesn't move while `LOG-END-OFFSET` grows.
- **Messages:** whether a message with the correlation ID exists at all on the expected topic; its `producer_app`; its timestamp relative to the seed. A **missing** message is evidence too.
- **Producer:** send retries, delivery or request timeouts, expired records, "buffer exhausted".
- **Broker:** rejected requests, offline partitions or no leader, ISR shrink, under-replicated partitions.
- **Consumer:** processing exceptions, the same offset redelivered over and over, dead-letter sends, rebalances, "max poll interval exceeded".

Remember: a message consumed about a minute after it was produced can be normal delivery delay, not clock skew. Leave timing to `investigator`.
