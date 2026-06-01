"""Tests for the Input_Parser (tasks 6.1 and 6.3).

Verifies that:
- Empty, whitespace-only, and >1000 char inputs raise InputValidationError
  WITHOUT contacting OllamaClient (Req 3.8)
- Valid inputs (1–1000 chars, non-blank) DO call OllamaClient.parse_sentence
  and return a ProposedGraph (Req 3.1, 16.1)
- Response validation caps nodes at 100 and edges at 200 (Req 3.2)
- Invalid node/edge types raise InvalidTypeError naming the type (Req 3.3)
- Unparseable responses raise UnparseableResponse (Req 3.4)
"""

from unittest.mock import MagicMock, patch

import pytest

from lifegraph.domain import (
    EDGE_TYPE_VALUES,
    NODE_TYPE_VALUES,
    EdgeType,
    NodeType,
    ProposedGraph,
)
from lifegraph.ollama_client import OllamaClient
from lifegraph.parser import (
    InputParser,
    InputValidationError,
    InvalidTypeError,
    UnparseableResponse,
    MAX_PROPOSED_NODES,
    MAX_PROPOSED_EDGES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ollama():
    """Create a mock OllamaClient that returns a valid raw response."""
    mock = MagicMock(spec=OllamaClient)
    mock.parse_sentence.return_value = {
        "nodes": [
            {"label": "Python", "type": "Skill", "attributes": {}},
        ],
        "edges": [],
    }
    return mock


@pytest.fixture
def parser(mock_ollama):
    """Create an InputParser with a mock OllamaClient."""
    return InputParser(ollama=mock_ollama)


# ---------------------------------------------------------------------------
# Input validation: rejection cases (no Ollama call)
# ---------------------------------------------------------------------------


class TestInputValidationRejection:
    """Tests that invalid inputs raise InputValidationError without calling Ollama."""

    def test_empty_string_raises(self, parser, mock_ollama):
        with pytest.raises(InputValidationError):
            parser.parse("")
        mock_ollama.parse_sentence.assert_not_called()

    def test_whitespace_only_raises(self, parser, mock_ollama):
        with pytest.raises(InputValidationError):
            parser.parse("   ")
        mock_ollama.parse_sentence.assert_not_called()

    def test_tabs_and_newlines_only_raises(self, parser, mock_ollama):
        with pytest.raises(InputValidationError):
            parser.parse("\t\n\r  \t")
        mock_ollama.parse_sentence.assert_not_called()

    def test_over_1000_chars_raises(self, parser, mock_ollama):
        long_input = "a" * 1001
        with pytest.raises(InputValidationError):
            parser.parse(long_input)
        mock_ollama.parse_sentence.assert_not_called()

    def test_way_over_1000_chars_raises(self, parser, mock_ollama):
        long_input = "x" * 5000
        with pytest.raises(InputValidationError):
            parser.parse(long_input)
        mock_ollama.parse_sentence.assert_not_called()


# ---------------------------------------------------------------------------
# Input validation: acceptance cases (Ollama IS called)
# ---------------------------------------------------------------------------


class TestInputValidationAcceptance:
    """Tests that valid inputs call OllamaClient and return a ProposedGraph."""

    def test_single_char_calls_ollama(self, parser, mock_ollama):
        result = parser.parse("a")
        mock_ollama.parse_sentence.assert_called_once_with("a")
        assert isinstance(result, ProposedGraph)

    def test_exactly_1000_chars_calls_ollama(self, parser, mock_ollama):
        sentence = "b" * 1000
        result = parser.parse(sentence)
        mock_ollama.parse_sentence.assert_called_once_with(sentence)
        assert isinstance(result, ProposedGraph)

    def test_normal_sentence_calls_ollama(self, parser, mock_ollama):
        sentence = "I am learning Python for my AI project"
        result = parser.parse(sentence)
        mock_ollama.parse_sentence.assert_called_once_with(sentence)
        assert isinstance(result, ProposedGraph)

    def test_sentence_with_leading_trailing_whitespace_is_valid(self, parser, mock_ollama):
        """A sentence with leading/trailing whitespace but non-blank content is valid."""
        sentence = "  hello world  "
        result = parser.parse(sentence)
        mock_ollama.parse_sentence.assert_called_once_with(sentence)
        assert isinstance(result, ProposedGraph)


# ---------------------------------------------------------------------------
# Raw response conversion
# ---------------------------------------------------------------------------


class TestRawToProposedGraph:
    """Tests that raw Ollama responses are converted to ProposedGraph."""

    def test_valid_nodes_are_converted(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": "Python", "type": "Skill", "attributes": {"level": "intermediate"}},
                {"label": "Build AI app", "type": "Goal", "attributes": {}},
            ],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("I know Python and want to build an AI app")

        assert len(result.nodes) == 2
        assert result.nodes[0].label == "Python"
        assert result.nodes[0].type == NodeType.SKILL
        assert result.nodes[0].attributes == {"level": "intermediate"}
        assert result.nodes[1].label == "Build AI app"
        assert result.nodes[1].type == NodeType.GOAL

    def test_valid_edges_are_converted(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": "Python", "type": "Skill"},
                {"label": "AI Project", "type": "Project"},
            ],
            "edges": [
                {
                    "source_label": "AI Project",
                    "source_type": "Project",
                    "target_label": "Python",
                    "target_type": "Skill",
                    "type": "requires",
                },
            ],
        }
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("My AI project requires Python")

        assert len(result.edges) == 1
        assert result.edges[0].source_label == "AI Project"
        assert result.edges[0].source_type == NodeType.PROJECT
        assert result.edges[0].target_label == "Python"
        assert result.edges[0].target_type == NodeType.SKILL
        assert result.edges[0].type == EdgeType.REQUIRES

    def test_empty_response_gives_empty_graph(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {}
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("something")

        assert result.nodes == []
        assert result.edges == []

    def test_invalid_node_type_raises_error(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": "Python", "type": "Skill"},
                {"label": "Invalid", "type": "NotAType"},
            ],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError, match="NotAType"):
            parser.parse("test")

    def test_invalid_edge_type_raises_error(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [],
            "edges": [
                {
                    "source_label": "A",
                    "source_type": "Skill",
                    "target_label": "B",
                    "target_type": "Goal",
                    "type": "invalid_edge_type",
                },
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError, match="invalid_edge_type"):
            parser.parse("test")


# ---------------------------------------------------------------------------
# Exclusive Ollama access (Req 16.1)
# ---------------------------------------------------------------------------


class TestExclusiveOllamaAccess:
    """Verify that model responses come exclusively through OllamaClient."""

    def test_parser_uses_ollama_client_interface(self, parser, mock_ollama):
        """The parser must call ollama.parse_sentence, not make direct HTTP calls."""
        parser.parse("test sentence")
        mock_ollama.parse_sentence.assert_called_once_with("test sentence")


# ---------------------------------------------------------------------------
# Response validation: UnparseableResponse (Req 3.4)
# ---------------------------------------------------------------------------


class TestUnparseableResponse:
    """Tests that non-convertible responses raise UnparseableResponse."""

    def test_non_dict_response_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = "not a dict"
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_none_response_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = None
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_list_response_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = [{"nodes": []}]
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_nodes_not_a_list_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {"nodes": "not a list", "edges": []}
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_edges_not_a_list_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {"nodes": [], "edges": "not a list"}
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_node_entry_not_dict_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {"nodes": ["not a dict"], "edges": []}
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_edge_entry_not_dict_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {"nodes": [], "edges": [42]}
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")

    def test_integer_response_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = 42
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(UnparseableResponse):
            parser.parse("test")


# ---------------------------------------------------------------------------
# Response validation: InvalidTypeError (Req 3.3)
# ---------------------------------------------------------------------------


class TestInvalidTypeError:
    """Tests that invalid types raise InvalidTypeError naming the type."""

    def test_invalid_node_type_names_the_type(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [{"label": "X", "type": "Banana"}],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError, match="Banana"):
            parser.parse("test")

    def test_invalid_edge_source_type_names_the_type(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [],
            "edges": [
                {
                    "source_label": "A",
                    "source_type": "FakeType",
                    "target_label": "B",
                    "target_type": "Skill",
                    "type": "requires",
                }
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError, match="FakeType"):
            parser.parse("test")

    def test_invalid_edge_target_type_names_the_type(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [],
            "edges": [
                {
                    "source_label": "A",
                    "source_type": "Skill",
                    "target_label": "B",
                    "target_type": "BadType",
                    "type": "requires",
                }
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError, match="BadType"):
            parser.parse("test")

    def test_invalid_edge_type_names_the_type(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [],
            "edges": [
                {
                    "source_label": "A",
                    "source_type": "Skill",
                    "target_label": "B",
                    "target_type": "Goal",
                    "type": "destroys",
                }
            ],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError, match="destroys"):
            parser.parse("test")

    def test_empty_node_type_raises(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [{"label": "X", "type": ""}],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)

        with pytest.raises(InvalidTypeError):
            parser.parse("test")


# ---------------------------------------------------------------------------
# Response validation: Bounds capping (Req 3.2)
# ---------------------------------------------------------------------------


class TestProposalBounds:
    """Tests that nodes are capped at 100 and edges at 200."""

    def test_nodes_capped_at_100(self, mock_ollama):
        # Generate 150 valid nodes
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": f"Node{i}", "type": "Skill", "attributes": {}}
                for i in range(150)
            ],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("test")

        assert len(result.nodes) == MAX_PROPOSED_NODES  # 100

    def test_edges_capped_at_200(self, mock_ollama):
        # Generate 250 valid edges
        mock_ollama.parse_sentence.return_value = {
            "nodes": [],
            "edges": [
                {
                    "source_label": f"A{i}",
                    "source_type": "Skill",
                    "target_label": f"B{i}",
                    "target_type": "Goal",
                    "type": "requires",
                }
                for i in range(250)
            ],
        }
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("test")

        assert len(result.edges) == MAX_PROPOSED_EDGES  # 200

    def test_exactly_100_nodes_not_truncated(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [
                {"label": f"Node{i}", "type": "Goal", "attributes": {}}
                for i in range(100)
            ],
            "edges": [],
        }
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("test")

        assert len(result.nodes) == 100

    def test_exactly_200_edges_not_truncated(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {
            "nodes": [],
            "edges": [
                {
                    "source_label": f"A{i}",
                    "source_type": "Skill",
                    "target_label": f"B{i}",
                    "target_type": "Goal",
                    "type": "supports",
                }
                for i in range(200)
            ],
        }
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("test")

        assert len(result.edges) == 200

    def test_zero_nodes_and_edges_is_valid(self, mock_ollama):
        mock_ollama.parse_sentence.return_value = {"nodes": [], "edges": []}
        parser = InputParser(ollama=mock_ollama)
        result = parser.parse("test")

        assert len(result.nodes) == 0
        assert len(result.edges) == 0
