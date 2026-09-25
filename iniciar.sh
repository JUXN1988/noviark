#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt && .venv/bin/python noviq_app.py
