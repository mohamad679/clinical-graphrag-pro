# Clinical GraphRAG Pro Enhancements (Phase 2)

## 1. Attachment Dropdown Menu & Functionality
- [x] Create an expandable dropdown menu anchored to the paperclip icon in `ChatInterface.tsx`.
- [x] Add menu options: "Upload Image", "Upload Document", and "Record Voice" (disabled).

## 4. UI Stabilization & Performance
- [x] Fix React rendering loop causing session message states to completely wipe themselves upon first response (changed structural `key` from UUID to incremental ID).
- [x] Add dynamic fetching for `getSession` inside `ChatInterface` to ensure historical loading returns.
- [x] Disengage `smooth` auto-scroll behavior explicitly during active server-sent event (SSE) streaming payload chunks to eliminate UI extreme lag.

## Remaining Implementation Items
- [x] Integrate document upload interface directly into the chat prompting image upload logic.
- [x] Display attached documents (PDF/word) in the preview area above the prompt.

## 2. API & Backend Enhancements
- [x] Ensure `sendMessageStream` payload correctly handles passing the attached document ID if a document is uploaded instead of an image.

## 3. UI Theme Adjustments
- [x] Locate global CSS file (`globals.css` / `index.css`) and change primary background variables from navy blue to black/deep dark gray to replicate premium chatbot themes.

## 5. Audio Integration (Phase 3)
- [x] **Backend API**: Create `POST /audio/transcribe` endpoint that accepts an audio upload, sends it to Groq's Whisper API (`whisper-large-v3`) with `language=en` (for translation/transcription), and returns the text.
- [x] **Frontend API Client**: Add `transcribeAudio` to `api.ts`.
- [x] **Frontend UI (Upload Audio)**: Change the "Record Voice" menu item to "Upload Audio". Allow users to select an audio file, send it for transcription, and paste the result into the chat input.
- [x] **Frontend UI (Live Record)**: Add a microphone button directly inside or next to the chat input field (like modern chatbots).
- [x] **Frontend State**: Implement `MediaRecorder` logic to capture microphone audio, show a recording active state (red dot/pulse), upload the blob when stopped, and inject transcribed text into the chat input prior to sending.

## 6. Phase 1: Agentic Foundation & Tool Registry
- [x] **Tool Abstraction Layer**: Create `backend/app/services/tools.py` to define strict Pydantic schemas and interface wrappers for existing capabilities (e.g., `SearchGraphTool`, `QueryDocumentsTool`).
- [x] **Base Agent Class**: Create `backend/app/services/agent.py` defining the core ReAct (Reasoning & Acting) loop that can accept a system prompt, tools, and maintain conversational memory.
- [x] **API Endpoint**: Add a new POST route in `backend/app/api/agents.py` to handle streamable agent task requests from the frontend.
- [x] **Frontend Integration**: Update `frontend/src/app/workflows/page.tsx` (or similar) and API client to connect to the new agentic endpoint, displaying the agent's thought process (Step -> Tool -> Observation).

## 7. Phase 2: Specialized Clinical Sub-Agents
- [x] **Agent Factory Pattern**: Refactor `agent.py` to allow instantiating differently-prompted sub-agents rather than a single monolithic ReAct agent.
- [x] **Data Extraction Agent**: Create an agent strictly prompted to extract lab values, dates, and entities from raw query/document strings into structured JSON.
- [x] **Pharmacovigilance Agent**: Create an agent with exclusive access to the `search_graph` and `drug_interaction` tools to check for cross-reactions.
- [x] **Differential Diagnosis Agent**: Create an agent that takes structured symptoms and uses clinical tools to generate weighted differential diagnoses.
- [x] **Orchestrator Coordination (Supervisor)**: Update the main `run` loop to act as a Supervisor, routing the user query to the appropriate sub-agent(s) and synthesizing their combined outputs.

## 8. Phase 3: Temporal Knowledge Graphs
- [x] **NetworkX Manager**: Create `backend/app/services/graph.py` wrapped around NetworkX that supports `start_date` and `end_date` edge properties.
- [x] **Temporal Querying**: Add graph traversal logic to find what edges/medications were active for a given entity on a specific date.
- [x] **Graph Persistence**: Implement load/save to local disk (e.g., GraphML) to ensure state survives reload.
- [x] **Tool Upgrade**: Upgrade `search_graph` in `tool_registry.py` to route through the real NetworkX temporal query engine.
- [x] **API Endpoints**: Wire up `/api/v1/graph/stats` and seed endpoints in `graph.py` to interact with the live graph.

## 9. Phase 4: Automated Verification & Calibration
- [x] **Adjudicator Prompt**: Refactor `clinical_eval` in `tool_registry.py` to use a heavy "Red Team" LLM prompt for safety/hallucination checking.
- [x] **Agent Intercept**: Modify `agent.py` to pause after Synthesis, draft the answer internally, and run it through `clinical_eval`.
- [x] **Verification Event**: Create a new SSE event `verification` that tells the frontend if the draft was Approved or Rejected.
- [x] **Calibration Enforcement**: If the Adjudicator rejects the draft, force the agent to apologize and explicitly state what data was missing/hallucinated, refusing to provide the unsafe draft.

## 10. Phase 5: 3D Knowledge Graph Visualization
- [x] **Dependencies**: Install `react-force-graph-3d` and `three` in the frontend.
- [x] **Backend API**: Add `export_for_visualization()` in `graph.py` and a `GET /api/v1/graph/visualize` endpoint.
- [x] **API Client**: Add `getGraphVisualization()` to `api.ts`.
- [x] **Frontend Component**: Create `GraphPanel.tsx` that renders the 3D graph, color-coding nodes by type.
- [x] **Integration**: Replace the inline `GraphView` in `page.tsx` with `<GraphPanel />`.

## 11. Phase 6: Clinical Data Ingestion
- [x] **Data Modeling**: Define 3 highly realistic synthetic patient profiles with interconnected diseases and medications.
- [x] **Seed Script**: Create `backend/scripts/seed_mimic.py` to programmatically inject nodes/edges into `TemporalGraphService` and text into `VectorStoreService`.
- [x] **Execution**: Run the seed script to permanently populate the backend directories.

## 12. Phase 7: Production Deployment
- [ ] **GitHub Sync**: Commit all Phase 5 and Phase 6 changes and push to `origin/main` to trigger Vercel deployment.
- [ ] **Hugging Face Deployment**: Push the updated backend Docker container code (including the Temporal Graph data) to the Hugging Face Space remote.
