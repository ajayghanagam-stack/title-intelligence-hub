#!/usr/bin/env bash
cd "$(dirname "$0")/.." && python scripts/run_evals.py --update-golden
