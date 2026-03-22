#!/bin/bash
cd "$(dirname "$0")"
chmod +x setup_macos.sh >/dev/null 2>&1 || true
./setup_macos.sh
