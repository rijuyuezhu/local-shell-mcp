"""Process-instance identity shared by durable runtime subsystems."""

import secrets

PROCESS_INSTANCE_ID = secrets.token_hex(16)
"""Opaque id that changes whenever the server process starts."""
