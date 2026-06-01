"""Property-based test for configuration defaulting (Property 31).

**Validates: Requirements 15.2**

For any subset of configuration settings that are omitted, load_config() SHALL
apply the documented default for each omitted setting while preserving any
explicitly provided valid values.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.config import (
    DEFAULT_DB_PATH,
    DEFAULT_HOP_DISTANCE,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    load_config,
)


# --- Strategies for valid configuration values ---

# Model: non-empty, non-whitespace-only strings
valid_model_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Port: integers in the valid range 1-65535
valid_port_st = st.integers(min_value=1, max_value=65535)

# DB path: non-empty, non-whitespace-only strings
valid_db_path_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() != "")

# Hop distance: positive integers
valid_hop_distance_st = st.integers(min_value=1, max_value=1000)

# Timeout: positive integers (seconds)
valid_timeout_st = st.integers(min_value=1, max_value=3600)


# Strategy that generates an optional value (either a valid value or None meaning "omitted")
optional_model_st = st.one_of(st.none(), valid_model_st)
optional_port_st = st.one_of(st.none(), valid_port_st)
optional_db_path_st = st.one_of(st.none(), valid_db_path_st)
optional_hop_distance_st = st.one_of(st.none(), valid_hop_distance_st)
optional_timeout_st = st.one_of(st.none(), valid_timeout_st)


@settings(max_examples=20)
@given(
    model=optional_model_st,
    port=optional_port_st,
    db_path=optional_db_path_st,
    hop_distance=optional_hop_distance_st,
    timeout=optional_timeout_st,
)
def test_configuration_defaulting(model, port, db_path, hop_distance, timeout):
    """Property 31: Configuration defaulting.

    **Validates: Requirements 15.2**

    For any subset of configuration settings that are omitted, load_config()
    SHALL apply the documented default for each omitted setting while preserving
    any explicitly provided valid values.
    """
    # Build a clean environment with only the provided settings
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIFEGRAPH_")}

    if model is not None:
        env["LIFEGRAPH_MODEL"] = model
    if port is not None:
        env["LIFEGRAPH_PORT"] = str(port)
    if db_path is not None:
        env["LIFEGRAPH_DB_PATH"] = db_path
    if hop_distance is not None:
        env["LIFEGRAPH_HOP_DISTANCE"] = str(hop_distance)
    if timeout is not None:
        env["LIFEGRAPH_TIMEOUT"] = str(timeout)

    with patch.dict(os.environ, env, clear=True):
        config = load_config()

    # For each setting: if provided, the config must use the provided value;
    # if omitted (None), the config must use the documented default.
    if model is not None:
        assert config.model == model, (
            f"Provided model={model!r} but got config.model={config.model!r}"
        )
    else:
        assert config.model == DEFAULT_MODEL, (
            f"Omitted model, expected default {DEFAULT_MODEL!r} "
            f"but got {config.model!r}"
        )

    if port is not None:
        assert config.port == port, (
            f"Provided port={port} but got config.port={config.port}"
        )
    else:
        assert config.port == DEFAULT_PORT, (
            f"Omitted port, expected default {DEFAULT_PORT} "
            f"but got {config.port}"
        )

    if db_path is not None:
        assert config.db_path == db_path, (
            f"Provided db_path={db_path!r} but got config.db_path={config.db_path!r}"
        )
    else:
        assert config.db_path == DEFAULT_DB_PATH, (
            f"Omitted db_path, expected default {DEFAULT_DB_PATH!r} "
            f"but got {config.db_path!r}"
        )

    if hop_distance is not None:
        assert config.hop_distance == hop_distance, (
            f"Provided hop_distance={hop_distance} "
            f"but got config.hop_distance={config.hop_distance}"
        )
    else:
        assert config.hop_distance == DEFAULT_HOP_DISTANCE, (
            f"Omitted hop_distance, expected default {DEFAULT_HOP_DISTANCE} "
            f"but got {config.hop_distance}"
        )

    if timeout is not None:
        assert config.timeout == timeout, (
            f"Provided timeout={timeout} but got config.timeout={config.timeout}"
        )
    else:
        assert config.timeout == DEFAULT_TIMEOUT, (
            f"Omitted timeout, expected default {DEFAULT_TIMEOUT} "
            f"but got {config.timeout}"
        )
