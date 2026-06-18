"""
Root conftest: set required env vars before any backend modules are imported.
"""
import os

# Provide a dummy Fernet key so core.security can be imported in tests
# without a real .env file present.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "-BlMCPFNkImegf-B_n6LjhVhabHugO8Vdidliq03Uck=",
)
