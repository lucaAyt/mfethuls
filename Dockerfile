FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1

ARG MFETHULS_EXTRAS=service

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY scripts /app/scripts

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e ".[${MFETHULS_EXTRAS}]" \
    && chmod +x /app/scripts/docker_entrypoint.sh

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["api"]
