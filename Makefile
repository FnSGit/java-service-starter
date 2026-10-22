.PHONY: install clean test

install:
	uv tool install --force --reinstall .

test:
	uv run pytest tests/ -v

clean:
	rm -rf build dist *.egg-info