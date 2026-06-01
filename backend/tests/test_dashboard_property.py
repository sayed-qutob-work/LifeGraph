"""Property-based tests for dashboard aggregation (Properties 28 and 29).

**Validates: Requirements 12.1, 12.2, 12.3**

Property 28: Dashboard skill and goal completeness
  WHEN the user opens the dashboard, THE Dashboard SHALL display all nodes of type
  Skill and all nodes of type Goal. No non-Skill node appears in result.skills and
  no non-Goal node appears in result.goals.

Property 29: Dashboard event partitioning and ordering
  For any set of Event nodes and any reference date "today", the dashboard's
  upcoming-events list SHALL equal exactly the events whose date is today or later,
  sorted in ascending date order, and its undated-events group SHALL equal exactly
  the events with no date attribute or invalid date, the two groups being disjoint.
"""

from __future__ import annotations

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.dashboard import aggregate_dashboard
from lifegraph.domain import Graph, Node, NodeType


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All node types for generating a mixed graph
all_node_types_st = st.sampled_from(list(NodeType))

# Valid node labels (1-200 chars, non-empty after strip)
node_label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Simple attributes (optional date for Event nodes, empty for others)
simple_attributes_st = st.just({})

# A date attribute strategy for Event nodes
event_date_st = st.one_of(
    st.just({}),  # no date
    st.dates(
        min_value=date(2000, 1, 1),
        max_value=date(2100, 12, 31),
    ).map(lambda d: {"date": d.isoformat()}),
)


@st.composite
def node_st(draw: st.DrawFn) -> Node:
    """Generate a random Node with a unique id, random type, and label."""
    node_id = draw(st.uuids().map(str))
    node_type = draw(all_node_types_st)
    label = draw(node_label_st)

    # Give Event nodes a chance to have a date attribute
    if node_type == NodeType.EVENT:
        attributes = draw(event_date_st)
    else:
        attributes = draw(simple_attributes_st)

    return Node(id=node_id, type=node_type, label=label, attributes=attributes)


@st.composite
def graph_with_various_types_st(draw: st.DrawFn) -> Graph:
    """Generate a graph with 0-30 nodes of various types."""
    nodes = draw(st.lists(node_st(), min_size=0, max_size=30))
    return Graph(nodes=nodes, edges=[])


# A fixed "today" for deterministic testing
reference_today = date(2025, 6, 15)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@settings(max_examples=20)
@given(graph=graph_with_various_types_st())
def test_dashboard_skill_and_goal_completeness(graph: Graph):
    """Property 28: Dashboard skill and goal completeness.

    **Validates: Requirements 12.1**

    For any graph with various node types:
    - Every Skill node in the graph appears in result.skills
    - Every Goal node in the graph appears in result.goals
    - No non-Skill node appears in result.skills
    - No non-Goal node appears in result.goals
    """
    result = aggregate_dashboard(graph, today=reference_today)

    # Collect expected skills and goals from the graph
    expected_skills = [n for n in graph.nodes if n.type == NodeType.SKILL]
    expected_goals = [n for n in graph.nodes if n.type == NodeType.GOAL]

    # 1. Every Skill node in the graph appears in result.skills
    result_skill_ids = {n.id for n in result.skills}
    for skill in expected_skills:
        assert skill.id in result_skill_ids, (
            f"Skill node {skill.id!r} (label={skill.label!r}) is in the graph "
            f"but missing from result.skills"
        )

    # 2. Every Goal node in the graph appears in result.goals
    result_goal_ids = {n.id for n in result.goals}
    for goal in expected_goals:
        assert goal.id in result_goal_ids, (
            f"Goal node {goal.id!r} (label={goal.label!r}) is in the graph "
            f"but missing from result.goals"
        )

    # 3. No non-Skill node appears in result.skills
    for node in result.skills:
        assert node.type == NodeType.SKILL, (
            f"Non-Skill node {node.id!r} (type={node.type.value}) "
            f"found in result.skills"
        )

    # 4. No non-Goal node appears in result.goals
    for node in result.goals:
        assert node.type == NodeType.GOAL, (
            f"Non-Goal node {node.id!r} (type={node.type.value}) "
            f"found in result.goals"
        )

    # Additionally verify exact counts match
    assert len(result.skills) == len(expected_skills), (
        f"Expected {len(expected_skills)} skills but got {len(result.skills)}"
    )
    assert len(result.goals) == len(expected_goals), (
        f"Expected {len(expected_goals)} goals but got {len(result.goals)}"
    )


