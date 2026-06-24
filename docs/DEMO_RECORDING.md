# Demo Recording Guide

This guide describes how to capture a polished, high-impact 60-90 second demo of the Clinical GraphRAG Pro platform. It focuses on demonstrating the hardened agent workflow, safety gates, dynamic light/dark theme, multi-tenant patient graph filters, and markdown report downloads.

> [!WARNING]
> **API Secrets Protection**: 
> Never record or commit any environment files (`.env`), terminal inputs containing raw JWT tokens, API keys, or database credentials. Clean your screen history and environment before starting the recording.

---

## 1. Setup & Preparation

Before starting the recording, ensure the environment is fully clean and bootstrapped:

1. **Clear current DB and Seed**:
   ```bash
   make demo
   ```
2. **Start the Stack**:
   ```bash
   make build
   make up
   ```
3. **Browser Setup**:
   - Open a fresh browser window and go to `http://localhost:3000`.
   - Log in using the admin account (bootstrapped default: `admin@clinicalgraph.ai`).

---

## 2. 60-90 Second Screen Recording Walkthrough Script

Aim for a smooth, continuous sequence:

### Step 1: Dark/Light Mode Theme Toggle (0 - 15s)
- **Action**: Locate the **🌓 Theme** toggle button at the bottom of the sidebar.
- **Action**: Click the theme toggle multiple times to demonstrate instant, flicker-free rendering between Dark Mode and Light Mode. Leave the UI in your preferred theme.
- **Narrative context**: "We've added a robust local storage persisted light/dark mode system that supports instant theme switching across all views without render flashing."

### Step 2: Chat Interface & Badged Citations (15 - 30s)
- **Action**: Navigate to the **Clinical Chat** page.
- **Action**: Click one of the recommended clinical query prompts or type:
  `What are the active diagnoses and current medications for patient pat-100?`
- **Action**: Let the model stream the response. Point out the inline **citation pills** (e.g. `[DOC1]`, `[GRAPH-COND-001]`) that have been parsed into styled badges.
- **Action**: Click on the **Download Report** button at the top toolbar of the chat interface to compile and export the session history, metrics, and safety disclaimer as a Markdown file.

### Step 3: Scoped Knowledge Graph Filtering (30 - 45s)
- **Action**: Navigate to the **Knowledge Graph** workspace.
- **Action**: Point out the default force-directed graph.
- **Action**: Enter `pat-100` into the new **Patient ID Scope** input field inside the stacked search panel and click **Filter**.
- **Action**: The graph will reload and display ONLY nodes and edges directly connected to `pat-100` (Patient, Medication, and Observation entities).
- **Action**: Toggle the Light/Dark theme once again while in the graph view to show that D3 node outlines, edge lines, and labels dynamically shift contrast to maintain perfect readability in both modes.

### Step 4: Hardened Agent Workflow & Abstention (45 - 60s)
- **Action**: Navigate to the **Agent Workflow** workspace.
- **Action**: Submit an out-of-scope query like:
  `What is the patient's orbital space telemetry reading?`
- **Action**: Watch the agent execution trace stream. Point out the critic evaluator verdict showing `ABSTAINED` due to `INSUFFICIENT_EVIDENCE`.
- **Action**: Click the **Download Report** button next to the agent workflow header to export the full trace, reasoning steps, tool usage details, and outcome metrics to a Markdown report.

---

## 3. Post-Recording Review Checklist

Verify the following before submitting or publishing your recording:
- [ ] No API keys, passwords, or credentials visible in terminal outputs.
- [ ] Interface transitions are smooth and latency stats are legible.
- [ ] Inline citation pills render correctly as teal/mint-colored badges.
- [ ] Report downloads execute successfully on button clicks.
