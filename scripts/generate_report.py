#!/usr/bin/env python3
import os
from datetime import datetime

def generate_report():
    print("Generating Clinical GraphRAG Pro Technical Report...")
    
    # Establish directories
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(root_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    # Read ARCHITECTURE.md
    arch_path = os.path.join(root_dir, "docs", "ARCHITECTURE.md")
    arch_content = ""
    if os.path.exists(arch_path):
        with open(arch_path, "r", encoding="utf-8") as f:
            arch_content = f.read()
    else:
        arch_content = "Architecture documentation not found."

    # Read ROADMAP.md
    roadmap_path = os.path.join(root_dir, "ROADMAP.md")
    roadmap_content = ""
    if os.path.exists(roadmap_path):
        with open(roadmap_path, "r", encoding="utf-8") as f:
            roadmap_content = f.read()
    else:
        roadmap_content = "Roadmap documentation not found."

    # Read BENCHMARK.md
    benchmark_path = os.path.join(root_dir, "results", "BENCHMARK.md")
    benchmark_content = ""
    if os.path.exists(benchmark_path):
        with open(benchmark_path, "r", encoding="utf-8") as f:
            benchmark_content = f.read()
    else:
        benchmark_content = "Benchmark documentation not found."

    # List diagrams
    diagrams_dir = os.path.join(root_dir, "docs", "diagrams")
    diagrams_list = []
    if os.path.exists(diagrams_dir):
        diagrams_list = sorted([f for f in os.listdir(diagrams_dir) if f.endswith(".mmd")])

    # Assemble report
    report_md = f"""# Clinical GraphRAG Pro Compilation Report

Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 1. System Diagrams Overview

Below is the list of active Mermaid architecture diagrams defined in the repository under `docs/diagrams/`:

"""
    for diag in diagrams_list:
        report_md += f"- **{diag}** (Path: `docs/diagrams/{diag}`)\n"
        
    report_md += "\n---\n\n## 2. Benchmark Summary\n\n"
    # Append benchmark content
    if benchmark_content:
        report_md += benchmark_content
    else:
        report_md += "No benchmark results compiled."

    report_md += "\n\n---\n\n## 3. System Architecture Details\n\n"
    report_md += arch_content

    report_md += "\n\n---\n\n## 4. Multi-Horizon Product Roadmap\n\n"
    report_md += roadmap_content

    # Write report
    report_out_path = os.path.join(reports_dir, "clinical_graphrag_report.md")
    with open(report_out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
        
    print(f"Report compiled successfully at: {report_out_path}")

if __name__ == "__main__":
    generate_report()
