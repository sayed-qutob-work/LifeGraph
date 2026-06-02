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
You extract a small, precise personal knowledge graph from one sentence.

Allowed node types:
Skill, Goal, Habit, Project, Event, Person, Organization, Program, Tool,
Technology, Model, Hardware, Topic, Recipe, Issue, Place, Resource

Allowed edge types:
uses, runs_model, current_model, considering_model, compared_with, for,
has_issue, possible_cause, at, referred_by, focuses_on, practices_on,
status, deadline, requires, supports, conflicts_with, motivated_by,
leads_to, part_of, owned_by, blocks, related_to

Return a JSON object with this exact structure:
{{
  "nodes": [
    {{"label": "...", "type": "...", "attributes": {{}}}}
  ],
  "edges": [
    {{"source_label": "...", "source_type": "...", "target_label": "...", "target_type": "...", "type": "..."}}
  ]
}}

Extraction rules:
- Return ONLY valid JSON, no extra text.
- Do not create nodes for the speaker: "I", "me", "myself", "my", or "my project".
- Prefer named, durable entities over generic placeholders like "research" unless it is the main topic.
- Preserve exact model names and versions, for example "Llama 3.1 8B" and "Mistral 7B".
- Use Tool for software tools/platforms like Ollama and Kira IDE.
- Use Technology for frameworks/databases/libraries like Flask, SQLite, Vis.js, React, Firebase, and Sharp.
- Use Model for AI models like Mistral 7B and Llama 3.1 8B.
- Use Organization for universities, companies, and programs' host institutions.
- Use Program for academic programs such as MESW.
- Use Topic for concepts and study areas such as knowledge graphs and AI memory systems.
- Use Recipe for named recipes and Issue for concrete problems or defects.
- Prefer specific edge types. Use related_to only if no specific edge type fits.
- Use attributes for compact facts such as status, dates, deployment, notes, and uncertainty.

Edge guidance:
- A project uses its stack: Project -> Technology/Tool with uses.
- A tool running a model uses Tool -> Model with runs_model.
- A project evaluating models uses current_model, considering_model, and compared_with.
- A recipe made for someone uses Recipe -> Person with for.
- Problems use subject -> Issue with has_issue and Issue -> cause with possible_cause.
- Applications/program facts use at and referred_by.
- Practice goals use focuses_on and practices_on.
- Status words like completed, live, sold, or needs finishing can be attributes or status edges.

Examples:
Sentence: I'm building LifeGraph using Flask, SQLite, Vis.js, and Ollama with Mistral 7B running locally.
{{
  "nodes": [
    {{"label": "LifeGraph", "type": "Project", "attributes": {{}}}},
    {{"label": "Flask", "type": "Technology", "attributes": {{}}}},
    {{"label": "SQLite", "type": "Technology", "attributes": {{}}}},
    {{"label": "Vis.js", "type": "Technology", "attributes": {{}}}},
    {{"label": "Ollama", "type": "Tool", "attributes": {{}}}},
    {{"label": "Mistral 7B", "type": "Model", "attributes": {{"deployment": "local"}}}}
  ],
  "edges": [
    {{"source_label": "LifeGraph", "source_type": "Project", "target_label": "Flask", "target_type": "Technology", "type": "uses"}},
    {{"source_label": "LifeGraph", "source_type": "Project", "target_label": "SQLite", "target_type": "Technology", "type": "uses"}},
    {{"source_label": "LifeGraph", "source_type": "Project", "target_label": "Vis.js", "target_type": "Technology", "type": "uses"}},
    {{"source_label": "LifeGraph", "source_type": "Project", "target_label": "Ollama", "target_type": "Tool", "type": "uses"}},
    {{"source_label": "Ollama", "source_type": "Tool", "target_label": "Mistral 7B", "target_type": "Model", "type": "runs_model"}}
  ]
}}

Sentence: I need to finish the Red Velvet cookie recipe for Pharadolla — the last batch spread too much and I think the butter ratio was off.
{{
  "nodes": [
    {{"label": "Red Velvet cookie recipe", "type": "Recipe", "attributes": {{"status": "needs finishing"}}}},
    {{"label": "Pharadolla", "type": "Person", "attributes": {{}}}},
    {{"label": "last batch spread too much", "type": "Issue", "attributes": {{}}}},
    {{"label": "butter ratio", "type": "Resource", "attributes": {{"uncertain": "true"}}}}
  ],
  "edges": [
    {{"source_label": "Red Velvet cookie recipe", "source_type": "Recipe", "target_label": "Pharadolla", "target_type": "Person", "type": "for"}},
    {{"source_label": "Red Velvet cookie recipe", "source_type": "Recipe", "target_label": "last batch spread too much", "target_type": "Issue", "type": "has_issue"}},
    {{"source_label": "last batch spread too much", "source_type": "Issue", "target_label": "butter ratio", "target_type": "Resource", "type": "possible_cause"}}
  ]
}}

Now extract this sentence:
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
