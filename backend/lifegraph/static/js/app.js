// LifeGraph application entry point.
//
// Initializes and connects the four browser components:
//   - Graph_View    (graphView.js)   — Vis.js network rendering
//   - Graph_Editor  (graphEditor.js) — node/edge create/edit/delete forms
//   - Dashboard     (dashboard.js)   — skills/goals/events summary
//   - Search_Filter (search.js)      — type/label filtering
//
// Wiring guarantee (Req 7.5): whenever the Graph_Store contents change through a
// create, edit, or delete operation (including confirming a parsed proposal),
// the Graph_View re-renders to match the current store contents. This is achieved
// by routing every store-mutating action through a single `handleGraphChanged`
// callback that re-renders the view (respecting any active search filter) and
// refreshes the dashboard.
"use strict";

(function () {
    // -----------------------------------------------------------------------
    // Shared application state
    // -----------------------------------------------------------------------
    var state = {
        graph: { nodes: [], edges: [] }, // local cache for editor dropdowns / lists
        editor: null,
        search: null,
        contextPanel: null,
        dashboardContainer: null,
        entitiesContainer: null,
    };

    var NODE_TYPES = Object.freeze([
        "Skill", "Goal", "Habit", "Project", "Event", "Person",
        "Organization", "Program", "Tool", "Technology", "Model",
        "Hardware", "Topic", "Recipe", "Issue", "Place", "Resource"
    ]);

    var EDGE_TYPES = Object.freeze([
        "uses", "runs_model", "current_model", "considering_model",
        "compared_with", "for", "has_issue", "possible_cause", "at",
        "referred_by", "focuses_on", "practices_on", "status", "deadline",
        "requires", "supports", "conflicts_with", "motivated_by",
        "leads_to", "part_of", "owned_by", "blocks", "related_to"
    ]);

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    /** Escape a string for safe insertion as HTML text content. */
    function escapeHtml(str) {
        return String(str == null ? "" : str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /** Escape a string for safe insertion as an HTML attribute. */
    function escapeAttr(str) {
        return String(str == null ? "" : str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function renderOptions(options, selected) {
        var html = "";
        options.forEach(function (option) {
            var isSelected = option === selected ? " selected" : "";
            html += '<option value="' + escapeAttr(option) + '"' + isSelected + '>' +
                escapeHtml(option) + "</option>";
        });
        return html;
    }

    /** Returns the current node list (used by Graph_Editor for edge endpoints). */
    function getNodes() {
        return (state.graph && state.graph.nodes) || [];
    }

    /** Look up a node by id from the local cache. */
    function findNode(nodeId) {
        return getNodes().filter(function (n) { return n.id === nodeId; })[0] || null;
    }

    /** Look up an edge by id from the local cache. */
    function findEdge(edgeId) {
        var edges = (state.graph && state.graph.edges) || [];
        return edges.filter(function (e) { return e.id === edgeId; })[0] || null;
    }

    /** Refresh the local graph cache from the backend. */
    async function refreshGraphCache() {
        try {
            state.graph = await fetchGraph();
        } catch (err) {
            // Graph_View surfaces its own fetch error; keep the previous cache so
            // the editor dropdowns/lists do not blank out unexpectedly.
            // eslint-disable-next-line no-console
            console.error("Failed to refresh graph cache:", err.message);
        }
    }

    // -----------------------------------------------------------------------
    // Central re-render hook (Req 7.5)
    // -----------------------------------------------------------------------

    /**
     * Called after any store-mutating action (create/edit/delete node or edge,
     * confirm proposal). Re-renders the Graph_View to match the current store,
     * refreshes the dashboard, and re-renders the entity list.
     *
     * If a search filter is active, the filtered view is re-applied so the
     * rendered network continues to match the user's current selection while
     * still reflecting the latest store contents.
     */
    async function handleGraphChanged() {
        await refreshGraphCache();

        if (state.search && state.search.isFiltered()) {
            // Re-run the active filter against the updated store.
            state.search.reapply();
        } else {
            // No filter active: re-render the full graph (Req 7.5).
            await refreshGraphView();
        }

        renderEntityList();

        if (state.dashboardContainer) {
            await refreshDashboard(state.dashboardContainer);
        }
    }

    // -----------------------------------------------------------------------
    // Sidebar layout
    // -----------------------------------------------------------------------

    /**
     * Build the sidebar structure and return references to each sub-container.
     */
    function buildSidebar(sidebar) {
        sidebar.innerHTML = "";

        function section(titleText) {
            var sec = document.createElement("section");
            sec.className = "app-section";
            if (titleText) {
                var h = document.createElement("h3");
                h.className = "app-section-title";
                h.textContent = titleText;
                sec.appendChild(h);
            }
            sidebar.appendChild(sec);
            return sec;
        }

        // --- Editor controls + form ---
        var editorSection = section("Editor");
        var controls = document.createElement("div");
        controls.className = "app-editor-controls";
        var addNodeBtn = document.createElement("button");
        addNodeBtn.type = "button";
        addNodeBtn.id = "app-add-node";
        addNodeBtn.className = "btn-primary";
        addNodeBtn.textContent = "Add Node";
        var addEdgeBtn = document.createElement("button");
        addEdgeBtn.type = "button";
        addEdgeBtn.id = "app-add-edge";
        addEdgeBtn.className = "btn-primary";
        addEdgeBtn.textContent = "Add Edge";
        controls.appendChild(addNodeBtn);
        controls.appendChild(addEdgeBtn);
        editorSection.appendChild(controls);

        var editorForm = document.createElement("div");
        editorForm.id = "app-editor-form";
        editorForm.className = "app-editor-form";
        editorSection.appendChild(editorForm);

        // --- Context snapshot (node selection → copy to clipboard) ---
        var contextSection = section("Context");
        var contextContainer = document.createElement("div");
        contextContainer.id = "app-context";
        contextSection.appendChild(contextContainer);

        // --- Natural-language parse ---
        var parseSection = section("Add from sentence");
        var parseForm = document.createElement("form");
        parseForm.id = "app-parse-form";
        parseForm.className = "app-parse-form";
        parseForm.innerHTML =
            '<textarea id="app-parse-input" rows="2" maxlength="1000" ' +
            'placeholder="Describe something, e.g. \'Learning Python supports my goal of building apps\'"></textarea>' +
            '<div class="form-actions">' +
            '<button type="submit" class="btn-primary">Parse</button>' +
            "</div>" +
            '<div class="app-parse-status" id="app-parse-status"></div>' +
            '<div class="app-parse-preview" id="app-parse-preview"></div>';
        parseSection.appendChild(parseForm);

        // --- Search & filter ---
        var searchSection = section(null);
        var searchContainer = document.createElement("div");
        searchContainer.id = "app-search";
        searchSection.appendChild(searchContainer);

        // --- Entities (nodes/edges with edit/delete) ---
        var entitiesSection = section("Entities");
        var entitiesContainer = document.createElement("div");
        entitiesContainer.id = "app-entities";
        entitiesSection.appendChild(entitiesContainer);

        // --- Dashboard ---
        var dashboardSection = section(null);
        var dashboardContainer = document.createElement("div");
        dashboardContainer.id = "app-dashboard";
        dashboardSection.appendChild(dashboardContainer);

        return {
            addNodeBtn: addNodeBtn,
            addEdgeBtn: addEdgeBtn,
            editorForm: editorForm,
            contextContainer: contextContainer,
            parseForm: parseForm,
            searchContainer: searchContainer,
            entitiesContainer: entitiesContainer,
            dashboardContainer: dashboardContainer,
        };
    }

    // -----------------------------------------------------------------------
    // Entity list (drives edit/delete through Graph_Editor)
    // -----------------------------------------------------------------------

    function renderEntityList() {
        var container = state.entitiesContainer;
        if (!container) return;

        var nodes = getNodes();
        var edges = (state.graph && state.graph.edges) || [];

        var html = "";

        html += '<h4 class="app-entities-heading">Nodes (' + nodes.length + ")</h4>";
        if (nodes.length === 0) {
            html += '<p class="app-entities-empty">No nodes yet.</p>';
        } else {
            html += '<ul class="app-entity-list">';
            nodes.forEach(function (node) {
                html +=
                    '<li class="app-entity" data-node-id="' + escapeHtml(node.id) + '">' +
                    '<span class="app-entity-label">' + escapeHtml(node.label) +
                    ' <em>(' + escapeHtml(node.type) + ")</em></span>" +
                    '<span class="app-entity-actions">' +
                    '<button type="button" class="app-edit-node" data-id="' + escapeHtml(node.id) + '">Edit</button>' +
                    '<button type="button" class="app-delete-node" data-id="' + escapeHtml(node.id) + '">Delete</button>' +
                    "</span></li>";
            });
            html += "</ul>";
        }

        html += '<h4 class="app-entities-heading">Edges (' + edges.length + ")</h4>";
        if (edges.length === 0) {
            html += '<p class="app-entities-empty">No edges yet.</p>';
        } else {
            html += '<ul class="app-entity-list">';
            edges.forEach(function (edge) {
                var src = findNode(edge.source);
                var tgt = findNode(edge.target);
                var srcLabel = src ? src.label : edge.source;
                var tgtLabel = tgt ? tgt.label : edge.target;
                html +=
                    '<li class="app-entity" data-edge-id="' + escapeHtml(edge.id) + '">' +
                    '<span class="app-entity-label">' + escapeHtml(srcLabel) +
                    " —[" + escapeHtml(edge.type) + "]→ " + escapeHtml(tgtLabel) + "</span>" +
                    '<span class="app-entity-actions">' +
                    '<button type="button" class="app-edit-edge" data-id="' + escapeHtml(edge.id) + '">Edit</button>' +
                    '<button type="button" class="app-delete-edge" data-id="' + escapeHtml(edge.id) + '">Delete</button>' +
                    "</span></li>";
            });
            html += "</ul>";
        }

        container.innerHTML = html;
        bindEntityListEvents(container);
    }

    function bindEntityListEvents(container) {
        container.querySelectorAll(".app-edit-node").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var node = findNode(btn.getAttribute("data-id"));
                if (node) state.editor.showEditNodeForm(node);
            });
        });
        container.querySelectorAll(".app-delete-node").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var id = btn.getAttribute("data-id");
                // Editor handles the high-degree confirmation gate and re-render.
                state.editor.deleteNodeWithConfirmation(id).catch(function (err) {
                    // eslint-disable-next-line no-alert
                    window.alert("Delete failed: " + err.message);
                });
            });
        });
        container.querySelectorAll(".app-edit-edge").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var edge = findEdge(btn.getAttribute("data-id"));
                if (edge) state.editor.showEditEdgeForm(edge);
            });
        });
        container.querySelectorAll(".app-delete-edge").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var id = btn.getAttribute("data-id");
                state.editor.deleteEdge(id).catch(function (err) {
                    // eslint-disable-next-line no-alert
                    window.alert("Delete failed: " + err.message);
                });
            });
        });
    }

    // -----------------------------------------------------------------------
    // Natural-language parse / confirm / reject wiring
    // -----------------------------------------------------------------------

    function wireParseForm(parseForm) {
        var input = parseForm.querySelector("#app-parse-input");
        var status = parseForm.querySelector("#app-parse-status");
        var preview = parseForm.querySelector("#app-parse-preview");
        var currentToken = null;

        function setStatus(msg) { status.textContent = msg || ""; }
        function clearPreview() { preview.innerHTML = ""; }

        parseForm.addEventListener("submit", function (e) {
            e.preventDefault();
            var sentence = (input.value || "").trim();
            clearPreview();
            if (sentence === "") {
                setStatus("Please enter a sentence.");
                return;
            }
            setStatus("Parsing…");
            parseSentence(sentence)
                .then(function (proposal) {
                    currentToken = proposal.proposal_token || null;
                    setStatus("");
                    showProposalPreview(proposal);
                })
                .catch(function (err) {
                    setStatus("Parse failed: " + err.message);
                });
        });

        function showProposalPreview(proposal) {
            var nodes = (proposal && proposal.nodes) || [];
            var edges = (proposal && proposal.edges) || [];

            var html = '<div class="app-proposal">';
            html += '<div class="app-proposal-summary">Proposed ' + nodes.length +
                " node" + (nodes.length !== 1 ? "s" : "") + " and " + edges.length +
                " edge" + (edges.length !== 1 ? "s" : "") + ".</div>";
            html += '<div class="app-proposal-error" id="app-proposal-error"></div>';

            html += '<div class="app-proposal-block"><h4>Nodes</h4>';
            if (nodes.length === 0) {
                html += '<p class="app-entities-empty">No nodes proposed.</p>';
            } else {
                html += '<div class="app-proposal-table app-proposal-node-table">';
                html += '<div class="app-proposal-row app-proposal-head">' +
                    '<span>Use</span><span>Label</span><span>Type</span><span>Attributes JSON</span></div>';
                nodes.forEach(function (n, index) {
                    html += '<div class="app-proposal-row" data-node-row="' + index + '">' +
                        '<label class="app-proposal-use"><input type="checkbox" class="proposal-node-include" checked /></label>' +
                        '<input class="proposal-node-label" value="' + escapeAttr(n.label) + '" />' +
                        '<select class="proposal-node-type">' + renderOptions(NODE_TYPES, n.type) + '</select>' +
                        '<textarea class="proposal-node-attrs" rows="1">' +
                        escapeHtml(JSON.stringify(n.attributes || {})) + '</textarea>' +
                        '</div>';
                });
                html += '</div>';
            }
            html += '</div>';

            html += '<div class="app-proposal-block"><h4>Edges</h4>';
            if (edges.length === 0) {
                html += '<p class="app-entities-empty">No edges proposed.</p>';
            } else {
                html += '<div class="app-proposal-table app-proposal-edge-table">';
                html += '<div class="app-proposal-row app-proposal-head">' +
                    '<span>Use</span><span>Source</span><span>Source type</span><span>Edge</span><span>Target</span><span>Target type</span></div>';
                edges.forEach(function (edge, index) {
                    html += '<div class="app-proposal-row" data-edge-row="' + index + '">' +
                        '<label class="app-proposal-use"><input type="checkbox" class="proposal-edge-include" checked /></label>' +
                        '<input class="proposal-edge-source-label" value="' + escapeAttr(edge.source_label) + '" />' +
                        '<select class="proposal-edge-source-type">' + renderOptions(NODE_TYPES, edge.source_type) + '</select>' +
                        '<select class="proposal-edge-type">' + renderOptions(EDGE_TYPES, edge.type) + '</select>' +
                        '<input class="proposal-edge-target-label" value="' + escapeAttr(edge.target_label) + '" />' +
                        '<select class="proposal-edge-target-type">' + renderOptions(NODE_TYPES, edge.target_type) + '</select>' +
                        '</div>';
                });
                html += '</div>';
            }
            html += '</div>';

            html += '<div class="form-actions">';
            html += '<button type="button" class="btn-primary" id="app-proposal-confirm">Save Proposal</button>';
            html += '<button type="button" class="btn-secondary" id="app-proposal-reject">Reject</button>';
            html += "</div></div>";
            preview.innerHTML = html;

            preview.querySelector("#app-proposal-confirm").addEventListener("click", function () {
                var editedProposal;
                try {
                    editedProposal = collectEditedProposal(preview);
                } catch (err) {
                    var errorEl = preview.querySelector("#app-proposal-error");
                    if (errorEl) errorEl.textContent = err.message;
                    return;
                }
                setStatus("Saving…");
                confirmProposal(editedProposal, currentToken)
                    .then(function () {
                        currentToken = null;
                        clearPreview();
                        input.value = "";
                        setStatus("Added to graph.");
                        // Store changed: re-render the view (Req 7.5).
                        return handleGraphChanged();
                    })
                    .catch(function (err) {
                        setStatus("Save failed: " + err.message);
                    });
            });

            preview.querySelector("#app-proposal-reject").addEventListener("click", function () {
                rejectProposal(currentToken)
                    .then(function () {
                        currentToken = null;
                        clearPreview();
                        setStatus("Proposal discarded.");
                    })
                    .catch(function (err) {
                        setStatus("Reject failed: " + err.message);
                    });
            });
        }

        function collectEditedProposal(container) {
            var edited = { nodes: [], edges: [] };

            container.querySelectorAll("[data-node-row]").forEach(function (row) {
                if (!row.querySelector(".proposal-node-include").checked) return;
                var label = row.querySelector(".proposal-node-label").value.trim();
                var type = row.querySelector(".proposal-node-type").value;
                var rawAttrs = row.querySelector(".proposal-node-attrs").value.trim();
                var attrs = {};

                if (!label) {
                    throw new Error("Every included node needs a label.");
                }
                if (NODE_TYPES.indexOf(type) === -1) {
                    throw new Error("Every included node needs a valid type.");
                }
                if (rawAttrs) {
                    attrs = JSON.parse(rawAttrs);
                    if (!attrs || Array.isArray(attrs) || typeof attrs !== "object") {
                        throw new Error("Node attributes must be a JSON object.");
                    }
                }

                edited.nodes.push({ label: label, type: type, attributes: attrs });
            });

            container.querySelectorAll("[data-edge-row]").forEach(function (row) {
                if (!row.querySelector(".proposal-edge-include").checked) return;
                var sourceLabel = row.querySelector(".proposal-edge-source-label").value.trim();
                var sourceType = row.querySelector(".proposal-edge-source-type").value;
                var targetLabel = row.querySelector(".proposal-edge-target-label").value.trim();
                var targetType = row.querySelector(".proposal-edge-target-type").value;
                var edgeType = row.querySelector(".proposal-edge-type").value;

                if (!sourceLabel || !targetLabel) {
                    throw new Error("Every included edge needs source and target labels.");
                }
                if (
                    NODE_TYPES.indexOf(sourceType) === -1 ||
                    NODE_TYPES.indexOf(targetType) === -1 ||
                    EDGE_TYPES.indexOf(edgeType) === -1
                ) {
                    throw new Error("Every included edge needs valid source, target, and edge types.");
                }
                if (
                    sourceLabel.toLowerCase() === targetLabel.toLowerCase() &&
                    sourceType === targetType
                ) {
                    throw new Error("Self-referential edges are not permitted.");
                }

                edited.edges.push({
                    source_label: sourceLabel,
                    source_type: sourceType,
                    target_label: targetLabel,
                    target_type: targetType,
                    type: edgeType,
                });
            });

            return edited;
        }
    }

    // -----------------------------------------------------------------------
    // Application bootstrap
    // -----------------------------------------------------------------------

    async function init() {
        var graphContainer = document.getElementById("graph-container");
        var sidebar = document.getElementById("sidebar");

        if (!graphContainer || !sidebar) {
            // eslint-disable-next-line no-console
            console.error("LifeGraph: required containers (#graph-container, #sidebar) not found.");
            return;
        }

        var refs = buildSidebar(sidebar);
        state.dashboardContainer = refs.dashboardContainer;
        state.entitiesContainer = refs.entitiesContainer;

        // 1. Graph_View — initial render (fetches GET /api/graph itself).
        await initGraphView(graphContainer);

        // Populate the local cache used by the editor and entity list.
        await refreshGraphCache();

        // 1a. Context_Panel — wired to graph node selection.
        state.contextPanel = new ContextPanel({
            container: refs.contextContainer,
            getNode: findNode,
        });
        state.contextPanel.clear();
        setSelectionCallback(function (nodeId) {
            state.contextPanel.onNodeSelected(nodeId);
        });

        // 2. Graph_Editor — every successful mutation routes through
        //    handleGraphChanged so the view re-renders (Req 7.5).
        state.editor = new GraphEditor({
            container: refs.editorForm,
            onGraphChanged: handleGraphChanged,
            getNodes: getNodes,
        });

        refs.addNodeBtn.addEventListener("click", function () {
            state.editor.showCreateNodeForm();
        });
        refs.addEdgeBtn.addEventListener("click", function () {
            state.editor.showCreateEdgeForm();
        });

        // 3. Search_Filter — hands filtered results to Graph_View.
        state.search = new SearchFilter({ container: refs.searchContainer });
        state.search.init();

        // 4. Dashboard — initial render.
        await initDashboard(refs.dashboardContainer);

        // 5. Natural-language parse → confirm/reject (confirm mutates the store).
        wireParseForm(refs.parseForm);

        // Render the initial entity list from the cache.
        renderEntityList();
    }

    // Run after the DOM is ready.
    if (typeof document !== "undefined") {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", init);
        } else {
            init();
        }
    }

    // Expose internals for testing in a CommonJS/Vitest environment.
    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            init: init,
            handleGraphChanged: handleGraphChanged,
            getNodes: getNodes,
            renderEntityList: renderEntityList,
            _state: state,
        };
    }
})();
