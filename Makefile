.PHONY: install test demo serve
install:
	python -m pip install -e '.[dev,ml]'
test:
	python -m pytest -q
demo:
	flood-cat analyse data/demo/exposure.csv --output runtime/demo-report.json
serve:
	flood-cat serve
