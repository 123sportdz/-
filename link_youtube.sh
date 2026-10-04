#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -d .venv ] && . .venv/bin/activate
python link_youtube.py
