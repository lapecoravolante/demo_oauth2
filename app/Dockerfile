FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY templates ./templates
COPY pyproject.toml uv.lock README.md main.py oauth.py ./

# Installa le dipendenze
RUN uv sync --frozen --no-dev --no-install-project

CMD ["uv", "run", "--no-dev", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]