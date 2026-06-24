# Local LLM Integration

Clinical GraphRAG Pro supports running reasoning pipelines on local models, ensuring zero-cost operations and high data privacy.

---

## 1. Supported Local Engines

- **Ollama**: Connects to an active Ollama instance (default: `http://localhost:11434`). Start via `ollama serve` and fetch models via `ollama pull <model_name>`.
- **llama.cpp**: Connects to the OpenAI-compatible server endpoints of llama.cpp (default: `http://localhost:8080`).
- **Local Hugging Face (local_hf)**: Disabled / Not implemented. Real Hugging Face local execution is not supported to avoid ungrounded simulated answers.

---

## 2. Configuration Settings

Modify the following environment variables in your `.env` or `backend/.env` file:

```env
# Select your provider
LLM_PROVIDER=ollama  # options: groq | gemini | ollama | llama_cpp | local_hf

# Specify the model name
LOCAL_LLM_MODEL=llama3  # or mistral, phi3, etc.

# Override server URLs if non-default
OLLAMA_URL=http://localhost:11434
LLAMA_CPP_URL=http://localhost:8080
```

---

## 3. Health Checks
The `/api/health/detailed` endpoint automatically queries the active local model server to ensure it is healthy and responsive. If connection fails, it registers the backing LLM service as degraded or unhealthy.

---

## 4. Setting up Ollama
To run the project with Ollama:
1. Make sure the Ollama daemon is running:
   ```bash
   ollama serve
   ```
2. Pull the model defined in `LOCAL_LLM_MODEL`:
   ```bash
   ollama pull llama3
   ```
3. Run the live demo using Ollama:
   ```bash
   make demo-live-ollama
   ```
