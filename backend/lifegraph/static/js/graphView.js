// LifeGraph Graph_View — Vis.js network rendering, per-type styling, selection, and error handling.
"use strict";

/**
 * Per-type node styling: every NodeType renders as a circle ("dot"). Types are
 * grouped into semantic families that share a color from the dark-surface
 * categorical palette (validated against the #1a1a19 panel surface). Label
 * font color is white for every type.
 */
const NODE_TYPE_STYLES = {
    // blue — Project
    Project:      { color: { background: "#3987e5", border: "#3987e5", highlight: { background: "#5598e7", border: "#3987e5" } }, shape: "dot", font: { color: "#ffffff" } },
    // aqua — Tool, Technology, Program
    Tool:         { color: { background: "#199e70", border: "#199e70", highlight: { background: "#6ac0a2", border: "#199e70" } }, shape: "dot", font: { color: "#ffffff" } },
    Technology:   { color: { background: "#199e70", border: "#199e70", highlight: { background: "#6ac0a2", border: "#199e70" } }, shape: "dot", font: { color: "#ffffff" } },
    Program:      { color: { background: "#199e70", border: "#199e70", highlight: { background: "#6ac0a2", border: "#199e70" } }, shape: "dot", font: { color: "#ffffff" } },
    // yellow — Goal, Habit
    Goal:         { color: { background: "#c98500", border: "#c98500", highlight: { background: "#dcb059", border: "#c98500" } }, shape: "dot", font: { color: "#ffffff" } },
    Habit:        { color: { background: "#c98500", border: "#c98500", highlight: { background: "#dcb059", border: "#c98500" } }, shape: "dot", font: { color: "#ffffff" } },
    // green — Skill, Topic
    Skill:        { color: { background: "#008300", border: "#008300", highlight: { background: "#59ae59", border: "#008300" } }, shape: "dot", font: { color: "#ffffff" } },
    Topic:        { color: { background: "#008300", border: "#008300", highlight: { background: "#59ae59", border: "#008300" } }, shape: "dot", font: { color: "#ffffff" } },
    // violet — Model, Hardware
    Model:        { color: { background: "#9085e9", border: "#9085e9", highlight: { background: "#b7b0f1", border: "#9085e9" } }, shape: "dot", font: { color: "#ffffff" } },
    Hardware:     { color: { background: "#9085e9", border: "#9085e9", highlight: { background: "#b7b0f1", border: "#9085e9" } }, shape: "dot", font: { color: "#ffffff" } },
    // red — Issue
    Issue:        { color: { background: "#e66767", border: "#e66767", highlight: { background: "#ef9c9c", border: "#e66767" } }, shape: "dot", font: { color: "#ffffff" } },
    // magenta — Person, Organization
    Person:       { color: { background: "#d55181", border: "#d55181", highlight: { background: "#e48ead", border: "#d55181" } }, shape: "dot", font: { color: "#ffffff" } },
    Organization: { color: { background: "#d55181", border: "#d55181", highlight: { background: "#e48ead", border: "#d55181" } }, shape: "dot", font: { color: "#ffffff" } },
    // orange — Event, Place, Recipe
    Event:        { color: { background: "#d95926", border: "#d95926", highlight: { background: "#e69372", border: "#d95926" } }, shape: "dot", font: { color: "#ffffff" } },
    Place:        { color: { background: "#d95926", border: "#d95926", highlight: { background: "#e69372", border: "#d95926" } }, shape: "dot", font: { color: "#ffffff" } },
    Recipe:       { color: { background: "#d95926", border: "#d95926", highlight: { background: "#e69372", border: "#d95926" } }, shape: "dot", font: { color: "#ffffff" } },
    // neutral — Resource
    Resource:     { color: { background: "#898781", border: "#898781", highlight: { background: "#b2b1ad", border: "#898781" } }, shape: "dot", font: { color: "#ffffff" } },
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
            font: style.font || { color: "#ffffff" },
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
            color: { color: "#383835", highlight: "#5598e7", inherit: false },
            font: { size: 10, align: "middle", color: "#898781" },
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
let _selectionCallback = null; // registered by app.js to drive the context panel

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
            nodeUpdates.push({ id: visNode.id, opacity: 1.0, font: { color: "#ffffff" } });
        } else {
            nodeUpdates.push({ id: visNode.id, opacity: 0.25, font: { color: "rgba(255,255,255,0.25)" } });
        }
    });
    _nodesDataSet.update(nodeUpdates);

    // Dim non-incident edges
    const edgeUpdates = [];
    _edgesDataSet.forEach(function (visEdge) {
        if (incidentEdgeIds.has(visEdge.id)) {
            edgeUpdates.push({ id: visEdge.id, color: { opacity: 1.0 }, font: { color: "#c3c2b7" } });
        } else {
            edgeUpdates.push({ id: visEdge.id, color: { opacity: 0.15 }, font: { color: "#383835" } });
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

/**
 * Register a callback invoked whenever node selection changes.
 * Called with the selected node ID (string) or null on deselect.
 *
 * @param {function(string|null): void} fn
 */
function setSelectionCallback(fn) {
    _selectionCallback = fn;
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
            color: { color: "#383835", highlight: "#5598e7", inherit: false },
            font: { color: "#898781" },
            width: 1.5,
        },
        nodes: {
            font: { size: 13, color: "#ffffff" },
        },
    };

    _network = new vis.Network(_container, { nodes: _nodesDataSet, edges: _edgesDataSet }, options);

    // Wire up click-to-select; notify context panel via registered callback
    _network.on("click", function (params) {
        var selectedId = (params.nodes && params.nodes.length > 0) ? params.nodes[0] : null;
        selectNode(selectedId);
        if (_selectionCallback) _selectionCallback(selectedId);
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
        nodeUpdates.push({ id: visNode.id, opacity: 1.0, font: { color: "#ffffff" } });
    });
    _nodesDataSet.update(nodeUpdates);

    var edgeUpdates = [];
    _edgesDataSet.forEach(function (visEdge) {
        edgeUpdates.push({ id: visEdge.id, color: { opacity: 1.0 }, font: { color: "#898781" } });
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
    module.exports = { transformGraphData, getNodeTypeStyle, NODE_TYPE_STYLES, setSelectionCallback };
}
