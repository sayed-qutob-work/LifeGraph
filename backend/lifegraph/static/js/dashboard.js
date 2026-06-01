// LifeGraph Dashboard UI
// Calls GET /api/dashboard via fetchDashboard() and renders skills, goals,
// upcoming events (sorted ascending by date), and undated events.
//
// Requirements: 12.1, 12.2, 12.3, 12.4
"use strict";

/**
 * Initialize the dashboard by fetching data and rendering all sections.
 *
 * @param {HTMLElement} container - The DOM element to render the dashboard into.
 * @returns {Promise<void>}
 */
async function initDashboard(container) {
    if (!container) {
        console.error("Dashboard: no container element provided.");
        return;
    }

    container.innerHTML = '<p class="dashboard-loading">Loading dashboard…</p>';

    try {
        const data = await fetchDashboard();
        renderDashboard(container, data);
    } catch (err) {
        container.innerHTML = "";
        const errorEl = document.createElement("p");
        errorEl.className = "dashboard-error";
        errorEl.textContent = "Failed to load dashboard: " + err.message;
        container.appendChild(errorEl);
    }
}

/**
 * Render the full dashboard into the given container.
 *
 * @param {HTMLElement} container - The DOM element to render into.
 * @param {object} data - Dashboard data from the API.
 * @param {Array} data.skills - Skill nodes.
 * @param {Array} data.goals - Goal nodes.
 * @param {Array} data.upcomingEvents - Upcoming event nodes sorted ascending by date.
 * @param {Array} data.undatedEvents - Event nodes without a date attribute.
 */
function renderDashboard(container, data) {
    container.innerHTML = "";

    const wrapper = document.createElement("div");
    wrapper.className = "dashboard";

    // Skills section
    wrapper.appendChild(renderSection("Skills", data.skills || [], renderNodeItem));

    // Goals section
    wrapper.appendChild(renderSection("Goals", data.goals || [], renderNodeItem));

    // Upcoming Events section (already sorted ascending by date from the API)
    wrapper.appendChild(
        renderSection("Upcoming Events", data.upcomingEvents || [], renderEventItem)
    );

    // Undated Events section
    wrapper.appendChild(
        renderSection("Undated Events", data.undatedEvents || [], renderEventItem)
    );

    container.appendChild(wrapper);
}

/**
 * Render a dashboard section with a heading and a list of items.
 *
 * @param {string} title - Section heading text.
 * @param {Array} items - Array of node objects to render.
 * @param {function} renderItem - Function to render a single item into an <li>.
 * @returns {HTMLElement} The section element.
 */
function renderSection(title, items, renderItem) {
    const section = document.createElement("section");
    section.className = "dashboard-section";

    const heading = document.createElement("h3");
    heading.className = "dashboard-section-title";
    heading.textContent = title;
    section.appendChild(heading);

    if (items.length === 0) {
        const empty = document.createElement("p");
        empty.className = "dashboard-empty";
        empty.textContent = "None";
        section.appendChild(empty);
        return section;
    }

    const list = document.createElement("ul");
    list.className = "dashboard-list";
    for (const item of items) {
        list.appendChild(renderItem(item));
    }
    section.appendChild(list);

    return section;
}

/**
 * Render a basic node item (skill or goal) as an <li>.
 *
 * @param {object} node - A node object with at least {id, label, type}.
 * @returns {HTMLLIElement}
 */
function renderNodeItem(node) {
    const li = document.createElement("li");
    li.className = "dashboard-item";
    li.dataset.nodeId = node.id;
    li.textContent = node.label;
    return li;
}

/**
 * Render an event node as an <li>, showing the date if available.
 *
 * @param {object} node - An event node with {id, label, type, attributes}.
 * @returns {HTMLLIElement}
 */
function renderEventItem(node) {
    const li = document.createElement("li");
    li.className = "dashboard-item dashboard-event-item";
    li.dataset.nodeId = node.id;

    const labelSpan = document.createElement("span");
    labelSpan.className = "dashboard-event-label";
    labelSpan.textContent = node.label;
    li.appendChild(labelSpan);

    const dateStr = node.attributes && node.attributes.date;
    if (dateStr) {
        const dateSpan = document.createElement("span");
        dateSpan.className = "dashboard-event-date";
        dateSpan.textContent = dateStr;
        li.appendChild(dateSpan);
    }

    return li;
}

/**
 * Refresh the dashboard by re-fetching and re-rendering.
 * Call this when the Graph_Store contents change (Req 12.4).
 *
 * @param {HTMLElement} container - The DOM element containing the dashboard.
 * @returns {Promise<void>}
 */
async function refreshDashboard(container) {
    await initDashboard(container);
}
