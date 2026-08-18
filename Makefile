.PHONY: test fixtures dist

test:
	python3 -m unittest discover -s tests -v

fixtures:
	python3 assets/fixtures/build_fixtures.py

dist:
	mkdir -p dist
	rm -f dist/i-tipp-ex.skill
	zip -r dist/i-tipp-ex.skill SKILL.md scripts references assets LICENSE README.md -x '*/__pycache__/*' -x '*.pyc' -x '.DS_Store'
