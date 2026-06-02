"""Input_Parser — validates input and delegates to Ollama_Client for parsing.

Converts natural-language sentences into ProposedGraph data by:
1. Validating input (length 1–1000, non-blank) BEFORE any Ollama contact (Req 3.8)
2. Delegating to OllamaClient.parse_sentence() exclusively (Req 16.1)
3. Converting the raw response into a ProposedGraph with validation (Req 3.2, 3.3, 3.4)

Raises InputValidationError for invalid input without making any LLM call.
Raises InvalidTypeError when a node/edge type is outside the allowed sets.
Raises UnparseableResponse when the raw output cannot be converted.
"""

from __future__ import annotations

from typing import Any, Dict

from lifegraph.domain import (
    EDGE_TYPE_VALUES,
    NODE_TYPE_VALUES,
    EdgeType,
    NodeType,
    ProposedEdge,
    ProposedGraph,
    ProposedNode,
)
from lifegraph.ollama_client import OllamaClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PROPOSED_NODES = 100
MAX_PROPOSED_EDGES = 200
IGNORED_LABELS = frozenset({
    "i",
    "me",
    "my",
    "myself",
    "my project",
})


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class InputValidationError(Exception):
    """Raised when input fails pre-Ollama validation (Req 3.8).

    Empty, whitespace-only, or >1000 character inputs are rejected without
    contacting the Ollama_Client.
    """

    pass


class InvalidTypeError(Exception):
    """Raised when a node or edge type is not in the allowed type sets (Req 3.3).

    The error message names the invalid type that was encountered.
    """

    pass


class UnparseableResponse(Exception):
    """Raised when the raw Ollama response cannot be converted into nodes/edges (Req 3.4).

    This covers cases where the response is not a dict, is missing the expected
    structure, or otherwise cannot be interpreted as graph data.
    """

    pass


# ---------------------------------------------------------------------------
# InputParser
# ---------------------------------------------------------------------------


