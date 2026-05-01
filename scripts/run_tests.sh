#!/bin/bash
# scripts/run_tests.sh — Run pytest sequentially for stability and log failures.

LOG_FILE="test_logs.md"
TMP_OUT="test_output.tmp"

echo "# CogniRepo Test Execution - $(date)" > "$LOG_FILE"
echo "" >> "$LOG_FILE"
echo "## Execution Log" >> "$LOG_FILE"
echo '```text' >> "$LOG_FILE"

echo "Running tests sequentially (-n 0) for stability... (Logging to $LOG_FILE)"

# Run pytest:
# -v: verbose (show each test)
# -n 0: disable xdist (sequential) to prevent deadlocks/crashes
# --tb=short: short traceback
# --color=yes: force color output
# --timeout=60: individual test timeout (if pytest-timeout is installed)
pytest -v -n 0 --tb=short --color=yes 2>&1 | tee "$TMP_OUT"

# Append all output to log file inside the code block
cat "$TMP_OUT" >> "$LOG_FILE"
echo '```' >> "$LOG_FILE"

# Summarize failures at the bottom of the md for quick reading
echo "" >> "$LOG_FILE"
echo "## Summary of Failures" >> "$LOG_FILE"
echo '```text' >> "$LOG_FILE"
grep -E "FAILURES|ERRORS" -A 50 "$TMP_OUT" >> "$LOG_FILE"
echo '```' >> "$LOG_FILE"

# Clean up
rm "$TMP_OUT"

echo "Tests completed. Check $LOG_FILE for details."
