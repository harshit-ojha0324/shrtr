# Multi-stage build shared by the API and the worker (compose overrides the command).
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
COPY workers ./workers
COPY scripts ./scripts
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 shrtr
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY workers ./workers
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
USER shrtr
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
