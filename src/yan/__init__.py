"""Yeas & Nays: data pipeline for U.S. House and Senate roll call votes."""

import time

# When this process started (time.monotonic()), give or take imports: run-time budgets
# count from here, since the job's timeout covers the whole run.
STARTED = time.monotonic()
