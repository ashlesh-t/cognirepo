# CogniRepo — common development targets
# Usage: make test | make lint

.PHONY: test lint

test:
	pytest tests/ -v --tb=short

lint:
	pylint $$(git ls-files '*.py' | grep -v 'venv/') \
		--disable=C,R,import-error \
		--fail-under=8.0