# ---------------------------------------------------------------------------
# Property 29: Dashboard event partitioning and ordering
# ---------------------------------------------------------------------------

# Strategies for generating Event nodes with various date attributes


@st.composite
def event_node_st(draw: st.DrawFn, today: date) -> Node:
    """Generate an Event node with various date attribute scenarios.

    Produces events with:
    - Valid future dates (date > today)
    - Valid today date (date == today)
    - Valid past dates (date < today)
    - Invalid date strings (not YYYY-MM-DD or impossible dates)
    - Missing date attribute entirely
    """
    node_id = draw(st.uuids().map(str))
    label = draw(node_label_st)

    # Choose a date attribute category
    date_category = draw(
        st.sampled_from(["future", "today", "past", "invalid", "missing"])
    )

    if date_category == "future":
        # Valid date strictly after today
        future_date = draw(
            st.dates(
                min_value=date.fromordinal(today.toordinal() + 1),
                max_value=date(2100, 12, 31),
            )
        )
        attributes = {"date": future_date.isoformat()}
    elif date_category == "today":
        # Exactly today
        attributes = {"date": today.isoformat()}
    elif date_category == "past":
        # Valid date strictly before today
        past_date = draw(
            st.dates(
                min_value=date(2000, 1, 1),
                max_value=date.fromordinal(today.toordinal() - 1),
            )
        )
        attributes = {"date": past_date.isoformat()}
    elif date_category == "invalid":
        # Invalid date strings
        invalid_date = draw(
            st.one_of(
                st.just("not-a-date"),
                st.just("2025-02-30"),
                st.just("2025-13-01"),
                st.just("abcdef"),
                st.just(""),
                st.just("2025/06/15"),
                st.just("15-06-2025"),
                st.text(min_size=1, max_size=20).filter(
                    lambda s: not _is_valid_date_str(s)
                ),
            )
        )
        attributes = {"date": invalid_date}
    else:
        # Missing date attribute entirely
        attributes = {}

    return Node(id=node_id, type=NodeType.EVENT, label=label, attributes=attributes)


def _is_valid_date_str(s: str) -> bool:
    """Check if a string is a valid YYYY-MM-DD date."""
    try:
        date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


@st.composite
def event_graph_st(draw: st.DrawFn) -> tuple[Graph, date]:
    """Generate a graph of Event nodes with a reference 'today' date."""
    today = draw(
        st.dates(min_value=date(2020, 1, 1), max_value=date(2080, 12, 31))
    )
    events = draw(
        st.lists(event_node_st(today=today), min_size=0, max_size=30)
    )
    # Also include some non-Event nodes to ensure they don't leak into event lists
    other_nodes = draw(
        st.lists(
            st.builds(
                Node,
                id=st.uuids().map(str),
                type=st.sampled_from(
                    [t for t in NodeType if t != NodeType.EVENT]
                ),
                label=node_label_st,
                attributes=st.just({}),
            ),
            min_size=0,
            max_size=10,
        )
    )
    all_nodes = events + other_nodes
    return Graph(nodes=all_nodes, edges=[]), today


