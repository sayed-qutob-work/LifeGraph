// LifeGraph Graph_Editor — node/edge create/edit/delete forms with client-side
// validation mirroring backend rules and high-degree delete confirmation gate.
//
// Requirements: 8.3, 8.4, 8.5, 8.7, 8.8, 9.3, 9.4
"use strict";

/**
 * The fixed set of allowed node types (Node_Type_Set).
 */
const NODE_TYPES = Object.freeze([
    "Skill", "Goal", "Habit", "Project", "Event", "Person", "Resource"
]);

/**
 * The fixed set of allowed edge types (Edge_Type_Set).
 */
const EDGE_TYPES = Object.freeze([
    "requires", "supports", "conflicts_with", "motivated_by",
    "leads_to", "part_of", "owned_by", "blocks", "related_to"
]);

/**
 * Threshold for the high-degree delete confirmation gate (Req 8.7).
 */
const DELETE_EDGE_THRESHOLD = 5;

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

/**
 * Validate a node label (trimmed, 1-100 chars).
 * Returns { valid: true, trimmed: string } or { valid: false, error: string }.
 */
function validateNodeLabel(label) {
    const trimmed = (label || "").trim();
    if (trimmed.length === 0) {
        return { valid: false, error: "A label is required.", trimmed };
    }
    if (trimmed.length > 100) {
        return {
            valid: false,
            error: "Label must not exceed 100 characters (currently " + trimmed.length + ").",
            trimmed
        };
    }
    return { valid: true, trimmed };
}

/**
 * Validate a node type against the Node_Type_Set.
 * Returns { valid: true } or { valid: false, error: string }.
 */
function validateNodeType(type) {
    if (!NODE_TYPES.includes(type)) {
        return {
            valid: false,
            error: "Invalid node type. Allowed types: " + NODE_TYPES.join(", ") + "."
        };
    }
    return { valid: true };
}

/**
 * Validate an edge type against the Edge_Type_Set.
 * Returns { valid: true } or { valid: false, error: string }.
 */
function validateEdgeType(type) {
    if (!EDGE_TYPES.includes(type)) {
        return {
            valid: false,
            error: "Invalid edge type. Allowed types: " + EDGE_TYPES.join(", ") + "."
        };
    }
    return { valid: true };
}

/**
 * Validate that source and target are not the same node (no self-edges, Req 9.4).
 * Returns { valid: true } or { valid: false, error: string }.
 */
function validateNoSelfEdge(sourceId, targetId) {
    if (sourceId === targetId) {
        return { valid: false, error: "Self-referential edges are not permitted." };
    }
    return { valid: true };
}

// ---------------------------------------------------------------------------
// Graph Editor class
// ---------------------------------------------------------------------------

/**
 * GraphEditor manages node/edge create/edit/delete forms.
 *
 * @param {object} options
 * @param {HTMLElement} options.container - The DOM element to render forms into.
 * @param {function} options.onGraphChanged - Callback invoked after a successful mutation.
 * @param {function} [options.getNodes] - Returns current nodes array for edge source/target selection.
 * @param {function} [options.confirmDialog] - Custom confirm dialog (defaults to window.confirm).
 */
function GraphEditor(options) {
    this.container = options.container;
    this.onGraphChanged = options.onGraphChanged || function () {};
    this.getNodes = options.getNodes || function () { return []; };
    this.confirmDialog = options.confirmDialog || function (msg) { return window.confirm(msg); };

    // Track current mode for the editor
    this._mode = null; // "create-node", "edit-node", "create-edge", "edit-edge"
    this._editTarget = null; // node or edge being edited
}

// ---------------------------------------------------------------------------
// Node forms
// ---------------------------------------------------------------------------

/**
 * Show the create-node form.
 */
GraphEditor.prototype.showCreateNodeForm = function (prefill) {
    this._mode = "create-node";
    this._editTarget = null;
    this._renderNodeForm(prefill || { label: "", type: "" });
};

/**
 * Show the edit-node form for an existing node.
 */
GraphEditor.prototype.showEditNodeForm = function (node) {
    this._mode = "edit-node";
    this._editTarget = node;
    this._renderNodeForm({ label: node.label, type: node.type });
};

/**
 * Render the node form (create or edit) into the container.
 * Preserves submitted values on validation rejection (Req 8.3, 8.4, 8.5).
 */
