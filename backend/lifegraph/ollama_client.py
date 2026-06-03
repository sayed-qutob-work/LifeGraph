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

Node type guide (pick the most specific type that fits the meaning):
- Person: a named individual.
- Organization: a company, university, or institution.
- Program: an academic or professional program — a degree, internship, or course of study. Never a piece of software, a website, or a game.
- Project: something the speaker is building or has built.
- Event: a dated or scheduled happening.
- Skill: an ability or technique a person practices or learns.
- Goal: an objective the speaker is explicitly pursuing.
- Habit: a recurring routine.
- Topic: a subject, concept, field of study, or a game.
- Tool: a software application, IDE, or platform.
- Technology: a framework, language, database, or library.
- Model: an AI or machine-learning model ONLY. Never label anything that is not an AI model as Model.
- Hardware: a physical computing component or machine — GPU, CPU, RAM, server, PC.
- Resource: a non-hardware resource the speaker draws on — ingredients, budget, materials, data.
- Recipe: a named cooking recipe.
- Issue: a concrete problem or defect.
- Place: a geographic location.

Extraction rules:
- Return ONLY valid JSON, no extra text.
- Never create a node for the speaker ("I", "me", "my", "myself") or for a bare "project".
- Create a Goal node only when the sentence explicitly frames something as a goal or objective the speaker is pursuing — phrases like "my goal is", "one of my goals is", "I want to", "I'm trying to". Name the Goal after the objective itself (e.g. "finish the MVP tasks"). Do NOT invent a Goal for a sentence that merely states a fact.
- Use the most specific full name that appears in the sentence (e.g. an "X site", not just "site").
- Preserve exact names and versions exactly as written.
- Put compact facts (status, dates, deployment, ownership, uncertainty) in attributes — do not turn them into separate nodes.
- Prefer a specific edge type; use related_to only when nothing else fits.

Edge guide:
- A project or effort uses its stack: Project -> Technology/Tool/Hardware with uses.
- A tool that runs a model: Tool -> Model with runs_model.
- Two models being weighed against each other: Model -> Model with compared_with.
- A recipe made for someone: Recipe -> Person with for. Use "for" ONLY for this recipe-to-person case.
- Problems: subject -> Issue with has_issue; Issue -> suspected cause with possible_cause.
- Applying to a program at an institution: Program -> Organization with at.
- A referral: the thing being referred is the SOURCE and the person giving the referral is the TARGET — Program -> Person with referred_by (the Person is always the referrer/target).
- A goal: Goal -> the Skill/Topic it centers on with focuses_on; Goal -> the Program/Event that drives it with motivated_by.
- Practising on something: Skill/Goal -> Hardware/Resource with practices_on.

Examples (these are illustrations only — follow their structure, never copy their entities):

Sentence: I'm writing a notes app in Django with Postgres, and I run Phi-3 locally through llama.cpp.
{{
  "nodes": [
    {{"label": "notes app", "type": "Project", "attributes": {{}}}},
    {{"label": "Django", "type": "Technology", "attributes": {{}}}},
    {{"label": "Postgres", "type": "Technology", "attributes": {{}}}},
    {{"label": "llama.cpp", "type": "Tool", "attributes": {{}}}},
    {{"label": "Phi-3", "type": "Model", "attributes": {{"deployment": "local"}}}}
  ],
  "edges": [
    {{"source_label": "notes app", "source_type": "Project", "target_label": "Django", "target_type": "Technology", "type": "uses"}},
    {{"source_label": "notes app", "source_type": "Project", "target_label": "Postgres", "target_type": "Technology", "type": "uses"}},
    {{"source_label": "notes app", "source_type": "Project", "target_label": "llama.cpp", "target_type": "Tool", "type": "uses"}},
    {{"source_label": "llama.cpp", "source_type": "Tool", "target_label": "Phi-3", "target_type": "Model", "type": "runs_model"}}
  ]
}}

Sentence: My goal is to sharpen my Rust skills before the Recurse Center batch that David referred me to.
{{
  "nodes": [
    {{"label": "sharpen Rust skills", "type": "Goal", "attributes": {{}}}},
    {{"label": "Rust", "type": "Skill", "attributes": {{}}}},
    {{"label": "Recurse Center batch", "type": "Program", "attributes": {{}}}},
    {{"label": "David", "type": "Person", "attributes": {{}}}}
  ],
  "edges": [
    {{"source_label": "sharpen Rust skills", "source_type": "Goal", "target_label": "Rust", "target_type": "Skill", "type": "focuses_on"}},
    {{"source_label": "sharpen Rust skills", "source_type": "Goal", "target_label": "Recurse Center batch", "target_type": "Program", "type": "motivated_by"}},
    {{"source_label": "Recurse Center batch", "source_type": "Program", "target_label": "David", "target_type": "Person", "type": "referred_by"}}
  ]
}}

Sentence: I still need to finish my sourdough recipe for my sister Lina — the last loaf came out too dense, maybe not enough water.
{{
  "nodes": [
    {{"label": "sourdough recipe", "type": "Recipe", "attributes": {{"status": "needs finishing"}}}},
    {{"label": "Lina", "type": "Person", "attributes": {{}}}},
    {{"label": "last loaf came out too dense", "type": "Issue", "attributes": {{}}}},
    {{"label": "water amount", "type": "Resource", "attributes": {{"uncertain": "true"}}}}
  ],
  "edges": [
    {{"source_label": "sourdough recipe", "source_type": "Recipe", "target_label": "Lina", "target_type": "Person", "type": "for"}},
    {{"source_label": "sourdough recipe", "source_type": "Recipe", "target_label": "last loaf came out too dense", "target_type": "Issue", "type": "has_issue"}},
    {{"source_label": "last loaf came out too dense", "source_type": "Issue", "target_label": "water amount", "target_type": "Resource", "type": "possible_cause"}}
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
            # Structured extraction must be deterministic. Ollama defaults to
            # temperature 0.8, which makes type/edge choices flip between runs
            # (the same sentence yielding "Skill" once and "Model" the next).
            # temperature 0 removes that sampling noise; the larger num_ctx
            # keeps the few-shot prompt from being truncated before the answer.
            "options": {
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": 1024,
            },
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
