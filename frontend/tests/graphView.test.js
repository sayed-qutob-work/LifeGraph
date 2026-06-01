/**
 * Property 16: Graph-to-view transform preserves labels
 *
 * For any graph, the Vis.js dataset transform SHALL produce exactly one item per node
 * carrying that node's label and exactly one item per edge carrying a label equal to
 * its edge type.
 *
 * **Validates: Requirements 7.2, 7.3**
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";
import fc from "fast-check";

// ---------------------------------------------------------------------------
// Load the REAL transform from graphView.js (the Graph_View implementation from
// task 13.2). graphView.js lives outside this Vite root and uses CommonJS
// `module.exports`, referencing the `vis` / `document` globals only inside
// functions. To exercise the actual shipped code without pulling an
// out-of-root file into Vite's module graph, we read the source and evaluate
// its CommonJS exports in a Node `vm` sandbox.
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

const { transformGraphData } = loadGraphViewModule();

// --- Arbitraries ---

const NODE_TYPES = ["Skill", "Goal", "Habit", "Project", "Event", "Person", "Resource"];
const EDGE_TYPES = [
  "requires", "supports", "conflicts_with", "motivated_by", "leads_to",
  "part_of", "owned_by", "blocks", "related_to",
];

/** Generate a valid node with a unique id and a non-empty label. */
const arbNode = fc.record({
  id: fc.uuid(),
  type: fc.constantFrom(...NODE_TYPES),
  label: fc.string({ minLength: 1, maxLength: 200 }),
  attributes: fc.constant({}),
});

/**
 * Generate a valid graph: a list of nodes and edges whose source/target reference
 * existing node ids (no dangling references) and no self-edges.
 */
const arbGraph = arbNode.chain((firstNode) =>
  fc.array(arbNode, { minLength: 0, maxLength: 20 }).chain((moreNodes) => {
    const nodes = [firstNode, ...moreNodes];
    // Deduplicate node ids
    const seenIds = new Set();
    const uniqueNodes = nodes.filter((n) => {
      if (seenIds.has(n.id)) return false;
      seenIds.add(n.id);
      return true;
    });

    // Edges need at least two distinct nodes to avoid self-edges. With 0 or 1
    // nodes the only edge would be a self-edge, so produce no edges.
    if (uniqueNodes.length < 2) {
      return fc.constant({ nodes: uniqueNodes, edges: [] });
    }

    const nodeIds = uniqueNodes.map((n) => n.id);
    const n = nodeIds.length;

    // Build edges with guaranteed-distinct endpoints (no self-edges) by picking
    // a source index and a non-zero shift, rather than filtering — filtering
    // could never satisfy `source !== target` when n === 1 and would stall.
    const arbEdge = fc.record({
      id: fc.uuid(),
      sourceIdx: fc.integer({ min: 0, max: n - 1 }),
      shift: fc.integer({ min: 1, max: n - 1 }),
      type: fc.constantFrom(...EDGE_TYPES),
    }).map((e) => ({
      id: e.id,
      source: nodeIds[e.sourceIdx],
      target: nodeIds[(e.sourceIdx + e.shift) % n],
      type: e.type,
    }));

    return fc.array(arbEdge, { minLength: 0, maxLength: 30 }).map((edges) => {
      // Deduplicate edge ids
      const seenEdgeIds = new Set();
      const uniqueEdges = edges.filter((e) => {
        if (seenEdgeIds.has(e.id)) return false;
        seenEdgeIds.add(e.id);
        return true;
      });
      return { nodes: uniqueNodes, edges: uniqueEdges };
    });
  })
);

/** Also test the empty graph case explicitly. */
const arbGraphIncludingEmpty = fc.oneof(
  fc.constant({ nodes: [], edges: [] }),
  arbGraph
);

describe("Property 16: Graph-to-view transform preserves labels", () => {
  it("produces exactly one vis item per node carrying that node's label", () => {
    /**
     * **Validates: Requirements 7.2, 7.3**
     */
    fc.assert(
      fc.property(arbGraphIncludingEmpty, (graphData) => {
        const { visNodes } = transformGraphData(graphData);

        // Exactly one vis item per input node
        expect(visNodes.length).toBe(graphData.nodes.length);

        // Each vis node carries the corresponding node's label
        const visNodeMap = new Map(visNodes.map((vn) => [vn.id, vn]));
        for (const node of graphData.nodes) {
          const visNode = visNodeMap.get(node.id);
          expect(visNode).toBeDefined();
          expect(visNode.label).toBe(node.label);
        }
      }),
      { numRuns: 20 }
    );
  });

  it("produces exactly one vis item per edge carrying a label equal to its edge type", () => {
    /**
     * **Validates: Requirements 7.2, 7.3**
     */
    fc.assert(
      fc.property(arbGraphIncludingEmpty, (graphData) => {
        const { visEdges } = transformGraphData(graphData);

        // Exactly one vis item per input edge
        expect(visEdges.length).toBe(graphData.edges.length);

        // Each vis edge carries a label equal to the edge's type
        const visEdgeMap = new Map(visEdges.map((ve) => [ve.id, ve]));
        for (const edge of graphData.edges) {
          const visEdge = visEdgeMap.get(edge.id);
          expect(visEdge).toBeDefined();
          expect(visEdge.label).toBe(edge.type);
        }
      }),
      { numRuns: 20 }
    );
  });
});
