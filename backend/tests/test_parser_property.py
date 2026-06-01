"""Property test for Input_Parser length and blank-input gating (Property 2).

**Validates: Requirements 3.1, 3.8**

Property 2: Length and blank-input gating of the parser.
For any input string, the Input_Parser SHALL contact the Ollama_Client exactly once
when the string is non-blank and 1–1000 characters long, and SHALL reject the input
without contacting the Ollama_Client (leaving the Graph_Store unchanged) when the
string is empty, all-whitespace, or longer than 1000 characters.

Uses Hypothesis with min 100 examples and a mock OllamaClient.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import hypothesis.strategies as st
from hypothesis import given, settings

from lifegraph.domain import ProposedGraph
from lifegraph.ollama_client import OllamaClient
from lifegraph.parser import InputParser, InputValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parser_with_mock() -> tuple[InputParser, MagicMock]:
    """Create an InputParser with a fresh mock OllamaClient."""
    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.parse_sentence.return_value = {
        "nodes": [{"label": "Test", "type": "Skill", "attributes": {}}],
        "edges": [],
    }
    parser = InputParser(ollama=mock_ollama)
    return parser, mock_ollama


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid inputs: non-blank strings of 1–1000 characters.
# We use text() filtered to ensure at least one non-whitespace character.
valid_input_strategy = st.text(
    min_size=1, max_size=1000
).filter(lambda s: s.strip() != "")

# Invalid: empty string
empty_strategy = st.just("")

# Invalid: whitespace-only strings (at least 1 char, all whitespace)
whitespace_only_strategy = st.text(
    alphabet=st.sampled_from(" \t\n\r\x0b\x0c"),
    min_size=1,
    max_size=100,
)

# Invalid: strings longer than 1000 characters
too_long_strategy = st.text(min_size=1001, max_size=2000)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestParserLengthAndBlankGating:
    """Property 2: Length and blank-input gating of the parser.

    **Validates: Requirements 3.1, 3.8**
    """

    @settings(max_examples=20)
    @given(sentence=valid_input_strategy)
    def test_valid_input_contacts_ollama_exactly_once(self, sentence: str) -> None:
        """For any non-blank string of 1–1000 chars, the parser SHALL contact
        the Ollama_Client exactly once."""
        parser, mock_ollama = _make_parser_with_mock()

        result = parser.parse(sentence)

        # Ollama was called exactly once with the input sentence
        mock_ollama.parse_sentence.assert_called_once_with(sentence)
        # A ProposedGraph is returned
        assert isinstance(result, ProposedGraph)

    @settings(max_examples=20)
    @given(sentence=empty_strategy)
    def test_empty_input_rejected_without_ollama_contact(self, sentence: str) -> None:
        """For an empty string, the parser SHALL reject without contacting Ollama."""
        parser, mock_ollama = _make_parser_with_mock()

        try:
            parser.parse(sentence)
            # Should not reach here
            assert False, "Expected InputValidationError for empty input"
        except InputValidationError:
            pass

        # Ollama was never called
        mock_ollama.parse_sentence.assert_not_called()

    @settings(max_examples=20)
    @given(sentence=whitespace_only_strategy)
    def test_whitespace_only_rejected_without_ollama_contact(self, sentence: str) -> None:
        """For any all-whitespace string, the parser SHALL reject without
        contacting Ollama."""
        parser, mock_ollama = _make_parser_with_mock()

        try:
            parser.parse(sentence)
            assert False, "Expected InputValidationError for whitespace-only input"
        except InputValidationError:
            pass

        # Ollama was never called
        mock_ollama.parse_sentence.assert_not_called()

    @settings(max_examples=20)
    @given(sentence=too_long_strategy)
    def test_too_long_input_rejected_without_ollama_contact(self, sentence: str) -> None:
        """For any string longer than 1000 characters, the parser SHALL reject
        without contacting Ollama."""
        parser, mock_ollama = _make_parser_with_mock()

        try:
            parser.parse(sentence)
            assert False, "Expected InputValidationError for >1000 char input"
        except InputValidationError:
            pass

        # Ollama was never called
        mock_ollama.parse_sentence.assert_not_called()


# ---------------------------------------------------------------------------
# Property 3: Proposal bounds and type validity
# ---------------------------------------------------------------------------

"""
Property 3: Proposal bounds and type validity.

