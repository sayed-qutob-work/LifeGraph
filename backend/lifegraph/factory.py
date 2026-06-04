"""Shared factory for creating LifeGraph components from configuration.

Used by both the Flask web server (api.py) and the MCP server (mcp_server.py)
so that both surfaces share the same configuration reading and object wiring.
"""

from __future__ import annotations

from lifegraph.config import DEFAULT_DB_PATH, load_config
from lifegraph.ollama_client import OllamaClient
from lifegraph.parser import InputParser
from lifegraph.store import GraphStore


def make_store(db_path: str = DEFAULT_DB_PATH) -> GraphStore:
    """Create a GraphStore pointing at the given database file."""
    return GraphStore(db_path)


def make_parser(config=None) -> InputParser | None:
    """Create an InputParser from config (reads env vars when config is None).

    Returns None if config cannot be loaded, so callers can degrade gracefully
    when Ollama is not configured.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            return None
    if config is None:
        return None
    ollama = OllamaClient(
        base_url="http://127.0.0.1:11434",
        model=config.model,
        timeout_seconds=config.timeout,
    )
    return InputParser(ollama)
