"""Explicit app factory for deterministic tests: never discover real user skills."""
from silicolab.server import create_app as application


def create_app(*args, **kwargs):
    kwargs.setdefault('skill_roots', [])
    kwargs.setdefault('mcp_roots', [])
    return application(*args, **kwargs)
