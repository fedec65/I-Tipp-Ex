.PHONY: test fixtures

test:
	python3 -m unittest discover -s tests -v

fixtures:
	python3 assets/fixtures/build_fixtures.py