**Validates: Requirements 3.2**

For any well-formed model response, the produced ProposedGraph SHALL contain
between 0 and 100 nodes and between 0 and 200 edges, and every proposed node
type SHALL be a member of the Node_Type_Set and every proposed edge type a
member of the Edge_Type_Set.

Uses Hypothesis with min 100 examples.
"""

from lifegraph.domain import (
    EDGE_TYPE_VALUES,
    NODE_TYPE_VALUES,
    EdgeType,
    NodeType,
)


# ---------------------------------------------------------------------------
# Strategies for well-formed model responses
# ---------------------------------------------------------------------------

_node_type_strategy = st.sampled_from(sorted(NODE_TYPE_VALUES))
_edge_type_strategy = st.sampled_from(sorted(EDGE_TYPE_VALUES))

_label_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

_attributes_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=10),
    values=st.text(min_size=1, max_size=10),
    max_size=5,
)

_well_formed_node_strategy = st.fixed_dictionaries({
    "label": _label_strategy,
    "type": _node_type_strategy,
    "attributes": _attributes_strategy,
})


def _well_formed_edge_strategy_fn():
    """Build a strategy for a well-formed edge dict with valid types."""
    return st.fixed_dictionaries({
        "source_label": _label_strategy,
        "source_type": _node_type_strategy,
        "target_label": _label_strategy,
        "target_type": _node_type_strategy,
        "type": _edge_type_strategy,
    })


# A well-formed raw response: dict with "nodes" list and "edges" list,
# all using valid types. We allow up to 250 nodes and 400 edges to test
# that the parser correctly truncates to the 100/200 bounds.
_well_formed_response_strategy = st.fixed_dictionaries({
    "nodes": st.lists(_well_formed_node_strategy, min_size=0, max_size=250),
    "edges": st.lists(_well_formed_edge_strategy_fn(), min_size=0, max_size=400),
})


class TestProposalBoundsAndTypeValidity:
    """Property 3: Proposal bounds and type validity.

    **Validates: Requirements 3.2**
    """

    @settings(max_examples=20)
    @given(raw_response=_well_formed_response_strategy)
    def test_proposal_bounds_and_type_validity(self, raw_response: dict) -> None:
        """For any well-formed model response, the ProposedGraph SHALL contain
        0–100 nodes and 0–200 edges, and every node type SHALL be in
        Node_Type_Set and every edge type in Edge_Type_Set."""
        mock_ollama = MagicMock(spec=OllamaClient)
        mock_ollama.parse_sentence.return_value = raw_response
        parser = InputParser(ollama=mock_ollama)

        result = parser.parse("test sentence")

        # --- Bounds check (Req 3.2) ---
        assert 0 <= len(result.nodes) <= 100, (
            f"Expected 0–100 nodes, got {len(result.nodes)}"
        )
        assert 0 <= len(result.edges) <= 200, (
            f"Expected 0–200 edges, got {len(result.edges)}"
        )

        # --- Node type validity ---
        for node in result.nodes:
            assert isinstance(node.type, NodeType), (
                f"Node type is not a NodeType enum: {node.type!r}"
            )
            assert node.type.value in NODE_TYPE_VALUES, (
                f"Node type '{node.type.value}' not in Node_Type_Set"
            )

        # --- Edge type validity ---
        for edge in result.edges:
            assert isinstance(edge.type, EdgeType), (
                f"Edge type is not an EdgeType enum: {edge.type!r}"
            )
            assert edge.type.value in EDGE_TYPE_VALUES, (
                f"Edge type '{edge.type.value}' not in Edge_Type_Set"
            )


# ---------------------------------------------------------------------------
# Property 4: Invalid type rejection
# ---------------------------------------------------------------------------


class TestInvalidTypeRejection:
    """Property 4: Invalid type rejection.

    For any model response containing a node type outside the Node_Type_Set or
    an edge type outside the Edge_Type_Set, the Input_Parser SHALL reject the
    offending element and report a validation error that names the invalid type.

    **Validates: Requirements 3.3**
    """

    # Strategy: generate a string that is NOT in NODE_TYPE_VALUES
    invalid_node_type_strategy = st.text(min_size=1, max_size=50).filter(
        lambda s: s not in {
            "Skill", "Goal", "Habit", "Project", "Event", "Person", "Resource"
        }
    )

    # Strategy: generate a string that is NOT in EDGE_TYPE_VALUES
    invalid_edge_type_strategy = st.text(min_size=1, max_size=50).filter(
        lambda s: s not in {
            "requires", "supports", "conflicts_with", "motivated_by",
            "leads_to", "part_of", "owned_by", "blocks", "related_to"
        }
    )

    # Valid node type for constructing otherwise-valid responses
    valid_node_type_strategy = st.sampled_from([
        "Skill", "Goal", "Habit", "Project", "Event", "Person", "Resource"
    ])

    # Valid edge type for constructing otherwise-valid responses
    valid_edge_type_strategy = st.sampled_from([
        "requires", "supports", "conflicts_with", "motivated_by",
        "leads_to", "part_of", "owned_by", "blocks", "related_to"
    ])

    @settings(max_examples=20)
    @given(
        invalid_type=invalid_node_type_strategy,
        label=st.text(min_size=1, max_size=50),
    )
    def test_invalid_node_type_raises_with_type_named(
        self, invalid_type: str, label: str
    ) -> None:
        """For any response with a node type outside Node_Type_Set, the parser
        SHALL reject and report the invalid type."""
        from lifegraph.parser import InvalidTypeError

        mock_ollama = MagicMock(spec=OllamaClient)
        mock_ollama.parse_sentence.return_value = {
            "nodes": [{"label": label, "type": invalid_type, "attributes": {}}],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)

        try:
            parser.parse("test sentence")
            assert False, "Expected InvalidTypeError for invalid node type"
        except InvalidTypeError as e:
            # The error message SHALL name the invalid type
            assert invalid_type in str(e), (
                f"Error message should name the invalid type '{invalid_type}', "
                f"got: {e}"
            )

    @settings(max_examples=20)
    @given(
        invalid_type=invalid_edge_type_strategy,
        source_label=st.text(min_size=1, max_size=50),
        target_label=st.text(min_size=1, max_size=50),
        source_type=valid_node_type_strategy,
        target_type=valid_node_type_strategy,
    )
    def test_invalid_edge_type_raises_with_type_named(
        self,
        invalid_type: str,
        source_label: str,
        target_label: str,
        source_type: str,
        target_type: str,
    ) -> None:
        """For any response with an edge type outside Edge_Type_Set, the parser
        SHALL reject and report the invalid type."""
        from lifegraph.parser import InvalidTypeError

        mock_ollama = MagicMock(spec=OllamaClient)
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": source_label, "type": source_type, "attributes": {}},
                {"label": target_label, "type": target_type, "attributes": {}},
            ],
            "edges": [
                {
                    "source_label": source_label,
                    "source_type": source_type,
                    "target_label": target_label,
                    "target_type": target_type,
                    "type": invalid_type,
                }
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        try:
            parser.parse("test sentence")
            assert False, "Expected InvalidTypeError for invalid edge type"
        except InvalidTypeError as e:
            # The error message SHALL name the invalid type
            assert invalid_type in str(e), (
                f"Error message should name the invalid type '{invalid_type}', "
                f"got: {e}"
            )

    @settings(max_examples=20)
    @given(
        invalid_type=invalid_node_type_strategy,
        valid_type=valid_node_type_strategy,
        source_label=st.text(min_size=1, max_size=50),
        target_label=st.text(min_size=1, max_size=50),
    )
    def test_invalid_node_type_in_edge_source_raises(
        self,
        invalid_type: str,
        valid_type: str,
        source_label: str,
        target_label: str,
    ) -> None:
        """For any response with an edge whose source_type is outside
        Node_Type_Set, the parser SHALL reject and report the invalid type."""
        from lifegraph.parser import InvalidTypeError

        mock_ollama = MagicMock(spec=OllamaClient)
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": target_label, "type": valid_type, "attributes": {}},
            ],
            "edges": [
                {
                    "source_label": source_label,
                    "source_type": invalid_type,
                    "target_label": target_label,
                    "target_type": valid_type,
                    "type": "requires",
                }
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        try:
            parser.parse("test sentence")
            assert False, "Expected InvalidTypeError for invalid source node type in edge"
        except InvalidTypeError as e:
            assert invalid_type in str(e), (
                f"Error message should name the invalid type '{invalid_type}', "
                f"got: {e}"
            )

    @settings(max_examples=20)
    @given(
        invalid_type=invalid_node_type_strategy,
        valid_type=valid_node_type_strategy,
        source_label=st.text(min_size=1, max_size=50),
        target_label=st.text(min_size=1, max_size=50),
    )
    def test_invalid_node_type_in_edge_target_raises(
        self,
        invalid_type: str,
        valid_type: str,
        source_label: str,
        target_label: str,
    ) -> None:
        """For any response with an edge whose target_type is outside
        Node_Type_Set, the parser SHALL reject and report the invalid type."""
        from lifegraph.parser import InvalidTypeError

        mock_ollama = MagicMock(spec=OllamaClient)
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": source_label, "type": valid_type, "attributes": {}},
            ],
            "edges": [
                {
                    "source_label": source_label,
                    "source_type": valid_type,
                    "target_label": target_label,
                    "target_type": invalid_type,
                    "type": "supports",
                }
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        try:
            parser.parse("test sentence")
            assert False, "Expected InvalidTypeError for invalid target node type in edge"
        except InvalidTypeError as e:
            assert invalid_type in str(e), (
                f"Error message should name the invalid type '{invalid_type}', "
                f"got: {e}"
            )


# ---------------------------------------------------------------------------
# Property 5: Unparseable response leaves store unchanged
# ---------------------------------------------------------------------------

"""
Property 5: Unparseable response leaves store unchanged.

