#!/usr/bin/env bash
# Download the published dataset from Hugging Face and print basic facts.
#
# What this proves:
#   - huggingface_hub can authenticate (anonymous read) and fetch the dataset.
#   - The local cache landed at the expected location (HF_HOME from .env,
#     or <repo>/.hf_cache by default).
#   - All 18 scenarios are present and load through data_loader.
#
# First run: downloads about 12 MB and takes a few seconds. Subsequent
# runs hit the cache and return in well under a second. To force a fresh
# download, delete the cache: `rm -rf .hf_cache`.
#
# Usage:
#   scripts/run_hf_smoke_test.sh
#
# Exits 0 on success, non-zero if the download or parse fails.

set -e
cd "$(dirname "$0")/.."

uv run python -m src.data_loader
