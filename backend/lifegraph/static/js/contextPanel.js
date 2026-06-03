// LifeGraph Context_Panel — node selection → context snapshot → clipboard.
//
// Usage:
//   var panel = new ContextPanel({ container: el, getNode: fn });
//   panel.clear();                    // show idle hint (no node selected)
//   panel.onNodeSelected(nodeId);     // called by app.js on graph click
"use strict";

/**
 * ContextPanel renders a context-snapshot UI for the selected node.
 *
 * @param {object} options
 * @param {HTMLElement} options.container - The DOM element to render into.
 * @param {function(string): object|null} options.getNode - Returns a node object by id (from local cache).
 */
function ContextPanel(options) {
    this.container = options.container;
    this.getNode = options.getNode || function () { return null; };
    this._currentNodeId = null;
}

/**
 * Show the idle hint (no node selected).
 */
ContextPanel.prototype.clear = function () {
    this._currentNodeId = null;
    this.container.innerHTML =
        '<p class="context-panel-hint">Click a node in the graph to copy its context snapshot.</p>';
};

/**
 * Called when the graph selection changes.
 * Passing null deselects and shows the idle hint.
 *
 * @param {string|null} nodeId
 */
ContextPanel.prototype.onNodeSelected = function (nodeId) {
    this._currentNodeId = nodeId;
    if (!nodeId) {
        this.clear();
        return;
    }
    var node = this.getNode(nodeId);
    this._render(node, nodeId);
};

/**
 * Render the panel for a selected node.
 *
 * @param {object|null} node - Node from local cache (may be null if cache is stale).
 * @param {string} nodeId
 */
ContextPanel.prototype._render = function (node, nodeId) {
    var label = node ? node.label : nodeId;
    var type = node ? node.type : "";

    var html = '<div class="context-panel">';

    // Node identity header
    html += '<div class="context-panel-header">';
    html += '<span class="context-panel-node-label">' + _cpEscape(label) + '</span>';
    if (type) {
        html += ' <em class="context-panel-node-type">(' + _cpEscape(type) + ')</em>';
    }
    html += '</div>';

    // Controls: hop depth + load button
    html += '<div class="context-panel-controls">';
    html += '<label for="context-hops" class="context-hops-label">Hops</label>';
    html += '<select id="context-hops" class="context-hops-select">';
    html += '<option value="1">1</option>';
    html += '<option value="2" selected>2</option>';
    html += '<option value="3">3</option>';
    html += '</select>';
    html += '<button type="button" class="btn-primary" id="context-load-btn">Load</button>';
    html += '</div>';

    // Status + snapshot output
    html += '<div id="context-status" class="context-status"></div>';
    html += '<textarea id="context-snapshot" class="context-snapshot" rows="8" readonly ' +
            'placeholder="Click Load to generate snapshot…"></textarea>';

    // Copy button
    html += '<div class="form-actions">';
    html += '<button type="button" class="btn-primary" id="context-copy-btn" disabled>Copy</button>';
    html += '</div>';

    html += '</div>';

    this.container.innerHTML = html;

    var loadBtn = document.getElementById("context-load-btn");
    var copyBtn = document.getElementById("context-copy-btn");
    var statusEl = document.getElementById("context-status");
    var snapshotEl = document.getElementById("context-snapshot");
    var hopsSelect = document.getElementById("context-hops");

    function loadSnapshot() {
        var hops = parseInt(hopsSelect.value, 10);
        statusEl.textContent = "Loading…";
        copyBtn.disabled = true;
        snapshotEl.value = "";

        fetchContext(nodeId, hops)
            .then(function (result) {
                statusEl.textContent = "";
                snapshotEl.value = result.snapshot || "";
                copyBtn.disabled = !snapshotEl.value;
            })
            .catch(function (err) {
                statusEl.textContent = "Error: " + err.message;
            });
    }

    loadBtn.addEventListener("click", loadSnapshot);

    copyBtn.addEventListener("click", function () {
        var text = snapshotEl.value;
        if (!text) return;

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text)
                .then(function () {
                    var orig = copyBtn.textContent;
                    copyBtn.textContent = "Copied!";
                    setTimeout(function () { copyBtn.textContent = orig; }, 1500);
                })
                .catch(function () {
                    // Clipboard API rejected (e.g. focus lost) — fall back to select
                    snapshotEl.select();
                });
        } else {
            // No Clipboard API — select so the user can Ctrl+C
            snapshotEl.select();
        }
    });
};

/** HTML-escape helper local to this module. */
function _cpEscape(str) {
    return String(str == null ? "" : str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
