.PHONY: install bot scan report dashboard test validate

install:
	pip install -r requirements.txt
	npm ci

bot:
	uvicorn target.bank_bot:app --port 8000 --reload

scan:
	python -m engine.run --targets bankbot-baseline bankbot-hardened

report:
	python -m report.render

dashboard:
	streamlit run dashboard/app.py

validate:
	python -m engine.benchmark

test:
	python -m pytest
