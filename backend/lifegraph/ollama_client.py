"""Ollama_Client — the sole LLM gateway for LifeGraph (Req 16).

Communicates with a locally running Ollama service to obtain language-model
responses. Enforces loopback-only connectivity (Req 1.2, 1.4) and raises
distinct errors for service-down, model-missing, and timeout conditions
(Req 14.1, 14.2, 14.4).

Interface:
    OllamaClient(base_url: str, model: str, timeout_seconds: int = 60)
    parse_sentence(sentence: str) -> dict  (raw proposal as dict)
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Dict
from urllib.parse import urlparse

import requests


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class ExternalConnectionError(Exception):
    """Raised when the resolved target is not a loopback address (Req 1.4)."""

    def __init__(self, host: str, resolved: str) -> None:
        self.host = host
        self.resolved = resolved
        super().__init__(
            f"external connection prevented: "
            f"host {host!r} resolved to non-loopback address {resolved!r}"
        )


class OllamaUnavailableError(Exception):
    """Raised when the Ollama service is unreachable or the model is missing (Req 14.1, 14.2)."""

    pass


class OllamaTimeoutError(Exception):
    """Raised when a request to Ollama exceeds the configured timeout (Req 14.4)."""

    pass


# ---------------------------------------------------------------------------
# Loopback guard
# ---------------------------------------------------------------------------


def _is_loopback(address: str) -> bool:
    """Check whether an IP address string is a loopback address.

    Loopback addresses:
      - IPv4: 127.0.0.0/8
      - IPv6: ::1
    """
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def verify_loopback(host: str) -> None:
    """Resolve *host* and verify it points to a loopback address.

    Raises ExternalConnectionError if the resolved address is not loopback.
    """
    try:
        # Resolve hostname to IP address(es)
        results = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        # Cannot resolve — treat as unavailable rather than external
        raise OllamaUnavailableError(
            f"Cannot resolve host {host!r}: {exc}"
        ) from exc

    if not results:
        raise OllamaUnavailableError(f"No addresses found for host {host!r}")

    # Check the first resolved address
    resolved_ip = results[0][4][0]

    if not _is_loopback(resolved_ip):
        raise ExternalConnectionError(host, resolved_ip)


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_PARSE_PROMPT_TEMPLATE = """\
You are a structured data extraction assistant for a personal knowledge graph.

Given the following sentence about someone's life, extract nodes and edges.

Allowed node types: Skill, Goal, Habit, Project, Event, Person, Resource
Allowed edge types: requires, supports, conflicts_with, motivated_by, leads_to, part_of, owned_by, blocks, related_to

Return a JSON object with this exact structure:
{{
  "nodes": [
    {{"label": "...", "type": "...", "attributes": {{}}}}
  ],
  "edges": [
    {{"source_label": "...", "source_type": "...", "target_label": "...", "target_type": "...", "type": "..."}}
  ]
}}

Rules:
- Each node must have a "label" (string) and "type" (one of the allowed node types).
- Each node may have an optional "attributes" object with string key-value pairs.
- Each edge must reference source and target by their label and type.
- Each edge must have a "type" from the allowed edge types.
- Return ONLY valid JSON, no extra text.

Sentence: {sentence}
"""


# ---------------------------------------------------------------------------
# OllamaClient
# ---------------------------------------------------------------------------


class OllamaClient:
    """Sole gateway to the language model (Req 16.2, 16.3).

    Verifies the base_url resolves to a loopback address before connecting
    (Req 1.2, 1.4). Raises distinct errors for service-down/model-missing
    (OllamaUnavailableError) and timeout (OllamaTimeoutError).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

        # Extract host from base_url for loopback verification
        parsed = urlparse(self.base_url)
        self._host = parsed.hostname or ""

    def parse_sentence(self, sentence: str) -> Dict[str, Any]:
        """Parse a natural-language sentence into raw structured graph data.

        This is the single defined interface for submitting a sentence and
        receiving structured graph data (Req 16.3).

        Args:
            sentence: The natural-language sentence to parse.

        Returns:
            A dict with "nodes" and "edges" keys (raw proposal), to be
            validated by the Input_Parser.

        Raises:
            ExternalConnectionError: If the resolved target is not loopback.
            OllamaUnavailableError: If the service is unreachable or the
                configured model is not installed.
            OllamaTimeoutError: If the request exceeds the configured timeout.
        """
        # Loopback guard: verify before every request (Req 1.2, 1.4)
        verify_loopback(self._host)

        # Build the prompt
        prompt = _PARSE_PROMPT_TEMPLATE.format(sentence=sentence)

        # Build the request payload for Ollama's generate API
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            raise OllamaTimeoutError(
                f"Request to Ollama timed out after {self.timeout_seconds} seconds"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailableError(
                f"Ollama service is unavailable at {self.base_url}: {exc}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaUnavailableError(
                f"Failed to connect to Ollama: {exc}"
            ) from exc

        # Handle HTTP error responses
        if response.status_code == 404:
            # Ollama returns 404 when the model is not found
            raise OllamaUnavailableError(
                f"Model {self.model!r} is not installed in Ollama. "
                f"Run 'ollama pull {self.model}' to install it."
            )

        if response.status_code != 200:
            raise OllamaUnavailableError(
                f"Ollama returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        # Parse the response JSON
        try:
            result = response.json()
        except ValueError as exc:
            raise OllamaUnavailableError(
                f"Ollama returned invalid JSON: {exc}"
            ) from exc

        # Ollama's generate API returns {"response": "...", ...}
        # The "response" field contains the model's text output
        raw_text = result.get("response", "")

        # Parse the model's JSON output
        import json

        try:
            parsed = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise OllamaUnavailableError(
                f"Model returned invalid JSON in response: {exc}"
            ) from exc

        # Ensure we have the expected structure (at minimum)
        if not isinstance(parsed, dict):
            raise OllamaUnavailableError(
                "Model response is not a JSON object"
            )

        # Return the raw proposal dict for the Input_Parser to validate
        return parsed
