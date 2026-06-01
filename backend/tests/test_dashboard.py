"""Tests for the dashboard aggregation module."""

from datetime import date

from lifegraph.dashboard import DashboardData, aggregate_dashboard
from lifegraph.domain import Graph, Node, NodeType


def _skill(id: str, label: str) -> Node:
    return Node(id=id, type=NodeType.SKILL, label=label)


def _goal(id: str, label: str) -> Node:
    return Node(id=id, type=NodeType.GOAL, label=label)


def _event(id: str, label: str, event_date: str | None = None) -> Node:
    attrs = {"date": event_date} if event_date else {}
    return Node(id=id, type=NodeType.EVENT, label=label, attributes=attrs)


def test_empty_graph():
    result = aggregate_dashboard(Graph(), today=date(2025, 6, 1))
    assert result == DashboardData()


def test_mixed_graph_partitioning():
    """Skills, goals, upcoming/past/undated events are correctly partitioned."""
    graph = Graph(nodes=[
        _skill("s1", "Python"),
        _goal("g1", "Ship MVP"),
        _event("e1", "Launch", "2025-07-01"),
        _event("e2", "Past", "2025-05-01"),
        _event("e3", "Someday"),
        Node(id="h1", type=NodeType.HABIT, label="Exercise"),
    ])
    result = aggregate_dashboard(graph, today=date(2025, 6, 1))
    assert [n.label for n in result.skills] == ["Python"]
    assert [n.label for n in result.goals] == ["Ship MVP"]
    assert [n.label for n in result.upcoming_events] == ["Launch"]
    assert [n.label for n in result.undated_events] == ["Someday"]


def test_today_included_and_ascending_order():
    """Events on today are upcoming; results are date-ascending."""
    graph = Graph(nodes=[
        _event("e1", "Later", "2025-08-01"),
        _event("e2", "Today", "2025-06-01"),
        _event("e3", "Middle", "2025-07-01"),
    ])
    result = aggregate_dashboard(graph, today=date(2025, 6, 1))
    assert [n.label for n in result.upcoming_events] == ["Today", "Middle", "Later"]


def test_invalid_dates_treated_as_undated():
    graph = Graph(nodes=[
        _event("e1", "Bad", "not-a-date"),
        _event("e2", "Empty", ""),
    ])
    result = aggregate_dashboard(graph, today=date(2025, 6, 1))
    assert len(result.undated_events) == 2
    assert result.upcoming_events == []
