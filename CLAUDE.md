# System Architecture Blueprint

This file details the project scope and architecture.

> **TreeMaker codebase reference:** For build commands, source layout, C++ conventions, and internal architecture of the TreeMaker compiler component, see [`treemaker_documentation.md`](treemaker_documentation.md).

## 1. Executive Summary & Core Challenge

**The Project:** An interactive, AI-driven Integrated Development Environment (IDE) for designing complex origami models. It operates like a conversational CAD tool where a user can dictate an anatomical concept, and the system outputs a mathematically perfect, foldable crease pattern alongside a 3D physical simulation.

**The Challenge:** Unlike traditional 3D CAD, origami is strictly constrained by the physical reality of a single, uncut flat sheet of paper. Large Language Models (LLMs) cannot reliably generate raw geometric coordinates without hallucinating physics-breaking errors.

**The Solution:** We separate Biological Intent from Rigid Geometry and Physics. The AI Agent acts as an orchestrator that translates natural language and images into an abstract "Stick Figure" (a Metric Tree). A deterministic C++ engine (TreeMaker) acts as the **Compiler** to generate geometry, a Java solver (Oriedita) acts as the **Static Linter** to validate the math, and a WebGL engine (Origami Simulator) acts as the **Runtime Visualizer** to prove physical foldability.

## 2. Core Data Structures: "Source Code" vs. "Compiled Output"

To prevent AI hallucinations, the system relies on a strict compiler-like data flow between two formats:

- **The Metric Tree (The "Source Code"):** An abstract JSON graph representing the subject's anatomy. It contains Nodes (joints/flap tips), Edges (the proportional lengths of limbs), and Constraints (e.g., bilateral symmetry). **This is the ONLY data structure the AI edits.**
    
- **The `.fold` File (The "Compiled Executable"):** The universal JSON standard for origami geometry. It contains the exact 2D coordinate vertices, mountain/valley assignments, and 3D folding state. The AI never touches this; it is generated strictly by the deterministic math backends.
    

## 3. The Three-Tier System Architecture

### Tier 1: The Frontend Viewport (Client-Side)

A web-based interface (React) that facilitates human-in-the-loop interaction and visualization.

- **Chat Terminal:** The conversational interface where the user prompts the agent.
    
- **Concept Art Board:** Displays 3D/2D concept images generated during the planning phase.
    
- **The Viewport (Powered by Origami Simulator):** An embedded WebGL/GPU-accelerated physics engine. It reads the final `.fold` file output and simulates the physical folding process from 0% to 100% in real-time, treating creases as hinges and paper faces as rigid bodies.
    

### Tier 2: The AI Orchestrator (The Agentic Loop)

A Python/Node-based AI runtime powered by a multimodal LLM (e.g., Claude 3.5 Sonnet, GPT-4o). It does not calculate folding math; it plans, uses tools, and debugs.

- **Knowledge Base (RAG):** The agent has vectorized access to Robert J. Lang's TreeMaker 4.0 Manual and origami design theory.
    
- **Tool Harness (MCP Skills):** The agent is equipped with tools to build trees and trigger the compiler and validation pipelines (detailed in Section 4).
    

### Tier 3: The Geometry & Validation Backend (Cloud Services)

A dual-engine headless cloud architecture handling geometry generation and mathematical proofs.

- **The Compiler (TreeMaker / C++):** Receives the Metric Tree and runs Circle/River Packing (nonlinear optimization to fit required flaps onto a square). It then runs the Universal Molecule algorithm to draw the exact crease lines, outputting the initial `.fold` file.
    
- **The Static Linter (Oriedita / Java API):** Receives the `.fold` file from TreeMaker. It rigorously checks the Maekawa and Kawasaki theorems (the absolute laws of flat-foldability) and deduces any missing mountain/valley alignments, ensuring the math is flawless before it reaches the physics simulator.
    

## 4. The Agent's Tool Harness (MCP Skills)

To bridge the AI with the backend engines, the agent uses a suite of Model Context Protocol (MCP) tools:

### A. Tree Drafting Tools (Graph Manipulation)

- `init_paper(width, height)`: Defines the starting canvas.
    
- `add_node(id, type)`: Creates a body part (e.g., `front_left_leg_tip`).
    
- `add_edge(node_A, node_B, weight)`: Connects parts and sets their proportional length.
    
- `set_symmetry(axis, node_pairs)`: Enforces mathematical mirroring.
    

### B. Execution & Validation Tools (Compiler & Linter Hooks)

- `compile_treemaker_math(tree_json)`: Sends the tree to the C++ backend for Circle Packing optimization. Returns success metrics or spatial errors (e.g., "Circles overlap").
    
- `generate_fold_file()`: Triggers the C++ backend to calculate the Universal Molecule and write the initial `.fold` geometry file.
    
