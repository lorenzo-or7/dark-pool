# Day Trader Skill (vendored)

Source: https://github.com/Jakeschincariol/day-trader-skill, v2.0.0 (commit 3d0f4ef), MIT License (see LICENSE).
Copied unmodified. Last checked against the GitHub repository on 2026-10-30: every vendored
file is byte-identical to upstream, except the two scanner SymDir fixtures, which differ only in
line endings (CRLF upstream, LF here after git normalization).

Included: trader-scanner, trader-timemachine, trader-entry, trader-exit, trader-budget,
trader-risk, trader-news, trader-analyst, trader-alerts, trader-pelosi, with their original
tests and fixtures.

Deliberately NOT included: trader-broker (order execution). DARK POOL never sends orders.
Because of that, upstream tests/test_broker.py, tests/test_risk.py and tests/test_repo.py
(which load or count trader-broker) are not copied either.

Integrated in the API: scanner, timemachine, entry, exit, budget, risk, news, analyst.
trader-alerts (Bloco 5) and trader-pelosi (Bloco 10) are wired to routes; the engines are not edited.

The DARK POOL backend calls these scripts through `app/engines/runner.py`
(argument lists, no shell, timeouts, cancellation) and never edits them.
