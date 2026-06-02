// LifeGraph Graph_View — Vis.js network rendering, per-type styling, selection, and error handling.
"use strict";

/**
 * Per-type node styling: each NodeType gets a distinct color and shape.
 * This mapping is injective — no two types share the same (color, shape) pair.
 */
const NODE_TYPE_STYLES = {
    Skill:        { color: { background: "#2E7D32", border: "#1B5E20", highlight: { background: "#66BB6A", border: "#1B5E20" } }, shape: "dot" },
    Goal:         { color: { background: "#F57C00", border: "#E65100", highlight: { background: "#FFB74D", border: "#E65100" } }, shape: "star" },
    Habit:        { color: { background: "#7B1FA2", border: "#4A148C", highlight: { background: "#BA68C8", border: "#4A148C" } }, shape: "diamond" },
    Project:      { color: { background: "#1976D2", border: "#0D47A1", highlight: { background: "#64B5F6", border: "#0D47A1" } }, shape: "square" },
    Event:        { color: { background: "#C62828", border: "#8E0000", highlight: { background: "#EF5350", border: "#8E0000" } }, shape: "triangle" },
    Person:       { color: { background: "#00838F", border: "#005662", highlight: { background: "#4DD0E1", border: "#005662" } }, shape: "ellipse" },
    Organization: { color: { background: "#455A64", border: "#263238", highlight: { background: "#90A4AE", border: "#263238" } }, shape: "database" },
    Program:      { color: { background: "#6D4C41", border: "#3E2723", highlight: { background: "#A1887F", border: "#3E2723" } }, shape: "hexagon" },
    Tool:         { color: { background: "#00796B", border: "#004D40", highlight: { background: "#4DB6AC", border: "#004D40" } }, shape: "box" },
    Technology:   { color: { background: "#5E35B1", border: "#311B92", highlight: { background: "#9575CD", border: "#311B92" } }, shape: "box" },
    Model:        { color: { background: "#AD1457", border: "#880E4F", highlight: { background: "#F06292", border: "#880E4F" } }, shape: "dot" },
    Hardware:     { color: { background: "#546E7A", border: "#29434E", highlight: { background: "#B0BEC5", border: "#29434E" } }, shape: "box" },
    Topic:        { color: { background: "#558B2F", border: "#33691E", highlight: { background: "#AED581", border: "#33691E" } }, shape: "ellipse" },
    Recipe:       { color: { background: "#D84315", border: "#BF360C", highlight: { background: "#FF8A65", border: "#BF360C" } }, shape: "diamond" },
    Issue:        { color: { background: "#B71C1C", border: "#7F0000", highlight: { background: "#E57373", border: "#7F0000" } }, shape: "triangleDown" },
    Place:        { color: { background: "#0277BD", border: "#01579B", highlight: { background: "#4FC3F7", border: "#01579B" } }, shape: "triangle" },
    Resource:     { color: { background: "#616161", border: "#424242", highlight: { background: "#BDBDBD", border: "#424242" } }, shape: "box" },
};

/**
 * Transform backend graph data into Vis.js DataSet-compatible arrays.
 * Each node gets its label and per-type styling.
 * Each edge gets a label equal to its edge type.
 *
 * @param {{ nodes: Array, edges: Array }} graphData - The graph from GET /api/graph
 * @returns {{ visNodes: Array, visEdges: Array }}
 */
function transformGraphData(graphData) {
    const visNodes = (graphData.nodes || []).map(function (node) {
        const style = NODE_TYPE_STYLES[node.type] || {};
        return {
            id: node.id,
            label: node.label,
            shape: style.shape || "dot",
            color: style.color || {},
            title: node.type + ": " + node.label,
            nodeType: node.type,
        };
    });

    const visEdges = (graphData.edges || []).map(function (edge) {
        return {
            id: edge.id,
            from: edge.source,
            to: edge.target,
            label: edge.type,
            arrows: "to",
            font: { size: 10, align: "middle" },
        };
    });

    return { visNodes: visNodes, visEdges: visEdges };
}

/**
 * Get the style mapping for a given node type.
 * Exported for testing (Property 17).
 *
 * @param {string} nodeType - A value from the Node_Type_Set
 * @returns {object|undefined} The style object or undefined if unknown type
 */
function getNodeTypeStyle(nodeType) {
    return NODE_TYPE_STYLES[nodeType];
}

// ---------------------------------------------------------------------------
// Graph_View state
// ---------------------------------------------------------------------------

let _network = null;
let _nodesDataSet = null;
let _edgesDataSet = null;
let _container = null;
let _selectedNodeId = null;
let _graphData = null; // last fetched raw graph data

/**
 * Initialize the Graph_View: create the Vis.js network in the given container,
 * fetch graph data, and render.
 *
 * @param {HTMLElement|string} container - DOM element or element ID for the network
 * @returns {Promise<void>}
 */
async function initGraphView(container) {
    if (typeof container === "string") {
        container = document.getElementById(container);
    }
    _container = container;

    // Clear any previous error
    _clearError();

    try {
        const graphData = await fetchGraph();
        _graphData = graphData;
        _renderNetwork(graphData);
    } catch (err) {
        _showError(err.message || "Failed to load graph data");
    }
}

/**
 * Refresh the graph view by re-fetching data and updating the network.
 * Called after create/edit/delete operations to reflect store changes (Req 7.5).
 *
 * @returns {Promise<void>}
 */
