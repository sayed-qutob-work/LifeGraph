"""Context_Serializer: deterministic subgraph serialization to plain text.

Implements a bounded BFS traversal from a root node, budget trimming by hop
distance, and a fixed plain-text template for pasting into AI conversations.

This module is a pure function of (graph, root_id, config) — no I/O beyond
reading the Graph passed in. Determinism (Req 10.5) is guaranteed by ordering
every traversal step by a stable key (hop distance, then node id) and by
rendering with a fixed template.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Set, Tuple

from lifegraph.domain import Edge, Graph, Node


class ContextSerializer:
    """Produces a deterministic plain-text context snapshot of a subgraph.

    Parameters
    ----------
    max_hops : int
        Maximum traversal depth from the root node (default 2).
    max_nodes : int
        Maximum number of nodes in the output (default 50).
    max_chars : int
        Maximum character length of the rendered output (default 4000).
    """

    def __init__(
        self,
        max_hops: int = 2,
        max_nodes: int = 50,
        max_chars: int = 4000,
    ) -> None:
        self.max_hops = max_hops
        self.max_nodes = max_nodes
        self.max_chars = max_chars

    def serialize(self, graph: Graph, root_id: str) -> str:
        """Serialize a subgraph rooted at *root_id* into plain text.

        Performs a stable-ordered BFS (ordered by hop distance ascending, then
        node id ascending) up to *max_hops*. Applies budget trimming when the
        subgraph exceeds *max_nodes* or *max_chars* by dropping nodes in
        descending order of hop distance (most distant first), and among
        same-distance nodes by descending node id.

        Returns a plain-text context snapshot including each node's type+label
        and each edge's type/source/target.

        Raises
        ------
        ValueError
            If *root_id* is not found in the graph.
        """
        # Build lookup structures
        node_map: Dict[str, Node] = {node.id: node for node in graph.nodes}

        if root_id not in node_map:
            raise ValueError(f"Root node '{root_id}' not found in graph")

        # Build adjacency: for each node, collect neighbor node ids (undirected)
        adjacency: Dict[str, Set[str]] = {node.id: set() for node in graph.nodes}
        for edge in graph.edges:
            if edge.source in adjacency and edge.target in adjacency:
                adjacency[edge.source].add(edge.target)
                adjacency[edge.target].add(edge.source)

        # BFS: stable-ordered traversal
        visited: Dict[str, int] = {}  # node_id -> hop distance
        queue: deque[Tuple[str, int]] = deque()

        visited[root_id] = 0
        queue.append((root_id, 0))

        while queue:
            current_id, current_hop = queue.popleft()

            if current_hop >= self.max_hops:
                continue

            # Get neighbors sorted by node id for determinism
            neighbors = sorted(adjacency.get(current_id, set()))
            for neighbor_id in neighbors:
                if neighbor_id not in visited:
                    visited[neighbor_id] = current_hop + 1
                    queue.append((neighbor_id, current_hop + 1))

        # Collect nodes ordered by (hop_distance, node_id) ascending
        included_nodes: List[Tuple[int, str]] = sorted(
            (hop, nid) for nid, hop in visited.items()
        )

        # Budget trimming (considers full rendered output including edges)
        included_nodes = self._trim_to_budget(included_nodes, node_map, graph.edges)

        # Determine the final set of included node ids
        included_ids: Set[str] = {nid for _, nid in included_nodes}

        # Collect edges where both endpoints are included, sorted for determinism
        included_edges: List[Edge] = sorted(
            (
                edge
                for edge in graph.edges
                if edge.source in included_ids and edge.target in included_ids
            ),
            key=lambda e: (e.type.value, e.source, e.target, e.id),
        )

        # Render plain text
        return self._render(included_nodes, included_edges, node_map)

    def _trim_to_budget(
        self,
        nodes: List[Tuple[int, str]],
        node_map: Dict[str, Node],
        all_edges: List[Edge],
    ) -> List[Tuple[int, str]]:
        """Trim nodes to fit within max_nodes and max_chars budgets.

        Drops nodes in descending order of hop distance; among same-distance
        nodes, drops by descending node id (i.e., keeps lower node ids first).

        The node list is already sorted by (hop_distance asc, node_id asc),
        so trimming from the end naturally drops the most distant nodes first,
        and among same-distance nodes drops the highest node id first.
        """
        # First trim by max_nodes
        if len(nodes) > self.max_nodes:
            nodes = nodes[: self.max_nodes]

        # Now check character budget with full rendering
        while nodes:
            included_ids = {nid for _, nid in nodes}
            included_edges = sorted(
                (
                    edge
                    for edge in all_edges
                    if edge.source in included_ids and edge.target in included_ids
                ),
                key=lambda e: (e.type.value, e.source, e.target, e.id),
            )
            text = self._render(nodes, included_edges, node_map)
            if len(text) <= self.max_chars:
                break
            # Drop the last node (most distant hop, highest id within that hop)
            nodes = nodes[:-1]

        return nodes

    def _render(
        self,
        nodes: List[Tuple[int, str]],
        edges: List[Edge],
        node_map: Dict[str, Node],
    ) -> str:
        """Render the final plain-text context snapshot."""
        lines: List[str] = []
        lines.append("=== Context Snapshot ===")
        lines.append("")
        lines.append("Nodes:")
        for hop, nid in nodes:
            node = node_map[nid]
            lines.append(f"  [{node.type.value}] {node.label} (hop {hop})")
        lines.append("")
        lines.append("Edges:")
        if edges:
            for edge in edges:
                source_node = node_map[edge.source]
                target_node = node_map[edge.target]
                lines.append(
                    f"  {source_node.label} --[{edge.type.value}]--> {target_node.label}"
                )
        else:
            lines.append("  (none)")
        lines.append("")
        return "\n".join(lines)
