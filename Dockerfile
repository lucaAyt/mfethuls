FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1

ARG MFETHULS_EXTRAS=service

# Shared libraries required by kaleido's bundled Chromium (SVG/image export).
# Only installed when the viz extra is present (streamlit service), harmless otherwise.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY scripts /app/scripts

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e ".[${MFETHULS_EXTRAS}]" \
    && chmod +x /app/scripts/docker_entrypoint.sh

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["api"]