GraphEditor.prototype._renderNodeForm = function (values) {
    var self = this;
    var isEdit = this._mode === "edit-node";
    var title = isEdit ? "Edit Node" : "Create Node";

    var html = '<form class="graph-editor-form" id="node-form">';
    html += '<h3>' + title + '</h3>';
    html += '<div class="form-group">';
    html += '<label for="node-label">Label</label>';
    html += '<input type="text" id="node-label" name="label" maxlength="100" value="' + escapeAttr(values.label) + '" />';
    html += '</div>';
    html += '<div class="form-group">';
    html += '<label for="node-type">Type</label>';
    html += '<select id="node-type" name="type">';
    html += '<option value="">-- Select type --</option>';
    for (var i = 0; i < NODE_TYPES.length; i++) {
        var selected = (values.type === NODE_TYPES[i]) ? ' selected' : '';
        html += '<option value="' + NODE_TYPES[i] + '"' + selected + '>' + NODE_TYPES[i] + '</option>';
    }
    html += '</select>';
    html += '</div>';
    html += '<div class="form-error" id="node-form-error"></div>';
    html += '<div class="form-actions">';
    html += '<button type="submit" class="btn-primary">' + (isEdit ? 'Save' : 'Create') + '</button>';
    html += '<button type="button" class="btn-secondary" id="node-form-cancel">Cancel</button>';
    html += '</div>';
    html += '</form>';

    this.container.innerHTML = html;

    var form = document.getElementById("node-form");
    var errorDiv = document.getElementById("node-form-error");

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        var labelInput = document.getElementById("node-label");
        var typeSelect = document.getElementById("node-type");
        var labelVal = labelInput.value;
        var typeVal = typeSelect.value;

        // Client-side validation
        var labelResult = validateNodeLabel(labelVal);
        if (!labelResult.valid) {
            errorDiv.textContent = labelResult.error;
            return; // Preserve submitted values (Req 8.4, 8.5)
        }

        var typeResult = validateNodeType(typeVal);
        if (!typeResult.valid) {
            errorDiv.textContent = typeResult.error;
            return; // Preserve submitted values (Req 8.3)
        }

        errorDiv.textContent = "";

        var data = { label: labelResult.trimmed, type: typeVal };

        if (isEdit) {
            updateNode(self._editTarget.id, data)
                .then(function () { self.onGraphChanged(); })
                .catch(function (err) { errorDiv.textContent = err.message; });
        } else {
            createNode(data)
                .then(function () { self.onGraphChanged(); })
                .catch(function (err) { errorDiv.textContent = err.message; });
        }
    });

    document.getElementById("node-form-cancel").addEventListener("click", function () {
        self.container.innerHTML = "";
        self._mode = null;
    });
};

// ---------------------------------------------------------------------------
// Node delete with high-degree confirmation gate
// ---------------------------------------------------------------------------

/**
 * Delete a node with the high-degree confirmation gate (Req 8.7, 8.8).
 *
 * Calls getNodeEdges(id) to get the edge count. If count >= 5, shows a
 * confirmation dialog. If the user cancels, no DELETE is issued and the
 * node and edges remain unchanged.
 *
 * @param {string} nodeId - The id of the node to delete.
 * @returns {Promise<boolean>} Resolves to true if deleted, false if cancelled.
 */
GraphEditor.prototype.deleteNodeWithConfirmation = function (nodeId) {
    var self = this;

    return getNodeEdges(nodeId).then(function (result) {
        var edgeCount = result.count;

        if (edgeCount >= DELETE_EDGE_THRESHOLD) {
            // High-degree node: require confirmation (Req 8.7)
            var message = "This node has " + edgeCount + " connected edge" +
                (edgeCount === 1 ? "" : "s") +
                " that will be removed. Are you sure you want to delete it?";

            if (!self.confirmDialog(message)) {
                // User cancelled — no DELETE issued (Req 8.8)
                return false;
            }
        }

        // Proceed with deletion
        return deleteNode(nodeId).then(function () {
            self.onGraphChanged();
            return true;
        });
    });
};

// ---------------------------------------------------------------------------
// Edge forms
// ---------------------------------------------------------------------------

/**
 * Show the create-edge form.
 */
GraphEditor.prototype.showCreateEdgeForm = function (prefill) {
    this._mode = "create-edge";
    this._editTarget = null;
    this._renderEdgeForm(prefill || { source: "", target: "", type: "" });
};

/**
 * Show the edit-edge form for an existing edge.
 */
GraphEditor.prototype.showEditEdgeForm = function (edge) {
    this._mode = "edit-edge";
    this._editTarget = edge;
    this._renderEdgeForm({ source: edge.source, target: edge.target, type: edge.type });
};

/**
 * Render the edge form (create or edit) into the container.
 * Preserves submitted values on validation rejection (Req 9.3, 9.4).
 */
