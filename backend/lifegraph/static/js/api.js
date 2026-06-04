// LifeGraph API client — fetch wrapper for all backend endpoints.
// Each function handles errors and returns parsed JSON.
"use strict";

/**
 * Base helper: performs a fetch, checks for HTTP errors, and returns JSON.
 * Throws an Error with the server's error message on non-2xx responses.
 */
async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let errorMessage = `HTTP ${response.status}`;
        try {
            const body = await response.json();
            if (body && body.error && body.error.message) {
                errorMessage = body.error.message;
            }
        } catch (_) {
            // If response body isn't JSON, use the status text
            errorMessage = response.statusText || errorMessage;
        }
        throw new Error(errorMessage);
    }
    // 204 No Content has no body
    if (response.status === 204) {
        return null;
    }
    return response.json();
}

/**
 * Fetch the full graph (all nodes and edges).
 * GET /api/graph → { nodes: [...], edges: [...] }
 */
async function fetchGraph() {
    return apiFetch("/api/graph");
}

/**
 * Create a node manually.
 * POST /api/nodes → created node object
 */
async function createNode(data) {
    return apiFetch("/api/nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

/**
 * Update an existing node's label, type, or attributes.
 * PUT /api/nodes/{id} → updated node object
 */
async function updateNode(id, data) {
    return apiFetch(`/api/nodes/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

/**
 * Delete a node (cascades to connected edges).
 * DELETE /api/nodes/{id} → { deletedEdgeIds: [...] }
 */
async function deleteNode(id) {
    return apiFetch(`/api/nodes/${encodeURIComponent(id)}`, {
        method: "DELETE",
    });
}

/**
 * Get the count of edges connected to a node (for delete-warning threshold).
 * GET /api/nodes/{id}/edges → { count: number }
 */
async function getNodeEdges(id) {
    return apiFetch(`/api/nodes/${encodeURIComponent(id)}/edges`);
}

/**
 * Create an edge between two nodes.
 * POST /api/edges → created edge object
 */
async function createEdge(data) {
    return apiFetch("/api/edges", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

/**
 * Update an existing edge's type.
 * PUT /api/edges/{id} → updated edge object
 */
async function updateEdge(id, data) {
    return apiFetch(`/api/edges/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

/**
 * Delete an edge (keeps source and target nodes intact).
 * DELETE /api/edges/{id} → null (204)
 */
async function deleteEdge(id) {
    return apiFetch(`/api/edges/${encodeURIComponent(id)}`, {
        method: "DELETE",
    });
}

/**
 * Parse a natural language sentence into a proposal.
 * POST /api/parse → ProposedGraph (awaiting confirmation)
 */
async function parseSentence(sentence) {
    return apiFetch("/api/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sentence }),
    });
}

/**
 * Confirm a parsed proposal, persisting it to the store.
 * POST /api/parse/confirm → { nodes: [...], edges: [...] }
 *
 * @param {object} proposal - The (possibly edited) proposal nodes/edges.
 * @param {string} [token] - The proposal_token returned by /api/parse.
 */
async function confirmProposal(proposal, token) {
    const body = Object.assign({}, proposal);
    if (token != null) {
        body.proposal_token = token;
    }
    return apiFetch("/api/parse/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
}

/**
 * Reject a parsed proposal (no write occurs).
 * POST /api/parse/reject → null (204)
 *
 * @param {string} [token] - The proposal_token returned by /api/parse.
 */
async function rejectProposal(token) {
    const body = token != null ? { proposal_token: token } : {};
    return apiFetch("/api/parse/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
}

/**
 * Fetch the dashboard data (skills, goals, upcoming/undated events).
 * GET /api/dashboard → { skills: [...], goals: [...], upcomingEvents: [...], undatedEvents: [...] }
 */
async function fetchDashboard() {
    return apiFetch("/api/dashboard");
}

/**
 * Get a context snapshot for a given node.
 * POST /api/context → { snapshot: string }
 *
 * @param {string} nodeId
 * @param {number} [hops] - Optional hop depth override (1–5). Uses server default if omitted.
 */
async function fetchContext(nodeId, hops) {
    const body = { node_id: nodeId };
    if (hops != null) {
        body.max_hops = hops;
    }
    return apiFetch("/api/context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
}

/**
 * Fetch recently created or updated nodes.
 * GET /api/recent?days=N → { nodes: [...] }
 *
 * @param {number} [days=7] - Look-back window in days.
 */
async function fetchRecent(days) {
    const url = days != null ? `/api/recent?days=${days}` : "/api/recent";
    return apiFetch(url);
}

/**
 * Search/filter the graph by type and/or label term.
 * GET /api/search?types=...&q=... → { nodes: [...], edges: [...] }
 */
async function searchGraph(params) {
    const searchParams = new URLSearchParams();
    if (params.types && params.types.length > 0) {
        for (const t of params.types) {
            searchParams.append("types", t);
        }
    }
    if (params.q) {
        searchParams.set("q", params.q);
    }
    const queryString = searchParams.toString();
    const url = queryString ? `/api/search?${queryString}` : "/api/search";
    return apiFetch(url);
}
