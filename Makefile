.PHONY: install test build build-fr build-eu build-nim run clean-artifacts
install:
	python3 -m pip install -r requirements.txt

test:
	PYTHONPATH=. python3 -m pytest -q

build: build-fr build-eu

build-fr:
	python3 build.py legi

build-eu:
	python3 build.py eu

build-nim:
	python3 build.py nim

run:
	python3 app.py

clean-artifacts:
	rm -rf artifacts/eu
