#!/usr/bin/env python3
"""
End-to-End Live Demo Runner for Clinical GraphRAG Pro.
Runs clinical queries through the RAG pipeline using Google Gemini, Ollama, or retrieval-only mode.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Add backend directory to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Import application components
from app.core.config import get_settings
from app.services.rag import rag_service

# Load settings singleton
settings = get_settings()


async def run_ingestion(skip_ingest: bool):
    """Optionally trigger ingestion and database bootstrapping."""
    if skip_ingest:
        print("Skipping ingestion as requested by CLI flag...")
        return "demo-tenant-id"

    print("Bootstrapping database and seeding synthetic clinical data...")
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "demo"))
    try:
        import seed_demo_data
        admin_user_id = await seed_demo_data._bootstrap_admin()
        await seed_demo_data._seed_retrieval_corpus()
        await seed_demo_data._seed_fhir_data(admin_user_id)
        print(f"Ingestion successful! Seeded under user/tenant ID: {admin_user_id}")
        return admin_user_id
    except Exception as e:
        print(f"Warning: Ingestion/seeding had issues: {e}")
        return "demo-tenant-id"


def compile_markdown_report(provider: str, model_name: str, results: list[dict]) -> str:
    """Build a detailed Markdown report for reviewers."""
    lines = [
        "# Clinical GraphRAG Pro - Live Demo Report",
        f"**LLM Provider:** `{provider}`",
        f"**Model Name:** `{model_name}`",
        f"**Date Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]

    for idx, res in enumerate(results, start=1):
        support_score = res.get("heuristic_evidence_support_score", res.get("confidence_score", 0.0))
        lines.extend([
            f"## Case Query [{idx}]: {res['query_type'].upper()}",
            f"**Query:** *\"{res['query']}\"*",
            "**Answer:**",
            f"{res['answer']}",
            "",
            f"**Heuristic Evidence-Support Score:** `{support_score}`",
            "This value is not calibrated clinical confidence.",
            f"**Execution Latency:** `{res['latency_ms']} ms`",
            f"**Abstention Triggered:** `{res['abstention_status']}`",
            f"**Validation Status:** `{res['verification_status']}`",
            "",
        ])

        if res.get("warnings"):
            lines.append("### Grounding & Safety Warnings:")
            for w in res["warnings"]:
                lines.append(f"- ⚠️ {w}")
            lines.append("")

        if res.get("citations"):
            lines.append("### Citations & Grounded References:")
            for cit in res["citations"]:
                marker = cit.get('marker', 'Citation')
                type_label = 'Document'
                if marker.startswith('GRAPH'):
                    type_label = 'Graph'
                elif marker.startswith('IMG'):
                    type_label = 'Image'
                lines.append(
                    f"- **[{marker}]** ({type_label}) in `{cit.get('document_name')}` (Chunk: `{cit.get('chunk_id')}`)"
                )
            lines.append("")

        if res.get("retrieved_chunks"):
            lines.append("### Retrieved Excerpts:")
            for chunk in res["retrieved_chunks"][:3]:
                snippet = chunk.get("chunk_text") or chunk.get("text") or ""
                if len(snippet) > 150:
                    snippet = snippet[:150] + "..."
                lines.append(
                    f"- **[{chunk.get('citation_id', 'SRC')}]** (Relevance: `{chunk.get('retrieval_score', 0.0):.2f}`): *\"{snippet}\"*"
                )
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.extend([
        "### Safety & Compliance Notice",
        "⚠️ **Disclaimer:** " + settings.disclaimer_text,
    ])
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="End-to-End Live Demo CLI")
    parser.add_argument(
        "--provider",
        choices=["gemini", "ollama", "retrieval-only"],
        default="retrieval-only",
        help="LLM provider to call (default: retrieval-only)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model name override (e.g. gemini-2.0-flash, llama3)",
    )
    parser.add_argument(
        "--tenant-id",
        default="",
        help="Tenant ID to filter retrieval (defaults to bootstrapped admin)",
    )
    parser.add_argument(
        "--patient-id",
        default="pat-100",
        help="Patient ID to scope Graph Context (default: pat-100)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory to save generated reports (default: reports)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip database seeding and ingestion",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail-fast and exit with error code if validation checks fail",
    )

    args = parser.parse_args()

    # Apply settings overrides
    settings.llm_provider = args.provider
    if args.model:
        if args.provider == "gemini":
            settings.gemini_model = args.model
        elif args.provider == "ollama":
            settings.local_llm_model = args.model

    print(f"Initializing Live Demo with provider: '{args.provider}' (model: '{args.model or 'default'}')...")

    # Bootstrap SQLite if needed
    if "sqlite" in settings.database_url:
        print("SQLite database detected. Bootstrapping tables...")
        from app.core.database import create_tables
        await create_tables()

    # Ingest data
    bootstrapped_tenant = await run_ingestion(args.skip_ingest)
    tenant_id = args.tenant_id or bootstrapped_tenant

    # Validate provider keys
    if args.provider == "gemini" and not settings.google_api_key:
        print("Error: GEMINI_API_KEY / GOOGLE_API_KEY is not configured in settings or environment.")
        if args.strict:
            sys.exit(1)
        print("Falling back to retrieval-only mode...")
        settings.llm_provider = "retrieval-only"

    # Health check probe
    from app.services.llm import llm_service
    health = await llm_service.health_check()
    print(f"Active LLM Service Health: {health}")

    # Queries definition
    demo_queries = [
        {
            "type": "factual",
            "query": "Has patient John Doe (ID: pat-100) been diagnosed with Essential Hypertension?",
            "check": lambda ans, conf, abst: not abst and conf > 0.0 and ("hypertension" in ans.lower() or "essential" in ans.lower() or "retrieval-only" in ans.lower()),
        },
        {
            "type": "abstention",
            "query": "What is patient John Doe's orbital space telemetry reading?",
            "check": lambda ans, conf, abst: abst and conf == 0.0 and "not have enough evidence" in ans.lower(),
        },
        {
            "type": "medication_temporal",
            "query": "List the vital signs and active medications recorded for patient John Doe (ID: pat-100).",
            "check": lambda ans, conf, abst: not abst and conf > 0.0,
        },
    ]

    results = []
    failed_validations = []

    for idx, q in enumerate(demo_queries, start=1):
        print(f"\nRunning Query [{idx}] ({q['type']}): '{q['query']}'")
        start_time = time.perf_counter()
        
        try:
            # Execute search and generation
            res = await rag_service.query(
                question=q["query"],
                user_id=tenant_id,
                tenant_id=tenant_id,
                patient_id=args.patient_id,
            )
            latency = int((time.perf_counter() - start_time) * 1000)
            
            answer = res.get("answer", "")
            sources = res.get("sources", [])
            citations = res.get("citations", [])
            trace = res.get("trace", {})
            support_score = (
                res.get("heuristic_evidence_support_score")
                or (trace.get("heuristic_evidence_support_score") if trace else None)
                or res.get("confidence_score")
                or 0.0
            )

            # Determine status indicators
            abstention = "not have enough evidence" in answer.lower() or "insufficient evidence" in answer.lower()
            
            # Run safety checks
            validation_passed = q["check"](answer, support_score, abstention)
            v_status = "PASSED" if validation_passed else "FAILED"
            if not validation_passed:
                failed_validations.append(q["type"])

            print(f"  Answer: {answer[:180]}...")
            print(f"  Evidence support: {support_score} | Latency: {latency} ms | Abstention: {abstention} | Validation: {v_status}")

            results.append({
                "query_type": q["type"],
                "query": q["query"],
                "answer": answer,
                "citations": citations,
                "retrieved_chunks": trace.get("retrieved_chunks") or sources,
                "provider_name": args.provider,
                "model_name": args.model or (settings.gemini_model if args.provider == "gemini" else settings.local_llm_model),
                "heuristic_evidence_support_score": support_score,
                "confidence_score": support_score,
                "confidence_score_deprecated": True,
                "latency_ms": latency,
                "abstention_status": abstention,
                "verification_status": v_status,
                "warnings": trace.get("guardrails", {}).get("warnings", []),
            })
        except Exception as exc:
            from app.core.logging_config import redact_secrets
            redacted_err = redact_secrets(str(exc))
            print(f"  Query execution failed: {redacted_err}")
            results.append({
                "query_type": q["type"],
                "query": q["query"],
                "answer": f"Error during execution: {redacted_err}",
                "citations": [],
                "retrieved_chunks": [],
                "provider_name": args.provider,
                "model_name": "error",
                "confidence_score": 0.0,
                "latency_ms": int((time.perf_counter() - start_time) * 1000),
                "abstention_status": False,
                "verification_status": "ERROR",
            })
            failed_validations.append(q["type"])

    # Output results
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    json_report = output_path / f"live_demo_{args.provider}.json"
    with open(json_report, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved JSON report to: {json_report}")

    md_content = compile_markdown_report(args.provider, args.model or "default", results)
    md_report = output_path / f"live_demo_{args.provider}.md"
    with open(md_report, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Saved Markdown report to: {md_report}")

    # Close resources
    await llm_service.close()

    if failed_validations:
        print(f"\n⚠️ Demo checks failed for: {failed_validations}")
        if args.strict:
            print("Strict validation mode is enabled. Failing exit.")
            sys.exit(1)
    else:
        print("\n🎉 ALL LIVE DEMO CHECKS PASSED SUCCESSFULLY!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
