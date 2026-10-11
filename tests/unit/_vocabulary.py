"""Synthetic scenario names (decision D6 + scenario topics).

They may appear in `mocklogs` and in tests, but never in `investigator` (it would
hardcode answers) or in the agent's SKILL.md (it would hint at answers).
"""

SCENARIO_VOCABULARY = [
    "order-api",
    "order-service",
    "product-service",
    "fulfillment-worker",
    "notification-worker",
    "edge-gateway",
    "partner-pricing",
    "orders.events",
    "pricing.events",
    "fulfillment.events",
    "fulfillment-consumers",
    "appdb",
    "notification-consumers",
    "cluster-a",
    "kafka-a:9092",
    "db-a",
]

# Phrases from the scenarios' injected faults. Generic signal names in the skills'
# "what to look for" lists (e.g. "ISR shrink") are fine; these exact story lines are not.
SCENARIO_STORY_PHRASES = [
    "Shrinking ISR from",
    "REQUEST_TIMED_OUT",
    "Expiring 1 record",
    "PricingTimeoutException",
    "Timed out waiting for pricing",
    "awaiting pricing event",
    "not published: pricing unavailable",
    "timed out waiting for in-sync replicas",
]
