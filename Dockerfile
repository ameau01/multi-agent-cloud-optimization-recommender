# Hermetic demo container for the multi-agent cloud-optimization recommender.
#
# What this container does:
#   Boots, replays the app-08 cycle from a vendored fixture (no LLM, no
#   network), renders report.md + trace.json + trace.md into /out, and
#   exits. No API key, no Hugging Face download, no external dependencies
#   at runtime.
#
# Why it exists:
#   So a hiring manager or reviewer can clone the repo, run
#   `docker compose up demo`, and read a real-looking recommendation
#   report in under a minute without configuring anything.
#
# What it does NOT do:
#   Make live LLM calls (use the developer path instead — see
#   docs/running.md). Connect to Hugging Face. Need an API key.

FROM python:3.11-slim

# Install uv (the project's dependency manager). Single binary, no extras.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Workdir matches the layout the project's scripts assume (project root).
WORKDIR /app

# Cache the dependency install layer: copy pyproject + uv.lock first, then
# sync. Source changes don't bust this layer.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project 2>/dev/null \
    || uv sync --no-install-project

# Project source — the layout the scripts/* and tests/* expect.
COPY src/ src/
COPY scripts/ scripts/
COPY tests/integration/agents/fixtures/ tests/integration/agents/fixtures/
COPY tests/run_replay.py tests/
COPY eval-set/ eval-set/
COPY README.md ./

# Make sure every shell script is executable in the image. The host's
# filesystem may or may not preserve the exec bit; this guarantees the
# `./scripts/foo.sh` invocations work inside the container regardless.
RUN chmod +x scripts/*.sh

# Final install of the project itself (now that src/ is present).
RUN uv sync --frozen 2>/dev/null || uv sync

# Demo output goes to /out, which docker-compose mounts as a volume so
# the host can read the rendered files after the container exits.
ENV AUDIT_DB_PATH=/out/.demo_audit.db

# No ENTRYPOINT — the docker-compose service picks the command:
#   service `demo`     → scripts/run_mock_demo.sh   (mock, no API key)
#   service `live-llm` → scripts/run_live_demo.sh   (live, needs .env API key)
CMD ["./scripts/run_mock_demo.sh", "--out-dir", "/out"]
