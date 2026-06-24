# Model Quantization

Using quantized models is highly recommended when running Clinical GraphRAG Pro on consumer-grade hardware.

---

## 1. Benefits of Quantization

- **Memory Reduction**: Running an unquantized 7B parameters model requires ~14GB VRAM. 4-bit quantization reduces this to ~4.5GB VRAM.
- **Cost Efficiency**: Allows using cheap local CPUs/GPUs or low-tier cloud instances rather than expensive cloud clusters.
- **Latency Tradeoff**: CPU processing for quantized models is often faster than unquantized parameters because of reduced memory bandwidth bottlenecks, though high GPU-bound scenarios may see a small overhead.

---

## 2. Quantization Options (GGUF / Ollama)

When selecting models:
- **Q4_K_M (4-bit Medium)**: Recommended balance between size, speed, and reasoning accuracy.
- **Q8_0 (8-bit)**: Closer to FP16 precision, slightly higher memory footprints (~7-8GB for a 7B model), but reduces hallucination potential in complex clinical reasoning.

---

## 3. Recommended Models for Local Execution
- **Ollama**: `ollama run llama3:8b-instruct-q4_K_M`
- **llama.cpp**: Download GGUF files for clinical LLMs (e.g. `BioMistral-7B.Q4_K_M.gguf`).
