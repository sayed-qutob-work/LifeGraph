"""Dashboard aggregation logic for LifeGraph.

Produces skills, goals, upcoming events (date >= today, ascending order,
today included), and a separate undated-events group from the graph.

Requirements: 12.1, 12.2, 12.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List

from lifegraph.domain import Graph, Node, NodeType


@dataclass
class DashboardData:
    """Aggregated dashboard output."""

    skills: List[Node] = field(default_factory=list)
    goals: List[Node] = field(default_factory=list)
    upcoming_events: List[Node] = field(default_factory=list)
    undated_events: List[Node] = field(default_factory=list)


def _parse_event_date(node: Node) -> date | None:
    """Try to parse the 'date' attribute of an Event node.

    Returns the parsed date if valid YYYY-MM-DD, or None if the attribute
    is missing, empty, or unparseable (invalid dates treated as undated).
    """
    date_str = node.attributes.get("date")
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def aggregate_dashboard(graph: Graph, today: date | None = None) -> DashboardData:
    """Aggregate dashboard data from the graph.

    Args:
        graph: The full graph snapshot containing all nodes and edges.
        today: The reference date for determining upcoming events.
               Defaults to date.today() if not provided. Injectable for testability.

    Returns:
        DashboardData with skills, goals, upcoming_events (sorted ascending by date,
        today included), and undated_events.
    """
    if today is None:
        today = date.today()

    skills: List[Node] = []
    goals: List[Node] = []
    upcoming_events: List[Node] = []
    undated_events: List[Node] = []

    for node in graph.nodes:
        if node.type == NodeType.SKILL:
            skills.append(node)
        elif node.type == NodeType.GOAL:
            goals.append(node)
        elif node.type == NodeType.EVENT:
            event_date = _parse_event_date(node)
            if event_date is None:
                # No date attribute or unparseable date -> undated group
                undated_events.append(node)
            elif event_date >= today:
                # Date is today or in the future -> upcoming
                upcoming_events.append(node)
            # else: past event, not shown on dashboard

    # Sort upcoming events by date ascending
    upcoming_events.sort(key=lambda n: _parse_event_date(n))  # type: ignore[arg-type]

    return DashboardData(
        skills=skills,
        goals=goals,
        upcoming_events=upcoming_events,
        undated_events=undated_events,
    )
