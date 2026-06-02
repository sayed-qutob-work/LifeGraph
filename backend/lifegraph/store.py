"""Graph_Store — SQLite-backed persistence layer for LifeGraph.

Manages the nodes and edges tables, enforces schema constraints (type checks,
label length, foreign keys, unique identity index), and provides read/write
methods for the graph data.

Requirements: 5.1, 5.7, 5.8, 4.1, 4.2, 4.3, 4.5, 5.2, 5.3, 5.4, 6.1, 6.4, 9.1, 9.2, 9.3, 9.4, 9.5
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Callable

from lifegraph.domain import (
    EDGE_TYPE_VALUES,
    Edge,
    EdgeType,
    Graph,
    Node,
    NodeType,
    NODE_TYPE_VALUES,
    ProposedGraph,
    normalize,
)
from lifegraph.validation import (
    validate_attributes,
    validate_event_date,
    validate_storage_label,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StorageError(Exception):
    """Raised when the database file is invalid or cannot be used."""

    def __init__(self, message: str, path: str | None = None) -> None:
        self.path = path
        super().__init__(message)


class NodeNotFoundError(Exception):
    """Raised when a node operation targets a non-existent node id."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"Node not found: '{node_id}'")


class EdgeNotFoundError(Exception):
    """Raised when an edge operation targets a non-existent edge id."""

    def __init__(self, edge_id: str) -> None:
        self.edge_id = edge_id
        super().__init__(f"Edge not found: '{edge_id}'")


class ReferentialIntegrityError(Exception):
    """Raised when an edge references a non-existent node id (Req 5.4)."""

    def __init__(self, missing_id: str) -> None:
        self.missing_id = missing_id
        super().__init__(
            f"Referential integrity error: node '{missing_id}' does not exist"
        )


class SelfEdgeError(Exception):
    """Raised when an edge's source and target are the same node (Req 9.4)."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(
            f"Self-referential edges are not permitted: source and target are both '{node_id}'"
        )


# ---------------------------------------------------------------------------
# Default ID factory
# ---------------------------------------------------------------------------


def uuid4_str() -> str:
    """Generate a UUIDv4 string for use as a node/edge identifier."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

_NODE_TYPE_CHECK = ",".join(f"'{value}'" for value in sorted(NODE_TYPE_VALUES))
_EDGE_TYPE_CHECK = ",".join(f"'{value}'" for value in sorted(EDGE_TYPE_VALUES))

_CREATE_NODES_SQL = f"""\
CREATE TABLE IF NOT EXISTS nodes (
    id               TEXT PRIMARY KEY,
    type             TEXT NOT NULL CHECK (type IN ({_NODE_TYPE_CHECK})),
    label            TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 200),
    normalized_label TEXT NOT NULL,
    attributes       TEXT NOT NULL DEFAULT '{{}}',
    UNIQUE (normalized_label, type)
)
"""

_CREATE_EDGES_SQL = f"""\
CREATE TABLE IF NOT EXISTS edges (
    id        TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    type      TEXT NOT NULL CHECK (type IN ({_EDGE_TYPE_CHECK})),
    CHECK (source_id <> target_id)
)
"""

_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
"""

_SCHEMA_SQL = f"""\
PRAGMA foreign_keys = ON;

