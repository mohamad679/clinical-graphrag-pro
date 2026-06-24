# Secure Multi-Tenant Caching

Clinical GraphRAG Pro includes a secure caching layer to speed up retrieval and reranking while maintaining strict data privacy boundaries.

---

## 1. Security Isolation (No Leakage)

To ensure that data from one patient or tenant never leaks to another through shared cache entries, all keys partition data explicitly using session parameters.

### Cache Key Format
```text
cgrag:{namespace}:{tenant_id}:{patient_id}:{input_payload_hash}
```

If a scoped query (such as `retrieval` or `rerank`) executes without active `tenant_id` and `patient_id` context variables, the cache manager bypasses the cache to guarantee safety.

---

## 2. Configuration Settings

Modify the caching behavior in your environment:

```env
# Enable/Disable caching
CACHE_ENABLED=true  # default: true

# Choose cache engine
CACHE_BACKEND=in-memory  # options: in-memory | redis

# Set Time to Live (TTL) in seconds
CACHE_TTL=3600  # default: 1 hour
```
