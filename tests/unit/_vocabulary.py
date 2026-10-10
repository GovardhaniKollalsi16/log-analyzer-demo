"""Synthetic scenario names (decision D6 + scenario topics).

They may appear in `mocklogs` and in tests, but never in `investigator` (it would
hardcode answers) or in the agent's SKILL.md (it would hint at answers).
"""

SCENARIO_VOCABULARY = [
    "order-api",
    "fulfillment-worker",
    "notification-worker",
    "edge-gateway",
    "partner-pricing",
    "orders.events",
    "pricing.events",
    "fulfillment-consumers",
    "appdb",
]
