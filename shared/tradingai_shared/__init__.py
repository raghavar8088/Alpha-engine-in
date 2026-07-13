"""TradingAI shared package: the internal domain model (`domain`) and the four plugin
contracts (`contracts`) that every service builds against. Install editable into each
service's venv: `pip install -e ../shared`.

`shared/market_data_schema.py` (Phase 1 snapshot field constants) predates this package
and stays as-is; new code should import from here instead."""