{_CREATE_NODES_SQL};
{_CREATE_EDGES_SQL};
{_INDEX_SQL}
"""


# ---------------------------------------------------------------------------
# GraphStore
# ---------------------------------------------------------------------------


class GraphStore:
    """SQLite-backed graph persistence with identity deduplication.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file. Created if absent.
    id_factory : Callable[[], str]
        Callable returning a unique string id. Defaults to uuid4_str.
        Inject a deterministic factory for testing.
    """

    def __init__(
        self,
        db_path: str,
        id_factory: Callable[[], str] = uuid4_str,
    ) -> None:
        self._db_path = db_path
        self._id_factory = id_factory
        self._conn: sqlite3.Connection | None = None
        self._initialize()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _initialize(self) -> None:
        """Open or create the database, applying schema if needed.

        - If the file does not exist, create it with the full schema (Req 5.7).
        - If the file exists but is not a valid SQLite database or lacks the
          expected tables, raise StorageError without overwriting (Req 5.8).
        """
        path = Path(self._db_path)
        file_exists = path.exists()

        if file_exists:
            # Validate the existing file is a usable SQLite database
            self._validate_existing_db(path)

        # Open connection (creates file if absent)
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions explicitly
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

        if not file_exists:
            # Fresh database — apply full schema
            self._conn.executescript(_SCHEMA_SQL)
        else:
            # Existing database — verify tables are present
            self._verify_tables()
            self._migrate_schema_if_needed()

    def _validate_existing_db(self, path: Path) -> None:
        """Check that an existing file is a valid SQLite database.

        Raises StorageError if the file cannot be opened as SQLite or is
        corrupted. Does NOT overwrite the file (Req 5.8).
        """
        try:
            conn = sqlite3.connect(str(path))
            # A quick integrity check — just reading the sqlite_master table
            conn.execute("SELECT count(*) FROM sqlite_master")
            conn.close()
        except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
            raise StorageError(
                f"Database file at '{path}' is not a valid SQLite database: {exc}",
                path=str(path),
            )

    def _verify_tables(self) -> None:
        """Verify the required tables exist in an existing database.

        Raises StorageError if the nodes or edges table is missing (Req 5.8).
        """
        assert self._conn is not None
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('nodes', 'edges')"
        )
        tables = {row[0] for row in cursor.fetchall()}
        missing = {"nodes", "edges"} - tables
        if missing:
            raise StorageError(
                f"Database file at '{self._db_path}' is missing required tables: "
                f"{', '.join(sorted(missing))}. The file will not be overwritten.",
                path=self._db_path,
            )

    def _migrate_schema_if_needed(self) -> None:
        """Rebuild tables when existing CHECK constraints lack current enum values."""
        assert self._conn is not None
        conn = self._conn

        if (
            self._table_allows_values("nodes", NODE_TYPE_VALUES)
            and self._table_allows_values("edges", EDGE_TYPE_VALUES)
        ):
            return

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        try:
            conn.execute("DROP INDEX IF EXISTS idx_nodes_type")
            conn.execute("DROP INDEX IF EXISTS idx_edges_source")
            conn.execute("DROP INDEX IF EXISTS idx_edges_target")

            conn.execute("ALTER TABLE edges RENAME TO edges_old")
            conn.execute("ALTER TABLE nodes RENAME TO nodes_old")

            conn.execute(_CREATE_NODES_SQL)
            conn.execute(_CREATE_EDGES_SQL)

            conn.execute(
                "INSERT INTO nodes (id, type, label, normalized_label, attributes) "
                "SELECT id, type, label, normalized_label, attributes FROM nodes_old"
            )
            conn.execute(
                "INSERT INTO edges (id, source_id, target_id, type) "
                "SELECT id, source_id, target_id, type FROM edges_old"
            )

            conn.execute("DROP TABLE edges_old")
            conn.execute("DROP TABLE nodes_old")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript(_INDEX_SQL)

    def _table_allows_values(self, table_name: str, values: frozenset[str]) -> bool:
        """Return true when a table's CREATE SQL mentions every enum value."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if row is None or not row["sql"]:
            return False
        create_sql = row["sql"]
        return all(f"'{value}'" in create_sql for value in values)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    @property
    def _connection(self) -> sqlite3.Connection:
        """Return the active connection, raising if closed."""
        if self._conn is None:
            raise StorageError("Database connection is closed.")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Row → domain object mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        """Convert a database row to a Node domain object."""
        attributes = json.loads(row["attributes"]) if row["attributes"] else {}
        return Node(
            id=row["id"],
            type=NodeType(row["type"]),
            label=row["label"],
            attributes=attributes,
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        """Convert a database row to an Edge domain object."""
        return Edge(
            id=row["id"],
            source=row["source_id"],
            target=row["target_id"],
            type=EdgeType(row["type"]),
        )

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_graph(self) -> Graph:
        """Return the full graph (all nodes and edges).

        Returns
        -------
        Graph
            A Graph containing all persisted nodes and edges.
        """
        conn = self._connection
        node_rows = conn.execute("SELECT * FROM nodes").fetchall()
        edge_rows = conn.execute("SELECT * FROM edges").fetchall()
        return Graph(
            nodes=[self._row_to_node(r) for r in node_rows],
            edges=[self._row_to_edge(r) for r in edge_rows],
        )

    def get_node(self, node_id: str) -> Node | None:
        """Fetch a single node by its identifier.

        Parameters
        ----------
        node_id : str
            The unique node identifier.

        Returns
        -------
        Node | None
            The node if found, otherwise None.
        """
        conn = self._connection
        row = conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def find_node(self, label: str, type: NodeType) -> Node | None:
        """Find a node by its normalized identity (label + type).

        Parameters
        ----------
        label : str
            The label to normalize and search for.
        type : NodeType
            The node type to match.

        Returns
        -------
        Node | None
            The matching node if found, otherwise None.
        """
        conn = self._connection
        normalized = normalize(label)
        row = conn.execute(
            "SELECT * FROM nodes WHERE normalized_label = ? AND type = ?",
            (normalized, type.value),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def incident_edges(self, node_id: str) -> list[Edge]:
        """Return all edges incident to a node (as source or target).

        Parameters
        ----------
        node_id : str
            The node identifier.

        Returns
        -------
        list[Edge]
            All edges where the node is either source or target.
        """
        conn = self._connection
        rows = conn.execute(
            "SELECT * FROM edges WHERE source_id = ? OR target_id = ?",
            (node_id, node_id),
        ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def nodes_by_type(self, types: set[NodeType]) -> list[Node]:
        """Return all nodes matching any of the given types.

        Parameters
        ----------
        types : set[NodeType]
            The set of node types to filter by.

        Returns
        -------
        list[Node]
            All nodes whose type is in the given set.
        """
        if not types:
            return []
        conn = self._connection
        placeholders = ",".join("?" for _ in types)
        type_values = [t.value for t in types]
        rows = conn.execute(
            f"SELECT * FROM nodes WHERE type IN ({placeholders})",
            type_values,
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        label: str,
        type: NodeType,
        attributes: dict[str, str] | None = None,
    ) -> Node:
        """Create a node or reuse an existing one with the same identity.

        Identity is determined by (normalized_label, type). If a node with the
        same identity already exists, it is returned unchanged (its id, stored
        label, and attributes are preserved). Otherwise a new node is created
        with a fresh UUID after validating label and attribute bounds.

        For Event nodes, if attributes contain a 'date' key, the date value is
        validated as a real YYYY-MM-DD calendar date.

        The entire operation runs in a single transaction.

        Parameters
        ----------
        label : str
            The node label (1–200 characters after validation).
        type : NodeType
            The node type from the Node_Type_Set.
        attributes : dict[str, str] | None
            Optional key-value attributes (≤50 entries, keys/values 1–255 chars).

        Returns
        -------
        Node
            The existing or newly created node.

        Raises
        ------
        LabelValidationError
            If the label is empty or exceeds 200 characters.
        AttributeValidationError
            If the attribute set violates bounds.
        DateValidationError
            If the node is an Event and has an invalid date attribute.
        """
        if attributes is None:
            attributes = {}

        conn = self._connection

        # Check for existing node with same identity first
        normalized_label = normalize(label)
        existing_row = conn.execute(
            "SELECT * FROM nodes WHERE normalized_label = ? AND type = ?",
            (normalized_label, type.value),
        ).fetchone()

        if existing_row is not None:
            # Reuse existing node — keep its id, stored label, and attributes
            return self._row_to_node(existing_row)

        # New node — validate before writing
        validate_storage_label(label)
        validate_attributes(attributes)

        # Validate Event date if applicable
        if type == NodeType.EVENT and "date" in attributes:
            validate_event_date(attributes["date"])

        node_id = self._id_factory()
        attrs_json = json.dumps(attributes)

        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT INTO nodes (id, type, label, normalized_label, attributes) "
                "VALUES (?, ?, ?, ?, ?)",
                (node_id, type.value, label, normalized_label, attrs_json),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return Node(
            id=node_id,
            type=type,
            label=label,
            attributes=attributes,
        )

    def update_node(
        self,
        node_id: str,
        *,
        label: str | None = None,
        type: NodeType | None = None,
        attributes: dict[str, str] | None = None,
    ) -> Node:
        """Update an existing node's label, type, and/or attributes.

        Only the provided (non-None) fields are updated. Validates new label
        (1–200 chars) if provided, validates new attributes if provided, and
        validates Event date if the resulting type is Event and attributes
        contain a 'date' key.

        The entire operation runs in a single transaction.

        Parameters
        ----------
        node_id : str
            The unique identifier of the node to update.
        label : str | None
            New label (validated 1–200 chars) or None to keep current.
        type : NodeType | None
            New type or None to keep current.
        attributes : dict[str, str] | None
            New attributes or None to keep current.

        Returns
        -------
        Node
            The updated node.

        Raises
        ------
        NodeNotFoundError
            If no node with the given id exists.
        LabelValidationError
            If the new label is empty or exceeds 200 characters.
        AttributeValidationError
            If the new attribute set violates bounds.
        DateValidationError
            If the resulting node is an Event and has an invalid date attribute.
        """
        conn = self._connection

        # Fetch existing node
        row = conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise NodeNotFoundError(node_id)

        # Determine final values
        current_node = self._row_to_node(row)
        new_label = label if label is not None else current_node.label
        new_type = type if type is not None else current_node.type
        new_attributes = attributes if attributes is not None else current_node.attributes

        # Validate new label if provided
        if label is not None:
            validate_storage_label(new_label)

        # Validate new attributes if provided
        if attributes is not None:
            validate_attributes(new_attributes)

        # Validate Event date if applicable
        if new_type == NodeType.EVENT and "date" in new_attributes:
            validate_event_date(new_attributes["date"])

        new_normalized = normalize(new_label)
        attrs_json = json.dumps(new_attributes)

        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE nodes SET type = ?, label = ?, normalized_label = ?, attributes = ? "
                "WHERE id = ?",
                (new_type.value, new_label, new_normalized, attrs_json, node_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return Node(
            id=node_id,
            type=new_type,
            label=new_label,
            attributes=new_attributes,
        )

    # ------------------------------------------------------------------
    # Edge write methods (Req 5.3, 5.4, 9.1, 9.2, 9.3, 9.4, 9.5)
    # ------------------------------------------------------------------

    def create_edge(self, source_id: str, target_id: str, type: EdgeType) -> Edge:
        """Create a new edge between two existing nodes.

        Validates that:
        - source and target are not the same node (no self-edges, Req 9.4)
        - source node exists in the nodes table (Req 5.4)
        - target node exists in the nodes table (Req 5.4)
        - edge type is a valid EdgeType (Req 9.3)

        The entire operation runs in a single transaction.

        Parameters
        ----------
        source_id : str
            The id of the source node (must exist).
        target_id : str
            The id of the target node (must exist, must differ from source_id).
        type : EdgeType
            The edge type from the Edge_Type_Set.

        Returns
        -------
        Edge
            The newly created edge.

        Raises
        ------
        SelfEdgeError
            If source_id == target_id.
        ReferentialIntegrityError
            If source or target node id is absent from the nodes table.
        """
        # Reject self-edges first (Req 9.4)
        if source_id == target_id:
            raise SelfEdgeError(source_id)

        conn = self._connection

        # Check referential integrity (Req 5.4)
        source_row = conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (source_id,)
        ).fetchone()
        if source_row is None:
            raise ReferentialIntegrityError(source_id)

        target_row = conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (target_id,)
        ).fetchone()
        if target_row is None:
            raise ReferentialIntegrityError(target_id)

        edge_id = self._id_factory()

        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
                (edge_id, source_id, target_id, type.value),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return Edge(
            id=edge_id,
            source=source_id,
            target=target_id,
            type=type,
        )

    def update_edge(self, edge_id: str, type: EdgeType) -> Edge:
        """Update an existing edge's type.

        The entire operation runs in a single transaction.

        Parameters
        ----------
        edge_id : str
            The unique identifier of the edge to update.
        type : EdgeType
            The new edge type from the Edge_Type_Set.

        Returns
        -------
        Edge
            The updated edge.

        Raises
        ------
        EdgeNotFoundError
            If no edge with the given id exists.
        """
        conn = self._connection

        # Fetch existing edge
        row = conn.execute(
            "SELECT * FROM edges WHERE id = ?", (edge_id,)
        ).fetchone()
        if row is None:
            raise EdgeNotFoundError(edge_id)

        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE edges SET type = ? WHERE id = ?",
                (type.value, edge_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return Edge(
            id=edge_id,
            source=row["source_id"],
            target=row["target_id"],
            type=type,
        )

    def delete_node(self, node_id: str) -> list[str]:
        """Delete a node and all its incident edges (cascade delete).

        Collects the ids of all incident edges first, then deletes the node.
        The ON DELETE CASCADE constraint in the schema removes the edges
        automatically within the same transaction.

        Parameters
        ----------
        node_id : str
            The unique identifier of the node to delete.

        Returns
        -------
        list[str]
            The ids of all edges that were removed (incident to the deleted node).

        Raises
        ------
        NodeNotFoundError
            If no node with the given id exists.
        """
        conn = self._connection

        # Verify node exists
        row = conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise NodeNotFoundError(node_id)

        # Collect incident edge ids before deletion
        edge_rows = conn.execute(
            "SELECT id FROM edges WHERE source_id = ? OR target_id = ?",
            (node_id, node_id),
        ).fetchall()
        deleted_edge_ids = [r["id"] for r in edge_rows]

        # Delete the node; ON DELETE CASCADE removes incident edges
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return deleted_edge_ids

    def delete_edge(self, edge_id: str) -> None:
        """Delete an edge, keeping its source and target nodes intact.

        The entire operation runs in a single transaction.

        Parameters
        ----------
        edge_id : str
            The unique identifier of the edge to delete.

        Raises
        ------
        EdgeNotFoundError
            If no edge with the given id exists.
        """
        conn = self._connection

        # Verify edge exists
        row = conn.execute(
            "SELECT id FROM edges WHERE id = ?", (edge_id,)
        ).fetchone()
        if row is None:
            raise EdgeNotFoundError(edge_id)

        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------
    # Proposal application (Req 3.6, 3.7, 4.4)
    # ------------------------------------------------------------------

    def apply_proposal(self, proposal: ProposedGraph) -> Graph:
        """Persist a confirmed proposal: resolve/create nodes, then create edges.

        For each ProposedNode, the method calls upsert_node which handles
        deduplication by (normalized_label, type) identity — reusing an
        existing node when one matches, or creating a new one otherwise.

        For each ProposedEdge, the method resolves the source and target by
        their (label, type) identity (looking up or creating the endpoint
        nodes first), then creates the edge.

        The entire operation runs in a single transaction. A rejected or
        never-confirmed proposal simply never calls this method, so no write
        occurs (Req 3.7).

        Parameters
        ----------
        proposal : ProposedGraph
            The confirmed proposal containing proposed nodes and edges.

        Returns
        -------
        Graph
            A Graph containing all nodes that were resolved/created and all
            edges that were created during this proposal application.
        """
        conn = self._connection
        result_nodes: list[Node] = []
        result_edges: list[Edge] = []

        conn.execute("BEGIN")
        try:
            # Phase 1: Resolve or create all proposed nodes
            for proposed_node in proposal.nodes:
                node = self._upsert_node_in_txn(
                    conn,
                    proposed_node.label,
                    proposed_node.type,
                    proposed_node.attributes,
                )
                result_nodes.append(node)

            # Phase 2: Resolve edge endpoints and create edges
            for proposed_edge in proposal.edges:
                # Resolve source endpoint by (label, type) identity
                source_node = self._resolve_or_create_endpoint(
                    conn, proposed_edge.source_label, proposed_edge.source_type
                )
                # Resolve target endpoint by (label, type) identity
                target_node = self._resolve_or_create_endpoint(
                    conn, proposed_edge.target_label, proposed_edge.target_type
                )

                # Create the edge (skip self-edges silently — they can't
                # occur from valid proposals but guard defensively)
                if source_node.id == target_node.id:
                    continue

                edge_id = self._id_factory()
                conn.execute(
                    "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
                    (edge_id, source_node.id, target_node.id, proposed_edge.type.value),
                )
                result_edges.append(
                    Edge(
                        id=edge_id,
                        source=source_node.id,
                        target=target_node.id,
                        type=proposed_edge.type,
                    )
                )

                # Track endpoint nodes in result if not already present
                if not any(n.id == source_node.id for n in result_nodes):
                    result_nodes.append(source_node)
                if not any(n.id == target_node.id for n in result_nodes):
                    result_nodes.append(target_node)

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return Graph(nodes=result_nodes, edges=result_edges)

    def _upsert_node_in_txn(
        self,
        conn: sqlite3.Connection,
        label: str,
        type: NodeType,
        attributes: dict[str, str],
    ) -> Node:
        """Upsert a node within an existing transaction (no BEGIN/COMMIT).

        If a node with the same (normalized_label, type) exists, reuse it.
        Otherwise validate and create a new node.
        """
        normalized_label = normalize(label)
        existing_row = conn.execute(
            "SELECT * FROM nodes WHERE normalized_label = ? AND type = ?",
            (normalized_label, type.value),
        ).fetchone()

        if existing_row is not None:
            return self._row_to_node(existing_row)

        # New node — validate before writing
        validate_storage_label(label)
        validate_attributes(attributes)

        # Validate Event date if applicable
        if type == NodeType.EVENT and "date" in attributes:
            validate_event_date(attributes["date"])

        node_id = self._id_factory()
        attrs_json = json.dumps(attributes)

        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, type.value, label, normalized_label, attrs_json),
        )

        return Node(
            id=node_id,
            type=type,
            label=label,
            attributes=attributes,
        )

    def _resolve_or_create_endpoint(
        self,
        conn: sqlite3.Connection,
        label: str,
        type: NodeType,
    ) -> Node:
        """Resolve an edge endpoint by (label, type) identity within a transaction.

        If a node with the same identity exists, return it. Otherwise create
        it with empty attributes (Req 4.4).
        """
        return self._upsert_node_in_txn(conn, label, type, {})
