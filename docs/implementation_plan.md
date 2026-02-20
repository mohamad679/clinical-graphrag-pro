# Implementation Plan: Multimodal Upload Menu & True Dark Theme

## Goal Description
1. Replace the single "paperclip" upload action with a popup menu containing three options: Upload Image, Upload Document, and Record Voice (disabled).
2. Allow users to upload both images and documents directly from the chat prompt.
3. Update the global application theme from navy blue (`#0f172a`) to a pure dark/black theme (`#000000` or `#0a0a0a`), matching premium styling like ChatGPT.


## Proposed Changes

### Frontend (User Interface)
#### [MODIFY] `frontend/src/app/globals.css`
- Update CSS variables for `--bg-*` and `--border-*` to use pure black and very dark gray shades instead of the current `slate` (navy) palette.

#### [MODIFY] `frontend/src/components/ChatInterface.tsx`
- **State**:
    - Add boolean state `isMenuOpen` to toggle the attachment menu popup.
    - Generalize `attachedImage` to `attachedFile` which can hold either Image or Document metadata (`{ id, name, type: 'image' | 'document' }`).
- **Icons**: Add specific icons for Image, Document, and Microphone inside the menu dropdown.
- **Inputs**: Add a secondary hidden `<input type="file" />` specifically configured for documents (`.pdf`, `.docx`, `.txt`), separate from the image input.
- **Functions**: Map the "Upload Document" button in the menu to trigger the document input, which then calls `uploadDocument(file)` from `api.ts`.
- **UI Render**: Render a small absolute positioned hovering menu above the paperclip when clicked. Map the "Voice" option to a disabled button with a visual indicator.

### Backend Routing (Context Verification)
#### [MODIFY] `backend/app/api/chat.py`
- *Self-correction/Verification*: Ensure the chat endpoint processes `attached_document_id`. If `attached_document_id` is provided, we need to instruct the RAG query engine to specifically filter results to *only* search that specific document ID, preventing vector leakage from other uploaded PDFs.

## Verification Plan
1. Start the React frontend and test clicking the paperclip icon.
2. Verify the popup menu opens and looks visually consistent with the new pure black theme.
3. Test uploading a dummy PDF and an Image sequentially via the new menu to ensure both inputs route their payloads correctly.
4. Verify the voice button is visually present but unclickable.

## Audio Integration (Phase 3)

### Goal Description
Enable users to upload audio files or record voice directly in the browser. The audio will be sent to the backend, transcribed (and translated to English) using Groq's Whisper model (`whisper-large-v3`), and the resulting text will be injected into the user's chat input area for review before sending.

### Backend Changes
#### [NEW] `backend/app/api/audio.py`
- Create a new FastAPI router with a `POST /transcribe` endpoint.
- Accept an `UploadFile` (audio blob/file).
- Use `httpx` to send the audio file to `https://api.groq.com/openai/v1/audio/translations` with the model `whisper-large-v3`.
- The `translations` endpoint automatically translates any language to English.
- Return the transcribed text.
#### [MODIFY] `backend/app/main.py`
- Include the new `audio.router`.

### Frontend Changes
#### [MODIFY] `frontend/src/lib/api.ts`
- Add an `uploadAudioForTranscription(file: File): Promise<string>` function.
#### [MODIFY] `frontend/src/components/ChatInterface.tsx`
- **Menu Option**: Change "Record Voice" to "Upload Audio" and wire it to a hidden `<input type="file" accept="audio/*" />`.
- **Live Recording UI**: Add a Microphone icon button directly inside the chat input container (next to the send/paperclip buttons).
- **Audio State**: Add state `isRecording` (boolean) and `mediaRecorderRef` (ref).
- **Recording Logic**: Use the browser's `navigator.mediaDevices.getUserMedia({ audio: true })` API to capture audio chunks.
- **Stop Logic**: When stopped, create a `File` or `Blob` from the chunks, call the API, and append the returned text to the `input` state.
- **Styling**: Add a pulsing red dot animation while recording to indicate active capture.

---

## Phase 1: Agentic Foundation & Tool Registry

### Goal Description
Lay the groundwork for Autonomous Agents by decoupling our current monolithic LLM service into modular, self-acting ReAct (Reasoning and Acting) loops. Agents require "Tools" to interact with the system (like extracting data or searching the graph). We will build the Tool Registry and a Base Agent Orchestrator that can dynamically select tools to accomplish a complex clinical task.

