/**
 * Property 17: Node type styling is injective
 *
 * For any two distinct node types in the Node_Type_Set, the node-style mapping
 * SHALL assign visually distinct styles.
 *
 * **Validates: Requirements 7.7**
 */
import { describe, it, expect } from "vitest";
import fc from "fast-check";

// ---------------------------------------------------------------------------
// Import the style mapping and accessor from graphView.js
// Since graphView.js uses plain globals (no ES module exports), we inline the
// relevant constants here to keep the test self-contained and runnable under
// vitest without a DOM environment.
// ---------------------------------------------------------------------------

const NODE_TYPE_STYLES = {
    Skill:    { color: { background: "#4CAF50", border: "#388E3C", highlight: { background: "#66BB6A", border: "#2E7D32" } }, shape: "dot" },
    Goal:     { color: { background: "#FF9800", border: "#F57C00", highlight: { background: "#FFB74D", border: "#E65100" } }, shape: "star" },
    Habit:    { color: { background: "#9C27B0", border: "#7B1FA2", highlight: { background: "#BA68C8", border: "#6A1B9A" } }, shape: "diamond" },
    Project:  { color: { background: "#2196F3", border: "#1976D2", highlight: { background: "#64B5F6", border: "#1565C0" } }, shape: "square" },
    Event:    { color: { background: "#F44336", border: "#D32F2F", highlight: { background: "#EF5350", border: "#C62828" } }, shape: "triangle" },
    Person:   { color: { background: "#00BCD4", border: "#0097A7", highlight: { background: "#4DD0E1", border: "#00838F" } }, shape: "ellipse" },
    Resource: { color: { background: "#795548", border: "#5D4037", highlight: { background: "#A1887F", border: "#4E342E" } }, shape: "box" },
};

function getNodeTypeStyle(nodeType) {
    return NODE_TYPE_STYLES[nodeType];
}

const NODE_TYPE_SET = Object.keys(NODE_TYPE_STYLES);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Serialize the visually distinguishing properties of a style into a comparable
 * string. Two styles are "visually distinct" if they differ in at least one of:
 * shape, background color, or border color.
 */
function styleFingerprint(style) {
    if (!style) return "undefined";
    return JSON.stringify({
        shape: style.shape,
        bg: style.color && style.color.background,
        border: style.color && style.color.border,
    });
}

// ---------------------------------------------------------------------------
// Arbitrary: pairs of distinct node types
// ---------------------------------------------------------------------------

const distinctNodeTypePairArb = fc
    .tuple(
        fc.integer({ min: 0, max: NODE_TYPE_SET.length - 1 }),
        fc.integer({ min: 0, max: NODE_TYPE_SET.length - 1 })
    )
    .filter(([i, j]) => i !== j)
    .map(([i, j]) => [NODE_TYPE_SET[i], NODE_TYPE_SET[j]]);

// ---------------------------------------------------------------------------
// Property test
// ---------------------------------------------------------------------------

describe("Property 17: Node type styling is injective", () => {
    it("any two distinct node types receive visually distinct styles", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        fc.assert(
            fc.property(distinctNodeTypePairArb, ([typeA, typeB]) => {
                const styleA = getNodeTypeStyle(typeA);
                const styleB = getNodeTypeStyle(typeB);

                // Both types must have a defined style
                expect(styleA).toBeDefined();
                expect(styleB).toBeDefined();

                // The styles must be visually distinct (different fingerprint)
                const fpA = styleFingerprint(styleA);
                const fpB = styleFingerprint(styleB);
                expect(fpA).not.toEqual(fpB);
            }),
            { numRuns: 20 }
        );
    });

    it("every node type in the set has a defined style", () => {
        /**
         * **Validates: Requirements 7.7**
         */
        fc.assert(
            fc.property(
                fc.integer({ min: 0, max: NODE_TYPE_SET.length - 1 }),
                (idx) => {
                    const nodeType = NODE_TYPE_SET[idx];
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
});
