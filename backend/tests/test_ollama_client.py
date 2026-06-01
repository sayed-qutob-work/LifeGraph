"""Unit tests for the OllamaClient loopback guard and error handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lifegraph.ollama_client import (
    ExternalConnectionError,
    OllamaClient,
    OllamaTimeoutError,
    OllamaUnavailableError,
    _is_loopback,
    verify_loopback,
)


# ---------------------------------------------------------------------------
# Loopback guard: _is_loopback
# ---------------------------------------------------------------------------


class TestIsLoopback:
    """Tests for the _is_loopback helper."""

    def test_ipv4_loopback_127_0_0_1(self):
        assert _is_loopback("127.0.0.1") is True

    def test_ipv4_loopback_127_255_255_255(self):
        assert _is_loopback("127.255.255.255") is True

    def test_ipv4_loopback_127_0_0_42(self):
        assert _is_loopback("127.0.0.42") is True

    def test_ipv6_loopback(self):
        assert _is_loopback("::1") is True

    def test_ipv4_non_loopback_private(self):
        assert _is_loopback("192.168.1.1") is False

    def test_ipv4_non_loopback_public(self):
        assert _is_loopback("8.8.8.8") is False

    def test_ipv6_non_loopback(self):
        assert _is_loopback("2001:db8::1") is False

    def test_invalid_address(self):
        assert _is_loopback("not-an-ip") is False

    def test_empty_string(self):
        assert _is_loopback("") is False


# ---------------------------------------------------------------------------
# Loopback guard: verify_loopback
# ---------------------------------------------------------------------------


class TestVerifyLoopback:
    """Tests for the verify_loopback function."""

    @patch("lifegraph.ollama_client.socket.getaddrinfo")
    def test_loopback_passes(self, mock_getaddrinfo):
        """Loopback address should pass without raising."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 0))
        ]
        # Should not raise
        verify_loopback("localhost")

    @patch("lifegraph.ollama_client.socket.getaddrinfo")
    def test_non_loopback_raises_external_connection_error(self, mock_getaddrinfo):
        """Non-loopback address should raise ExternalConnectionError."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0))
        ]
        with pytest.raises(ExternalConnectionError) as exc_info:
            verify_loopback("example.com")

        assert "external connection prevented" in str(exc_info.value)
        assert exc_info.value.host == "example.com"
        assert exc_info.value.resolved == "93.184.216.34"

    @patch("lifegraph.ollama_client.socket.getaddrinfo")
    def test_unresolvable_host_raises_unavailable(self, mock_getaddrinfo):
        """Unresolvable host should raise OllamaUnavailableError."""
        import socket
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")

        with pytest.raises(OllamaUnavailableError) as exc_info:
            verify_loopback("nonexistent.invalid")

        assert "Cannot resolve host" in str(exc_info.value)


# ---------------------------------------------------------------------------
# OllamaClient: parse_sentence
# ---------------------------------------------------------------------------


class TestOllamaClientParseSentence:
    """Tests for OllamaClient.parse_sentence."""

    def _make_client(self, base_url="http://127.0.0.1:11434", model="llama3", timeout=60):
        return OllamaClient(base_url=base_url, model=model, timeout_seconds=timeout)

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_successful_parse(self, mock_post, mock_verify):
        """Successful parse returns the model's JSON output as a dict."""
        expected = {
            "nodes": [{"label": "Python", "type": "Skill", "attributes": {}}],
            "edges": [],
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": json.dumps(expected)}
        mock_post.return_value = mock_response

        client = self._make_client()
        result = client.parse_sentence("I am learning Python")

        assert result == expected
        mock_verify.assert_called_once_with("127.0.0.1")

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_timeout_raises_ollama_timeout_error(self, mock_post, mock_verify):
        """Request timeout raises OllamaTimeoutError."""
        import requests as req_lib
        mock_post.side_effect = req_lib.exceptions.Timeout("timed out")

        client = self._make_client(timeout=10)

        with pytest.raises(OllamaTimeoutError) as exc_info:
            client.parse_sentence("test sentence")

        assert "timed out" in str(exc_info.value).lower()

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_connection_error_raises_unavailable(self, mock_post, mock_verify):
        """Connection error raises OllamaUnavailableError."""
        import requests as req_lib
        mock_post.side_effect = req_lib.exceptions.ConnectionError("refused")

        client = self._make_client()

        with pytest.raises(OllamaUnavailableError) as exc_info:
            client.parse_sentence("test sentence")

        assert "unavailable" in str(exc_info.value).lower()

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_404_raises_model_not_installed(self, mock_post, mock_verify):
        """HTTP 404 indicates model not installed."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "model not found"
        mock_post.return_value = mock_response

        client = self._make_client(model="nonexistent-model")

        with pytest.raises(OllamaUnavailableError) as exc_info:
            client.parse_sentence("test sentence")

        assert "not installed" in str(exc_info.value).lower()
        assert "nonexistent-model" in str(exc_info.value)

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_500_raises_unavailable(self, mock_post, mock_verify):
        """HTTP 500 raises OllamaUnavailableError."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "internal server error"
        mock_post.return_value = mock_response

        client = self._make_client()

        with pytest.raises(OllamaUnavailableError):
            client.parse_sentence("test sentence")

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_invalid_json_response_raises_unavailable(self, mock_post, mock_verify):
        """Invalid JSON in Ollama response raises OllamaUnavailableError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("bad json")
        mock_post.return_value = mock_response

        client = self._make_client()

        with pytest.raises(OllamaUnavailableError) as exc_info:
            client.parse_sentence("test sentence")

        assert "invalid json" in str(exc_info.value).lower()

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_model_returns_non_json_text(self, mock_post, mock_verify):
        """Model returning non-JSON text in 'response' field raises error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "This is not JSON at all"}
        mock_post.return_value = mock_response

        client = self._make_client()

        with pytest.raises(OllamaUnavailableError):
            client.parse_sentence("test sentence")

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_model_returns_non_dict(self, mock_post, mock_verify):
        """Model returning a JSON array instead of object raises error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": json.dumps([1, 2, 3])}
        mock_post.return_value = mock_response

        client = self._make_client()

        with pytest.raises(OllamaUnavailableError) as exc_info:
            client.parse_sentence("test sentence")

        assert "not a json object" in str(exc_info.value).lower()

    def test_non_loopback_base_url_raises_external_connection_error(self):
        """Client with non-loopback base_url raises ExternalConnectionError."""
        with patch("lifegraph.ollama_client.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0))
            ]
            client = self._make_client(base_url="http://example.com:11434")

            with pytest.raises(ExternalConnectionError) as exc_info:
                client.parse_sentence("test sentence")

            assert "external connection prevented" in str(exc_info.value)

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_correct_api_endpoint_and_payload(self, mock_post, mock_verify):
        """Verify the correct Ollama API endpoint and payload structure."""
        expected_response = {"nodes": [], "edges": []}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": json.dumps(expected_response)}
        mock_post.return_value = mock_response

        client = self._make_client(model="mistral", timeout=30)
        client.parse_sentence("I enjoy running")

        # Verify the call
        mock_post.assert_called_once()
        call_args = mock_post.call_args

        # Check URL
        assert call_args[0][0] == "http://127.0.0.1:11434/api/generate" or \
               call_args.kwargs.get("url") == "http://127.0.0.1:11434/api/generate" or \
               (len(call_args[0]) > 0 and call_args[0][0] == "http://127.0.0.1:11434/api/generate")

        # Check payload structure
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["model"] == "mistral"
        assert payload["stream"] is False
        assert payload["format"] == "json"
        assert "I enjoy running" in payload["prompt"]

        # Check timeout
        assert call_args.kwargs.get("timeout") == 30 or call_args[1].get("timeout") == 30

    @patch("lifegraph.ollama_client.verify_loopback")
    @patch("lifegraph.ollama_client.requests.post")
    def test_loopback_verified_before_each_request(self, mock_post, mock_verify):
        """Loopback guard is checked before every request."""
        expected_response = {"nodes": [], "edges": []}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": json.dumps(expected_response)}
        mock_post.return_value = mock_response

        client = self._make_client()
        client.parse_sentence("first call")
        client.parse_sentence("second call")

        assert mock_verify.call_count == 2
