"""Server startup and main entry point for LifeGraph.

Validates critical startup conditions in order:
1. Declared dependencies importable
2. Configuration valid
3. Database readable/valid or created empty (without overwriting invalid file)
4. Ollama reachable
5. Port free

Binds Flask to 127.0.0.1 on the configured/default port. Aborts with a
specific message naming any failed condition and serves no request.

Requirements: 1.1, 1.5, 2.1, 2.4, 2.5, 2.6, 5.7, 5.8, 15.3, 16.2
"""

from __future__ import annotations

import socket
import sys


def _check_dependencies() -> None:
    """Verify all declared dependencies are importable (Req 2.4)."""
    required_modules = [
        "flask",
        "requests",
        "hypothesis",
        "pytest",
    ]
    missing = []
    for mod_name in required_modules:
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(mod_name)

    if missing:
        raise StartupError(
            f"Missing required dependencies: {', '.join(missing)}. "
            f"Install them with: pip install {' '.join(missing)}"
        )


def _check_config():
    """Load and validate configuration (Req 15.3).

    Returns the validated LifeGraphConfig.
    """
    from lifegraph.config import ConfigError, load_config

    try:
        return load_config()
    except ConfigError as exc:
        raise StartupError(
            f"Configuration error: {exc}"
        ) from exc


def _check_database(db_path: str) -> None:
    """Verify the database is readable/valid or can be created (Req 5.7, 5.8).

    If the file exists but is invalid, raises without overwriting.
    If the file does not exist, GraphStore will create it.
    """
    import os
    import sqlite3

    if os.path.exists(db_path):
        # Check if it's a valid SQLite database
        try:
            conn = sqlite3.connect(db_path)
            # Try to read the schema to verify it's a valid SQLite file
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            conn.close()
        except sqlite3.DatabaseError as exc:
            raise StartupError(
                f"Database file '{db_path}' exists but is invalid: {exc}. "
                f"Will not overwrite — please remove or fix the file manually."
            ) from exc
        except OSError as exc:
            raise StartupError(
                f"Cannot read database file '{db_path}': {exc}"
            ) from exc
    else:
        # Verify the directory is writable so we can create the DB
        db_dir = os.path.dirname(db_path) or "."
        if not os.access(db_dir, os.W_OK):
            raise StartupError(
                f"Cannot create database at '{db_path}': "
                f"directory '{db_dir}' is not writable."
            )


def _check_ollama(config) -> None:
    """Verify Ollama is reachable (Req 2.5).

    Makes a lightweight request to the Ollama API to confirm connectivity.
    """
    import requests as req_lib

    base_url = "http://127.0.0.1:11434"
    try:
        resp = req_lib.get(f"{base_url}/api/tags", timeout=5)
        if resp.status_code != 200:
            raise StartupError(
                f"Ollama returned HTTP {resp.status_code}. "
                f"Ensure Ollama is running on localhost:11434."
            )
    except req_lib.exceptions.ConnectionError:
        raise StartupError(
            "Ollama is not reachable at http://127.0.0.1:11434. "
            "Start Ollama with 'ollama serve' before running LifeGraph."
        )
    except req_lib.exceptions.Timeout:
        raise StartupError(
            "Ollama health check timed out. "
            "Ensure Ollama is running and responsive."
        )


def _check_port_free(port: int) -> None:
    """Verify the configured port is available (Req 2.6)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        raise StartupError(
            f"Port {port} is already in use. "
            f"Stop the other process or configure a different port "
            f"via LIFEGRAPH_PORT."
        )
    finally:
        sock.close()


class StartupError(Exception):
    """Raised when a critical startup condition fails."""

    pass


def startup() -> None:
    """Run all startup checks and launch the Flask server.

    Validates conditions in order and aborts with a specific message
    naming the failed condition. Serves no request if any check fails.
    """
    # 1. Check dependencies
    _check_dependencies()

    # 2. Check configuration
    config = _check_config()

    # 3. Check database
    _check_database(config.db_path)

    # 4. Check Ollama reachability
    _check_ollama(config)

    # 5. Check port availability
    _check_port_free(config.port)

    # All checks passed — create and run the app
    from lifegraph.api import create_app

    app = create_app({
        "db_path": config.db_path,
        "lifegraph_config": config,
    })

    print(f"LifeGraph starting on http://127.0.0.1:{config.port}")
    app.run(host="127.0.0.1", port=config.port, debug=False)


def main() -> None:
    """Main entry point with error handling."""
    try:
        startup()
    except StartupError as exc:
        print(f"STARTUP ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
