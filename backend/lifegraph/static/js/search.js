// LifeGraph Search_Filter UI
// Composes type filters and a label search term into GET /api/search,
// hands results to Graph_View, and restores the full graph when cleared.
//
// Requirements: 13.1, 13.2, 13.3, 13.4, 13.5
"use strict";

/**
 * The fixed set of allowed node types for filter checkboxes.
 */
var SEARCH_NODE_TYPES = Object.freeze([
    "Skill", "Goal", "Habit", "Project", "Event", "Person", "Resource"
]);

// ---------------------------------------------------------------------------
// SearchFilter class
// ---------------------------------------------------------------------------

/**
 * SearchFilter manages the search/filter UI panel.
 *
 * @param {object} options
 * @param {HTMLElement} options.container - The DOM element to render the search UI into.
 */
function SearchFilter(options) {
    this.container = options.container;
    this._activeTypes = [];
    this._activeTerm = "";
    this._isFiltered = false;
}

/**
 * Initialize the search filter UI by rendering the form.
 */
SearchFilter.prototype.init = function () {
    this._render();
    this._bindEvents();
};

/**
 * Returns true if any filter is currently active.
 * @returns {boolean}
 */
SearchFilter.prototype.isFiltered = function () {
    return this._isFiltered;
};

/**
 * Re-run the currently active filter against the (possibly updated) store and
 * hand the fresh results to Graph_View. Used after a store-mutating action so
 * a filtered view stays in sync with the latest Graph_Store contents (Req 7.5).
 *
 * Uses the last-applied filter state (types/term) rather than re-reading the
 * form, so it is safe to call programmatically. If no filter is active, the
 * full graph is restored.
 */
SearchFilter.prototype.reapply = function () {
    var self = this;

    if (this._activeTypes.length === 0 && this._activeTerm === "") {
        this._restoreFullGraph();
        return;
    }

    var params = {};
    if (this._activeTypes.length > 0) {
        params.types = this._activeTypes;
    }
    if (this._activeTerm !== "") {
        params.q = this._activeTerm;
    }

    searchGraph(params)
        .then(function (result) {
            self._isFiltered = true;
            renderFilteredGraph(result);
            var nodeCount = (result.nodes || []).length;
            var edgeCount = (result.edges || []).length;
            self._setStatus(
                "Showing " + nodeCount + " node" + (nodeCount !== 1 ? "s" : "") +
                ", " + edgeCount + " edge" + (edgeCount !== 1 ? "s" : "")
            );
        })
        .catch(function (err) {
            self._setStatus("Error: " + err.message);
        });
};

/**
 * Render the search/filter form into the container.
 */
SearchFilter.prototype._render = function () {
    var html = '<div class="search-filter">';
    html += '<h3 class="search-filter-title">Search &amp; Filter</h3>';

    // Label search input
    html += '<div class="form-group">';
    html += '<label for="search-label">Label</label>';
    html += '<input type="text" id="search-label" name="q" placeholder="Search by label…" />';
    html += '</div>';

    // Type filter checkboxes
    html += '<div class="form-group">';
    html += '<label>Node Types</label>';
    html += '<div class="search-type-checkboxes" id="search-type-checkboxes">';
    for (var i = 0; i < SEARCH_NODE_TYPES.length; i++) {
        var nodeType = SEARCH_NODE_TYPES[i];
        html += '<label class="search-type-checkbox">';
        html += '<input type="checkbox" name="search-type" value="' + nodeType + '" />';
        html += ' ' + nodeType;
        html += '</label>';
    }
    html += '</div>';
    html += '</div>';

    // Action buttons
    html += '<div class="form-actions">';
    html += '<button type="button" class="btn-primary" id="search-apply-btn">Apply</button>';
    html += '<button type="button" class="btn-secondary" id="search-clear-btn">Clear</button>';
    html += '</div>';

    // Status indicator
    html += '<div class="search-status" id="search-status"></div>';

    html += '</div>';

    this.container.innerHTML = html;
};

/**
 * Bind event listeners to the search form elements.
 */
SearchFilter.prototype._bindEvents = function () {
    var self = this;

    var applyBtn = document.getElementById("search-apply-btn");
    var clearBtn = document.getElementById("search-clear-btn");
    var labelInput = document.getElementById("search-label");

    if (applyBtn) {
        applyBtn.addEventListener("click", function () {
            self._applyFilters();
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener("click", function () {
            self._clearFilters();
        });
    }

    // Also apply on Enter key in the label input
    if (labelInput) {
        labelInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                self._applyFilters();
            }
        });
    }
};

/**
 * Gather the current filter state from the form and apply it.
 * Calls searchGraph and hands results to Graph_View via renderFilteredGraph.
 * When no filters are active, restores the full graph.
 */
SearchFilter.prototype._applyFilters = function () {
    var self = this;

    // Gather selected types
    var selectedTypes = [];
    var checkboxes = document.querySelectorAll('#search-type-checkboxes input[type="checkbox"]');
    for (var i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].checked) {
            selectedTypes.push(checkboxes[i].value);
        }
    }

    // Gather label term
    var labelInput = document.getElementById("search-label");
    var term = labelInput ? labelInput.value.trim() : "";

    this._activeTypes = selectedTypes;
    this._activeTerm = term;

    // If no filters are active, restore the full graph
    if (selectedTypes.length === 0 && term === "") {
        this._restoreFullGraph();
        return;
    }

    // Build search params and call the API
    var params = {};
    if (selectedTypes.length > 0) {
        params.types = selectedTypes;
    }
    if (term !== "") {
        params.q = term;
    }

    this._setStatus("Searching…");

    searchGraph(params)
        .then(function (result) {
            self._isFiltered = true;
            // Hand results to Graph_View (Req 13.5)
            renderFilteredGraph(result);
            var nodeCount = (result.nodes || []).length;
            var edgeCount = (result.edges || []).length;
            self._setStatus(
                "Showing " + nodeCount + " node" + (nodeCount !== 1 ? "s" : "") +
                ", " + edgeCount + " edge" + (edgeCount !== 1 ? "s" : "")
            );
        })
        .catch(function (err) {
            self._setStatus("Error: " + err.message);
        });
};

/**
 * Clear all filters and restore the full graph (Req 13.4).
 */
SearchFilter.prototype._clearFilters = function () {
    // Reset form state
    var labelInput = document.getElementById("search-label");
    if (labelInput) {
        labelInput.value = "";
    }

    var checkboxes = document.querySelectorAll('#search-type-checkboxes input[type="checkbox"]');
    for (var i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = false;
    }

    this._activeTypes = [];
    this._activeTerm = "";

    this._restoreFullGraph();
};

/**
 * Restore the full graph by calling refreshGraphView (Req 13.4, 13.5).
 */
SearchFilter.prototype._restoreFullGraph = function () {
    var self = this;
    this._isFiltered = false;
    this._setStatus("");

    // Refresh the graph view to show all nodes and edges
    refreshGraphView().catch(function (err) {
        self._setStatus("Error restoring graph: " + err.message);
    });
};

/**
 * Update the status indicator text.
 * @param {string} message
 */
SearchFilter.prototype._setStatus = function (message) {
    var statusEl = document.getElementById("search-status");
    if (statusEl) {
        statusEl.textContent = message;
    }
};
