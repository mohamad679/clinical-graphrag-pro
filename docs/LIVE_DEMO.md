# Live & Offline Demo Guide

This document details how to run the end-to-end clinical GraphRAG query demo in either an offline (retrieval-only) mode or a live (LLM-integrated) mode.

---

## A. Retrieval-Only (Offline) Mode
**No API key required.** This mode runs entirely locally, bypassing the LLM generation phase and directly returning formatted summaries of the retrieved context documents alongside grounded citations.

### 1. Requirements
- Python virtual environment set up (`make install`)
- A populated FAISS/SQLite vector and DB index (automatically bootstrapped during the demo)

### 2. Execution Command
Run the offline demo using the Makefile shortcut:
```bash
make demo-offline
```
Or run the CLI directly:
```bash
.venv/bin/python scripts/run_live_demo.py --provider retrieval-only
```

### 3. Expected Outputs
- Running the script will trigger three test queries on synthetic patient data.
- The execution results, retrieved chunks, and metadata will be saved to:
  - `reports/live_demo_retrieval-only.json`
  - `reports/live_demo_retrieval-only.md`

---

## B. Live Google Gemini Mode
**Requires a valid Google Gemini API Key.** This mode executes the full end-to-end RAG pipeline, making actual REST requests to the Google Gemini API to synthesize medical decision-support answers with grounded inline citation markers.

### 1. Requirements & Configuration
You must configure your API key in your environment or local `.env` file. The service accepts either `GEMINI_API_KEY` or `GOOGLE_API_KEY`.

#### Option 1: Via Environment Variables
```bash
export GEMINI_API_KEY="<set-your-key-in-your-shell-or-secret-manager>"
```

#### Option 2: Via `.env` File
Create or modify your `.env` file in the root directory:
```env
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash
GEMINI_API_KEY=<set-your-key-in-your-local-env-file-only>
```

### 2. Execution Command
Run the live Gemini demo:
```bash
make demo-live-google
```
Or run the CLI directly:
```bash
.venv/bin/python scripts/run_live_demo.py --provider gemini --model gemini-2.0-flash
```

### 3. Expected Outputs
- The system will connect to the Generative Language API, verify credentials via a health check, and execute the three test queries.
- Detailed execution metrics and clinical answers will be compiled under:
  - `reports/live_demo_gemini.json`
  - `reports/live_demo_gemini.md`

---

## C. Live Ollama Mode
**Requires a locally running Ollama instance.** This mode routes RAG generation to a local model runner, preserving complete data privacy without sending medical data over the internet.

### 1. Requirements & Setup
1. Download and install [Ollama](https://ollama.com).
2. Start the Ollama background service:
   ```bash
   ollama serve
   ```
3. Pull the model you want to use (e.g. `llama3`):
   ```bash
   ollama pull llama3
   ```

### 2. Execution Command
Run the live Ollama demo:
```bash
make demo-live-ollama
```
Or run the CLI directly:
```bash
.venv/bin/python scripts/run_live_demo.py --provider ollama --model llama3
```

---

## D. Troubleshooting

### 1. "Could not connect to Ollama server"
- **Cause:** Ollama service is not running or is bound to a different port.
- **Fix:** Run `ollama serve` or configure your custom URL using `OLLAMA_URL` in `.env`.

### 2. "Google Gemini API key is missing"
- **Cause:** Neither `GEMINI_API_KEY` nor `GOOGLE_API_KEY` was found in `.env` or system environment variables.
- **Fix:** Run `echo $GEMINI_API_KEY` to verify it's exported, or check that your `.env` is loaded correctly.

### 3. Credentials leaking in logged URLs
- **Fix:** Gemini calls are secured via header-based authentication using `x-goog-api-key`. Verify that request paths in debug logs do not append `?key=...`.