async function refreshGraphView() {
    _clearError();

    try {
        const graphData = await fetchGraph();
        _graphData = graphData;
        _updateNetwork(graphData);
    } catch (err) {
        _showError(err.message || "Failed to refresh graph data");
    }
}

/**
 * Render the graph with a filtered dataset (used by Search_Filter).
 * Does not fetch from the API — uses the provided data directly.
 *
 * @param {{ nodes: Array, edges: Array }} graphData - Filtered graph data
 */
function renderFilteredGraph(graphData) {
    _clearError();
    _graphData = graphData;
    _updateNetwork(graphData);
}

/**
 * Handle node selection: highlight the selected node and its incident edges.
 * Called programmatically or via Vis.js click event.
 *
 * @param {string|null} nodeId - The node ID to select, or null to deselect
 */
function selectNode(nodeId) {
    _selectedNodeId = nodeId;

    if (!_nodesDataSet || !_edgesDataSet || !_graphData) {
        return;
    }

    if (!nodeId) {
        // Deselect: restore all nodes and edges to default styling
        _resetHighlighting();
        return;
    }

    // Find incident edge IDs
    const incidentEdgeIds = new Set();
    (_graphData.edges || []).forEach(function (edge) {
        if (edge.source === nodeId || edge.target === nodeId) {
            incidentEdgeIds.add(edge.id);
        }
    });

    // Dim non-selected nodes
    const nodeUpdates = [];
    _nodesDataSet.forEach(function (visNode) {
        if (visNode.id === nodeId) {
            nodeUpdates.push({ id: visNode.id, opacity: 1.0, font: { color: "#000" } });
        } else {
            nodeUpdates.push({ id: visNode.id, opacity: 0.3, font: { color: "#aaa" } });
        }
    });
    _nodesDataSet.update(nodeUpdates);

    // Dim non-incident edges
    const edgeUpdates = [];
    _edgesDataSet.forEach(function (visEdge) {
        if (incidentEdgeIds.has(visEdge.id)) {
            edgeUpdates.push({ id: visEdge.id, color: { opacity: 1.0 }, font: { color: "#333" } });
        } else {
            edgeUpdates.push({ id: visEdge.id, color: { opacity: 0.15 }, font: { color: "#ccc" } });
        }
    });
    _edgesDataSet.update(edgeUpdates);
}

/**
 * Get the currently selected node ID.
 * @returns {string|null}
 */
function getSelectedNodeId() {
    return _selectedNodeId;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Create the Vis.js network from scratch.
 */
function _renderNetwork(graphData) {
    const transformed = transformGraphData(graphData);

    _nodesDataSet = new vis.DataSet(transformed.visNodes);
    _edgesDataSet = new vis.DataSet(transformed.visEdges);

    var options = {
        interaction: {
            hover: true,
            selectConnectedEdges: false,
        },
        physics: {
            stabilization: { iterations: 150 },
        },
        edges: {
            smooth: { type: "continuous" },
        },
        nodes: {
            font: { size: 14 },
        },
    };

    _network = new vis.Network(_container, { nodes: _nodesDataSet, edges: _edgesDataSet }, options);

    // Wire up click-to-select
    _network.on("click", function (params) {
        if (params.nodes && params.nodes.length > 0) {
            selectNode(params.nodes[0]);
        } else {
            selectNode(null);
        }
    });
}

/**
 * Update an existing network with new data (avoids full re-creation).
 */
function _updateNetwork(graphData) {
    if (!_network) {
        // Network not yet created — do a full render
        _renderNetwork(graphData);
        return;
    }

    var transformed = transformGraphData(graphData);

    _nodesDataSet.clear();
    _nodesDataSet.add(transformed.visNodes);

    _edgesDataSet.clear();
    _edgesDataSet.add(transformed.visEdges);

    _selectedNodeId = null;
}

/**
 * Reset all highlighting to default (deselect).
 */
function _resetHighlighting() {
    if (!_nodesDataSet || !_edgesDataSet) return;

    var nodeUpdates = [];
    _nodesDataSet.forEach(function (visNode) {
        nodeUpdates.push({ id: visNode.id, opacity: 1.0, font: { color: "#343434" } });
    });
    _nodesDataSet.update(nodeUpdates);

    var edgeUpdates = [];
    _edgesDataSet.forEach(function (visEdge) {
        edgeUpdates.push({ id: visEdge.id, color: { opacity: 1.0 }, font: { color: "#343434" } });
    });
    _edgesDataSet.update(edgeUpdates);
}

/**
 * Show an error banner and ensure no partial network is displayed (Req 7.9).
 */
function _showError(message) {
    // Destroy any existing network to prevent partial display
    if (_network) {
        _network.destroy();
        _network = null;
    }
    _nodesDataSet = null;
    _edgesDataSet = null;
    _graphData = null;

    // Clear the container
    if (_container) {
        _container.innerHTML = "";
    }

    // Show error banner
    var errorDiv = document.createElement("div");
    errorDiv.className = "error-banner";
    errorDiv.setAttribute("role", "alert");
    errorDiv.textContent = "Error: " + message;
    if (_container) {
        _container.appendChild(errorDiv);
    }
}

/**
 * Clear any error banner from the container.
 */
function _clearError() {
    if (_container) {
        var existing = _container.querySelector(".error-banner");
        if (existing) {
            existing.remove();
        }
    }
}

// Module exports for testing (Node.js / Vitest environment)
if (typeof module !== "undefined" && module.exports) {
    module.exports = { transformGraphData, getNodeTypeStyle, NODE_TYPE_STYLES };
}