### Backend Changes
#### [NEW] `backend/app/services/tools.py`
- Define a base `Tool` interface (Name, Description, Input Schema).
- Implement `QueryDocumentsTool`: Wraps `qdrant_service.search`.
- Implement `SearchGraphTool`: Wraps `graph_service.search_knowledge_graph`.
- Implement `ClinicalEvalTool`: Wraps a basic LLM prompt to review an answer for safety/faithfulness.

#### [NEW] `backend/app/services/agent.py`
- Implement a `ReActAgent` class using `langchain` paradigms (or custom native async logic).
- It takes a `System Prompt`, `[Tools]`, and a user task.
- It loops: 
  - `Thought`: What should I do next?
  - `Action`: Which tool do I use? (Output as structured JSON)
  - `Observation`: The result of the tool execution.
- Emits real-time SSE (Server-Sent Events) for each `Thought` and `Action` step so the frontend can stream it.

#### [MODIFY] `backend/app/api/agents.py`
- Update the existing placeholder router to accept a `task` string.
- Instantiate the `ReActAgent` with the core clinical tools.
- Return a `StreamingResponse` yielding the agent's internal monologue and final answer.

### Frontend Changes
#### [MODIFY] `frontend/src/app/(dashboard)/workflows/page.tsx`
- Build an "Agent Terminal" UI.
- Instead of standard chat, the UI will display an expanding tree of the agent's live thought process.
  - E.g., `[Thinking] -> [Using Tool: SearchGraph] -> [Found 3 Results] -> [Synthesizing]`.
- Connect to the new `/api/v1/agents/task` streaming endpoint.

---

## Phase 2: Specialized Clinical Sub-Agents

### Goal Description
With the foundation of the Tool Registry and base ReAct loop in place, we will implement the **Supervisor-Worker Agent Architecture**. Instead of one monolithic LLM trying to do everything, we will create rigidly prompted "Expert" sub-agents (Workers) that are orchestrated by a lead "Supervisor" agent.

### Backend Changes

#### [MODIFY] `backend/app/services/agent.py`
- **Agent Factory**: Refactor the `AgentOrchestrator` to support specialized sub-agent prompts. 
- Implement **Three Sub-Agents**:
  1. `DataExtractionAgent`: Prompted specifically to parse messy clinical narratives into structured JSON (vitals, meds, history). Accesses no external tools, acts purely as an NLP parser.
  2. `PharmacovigilanceAgent`: Specializes purely in medication safety. Prompted to *only* use the `drug_interaction` and `search_graph` tools to identify adverse events.
  3. `DiagnosticsAgent`: Prompted to generate Differential Diagnoses with confidence scores based on extracted symptoms.
- **Supervisor Routing**: Modify `_generate_plan` to act as the Supervisor. When a query is received, the Supervisor decides *which* sub-agent should handle the task, explicitly invoking them in sequence or parallel, aggregating their insights, and doing the final medical synthesis.

### Frontend Changes
- The frontend `WorkflowPanel.tsx` is already built to intercept SSE `reasoning` and `tool_call` tokens. 
- The SSE stream payload will be enriched to include `agent_name` (e.g., `[Pharmacovigilance Agent] is checking drug interactions...`) so the user can see *which* specialist is active.

---

## Phase 3: Temporal & Dynamic Knowledge Graphs

### Goal Description
Standard RAG systems treat documents and knowledge as a static snapshot. Real clinical data is incredibly chronological. We will upgrade the system from a static vector store to a **Temporal Knowledge Graph (TKG)**. The system will use NetworkX to store entities (Patients, Drugs, Diseases) and relationships (TREATS, HAS_CONDITION) that are bound by `start_date` and `end_date`.

### Backend Changes

#### [NEW] `backend/app/services/graph.py`
- Create a `TemporalGraphService` using `networkx`.
- **Add methods**:
  - `add_entity(node_id, label, properties)`: E.g., adding "Hypertension" or "Lisinopril".
  - `add_temporal_relation(source, target, relationship_type, start_date, end_date)`: E.g., `(PatientX)-[TOOK_MEDICATION {start: 2022, end: 2024}]->(Lisinopril)`.
  - `query_temporal_state(node_id, target_date)`: Given a date, returns the sub-graph of active conditions and medications for that entity on that exact date.
- Add persistence (saving the NetworkX graph to a `.graphml` or `.gpickle` file in the database directory so it survives restarts).

