"""Tests for the configuration module."""

import os

import pytest

from lifegraph.config import (
    ConfigError,
    DEFAULT_DB_PATH,
    DEFAULT_HOP_DISTANCE,
    DEFAULT_MODEL,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    LifeGraphConfig,
    load_config,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove all LIFEGRAPH_ env vars before each test."""
    for key in list(os.environ.keys()):
        if key.startswith("LIFEGRAPH_"):
            monkeypatch.delenv(key, raising=False)


class TestDefaults:
    """When no environment variables are set, documented defaults apply."""

    def test_all_defaults(self):
        config = load_config()
        assert config.model == DEFAULT_MODEL
        assert config.port == DEFAULT_PORT
        assert config.db_path == DEFAULT_DB_PATH
        assert config.hop_distance == DEFAULT_HOP_DISTANCE
        assert config.timeout == DEFAULT_TIMEOUT

    def test_default_values_are_documented(self):
        """Verify the documented default values match expectations."""
        assert DEFAULT_MODEL == "llama3"
        assert DEFAULT_PORT == 5000
        assert DEFAULT_DB_PATH == "lifegraph.db"
        assert DEFAULT_HOP_DISTANCE == 2
        assert DEFAULT_TIMEOUT == 60


class TestValidValues:
    """Valid environment variable values are accepted."""

    def test_custom_model(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_MODEL", "mistral")
        config = load_config()
        assert config.model == "mistral"

    def test_custom_port(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "8080")
        config = load_config()
        assert config.port == 8080

    def test_custom_db_path(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_DB_PATH", "/tmp/my_graph.db")
        config = load_config()
        assert config.db_path == "/tmp/my_graph.db"

    def test_custom_hop_distance(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_HOP_DISTANCE", "3")
        config = load_config()
        assert config.hop_distance == 3

    def test_custom_timeout(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_TIMEOUT", "120")
        config = load_config()
        assert config.timeout == 120

    def test_port_boundary_low(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "1")
        config = load_config()
        assert config.port == 1

    def test_port_boundary_high(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "65535")
        config = load_config()
        assert config.port == 65535

    def test_hop_distance_one(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_HOP_DISTANCE", "1")
        config = load_config()
        assert config.hop_distance == 1

    def test_timeout_one(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_TIMEOUT", "1")
        config = load_config()
        assert config.timeout == 1


class TestInvalidValues:
    """Invalid values raise ConfigError naming the setting."""

    def test_non_numeric_port(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "abc")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_PORT"
        assert "abc" in str(exc_info.value)

    def test_port_zero(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "0")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_PORT"

    def test_port_negative(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "-1")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_PORT"

    def test_port_too_high(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "65536")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_PORT"

    def test_port_float(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "3.14")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_PORT"

    def test_empty_model(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_MODEL", "   ")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_MODEL"

    def test_empty_db_path(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_DB_PATH", "   ")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_DB_PATH"

    def test_non_numeric_hop_distance(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_HOP_DISTANCE", "two")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_HOP_DISTANCE"

    def test_zero_hop_distance(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_HOP_DISTANCE", "0")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_HOP_DISTANCE"

    def test_negative_hop_distance(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_HOP_DISTANCE", "-1")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_HOP_DISTANCE"

    def test_non_numeric_timeout(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_TIMEOUT", "fast")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_TIMEOUT"

    def test_zero_timeout(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_TIMEOUT", "0")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_TIMEOUT"

    def test_negative_timeout(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_TIMEOUT", "-30")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        assert exc_info.value.setting == "LIFEGRAPH_TIMEOUT"


class TestConfigError:
    """ConfigError includes the setting name and value in its message."""

    def test_error_message_includes_setting(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_PORT", "not_a_number")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        error = exc_info.value
        assert "LIFEGRAPH_PORT" in str(error)
        assert "not_a_number" in str(error)

    def test_error_attributes(self, monkeypatch):
        monkeypatch.setenv("LIFEGRAPH_TIMEOUT", "xyz")
        with pytest.raises(ConfigError) as exc_info:
            load_config()
        error = exc_info.value
        assert error.setting == "LIFEGRAPH_TIMEOUT"
        assert error.value == "xyz"
        assert "integer" in error.reason


class TestImmutability:
    """LifeGraphConfig is immutable (frozen dataclass)."""

    def test_cannot_modify_config(self):
        config = load_config()
        with pytest.raises(Exception):
            config.port = 9999  # type: ignore[misc]
