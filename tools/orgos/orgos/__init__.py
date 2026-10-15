"""orgos: the team's operating system.

Persistent task records, agent roster, reviewer assignment, merge verification, a PR
watchdog, execution budgets and a read-only dashboard. Everything that ordinary code can
decide (state transitions, queueing, dependency cycles, reviewer selection, deduplication)
is decided here deterministically, so a model is only called when judgment is needed.

Internal tooling: not part of the product, not deployed to AWS.
"""
