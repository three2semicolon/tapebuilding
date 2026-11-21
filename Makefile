.PHONY: build start dev lint

build:
	npm run build --prefix src/app/ui

start:
	uv run app

dev:
	npm run dev --prefix src/app/ui

lint:
	uv run ruff check src/
	npm run lint --prefix src/app/ui
