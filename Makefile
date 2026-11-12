# AnsibleCLI — developer tasks
#
#   make            show this help
#   make install    create .venv and install the package + dev extras
#   make run        launch the interactive wizard
#   make test       run the test suite
#   make lint       ruff check
#   make fmt        import sorting + safe fixes
#   make check      lint + test (run this before every commit)
#   make bump       bump patch version (PART=minor|major to override)
#   make release    check + bump + commit + tag + push

PYTHON  ?= python3
VENV     = .venv
BIN      = $(VENV)/bin
STAMP    = $(VENV)/.installed
PART    ?= patch
REMOTE  ?= origin
BRANCH  ?= main
VERSION  = $(PYTHON) scripts/bump_version.py --current

.DEFAULT_GOAL := help
.PHONY: help install run test test-verbose lint fmt check build clean bump release tag-only

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(STAMP): pyproject.toml ## (re)install whenever dependencies change
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e '.[dev]'
	@touch $@

install: $(STAMP) ## Create .venv and install package + dev deps

run: $(STAMP) ## Launch the interactive wizard
	$(BIN)/ansiblecli

test: $(STAMP) ## Run the test suite
	$(BIN)/python -m pytest

test-verbose: $(STAMP) ## Run tests with verbose output
	$(BIN)/python -m pytest -v

lint: $(STAMP) ## Run ruff
	$(BIN)/python -m ruff check .

fmt: $(STAMP) ## Auto-fix import order and simple lint issues
	$(BIN)/python -m ruff check . --fix

check: lint test ## Lint + test — run before committing

build: $(STAMP) ## Build sdist + wheel into dist/
	$(BIN)/python -m build

clean: ## Remove caches and build artifacts
	rm -rf dist build *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

bump: ## Bump version in ansiblecli/__init__.py (PART=patch|minor|major)
	$(PYTHON) scripts/bump_version.py $(PART)

tag-only: ## Tag whatever version is currently in the source
	git tag -a "v$(shell $(VERSION))" -m "ansiblecli v$(shell $(VERSION))"

release: check ## check, then bump + commit + tag + push (fires the release workflow)
	$(PYTHON) scripts/bump_version.py $(PART)
	@V=$$($(VERSION)); \
		echo "Releasing v$$V"; \
		git add ansiblecli/__init__.py; \
		git commit -m "Release v$$V"; \
		git tag -a "v$$V" -m "ansiblecli v$$V"; \
		git push $(REMOTE) $(BRANCH) --follow-tags
