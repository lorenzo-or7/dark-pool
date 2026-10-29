# Day Trader Skill (vendored)

Source: https://github.com/Jakeschincariol/day-trader-skill, v2.0.0, MIT License (see LICENSE).
Copied unmodified from the installed Claude plugin on 2026-10-29.

Included: trader-scanner, trader-timemachine, trader-entry, trader-exit,
trader-budget, trader-risk, trader-news, trader-analyst, with their original
tests and fixtures.

Deliberately NOT included: trader-broker (order execution). DARK POOL never
sends orders. trader-alerts and trader-pelosi are not integrated in v0.1.

The DARK POOL backend calls these scripts through `app/engines/runner.py`
(argument lists, no shell, timeouts, cancellation) and never edits them.