GraphEditor.prototype._renderEdgeForm = function (values) {
    var self = this;
    var isEdit = this._mode === "edit-edge";
    var title = isEdit ? "Edit Edge" : "Create Edge";
    var nodes = this.getNodes();

    var html = '<form class="graph-editor-form" id="edge-form">';
    html += '<h3>' + title + '</h3>';

    if (!isEdit) {
        // Source node selector
        html += '<div class="form-group">';
        html += '<label for="edge-source">Source Node</label>';
        html += '<select id="edge-source" name="source">';
        html += '<option value="">-- Select source --</option>';
        for (var i = 0; i < nodes.length; i++) {
            var srcSelected = (values.source === nodes[i].id) ? ' selected' : '';
            html += '<option value="' + escapeAttr(nodes[i].id) + '"' + srcSelected + '>' +
                escapeHtml(nodes[i].label) + ' (' + nodes[i].type + ')</option>';
        }
        html += '</select>';
        html += '</div>';

        // Target node selector
        html += '<div class="form-group">';
        html += '<label for="edge-target">Target Node</label>';
        html += '<select id="edge-target" name="target">';
        html += '<option value="">-- Select target --</option>';
        for (var j = 0; j < nodes.length; j++) {
            var tgtSelected = (values.target === nodes[j].id) ? ' selected' : '';
            html += '<option value="' + escapeAttr(nodes[j].id) + '"' + tgtSelected + '>' +
                escapeHtml(nodes[j].label) + ' (' + nodes[j].type + ')</option>';
        }
        html += '</select>';
        html += '</div>';
    }

    // Edge type selector
    html += '<div class="form-group">';
    html += '<label for="edge-type">Type</label>';
    html += '<select id="edge-type" name="type">';
    html += '<option value="">-- Select type --</option>';
    for (var k = 0; k < EDGE_TYPES.length; k++) {
        var typeSelected = (values.type === EDGE_TYPES[k]) ? ' selected' : '';
        html += '<option value="' + EDGE_TYPES[k] + '"' + typeSelected + '>' + EDGE_TYPES[k] + '</option>';
    }
    html += '</select>';
    html += '</div>';

    html += '<div class="form-error" id="edge-form-error"></div>';
    html += '<div class="form-actions">';
    html += '<button type="submit" class="btn-primary">' + (isEdit ? 'Save' : 'Create') + '</button>';
    html += '<button type="button" class="btn-secondary" id="edge-form-cancel">Cancel</button>';
    html += '</div>';
    html += '</form>';

    this.container.innerHTML = html;

    var form = document.getElementById("edge-form");
    var errorDiv = document.getElementById("edge-form-error");

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        var typeSelect = document.getElementById("edge-type");
        var typeVal = typeSelect.value;

        // Validate edge type (Req 9.3)
        var typeResult = validateEdgeType(typeVal);
        if (!typeResult.valid) {
            errorDiv.textContent = typeResult.error;
            return; // Preserve submitted values
        }

        if (isEdit) {
            // Edit: only update the type
            errorDiv.textContent = "";
            updateEdge(self._editTarget.id, { type: typeVal })
                .then(function () { self.onGraphChanged(); })
                .catch(function (err) { errorDiv.textContent = err.message; });
        } else {
            // Create: validate source, target, and no self-edge
            var sourceSelect = document.getElementById("edge-source");
            var targetSelect = document.getElementById("edge-target");
            var sourceVal = sourceSelect.value;
            var targetVal = targetSelect.value;

            if (!sourceVal) {
                errorDiv.textContent = "Please select a source node.";
                return;
            }
            if (!targetVal) {
                errorDiv.textContent = "Please select a target node.";
                return;
            }

            // No self-edges (Req 9.4)
            var selfEdgeResult = validateNoSelfEdge(sourceVal, targetVal);
            if (!selfEdgeResult.valid) {
                errorDiv.textContent = selfEdgeResult.error;
                return; // Preserve submitted values
            }

            errorDiv.textContent = "";
            createEdge({ source: sourceVal, target: targetVal, type: typeVal })
                .then(function () { self.onGraphChanged(); })
                .catch(function (err) { errorDiv.textContent = err.message; });
        }
    });

    document.getElementById("edge-form-cancel").addEventListener("click", function () {
        self.container.innerHTML = "";
        self._mode = null;
    });
};

// ---------------------------------------------------------------------------
// Edge delete
// ---------------------------------------------------------------------------

/**
 * Delete an edge (no confirmation gate needed for edges).
 *
 * @param {string} edgeId - The id of the edge to delete.
 * @returns {Promise<boolean>} Resolves to true when deleted.
 */
GraphEditor.prototype.deleteEdge = function (edgeId) {
    var self = this;
    return deleteEdge(edgeId).then(function () {
        self.onGraphChanged();
        return true;
    });
};

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/**
 * Escape a string for use in an HTML attribute value.
 */
function escapeAttr(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

/**
 * Escape a string for use in HTML text content.
 */
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