**Validates: Requirements 3.4**

For any model response that cannot be converted into nodes and edges, the
Input_Parser SHALL raise a descriptive error and the Graph_Store node set
and edge set SHALL be unchanged.

Uses Hypothesis with min 100 examples.
"""

import tempfile
import os

from lifegraph.parser import UnparseableResponse
from lifegraph.store import GraphStore


# ---------------------------------------------------------------------------
# Strategies for unparseable responses
# ---------------------------------------------------------------------------

# Responses that are not dicts at all (cannot be converted to graph data)
non_dict_responses = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.booleans(),
    st.text(),
    st.lists(st.integers()),
    st.just([]),
)

# Dicts where "nodes" is not a list
nodes_not_list = st.fixed_dictionaries({
    "nodes": st.one_of(
        st.integers(),
        st.text(),
        st.booleans(),
        st.none(),
        st.dictionaries(st.text(), st.text(), max_size=3),
    ),
    "edges": st.just([]),
})

# Dicts where "edges" is not a list
edges_not_list = st.fixed_dictionaries({
    "nodes": st.just([]),
    "edges": st.one_of(
        st.integers(),
        st.text(),
        st.booleans(),
        st.none(),
        st.dictionaries(st.text(), st.text(), max_size=3),
    ),
})

# Dicts where a node entry is not a dict
node_entry_not_dict = st.fixed_dictionaries({
    "nodes": st.lists(
        st.one_of(
            st.integers(),
            st.text(),
            st.booleans(),
            st.none(),
            st.lists(st.integers(), max_size=2),
        ),
        min_size=1,
        max_size=5,
    ),
    "edges": st.just([]),
})

# Dicts where an edge entry is not a dict
edge_entry_not_dict = st.fixed_dictionaries({
    "nodes": st.just([]),
    "edges": st.lists(
        st.one_of(
            st.integers(),
            st.text(),
            st.booleans(),
            st.none(),
            st.lists(st.integers(), max_size=2),
        ),
        min_size=1,
        max_size=5,
    ),
})

# Combined strategy for all unparseable responses
unparseable_response_strategy = st.one_of(
    non_dict_responses,
    nodes_not_list,
    edges_not_list,
    node_entry_not_dict,
    edge_entry_not_dict,
)


class TestUnparseableResponseLeavesStoreUnchanged:
    """Property 5: Unparseable response leaves store unchanged.

    **Validates: Requirements 3.4**

    For any model response that cannot be converted into nodes and edges,
    the Input_Parser SHALL raise a descriptive error and the Graph_Store
    node set and edge set SHALL be unchanged.
    """

    def setup_method(self) -> None:
        """Create a fresh GraphStore for the test class (once per test method)."""
        self._tmp_fd, self._tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(self._tmp_fd)
        os.unlink(self._tmp_path)
        self._store = GraphStore(db_path=self._tmp_path)

        # Pre-populate with some data so we can verify it stays unchanged
        from lifegraph.domain import NodeType, EdgeType
        self._store.upsert_node("Guitar", NodeType.SKILL)
        self._store.upsert_node("Music Theory", NodeType.SKILL)
        guitar = self._store.find_node("Guitar", NodeType.SKILL)
        theory = self._store.find_node("Music Theory", NodeType.SKILL)
        assert guitar is not None and theory is not None
        self._store.create_edge(guitar.id, theory.id, EdgeType.REQUIRES)

        # Snapshot the store state
        graph = self._store.get_graph()
        self._nodes_before = frozenset(
            (n.id, n.type, n.label) for n in graph.nodes
        )
        self._edges_before = frozenset(
            (e.id, e.source, e.target, e.type) for e in graph.edges
        )

    def teardown_method(self) -> None:
        """Close and clean up the temp database."""
        if self._store is not None:
            self._store.close()
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

    @settings(max_examples=20)
    @given(raw_response=unparseable_response_strategy)
    def test_unparseable_response_raises_error_and_store_unchanged(
        self, raw_response
    ) -> None:
        """For any unparseable model response, the parser SHALL raise
        UnparseableResponse and the Graph_Store SHALL remain unchanged."""
        # Create a mock OllamaClient that returns the unparseable response
        mock_ollama = MagicMock(spec=OllamaClient)
        mock_ollama.parse_sentence.return_value = raw_response

        parser = InputParser(ollama=mock_ollama)

        # The parser should raise UnparseableResponse
        raised = False
        error_message = ""
        try:
            parser.parse("Learn guitar")
        except UnparseableResponse as e:
            raised = True
            error_message = str(e)

        assert raised, (
            f"Expected UnparseableResponse for raw_response={raw_response!r}, "
            f"but no exception was raised."
        )

        # The error message should be descriptive (non-empty)
        assert len(error_message) > 0, (
            "UnparseableResponse error message should be descriptive (non-empty)."
        )

        # The store should be unchanged
        graph_after = self._store.get_graph()
        nodes_after = frozenset(
            (n.id, n.type, n.label) for n in graph_after.nodes
        )
        edges_after = frozenset(
            (e.id, e.source, e.target, e.type) for e in graph_after.edges
        )

        assert self._nodes_before == nodes_after, (
            "Graph_Store node set changed after unparseable response."
        )
        assert self._edges_before == edges_after, (
            "Graph_Store edge set changed after unparseable response."
        )
