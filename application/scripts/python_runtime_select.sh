#!/bin/bash
# Shared CoDIR IA selector for standard CPython runtimes on macOS/Linux shells.
# The caller must define or pass the path to python_runtime_probe.py.

codir_select_python() {
    local probe="$1"
    local log_file="${2:-/dev/null}"
    local candidate output rc status version executable message

    CODIR_PYTHON_BIN=""
    CODIR_PYTHON_VERSION=""
    CODIR_PYTHON_STATUS=""
    CODIR_PYTHON_REJECTIONS=""

    for candidate in python3.12 python3.11 python3.13 python3.14 python3; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        output=$("$candidate" "$probe" 2>&1)
        rc=$?
        printf '%s\n' "[python] candidate=$candidate rc=$rc" "$output" >> "$log_file" 2>/dev/null || true
        status=$(printf '%s\n' "$output" | sed -n 's/^CODIR_PY_STATUS=//p' | head -n 1)
        version=$(printf '%s\n' "$output" | sed -n 's/^CODIR_PY_VERSION=//p' | head -n 1)
        executable=$(printf '%s\n' "$output" | sed -n 's/^CODIR_PY_EXECUTABLE=//p' | head -n 1)
        message=$(printf '%s\n' "$output" | sed -n 's/^CODIR_PY_MESSAGE=//p' | head -n 1)
        if [ "$rc" -eq 0 ] && [ -n "$executable" ]; then
            CODIR_PYTHON_BIN="$executable"
            CODIR_PYTHON_VERSION="$version"
            CODIR_PYTHON_STATUS="OK"
            export CODIR_PYTHON_BIN CODIR_PYTHON_VERSION CODIR_PYTHON_STATUS
            return 0
        fi
        [ -n "$status" ] && CODIR_PYTHON_REJECTIONS="${CODIR_PYTHON_REJECTIONS}${candidate}: ${status} (${version:-unknown}) ${message}; "
    done
    export CODIR_PYTHON_BIN CODIR_PYTHON_VERSION CODIR_PYTHON_STATUS CODIR_PYTHON_REJECTIONS
    return 1
}