#### [MODIFY] `backend/app/services/tool_registry.py`
- Update the `search_graph` tool to accept temporal parameters (`target_date`). 
- Replace the mock response with actual calls to `TemporalGraphService.query_temporal_state()`.

#### [MODIFY] `backend/app/api/graph.py`
- Enhance the `graph_stats` endpoint to return the actual count of nodes and edges in the NetworkX graph.
- Add an endpoint `POST /graph/entities` to manually seed/add data to the graph for testing.

---

## Phase 4: Automated Verification & Calibration

### Goal Description
Safety is the biggest hurdle for clinical AI. We need deterministic "Calibration"—the AI must know what it does not know. Before the user sees any final answer from the Supervisor Agent, an invisible "Adjudicator" (Adversarial Critic) model will review the drafted response against the retrieved source documents specifically hunting for contradictions, hallucinations, or unsafe medical advice.

### Backend Changes

#### [MODIFY] `backend/app/services/agent.py`
- Step 4 (Synthesis) currently streams directly to the user. We will intercept the synthesis.
- After synthesis, pass the assembled `draft_response` and the `context` to the `ClinicalEvalTool`.

#### [MODIFY] `backend/app/services/tool_registry.py`
- Refactor `tool_clinical_eval` to invoke `llm_service.generate()` with an adversarial "Red Team" prompt.
- The Adjudicator should output a rigid JSON: `{"status": "APPROVED", "confidence_score": 0.95, "flags": []}` or `{"status": "REJECTED", "flags": ["Hallucinated drug dose"]}`.

#### [MODIFY] `backend/app/api/agents.py` & `frontend/src/components/WorkflowPanel.tsx`
- Emit a new `"type": "verification"` SSE event. 
- If `APPROVED`, emit the final answer. 
- If `REJECTED`, the Supervisor refuses to answer and outputs: "Insufficient clinical evidence to safely answer this query. Flags: [reasons]".

---

# Roadmap to 2026: Achieving State-of-the-Art (SOTA) in Clinical AI

To elevate **Clinical GraphRAG Pro** from a powerful multimodal AI to a 2026 industry-leading platform (surpassing generic models and standard RAG paradigms), the system architecture must evolve towards **Autonomous Agentic Orchestration**, **Predictive Multimodality**, and **Continuous Verification**. 

Here are the highest-impact architectural additions to dominate the 2026 Clinical AI space:

## 1. Multi-Agent Clinical Orchestration (Agentic Workflows)
Currently, the AI acts as a smart "Oracle" (you ask, it retrieves and answers). By 2026, SOTA systems will be **active collaborators**.
- **The Upgrade**: Implement a multi-agent framework (e.g., using LangGraph or AutoGen) where specialized sub-agents operate under a "Lead Physician Agent."
- **How it works**: When a user uploads a clinical trial document, the system spins up:
  1. A *Data Extraction Agent* to pull tabular lab values.
  2. A *Pharmacovigilance Agent* to cross-reference extracted drugs against the Knowledge Graph for unknown interactions.
  3. A *Differential Diagnosis Agent* to propose alternative diagnoses based on the symptoms.
- **Why it's SOTA**: It moves the system from "Question Answering" to "Autonomous Task Completion" (e.g., "Analyze this patient history and generate a pre-authorization insurance appeal letter").

## 2. Temporal & Dynamic Knowledge Graphs
Current GraphRAG systems are largely static (nodes connect to edges). Medical data, however, is intensely chronological.
- **The Upgrade**: Upgrade the Neo4j/NetworkX graph to a **Temporal Knowledge Graph (TKG)**.
- **How it works**: Nodes and edges gain "validity timeframes" (e.g., Patient X *had* hypertension from 2020-2023). 
- **Why it's SOTA**: The LLM will be able to perform complex chronological reasoning. Instead of just knowing a patient took a drug, it can answer: *"Did the onset of acute kidney injury occur within 14 days of starting the ACE inhibitor?"* This requires native temporal graph traversal—a massive leap over current standard RAG.

## 3. Real-Time Multimodal Streaming (Vision + Audio + Text)
The current pipeline processes audio, then text, then image sequentially. 2026 SOTA requires native, synchronous multimodal streaming.
- **The Upgrade**: Integrate natively multimodal models (like the forthcoming open-source equivalents to GPT-4o or Gemini 1.5 Pro) that accept interleaved audio, video, and text in the same token stream.
- **How it works**: A clinician could hold their phone recording an operation, speak verbally *"What is this lesion here?"* while pointing a camera, and the LLM processes the video frames and the spoken audio track simultaneously in real-time.
- **Why it's SOTA**: Eliminates the latency of transcribing audio to text first. The model "hears" the tone of voice (e.g., patient distress) and "sees" the clinical presentation simultaneously, achieving true zero-shot clinical reasoning.

