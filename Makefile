# Единая команда проверки проекта: линт, тайпчек и тесты для backend и
# frontend (см. CLAUDE.md, раздел 4). `make check` возвращает ненулевой код
# выхода при любой ошибке любого из шагов.

PYTHON ?= python3.12
BACKEND_DIR := backend
FRONTEND_DIR := frontend
BACKEND_VENV := $(BACKEND_DIR)/.venv
BACKEND_VENV_MARKER := $(BACKEND_VENV)/.installed
FRONTEND_MODULES_MARKER := $(FRONTEND_DIR)/node_modules/.installed

.PHONY: check check-backend check-frontend \
	backend-lint backend-typecheck backend-test \
	frontend-lint frontend-typecheck \
	clean

check: check-backend check-frontend
	@echo "OK: все проверки backend и frontend прошли."

check-backend: backend-lint backend-typecheck backend-test

check-frontend: frontend-lint frontend-typecheck

# --- backend ---

$(BACKEND_VENV_MARKER): $(BACKEND_DIR)/pyproject.toml
	$(PYTHON) -m venv $(BACKEND_VENV)
	$(BACKEND_VENV)/bin/pip install --upgrade pip -q
	$(BACKEND_VENV)/bin/pip install -e "$(BACKEND_DIR)[dev]" -q
	touch $(BACKEND_VENV_MARKER)

# ../alembic/env.py — обычный код, проверяется вместе с backend/. Остальное
# в alembic/ (versions/*.py) — сгенерированные Alembic миграции, их не линтим:
# шаблон script.py.mako сам импортирует op/sa и Union, даже когда конкретная
# миграция их не использует (как эта, пустая) — ruff закономерно ругался бы
# на unused-import в каждой второй миграции.
backend-lint: $(BACKEND_VENV_MARKER)
	cd $(BACKEND_DIR) && .venv/bin/ruff check . ../alembic/env.py

backend-typecheck: $(BACKEND_VENV_MARKER)
	cd $(BACKEND_DIR) && .venv/bin/mypy . ../alembic/env.py

# pytest возвращает код 5, если не собрано ни одного теста — это ожидаемо,
# пока backend/tests/ пуст (раздел с тестами появится вместе с прикладным
# кодом), и не должно считаться ошибкой `make check`.
backend-test: $(BACKEND_VENV_MARKER)
	@cd $(BACKEND_DIR) && .venv/bin/pytest; code=$$?; \
	if [ $$code -eq 5 ]; then \
		echo "pytest: тестов пока нет (exit 5) — не считается ошибкой"; \
		exit 0; \
	else \
		exit $$code; \
	fi

# --- frontend ---

$(FRONTEND_MODULES_MARKER): $(FRONTEND_DIR)/package.json
	cd $(FRONTEND_DIR) && npm install
	touch $(FRONTEND_MODULES_MARKER)

frontend-lint: $(FRONTEND_MODULES_MARKER)
	cd $(FRONTEND_DIR) && npm run lint

frontend-typecheck: $(FRONTEND_MODULES_MARKER)
	cd $(FRONTEND_DIR) && npm run typecheck

# --- прочее ---

clean:
	rm -rf $(BACKEND_VENV) $(FRONTEND_DIR)/node_modules
