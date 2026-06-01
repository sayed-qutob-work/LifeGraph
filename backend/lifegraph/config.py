"""Configuration module for LifeGraph.

Reads configuration from environment variables prefixed with LIFEGRAPH_.
Applies documented defaults for omitted settings and raises a startup error
naming any invalid value.

Environment Variables:
    LIFEGRAPH_MODEL       - Ollama model name (default: "llama3")
    LIFEGRAPH_PORT        - Web server localhost port (default: 5000)
    LIFEGRAPH_DB_PATH     - SQLite database file path (default: "lifegraph.db")
    LIFEGRAPH_HOP_DISTANCE - Default context export hop distance (default: 2)
    LIFEGRAPH_TIMEOUT     - Ollama request timeout in seconds (default: 60)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised at startup when a configuration value is invalid."""

    def __init__(self, setting: str, value: str, reason: str) -> None:
        self.setting = setting
        self.value = value
        self.reason = reason
        super().__init__(
            f"Invalid configuration value for {setting}: "
            f"{value!r} ({reason})"
        )


# Documented defaults
DEFAULT_MODEL = "llama3"
DEFAULT_PORT = 5000
DEFAULT_DB_PATH = "lifegraph.db"
DEFAULT_HOP_DISTANCE = 2
DEFAULT_TIMEOUT = 60


@dataclass(frozen=True)
class LifeGraphConfig:
    """Immutable application configuration."""

    model: str
    port: int
    db_path: str
    hop_distance: int
    timeout: int


def load_config() -> LifeGraphConfig:
    """Load and validate configuration from environment variables.

    Returns a validated LifeGraphConfig with defaults applied for any
    omitted settings.

    Raises:
        ConfigError: If any provided configuration value is invalid,
            naming the specific setting that failed validation.
    """
    model = os.environ.get("LIFEGRAPH_MODEL", DEFAULT_MODEL)
    if not model.strip():
        raise ConfigError("LIFEGRAPH_MODEL", model, "model name must not be empty")

    port = _parse_port(os.environ.get("LIFEGRAPH_PORT"))
    db_path = _parse_db_path(os.environ.get("LIFEGRAPH_DB_PATH"))
    hop_distance = _parse_hop_distance(os.environ.get("LIFEGRAPH_HOP_DISTANCE"))
    timeout = _parse_timeout(os.environ.get("LIFEGRAPH_TIMEOUT"))

    return LifeGraphConfig(
        model=model,
        port=port,
        db_path=db_path,
        hop_distance=hop_distance,
        timeout=timeout,
    )


def _parse_port(raw: str | None) -> int:
    """Parse and validate the port number."""
    if raw is None:
        return DEFAULT_PORT

    try:
        port = int(raw)
    except ValueError:
        raise ConfigError("LIFEGRAPH_PORT", raw, "must be an integer")

    if port < 1 or port > 65535:
        raise ConfigError(
            "LIFEGRAPH_PORT", raw, "must be between 1 and 65535"
        )

    return port


def _parse_db_path(raw: str | None) -> str:
    """Parse and validate the database file path."""
    if raw is None:
        return DEFAULT_DB_PATH

    if not raw.strip():
        raise ConfigError(
            "LIFEGRAPH_DB_PATH", raw, "database path must not be empty"
        )

    return raw


def _parse_hop_distance(raw: str | None) -> int:
    """Parse and validate the default context export hop distance."""
    if raw is None:
        return DEFAULT_HOP_DISTANCE

    try:
        hop_distance = int(raw)
    except ValueError:
        raise ConfigError("LIFEGRAPH_HOP_DISTANCE", raw, "must be an integer")

    if hop_distance < 1:
        raise ConfigError(
            "LIFEGRAPH_HOP_DISTANCE", raw, "must be a positive integer"
        )

    return hop_distance


def _parse_timeout(raw: str | None) -> int:
    """Parse and validate the Ollama request timeout in seconds."""
    if raw is None:
        return DEFAULT_TIMEOUT

    try:
        timeout = int(raw)
    except ValueError:
        raise ConfigError("LIFEGRAPH_TIMEOUT", raw, "must be an integer")

    if timeout < 1:
        raise ConfigError(
            "LIFEGRAPH_TIMEOUT", raw, "must be a positive integer (seconds)"
        )

    return timeout