- `validate_flat_foldability(fold_file)`: Passes the file to the headless **Oriedita API** to perform a programmatic sanity check of the Maekawa/Kawasaki theorems. Returns either a "Pass" or specific vertex math errors (e.g., "Vertex 45 violates Kawasaki's theorem by 2 degrees").
    

### C. Context Tools

- `query_origami_theory(search_term)`: Searches domain-specific rules (e.g., "How to force an edge flap").
    

## 5. The End-to-End Execution Flow (Query to Output)

When a user submits a novel prompt—e.g., "Design a water bear (tardigrade)"—the system executes a 5-step multimodal loop:

### Step 1: The Concept Art Phase (Text-to-Image)

- **Action:** The Agent calls an image generation API to create a simple, non-origami concept image of a water bear.
    
- **Human-in-the-Loop:** The UI displays the concept image to the user for approval regarding anatomy and proportions.
    

### Step 2: Vision-to-Tree Parsing (Multimodal Translation)

- **Action:** The Agent passes the approved concept image into its multimodal vision model.
    
- **Analysis & Drafting:** The AI measures relative limb proportions and autonomously writes the `add_node()` and `add_edge()` commands to construct the Metric Tree representing the visual data.
    

### Step 3: The Reality Check (UI Update)

- **Action:** The UI displays the generated "Stick Figure" (Metric Tree) next to the Concept Art, showing how the biological request maps to an origami graph.
    

### Step 4: The Compilation & Debugging Loop (TreeMaker + Oriedita)

- **Action:** The Agent calls `compile_treemaker_math()`.
    
- **Spatial Debugging:** If the 8 thick legs take up too much paper, TreeMaker returns a packing error. The Agent autonomously scales down leg edge weights using MCP tools and recompiles until a spatial optimum is found.
    
- **Geometric Generation:** Once packed, the Agent calls `generate_fold_file()` to create the crease polygons.
    
- **Axiomatic Linting:** The Agent immediately calls `validate_flat_foldability()`. If the Oriedita engine detects floating-point anomalies or missing mountain/valley assignments that break the Kawasaki/Maekawa theorems, it feeds the specific vertex errors back to the Agent for adjustment.
    

### Step 5: Final Render & Physics Simulation (Origami Simulator)

- **Action:** The fully mathematically verified `.fold` file is streamed to the user's browser.
    
- **Render:** The embedded **Origami Simulator** takes over in the Viewport. It visualizes the flat crease pattern and physically animates the paper collapsing into the 3D water bear base, proving to the user that the design is mathematically flawless and perfectly foldable in the real world.

## 6. Future Enhancements & Optimization: The Heuristic "World Model"

_(Inspired by the neuro-symbolic approach of the Learn2Fold research paper)_

**The Bottleneck:** In the v1 architecture, the AI Orchestrator passes its generated Metric Tree directly to the C++ TreeMaker engine (Step 4). If the AI drafts physically impossible proportions (e.g., 10 massive legs radiating from a tiny central node), the deterministic engine must execute a computationally expensive circle-packing optimization sequence just to eventually fail and return an error. Over multiple debugging iterations, this creates severe latency for the user.

**The Solution (Tier 2.5):** To improve system speed and reduce compute costs, a lightweight heuristic checker (a surrogate "World Model") will be inserted between the AI Agent and the C++ Compiler to act as a high-speed gatekeeper.

- **The Fast Pass:** A trained, lightweight machine learning model (e.g., a simple neural network or XGBoost model) will instantly evaluate the topological graph of the Metric Tree. Instead of doing the exact geometry math, it will return a probability score (e.g., "12% chance of success: Edge weights likely exceed paper boundary").
    
- **Agentic Pre-computation:** The Agent's Tool Harness will be expanded to include `predict_tree_feasibility(tree_json)`. If the checker returns a low score, the Agent can iteratively shrink or adjust the proportions in milliseconds, entirely bypassing the heavy C++ backend.
    
- **The Shielded Compiler:** The deterministic C++ engine will only execute on Metric Trees that have passed the heuristic check, drastically reducing the time it takes to return a final `.fold` file to the user viewport.
    

**Bootstrapping the Training Data:** Because no public dataset exists for predicting Metric Tree flat-foldability, the heuristic model will be trained using synthetic data generated by the IDE itself:

1. **Generation:** A headless script will rapidly generate hundreds of thousands of randomized Metric Trees (varying node counts, edge weights, and symmetries).
    
2. **Brute-Force Labeling:** The Tier 3 C++ compiler will process every random tree, labeling each graph as a `Success` or `Failure` based on whether the circles successfully packed into a square.
    
3. **Training:** The resulting dataset will be used to train the heuristic checker, effectively teaching a fast AI model the hidden mathematical boundaries of deterministic circle packing.
