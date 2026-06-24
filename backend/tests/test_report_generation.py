import os
import subprocess

def test_report_compilation():
    """Verify that the generate_report.py script compiles the markdown report successfully."""
    # Find repository root
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(backend_dir)
    script_path = os.path.join(root_dir, "scripts", "generate_report.py")
    report_path = os.path.join(root_dir, "reports", "clinical_graphrag_report.md")
    
    # Ensure any old report is removed
    if os.path.exists(report_path):
        os.remove(report_path)
        
    # Execute the report generator script
    result = subprocess.run(
        ["python3", script_path],
        capture_output=True,
        text=True,
        check=True
    )
    
    # Assert successful execution
    assert result.returncode == 0
    assert "Report compiled successfully" in result.stdout
    
    # Assert report file exists and contains core sections
    assert os.path.exists(report_path)
    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    assert "# Clinical GraphRAG Pro Compilation Report" in content
    assert "## 1. System Diagrams Overview" in content
    assert "## 2. Benchmark Summary" in content
    assert "## 3. System Architecture Details" in content
    assert "## 4. Multi-Horizon Product Roadmap" in content