## 4. Federated Fine-Tuning Labs & Differential Privacy
Hospitals cannot share patient data (HIPAA). Therefore, the best AI in 2026 will be the one that learns from *every* hospital without ever seeing the raw data.
- **The Upgrade**: Evolve the current "Fine-Tune" tab into a **Federated Learning Node**.
- **How it works**: Instead of sending data to a central server, the base model is downloaded to the local hospital's secure enclave. The hospital fine-tunes the model on their specific patient data. Then, only the cryptographic *weight updates* (the mathematical learnings) are encrypted and sent back to the master Clinical GraphRAG model using Differential Privacy.
- **Why it's SOTA**: This solves the medical AI data bottleneck. The platform becomes a hive-mind that gets smarter from thousands of hospitals' data, while guaranteeing zero PHI (Protected Health Information) leakage.

## 5. Automated "Red Teaming" & Calibration Error Boundaries
Safety is the #1 block to clinical AI adoption. Currently, your Evaluation tab measures Faithfulness. 
- **The Upgrade**: Implement an internal "Adversarial Critic" model.
- **How it works**: Before *any* answer is shown to the user, an invisible second LLM (the Adjudicator) reviews the generated answer against the retrieved documents specifically trying to find contradictions, lethal medical advice, or hallucinations. If the Adjudicator flags the answer, the system refuses to answer and outputs "Insufficient clinical evidence."
- **Why it's SOTA**: This achieves mathematical "Calibration"—the AI actively knows what it does *not* know. Medical boards and FDA regulatory approvals will require this level of deterministic safety gating by 2026.

---

## Phase 5: 3D Knowledge Graph Visualization

### Goal Description
Transform the placeholder "Knowledge Graph" tab into an interactive, 3D visual experience using `react-force-graph-3d`. This provides a massive "wow" factor for a portfolio piece, allowing users to visually fly through clinical entities (drugs, symptoms, diseases) and their relationships.

### Backend Changes
#### [MODIFY] `backend/app/services/graph.py`
- Add a new method `export_for_visualization()` to `TemporalGraphService` that iterates over networkx nodes/edges and returns a dictionary with `{"nodes": [], "links": []}` suited for ForceGraph.
#### [MODIFY] `backend/app/api/graph.py`
- Add a new `GET /visualize` endpoint that calls `export_for_visualization()`.

### Frontend Changes
#### [NEW] `frontend/src/components/GraphPanel.tsx`
- Build a new component to replace the inline `GraphView` in `page.tsx`.
- Integrate `react-force-graph-3d` to render the nodes and links. Color-code nodes by type (e.g., Disease = Red, Drug = Blue, Patient = Green). Add 3D text labels above nodes for easy reading.
#### [MODIFY] `frontend/src/lib/api.ts`
- Add an API function `getGraphVisualization()` to fetch the nodes and links.
#### [MODIFY] `frontend/src/app/page.tsx`
- Replace the inline `GraphView` with the new `<GraphPanel />` component.

---

## Phase 6: Clinical Data Ingestion (MIMIC-IV Synthetic)

### Goal Description
A Knowledge Graph is only as impressive as its data. We will create a Python script to seed the database with complex, highly realistic synthetic patient profiles modeled after the MIMIC-IV dataset schema. This will populate the 3D visualizer with a dense web of interactions and give the RAG agents substantial medical text to reason over.

### Backend Changes
#### [NEW] `backend/scripts/seed_mimic.py`
- Create a standalone Python script that can be executed from the terminal.
- Define 3-4 complex patient personas (e.g., a patient with Diabetic Ketoacidosis, a patient with a Myocardial Infarction, etc.).
- The script will simultaneously:
  1. Push long-form clinical summaries (Admission Notes, Discharge Summaries) into the `vector_store_service`.
  2. Push explicit entities (Patients, Drugs, Diseases, Labs) and temporal edges into the `temporal_graph_service`.
- Add a new endpoint to trigger this if needed, or simply run it directly via the CLI.
#### [MODIFY] `backend/app/api/graph.py`
- Modify or add a `/seed-realistic` endpoint to trigger the script programmatically if preferred.
