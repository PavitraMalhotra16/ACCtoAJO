"""
Root conftest: set required env vars and sys.path before any backend modules are imported.
"""
import os
import sys

# Ensure 'backend/' is on sys.path so tests can import db, pipeline, etc. without package prefix
sys.path.insert(0, os.path.dirname(__file__))

# Provide a dummy Fernet key so core.security can be imported in tests
# without a real .env file present.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "-BlMCPFNkImegf-B_n6LjhVhabHugO8Vdidliq03Uck=",
)
