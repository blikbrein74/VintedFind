#!/bin/bash
# Double-click to start VintedFind. Keep this window open while you want alerts.
cd "$(dirname "$0")"
( sleep 2; open "http://localhost:8765" ) &
caffeinate -i python3 server.py "$@"
