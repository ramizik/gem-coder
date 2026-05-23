PY := uv run
GO_BIN_DIR := src/gemcoder/_bin
TUI_BIN := $(GO_BIN_DIR)/gemcoder-tui

.PHONY: help install test lint tui tui-clean tui-run serve clean

help:
	@echo "Targets:"
	@echo "  install   uv sync --extra dev (Python deps)"
	@echo "  test      run pytest"
	@echo "  lint      run ruff"
	@echo "  tui       build the Bubble Tea binary into $(TUI_BIN)"
	@echo "  tui-run   build and launch the TUI"
	@echo "  serve     run the JSON-RPC server (manual debug)"
	@echo "  clean     remove build artifacts"

install:
	uv sync --extra dev

test:
	$(PY) --extra dev pytest -q

lint:
	$(PY) ruff check .

$(TUI_BIN): tui/go.mod $(shell find tui -name '*.go' 2>/dev/null)
	mkdir -p $(GO_BIN_DIR)
	cd tui && go build -o ../$(TUI_BIN) ./cmd/gemcoder-tui

tui: $(TUI_BIN)

tui-run: tui
	./$(TUI_BIN)

tui-clean:
	rm -rf $(GO_BIN_DIR)

serve:
	$(PY) gemcoder serve

clean: tui-clean
	rm -rf .pytest_cache src/**/__pycache__
