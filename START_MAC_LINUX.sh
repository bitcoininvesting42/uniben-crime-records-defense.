#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo 'UNIBEN Crime Records and Information System'
echo 'Open http://127.0.0.1:8080 in your browser. Press Ctrl+C to exit.'
python3 server.py
