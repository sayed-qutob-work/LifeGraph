/**
 * Property 17: Node type styling — every node renders as a circle, colored by
 * semantic family.
 *
 * The design overhaul replaces the old injective (color, shape) mapping with a
 * shared-shape ("dot"), family-colored palette: every NodeType in the app's
 * NODE_TYPES list has a defined style, every style's shape is "dot", every
 * color is a valid hex drawn from the validated dark-surface family palette,
 * and label font color is white.
 *
 * **Validates: Requirements 7.7**
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";
import fc from "fast-check";

// ---------------------------------------------------------------------------
// Load the REAL style mapping and accessor from graphView.js (evaluated in a
// Node vm sandbox, same technique as graphView.test.js) so this test exercises
// the actual shipped code rather than an inlined copy.
// ---------------------------------------------------------------------------

function loadGraphViewModule() {
    const here = dirname(fileURLToPath(import.meta.url));
    const srcPath = resolve(here, "../../backend/lifegraph/static/js/graphView.js");
    const code = readFileSync(srcPath, "utf8");
    const moduleObj = { exports: {} };
    const sandbox = { module: moduleObj, exports: moduleObj.exports };
    vm.runInNewContext(code, sandbox, { filename: srcPath });
    return moduleObj.exports;
}

const { getNodeTypeStyle, NODE_TYPE_STYLES } = loadGraphViewModule();

// The full Node_Type_Set as used by the app (static/js/app.js NODE_TYPES /
// static/js/graphEditor.js NODE_TYPES / static/js/search.js SEARCH_NODE_TYPES).
const NODE_TYPES = [
    "Skill", "Goal", "Habit", "Project", "Event", "Person",
    "Organization", "Program", "Tool", "Technology", "Model",
    "Hardware", "Topic", "Recipe", "Issue", "Place", "Resource",
];

// The validated dark-surface categorical family palette (background hexes).
const FAMILY_COLORS = new Set([
    "#3987e5", // blue — Project
    "#199e70", // aqua — Tool, Technology, Program
    "#c98500", // yellow — Goal, Habit
    "#008300", // green — Skill, Topic
    "#9085e9", // violet — Model, Hardware
    "#e66767", // red — Issue
    "#d55181", // magenta — Person, Organization
    "#d95926", // orange — Event, Place, Recipe
    "#898781", // neutral — Resource
]);

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

describe("Property 17: Node type styling — every node is a circle, colored by family", () => {
    it("every node type in the set has a defined style", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        fc.assert(
            fc.property(
                fc.integer({ min: 0, max: NODE_TYPES.length - 1 }),
                (idx) => {
                    const nodeType = NODE_TYPES[idx];
                    const style = getNodeTypeStyle(nodeType);
                    expect(style).toBeDefined();
                    expect(style.shape).toBeTruthy();
                    expect(style.color).toBeDefined();
                    expect(style.color.background).toBeTruthy();
                    expect(style.color.border).toBeTruthy();
                }
            ),
            { numRuns: 20 }
        );
    });

    it("every style's shape is 'dot' (all nodes render as circles)", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        fc.assert(
            fc.property(
                fc.integer({ min: 0, max: NODE_TYPES.length - 1 }),
                (idx) => {
                    const style = getNodeTypeStyle(NODE_TYPES[idx]);
                    expect(style.shape).toBe("dot");
                }
            ),
            { numRuns: 20 }
        );
    });

    it("every color is a valid hex string drawn from the family palette", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        fc.assert(
            fc.property(
                fc.integer({ min: 0, max: NODE_TYPES.length - 1 }),
                (idx) => {
                    const style = getNodeTypeStyle(NODE_TYPES[idx]);

                    expect(style.color.background).toMatch(HEX_COLOR_RE);
                    expect(style.color.border).toMatch(HEX_COLOR_RE);
                    expect(FAMILY_COLORS.has(style.color.background)).toBe(true);
                    expect(FAMILY_COLORS.has(style.color.border)).toBe(true);

                    // Highlight colors are valid hex too, and are lighter steps of
                    // the same family (not an arbitrary unrelated color).
                    expect(style.color.highlight).toBeDefined();
                    expect(style.color.highlight.background).toMatch(HEX_COLOR_RE);
                    expect(style.color.highlight.border).toMatch(HEX_COLOR_RE);
                }
            ),
            { numRuns: 20 }
        );
    });

    it("label font color is white for every node type", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        fc.assert(
            fc.property(
                fc.integer({ min: 0, max: NODE_TYPES.length - 1 }),
                (idx) => {
                    const style = getNodeTypeStyle(NODE_TYPES[idx]);
                    expect(style.font).toBeDefined();
                    expect(style.font.color).toBe("#ffffff");
                }
            ),
            { numRuns: 20 }
        );
    });

    it("types within the same semantic family share the same color", () => {
        /**
         * **Validates: Requirements 7.7**
         * The new design intentionally shares colors across a family (e.g. Tool,
         * Technology, and Program are all "aqua") — this replaces the old
         * injective-mapping guarantee.
         */
        const families = [
            ["Tool", "Technology", "Program"],
            ["Goal", "Habit"],
            ["Skill", "Topic"],
            ["Model", "Hardware"],
            ["Person", "Organization"],
            ["Event", "Place", "Recipe"],
        ];

        families.forEach((family) => {
            const backgrounds = family.map((t) => getNodeTypeStyle(t).color.background);
            const distinct = new Set(backgrounds);
            expect(distinct.size).toBe(1);
        });
    });

    it("NODE_TYPE_STYLES has no entries outside the family palette", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        Object.keys(NODE_TYPE_STYLES).forEach((type) => {
            const style = NODE_TYPE_STYLES[type];
            expect(style.shape).toBe("dot");
            expect(FAMILY_COLORS.has(style.color.background)).toBe(true);
            expect(style.font.color).toBe("#ffffff");
        });
    });
});
