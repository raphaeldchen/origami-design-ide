# MCP Tool Harness

Based on the architectural details and the software model outlined in the _TreeMaker 4.0 Manual_, we can build out a highly accurate and domain-specific MCP Tool Harness.

In TreeMaker, the internal architecture dictates that every element inherits from a base `Part` class (specifically `Node`, `Edge`, `Path`, `Poly`, and `Condition`). The AI Agent only needs to manipulate the "pre-compiled" parts (`Node`, `Edge`, `Path`, and `Condition`). The geometric compilation engine will handle the "post-compiled" parts (`Poly`, `Vertex`, `Crease`).

Here is a fleshed-out specification for your Agent's MCP Tools based directly on TreeMaker's mathematical and software model.


### A. Graph Formulation Tools (The "Stick Figure")

TreeMaker treats the model as a strict network of Nodes and Edges. Terminal nodes represent the tips of the flaps, while edges represent the flaps themselves.

- `init_paper(width: float, height: float)`
    
    - **Purpose:** Defines the dimensions of the paper canvas. While origami usually assumes a 1x1 square , TreeMaker’s math supports rectangles.
        
- `add_node(id: int, label: str, is_pinned: bool, x: float=null, y: float=null)`
    
    - **Purpose:** Creates a joint or flap tip.
        
    - **TreeMaker Mapping:** Nodes are uniquely identified by an integer index. The agent can use `is_pinned` and provide exact (x,y) coordinates if a specific point _must_ originate from a specific spot on the paper (like forcing the head to a corner).
        
- `add_edge(id: int, node_A: int, node_B: int, length: float)`
    
    - **Purpose:** Connects two nodes to define an appendage.
        
    - **TreeMaker Mapping:** The `length` parameter represents the relative desired length of the corresponding origami flap, not absolute screen coordinates.


### B. The Condition Tools (Mathematical Constraints)

This is the most critical addition based on the manual. TreeMaker relies heavily on "Conditions" applied to Nodes, Edges, and Paths to enforce symmetry and control how the tree packs into the square. Instead of a generic `set_symmetry` tool, the agent should have access to the exact constraints the TreeMaker solver expects.

- `add_condition(condition_type: string, targets: list[int])`
    
    - **Purpose:** Applies a structural constraint to the graph before compilation.
        
    - **Valid `condition_type` parameters based on TreeMaker's engine:**
        
        - `"NODES_SYMMETRIC"`: Takes two node IDs. Insures the two nodes (e.g., left leg, right leg) are perfect mirror images about the base's line of symmetry.
            
        - `"NODES_COLLINEAR"`: Takes three node IDs. Forces three nodes to lie on a straight line, which is useful for creating mathematically clean crease patterns.
            
        - `"EDGE_LENGTH_FIXED"`: Takes one edge ID. Forces an edge to have zero "strain" (prevents the compiler from shrinking/stretching the flap during optimization).
            
        - `"EDGES_SAME_STRAIN"`: Takes two edge IDs. Forces two separate flaps to stretch or shrink by the exact same proportion during optimization.
            
        - `"PATH_ACTIVE"`: Takes a path between two nodes. Forces the path's actual length on the paper to perfectly equal its mathematical minimum, guaranteeing that a main crease axis forms between those points.
            

### C. Execution & Compilation Tools (The Solver Pipeline)

TreeMaker solves origami in phases using nonlinear constrained optimization. The agent shouldn't just trigger one monolithic compile; it needs to step through TreeMaker's specific calculation phases to debug spatial errors.

- `run_scale_optimization(tree_json: dict)`
    
    - **Purpose:** The first pass of the compiler. It calculates the largest possible base that fits on the paper without flaps overlapping.
        
    - **Agent usage:** If this returns an exceptionally small "Scale" value (e.g., 0.05), the agent knows its limb lengths are physically impossible to pack efficiently and can adjust edge lengths before proceeding.
        
- `run_strain_optimization(tree_json: dict)`
    
    - **Purpose:** If the tree doesn't fit perfectly, TreeMaker introduces "strain" (elasticity) into the edges. This tool minimizes that strain to find a perfect fit.
        
- `relieve_strain(tree_json: dict)`
    
    - **Purpose:** Absorbs any remaining strain directly into the permanent length of the edges. The agent runs this to finalize the true proportions of the model.
        
- `generate_fold_file(optimized_tree_json: dict)`
    
    - **Purpose:** Triggers the final backend execution. TreeMaker calculates the "Universal Molecule" (the actual 2D polygons and mountain/valley creases) based on the optimized tree. Returns the strict `.fold` file.
        

### D. The Linter & Debug Tools

Once the C++ TreeMaker backend outputs the `.fold` file, the Java-based Oriedita engine takes over for static analysis.

- `validate_flat_foldability(fold_file: dict)`
    
    - **Purpose:** Programmatic sanity check.
        
    - **Agent usage:** If the engine returns an error like "Vertex 45 violates Kawasaki's Theorem," the agent must parse that the angles around Vertex 45 do not alternate sums to 180 degrees. The agent can then use `query_origami_theory("Kawasaki theorem violation fixes")` to learn how to add a dummy node/crease to resolve the dead-end geometry.
        

By structuring the MCP tools around `Nodes`, `Edges`, `Conditions`, and the specific step-by-step optimization routines (Scale -> Strain -> Relieve -> Build Polygons), you force the LLM to "think" exactly like TreeMaker's deterministic C++ engine.