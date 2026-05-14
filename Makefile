.PHONY: install clean

install:
	uv tool install --force --reinstall .

clean:
	rm -rf build dist *.egg-info