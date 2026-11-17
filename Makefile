# Full pipeline, same order as CI.
all:
	python scripts/generate_data.py
	dbt build --profiles-dir . --exclude tag:post_ml
	python scripts/forecast_revenue.py
	python scripts/score_accounts.py
	dbt build --profiles-dir . --select tag:post_ml

tune:
	python scripts/tune_forecast.py
