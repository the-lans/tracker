FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml ./
COPY . .

RUN pip install --no-cache-dir ".[dev]"

EXPOSE 8000

# TODO: разделить на dev/prod-стадии (без --reload и dev-зависимостей в проде),
# когда появится реальный код api/, services/, db/, clients/, tasks/, ws/, logging/.
# Команды worker/beat переопределяют CMD через docker-compose.yml (тот же образ).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
