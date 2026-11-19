"""Bloco 11: the paper-trading agent (Alpaca paper account only).

Runs as its own process (scripts/paper_agent.py), never inside the public web app: no route of the
API imports this package, so no visitor can start, stop or steer it. Off by default
(DP_AGENT_MODE=off). The order endpoint is the paper one and there is no setting to change it:
trading real money is not implemented.
"""
