FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1

ARG MFETHULS_EXTRAS=service

# Google Chrome for kaleido SVG/image export (kaleido 1.x uses Chrome, not bundled Chromium).
RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY scripts /app/scripts

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -e ".[${MFETHULS_EXTRAS}]" \
    && chmod +x /app/scripts/docker_entrypoint.sh

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["api"]
