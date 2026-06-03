"""Dashboard aggregation logic for LifeGraph.

Produces skills, goals, upcoming events (date >= today, ascending order,
today included), and a separate undated-events group from the graph.

Requirements: 12.1, 12.2, 12.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List

from lifegraph.domain import Graph, Node, NodeType


@dataclass
class DashboardData:
    """Aggregated dashboard output."""

    skills: List[Node] = field(default_factory=list)
    goals: List[Node] = field(default_factory=list)
    upcoming_events: List[Node] = field(default_factory=list)
    undated_events: List[Node] = field(default_factory=list)
    past_events: List[Node] = field(default_factory=list)
    recent_nodes: List[Node] = field(default_factory=list)


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


def aggregate_dashboard(
    graph: Graph,
    today: date | None = None,
    recent_cutoff: str | None = None,
) -> DashboardData:
    """Aggregate dashboard data from the graph.

    Args:
        graph: The full graph snapshot containing all nodes and edges.
        today: Reference date for event classification. Defaults to date.today().
        recent_cutoff: ISO-8601 UTC string; nodes with a timestamp >= this value
            are included in recent_nodes. Defaults to 7 days ago. Pass an empty
            string to skip the recent calculation.

    Returns:
        DashboardData with skills, goals, upcoming/undated/past events, and
        recently touched nodes.
    """
    if today is None:
        today = date.today()

    if recent_cutoff is None:
        recent_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

    skills: List[Node] = []
    goals: List[Node] = []
    upcoming_events: List[Node] = []
    undated_events: List[Node] = []
    past_events: List[Node] = []
    recent_nodes: List[Node] = []

    for node in graph.nodes:
        if node.type == NodeType.SKILL:
            skills.append(node)
        elif node.type == NodeType.GOAL:
            goals.append(node)
        elif node.type == NodeType.EVENT:
            event_date = _parse_event_date(node)
            if event_date is None:
                undated_events.append(node)
            elif event_date >= today:
                upcoming_events.append(node)
            else:
                past_events.append(node)

        # Recent: any node with a non-empty timestamp within the window
        if recent_cutoff:
            ts = node.updated_at or node.created_at
            if ts and ts >= recent_cutoff:
                recent_nodes.append(node)

    # Sort upcoming events ascending, past events descending (most recent first)
    upcoming_events.sort(key=lambda n: _parse_event_date(n))  # type: ignore[arg-type]
    past_events.sort(key=lambda n: _parse_event_date(n), reverse=True)  # type: ignore[arg-type]
    recent_nodes.sort(
        key=lambda n: max(n.updated_at or "", n.created_at or ""),
        reverse=True,
    )

    return DashboardData(
        skills=skills,
        goals=goals,
        upcoming_events=upcoming_events,
        undated_events=undated_events,
        past_events=past_events,
        recent_nodes=recent_nodes,
    )