@settings(max_examples=20)
@given(data=event_graph_st())
def test_dashboard_event_partitioning_and_ordering(data: tuple[Graph, date]):
    """Property 29: Dashboard event partitioning and ordering.

    **Validates: Requirements 12.2, 12.3**

    For any set of Event nodes and any reference date "today":
    - All upcoming events have date >= today
    - upcoming_events are sorted ascending by date
    - undated_events have no valid date attribute
    - No past events appear in either list
    - Today's events are in upcoming_events
    - The two groups (upcoming and undated) are disjoint
    """
    graph, today = data
    result = aggregate_dashboard(graph, today=today)

    # Collect all Event nodes from the graph
    event_nodes = [n for n in graph.nodes if n.type == NodeType.EVENT]

    # Helper: parse a node's date attribute
    def parse_date(node: Node) -> date | None:
        date_str = node.attributes.get("date")
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    # 1. All upcoming events have date >= today
    for node in result.upcoming_events:
        event_date = parse_date(node)
        assert event_date is not None, (
            f"Event {node.id!r} (label={node.label!r}) is in upcoming_events "
            f"but has no valid date attribute"
        )
        assert event_date >= today, (
            f"Event {node.id!r} (label={node.label!r}) has date {event_date} "
            f"which is before today ({today}), but it's in upcoming_events"
        )

    # 2. upcoming_events are sorted ascending by date
    upcoming_dates = [parse_date(n) for n in result.upcoming_events]
    for i in range(len(upcoming_dates) - 1):
        assert upcoming_dates[i] <= upcoming_dates[i + 1], (  # type: ignore[operator]
            f"upcoming_events not sorted ascending: "
            f"{upcoming_dates[i]} > {upcoming_dates[i + 1]} "
            f"at positions {i} and {i + 1}"
        )

    # 3. undated_events have no valid date attribute
    for node in result.undated_events:
        event_date = parse_date(node)
        assert event_date is None, (
            f"Event {node.id!r} (label={node.label!r}) has a valid date "
            f"{event_date} but is in undated_events"
        )

    # 4. No past events appear in either list
    upcoming_ids = {n.id for n in result.upcoming_events}
    undated_ids = {n.id for n in result.undated_events}
    for node in event_nodes:
        event_date = parse_date(node)
        if event_date is not None and event_date < today:
            assert node.id not in upcoming_ids, (
                f"Past event {node.id!r} (date={event_date}) "
                f"should not be in upcoming_events"
            )
            assert node.id not in undated_ids, (
                f"Past event {node.id!r} (date={event_date}) "
                f"should not be in undated_events"
            )

    # 5. Today's events are in upcoming_events
    for node in event_nodes:
        event_date = parse_date(node)
        if event_date == today:
            assert node.id in upcoming_ids, (
                f"Event {node.id!r} with today's date ({today}) "
                f"should be in upcoming_events"
            )

    # 6. The two groups (upcoming and undated) are disjoint
    overlap = upcoming_ids & undated_ids
    assert not overlap, (
        f"upcoming_events and undated_events overlap: {overlap}"
    )

    # 7. All Event nodes are accounted for (upcoming + undated + past = all events)
    # Every event with date >= today should be in upcoming
    # Every event with no valid date should be in undated
    # Every event with date < today should be in neither
    for node in event_nodes:
        event_date = parse_date(node)
        if event_date is not None and event_date >= today:
            assert node.id in upcoming_ids, (
                f"Event {node.id!r} (date={event_date} >= today={today}) "
                f"should be in upcoming_events but is missing"
            )
        elif event_date is None:
            assert node.id in undated_ids, (
                f"Event {node.id!r} with no valid date "
                f"should be in undated_events but is missing"
            )
        else:
            # Past event: should not be in either list
            assert node.id not in upcoming_ids and node.id not in undated_ids, (
                f"Past event {node.id!r} (date={event_date}) "
                f"should not appear in any dashboard event list"
            )

    # 8. Only Event nodes appear in the event lists
    for node in result.upcoming_events:
        assert node.type == NodeType.EVENT, (
            f"Non-Event node {node.id!r} (type={node.type.value}) "
            f"found in upcoming_events"
        )
    for node in result.undated_events:
        assert node.type == NodeType.EVENT, (
            f"Non-Event node {node.id!r} (type={node.type.value}) "
            f"found in undated_events"
        )