class InputParser:
    """Validates input and delegates to OllamaClient for NL parsing.

    Validation order: length/blank checks run BEFORE any Ollama contact (Req 3.8).
    Model responses are obtained exclusively through OllamaClient (Req 16.1).
    """

    def __init__(
        self,
        ollama: OllamaClient,
        node_types: frozenset[str] = NODE_TYPE_VALUES,
        edge_types: frozenset[str] = EDGE_TYPE_VALUES,
    ) -> None:
        self.ollama = ollama
        self.node_types = node_types
        self.edge_types = edge_types

    def parse(self, sentence: str) -> ProposedGraph:
        """Validate input, then delegate to Ollama, then validate the response.

        Args:
            sentence: The natural-language sentence to parse.

        Returns:
            A ProposedGraph with 0–100 nodes and 0–200 edges.

        Raises:
            InputValidationError: If the input is empty, whitespace-only,
                or exceeds 1000 characters (no Ollama call made).
            UnparseableResponse: If the response cannot be converted to
                nodes and edges (Req 3.4).
            InvalidTypeError: If a node/edge type is outside the allowed
                sets (Req 3.3).
            OllamaUnavailableError: If the Ollama service is unreachable.
            OllamaTimeoutError: If the request exceeds the configured timeout.
        """
        # --- Input validation gating (Req 3.8) ---
        # Check BEFORE any Ollama contact
        self._validate_input(sentence)

        # --- Delegate to OllamaClient exclusively (Req 16.1) ---
        raw_response = self.ollama.parse_sentence(sentence)

        # --- Response validation into ProposedGraph (Req 3.2, 3.3, 3.4) ---
        return self._raw_to_proposed_graph(raw_response)

    def proposal_from_raw(self, raw: Any) -> ProposedGraph:
        """Validate raw proposal JSON into a ProposedGraph without calling Ollama."""
        return self._raw_to_proposed_graph(raw)

    def _validate_input(self, sentence: str) -> None:
        """Validate sentence length and non-blank before Ollama contact.

        Raises InputValidationError if:
        - sentence is empty (length 0)
        - sentence contains only whitespace
        - sentence exceeds 1000 characters
        """
        if not sentence:
            raise InputValidationError(
                "Input sentence must not be empty."
            )

        if sentence.strip() == "":
            raise InputValidationError(
                "Input sentence must not be blank (whitespace-only)."
            )

        if len(sentence) > 1000:
            raise InputValidationError(
                f"Input sentence must not exceed 1000 characters "
                f"(got {len(sentence)})."
            )

    def _raw_to_proposed_graph(self, raw: Any) -> ProposedGraph:
        """Convert a raw response from Ollama into a validated ProposedGraph.

        Validation (Req 3.2, 3.3, 3.4):
        - Raises UnparseableResponse if the response is not a dict or lacks
          the expected structure (nodes/edges as lists).
        - Raises InvalidTypeError naming the invalid type if a node type is
          not in NODE_TYPE_VALUES or an edge type is not in EDGE_TYPE_VALUES.
        - Caps nodes at MAX_PROPOSED_NODES (100) and edges at MAX_PROPOSED_EDGES
          (200) by truncation.
        """
        # --- Structural validation (Req 3.4) ---
        if not isinstance(raw, dict):
            raise UnparseableResponse(
                "Response is not a dictionary — cannot convert to graph data."
            )

        raw_nodes = raw.get("nodes", [])
        raw_edges = raw.get("edges", [])

        if not isinstance(raw_nodes, list):
            raise UnparseableResponse(
                "Response 'nodes' field is not a list — cannot convert to graph data."
            )

        if not isinstance(raw_edges, list):
            raise UnparseableResponse(
                "Response 'edges' field is not a list — cannot convert to graph data."
            )

        # --- Node conversion with type validation (Req 3.3) ---
        nodes: list[ProposedNode] = []
        for item in raw_nodes:
            if not isinstance(item, dict):
                raise UnparseableResponse(
                    "A node entry is not a dictionary — cannot convert to graph data."
                )

            label = item.get("label", "")
            type_str = item.get("type", "")
            attributes = item.get("attributes", {})

            # Validate node type against NODE_TYPE_VALUES (Req 3.3)
            if type_str not in self.node_types:
                raise InvalidTypeError(
                    f"Invalid node type: '{type_str}'"
                )

            node_type = NodeType(type_str)

            if not isinstance(attributes, dict):
                attributes = {}

            if self._should_ignore_label(label):
                continue

            # Ensure attributes are string->string
            clean_attrs = {
                str(k): str(v)
                for k, v in attributes.items()
            }

            nodes.append(ProposedNode(
                type=node_type,
                label=str(label),
                attributes=clean_attrs,
            ))

        # --- Edge conversion with type validation (Req 3.3) ---
        edges: list[ProposedEdge] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                raise UnparseableResponse(
                    "An edge entry is not a dictionary — cannot convert to graph data."
                )

            source_label = item.get("source_label", "")
            source_type_str = item.get("source_type", "")
            target_label = item.get("target_label", "")
            target_type_str = item.get("target_type", "")
            edge_type_str = item.get("type", "")

            # Validate source node type
            if source_type_str not in self.node_types:
                raise InvalidTypeError(
                    f"Invalid node type: '{source_type_str}'"
                )

            # Validate target node type
            if target_type_str not in self.node_types:
                raise InvalidTypeError(
                    f"Invalid node type: '{target_type_str}'"
                )

            # Validate edge type against EDGE_TYPE_VALUES (Req 3.3)
            if edge_type_str not in self.edge_types:
                raise InvalidTypeError(
                    f"Invalid edge type: '{edge_type_str}'"
                )

            source_type = NodeType(source_type_str)
            target_type = NodeType(target_type_str)
            edge_type = EdgeType(edge_type_str)

            if (
                self._should_ignore_label(source_label)
                or self._should_ignore_label(target_label)
            ):
                continue

            edges.append(ProposedEdge(
                source_label=str(source_label),
                source_type=source_type,
                target_label=str(target_label),
                target_type=target_type,
                type=edge_type,
            ))

        # --- Cap at bounds (Req 3.2): truncate, don't reject ---
        nodes = nodes[:MAX_PROPOSED_NODES]
        edges = edges[:MAX_PROPOSED_EDGES]

        return ProposedGraph(nodes=nodes, edges=edges)

    def _should_ignore_label(self, label: Any) -> bool:
        """Return true for speaker/self placeholders that should not be persisted."""
        return str(label).strip().casefold() in IGNORED_LABELS
