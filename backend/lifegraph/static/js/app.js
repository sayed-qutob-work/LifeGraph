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
        dashboardContainer: null,
        entitiesContainer: null,
    };

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
            html += "<p>Proposed: " + nodes.length + " node" + (nodes.length !== 1 ? "s" : "") +
                ", " + edges.length + " edge" + (edges.length !== 1 ? "s" : "") + ".</p>";
            if (nodes.length > 0) {
                html += "<ul>";
                nodes.forEach(function (n) {
                    html += "<li>" + escapeHtml(n.label) + " <em>(" + escapeHtml(n.type) + ")</em></li>";
                });
                html += "</ul>";
            }
            html += '<div class="form-actions">';
            html += '<button type="button" class="btn-primary" id="app-proposal-confirm">Confirm</button>';
            html += '<button type="button" class="btn-secondary" id="app-proposal-reject">Reject</button>';
            html += "</div></div>";
            preview.innerHTML = html;

            preview.querySelector("#app-proposal-confirm").addEventListener("click", function () {
                setStatus("Saving…");
                confirmProposal(proposal)
                    .then(function () {
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
                rejectProposal()
                    .then(function () {
                        clearPreview();
                        setStatus("Proposal discarded.");
                    })
                    .catch(function (err) {
                        setStatus("Reject failed: " + err.message);
                    });
            });
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
