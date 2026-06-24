#!/usr/bin/env python3
"""
Release Integrity Audit Script for Clinical GraphRAG Pro.
Audits the repository for credentials, leaks, stale cache artifacts, and configuration bugs.
"""

import os
import re
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cmd(args: list[str]) -> str:
    try:
        res = subprocess.run(args, capture_output=True, text=True, cwd=REPO_ROOT, check=True)
        return res.stdout.strip()
    except Exception:
        return ""


def check_git_tracked_files():
    """Verify no untracked/cache files are committed."""
    print("Checking git-tracked files for cache artifacts...")
    errors = []
    
    # Run git ls-files
    output = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=REPO_ROOT)
    if output.returncode == 0:
        for file in output.stdout.splitlines():
            path = Path(file)
            # Check for __pycache__ or .venv or .pytest_cache
            if "__pycache__" in file or ".pytest_cache" in file or ".venv" in file:
                errors.append(f"Tracked cache/environment directory found in git index: {file}")
            if path.name == ".env":
                errors.append(f"Tracked .env file detected in git index: {file}!")
    return errors


def audit_file_content():
    """Scan all source files for keys, unredacted tokens, or placeholder leakage."""
    print("Auditing codebase file contents for hardcoded credentials...")
    errors = []
    
    # Credentials patterns
    patterns = {
        "Gemini API Key": re.compile(r"AIzaSy[A-Za-z0-9_-]{35}"),
        "Groq API Key": re.compile(r"gsk_[A-Za-z0-9_-]{50}"),
        "JWT Token": re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
        "Bearer Token": re.compile(r"Bearer\s+([a-zA-Z0-9_\-\.]{15,})"),
        "Unredacted URL key": re.compile(r"key=(AIzaSy[A-Za-z0-9_-]{5,})"),
        "Unredacted URL token": re.compile(r"token=([a-zA-Z0-9_-]{10,})"),
    }
    
    # Safe files to ignore
    exclude_dirs = {
        ".venv",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "reports",
        "results",
    }
    exclude_files = {
        "check_release_integrity.py",
        ".env.example",
        "README.md",
        "ROADMAP.md",
        "test_safety_grounding.py",
        "test_live_demo.py",
        "test_redaction.py",
        "logging_config.py",
        "llm.py",
    }
    
    for root, dirs, files in os.walk(REPO_ROOT):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            if file in exclude_files or file.endswith(".png") or file.endswith(".jpg") or file.endswith(".pdf"):
                continue
                
            file_path = Path(root) / file
            # Skip if file size is too big
            if file_path.stat().st_size > 1024 * 1024:
                continue
                
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                for name, pat in patterns.items():
                    for match in pat.finditer(content):
                        # Filter out known safe placeholders (e.g. CHANGE_ME)
                        val = match.group(0)
                        if "CHANGE_ME" in val or "your_gemini_api_key" in val or "placeholder" in val.lower() or val in {"token=access_token", "token=refresh_token"}:
                            continue
                        errors.append(f"Hardcoded {name} pattern found in {file_path.relative_to(REPO_ROOT)}: {val[:15]}...")
            except Exception:
                # Skip unreadable binary/etc
                pass
                
    return errors


def check_docs_integrity():
    """Verify internal documentation links are consistent and free of toxic product claims."""
    print("Auditing documentation links and clinical-safety claims...")
    errors = []
    
    unsupported_claims = [
        "hipaa-compliant",
        "clinically validated",
        "production-ready",
        "sota",
        "safe for real patient care",
        "frontier model",
        "large-scale model",
    ]
    
    for file in REPO_ROOT.glob("**/*.md"):
        # Exclude directories
        if any(ignored in file.parts for ignored in {".venv", ".git", "node_modules", "__pycache__", ".pytest_cache", "results"}):
            continue
            
        try:
            content = file.read_text(encoding="utf-8", errors="replace")
            content_lower = content.lower()
            
            # Audit clinical/HIPAA claims
            for claim in unsupported_claims:
                if claim in content_lower:
                    is_negated = False
                    
                    # 1. Check general disclaimer patterns in the document
                    general_disclaimers = [
                        "intentionally not claimed",
                        "explicitly denied",
                        "educational reference",
                        "research engineering platform",
                        "not approved for diagnostic use",
                        "not clinically validated",
                        "scaffolding engine",
                        "portfolio",
                        "prototype",
                        "not a clinically validated",
                        "no prospective validation",
                        "not certified under hipaa",
                        "do not make the system hipaa",
                        "do not constitute hipaa",
                        "not hipaa-certified or hipaa-compliant",
                    ]
                    if any(disclaimer in content_lower for disclaimer in general_disclaimers):
                        is_negated = True
                        
                    # 2. Check sliding window before match
                    if not is_negated:
                        for match in re.finditer(re.escape(claim), content_lower):
                            start = match.start()
                            window = content_lower[max(0, start - 65):start]
                            negators = ["not", "non-", "no", "never", "denied", "disclaimer", "scaffolding", "portfolio", "educational", "demo", "synthetic", "research"]
                            if any(negator in window for negator in negators):
                                is_negated = True
                                break
                                
                    if not is_negated:
                        errors.append(f"Documentation {file.relative_to(REPO_ROOT)} makes unsupported/unverified claim: '{claim}'")
                        
            # Check internal relative markdown links
            links = re.findall(r"\[.*?\]\((.*?\.md)\)", content)
            for link in links:
                if link.startswith("http"):
                    continue
                if link.startswith("file:///"):
                    # Resolve absolute file scheme link
                    path_str = link.replace("file://", "")
                    path_str = path_str.split("#")[0]
                    link_path = Path(path_str)
                    if not link_path.exists():
                        errors.append(f"Documentation {file.relative_to(REPO_ROOT)} contains broken file link: {link}")
                    continue
                # Resolve relative link
                link_path = (file.parent / link).resolve()
                if not link_path.exists():
                    errors.append(f"Documentation {file.relative_to(REPO_ROOT)} contains broken relative link: {link}")
        except Exception as e:
            errors.append(f"Failed to audit document {file.relative_to(REPO_ROOT)}: {e}")
            
    return errors


def check_benchmark_reports():
    """Audit report files and generated benchmark assets for leaking keys or errors."""
    print("Auditing generated report directories and benchmark runs...")
    errors = []
    
    report_dirs = [REPO_ROOT / "reports", REPO_ROOT / "results"]
    for rd in report_dirs:
        if not rd.exists():
            continue
        for file in rd.glob("**/*"):
            if file.is_dir() or file.suffix not in {".md", ".json", ".txt"}:
                continue
            try:
                content = file.read_text(encoding="utf-8", errors="replace")
                content_lower = content.lower()
                
                # Check for runtime errors/exceptions in benchmark reports
                error_patterns = [
                    "traceback (most recent call last)",
                    "gaierror: ",
                    "runtimeerror: ",
                    "400 bad request",
                    "500 internal server error",
                    "api_key_error",
                    "connection failed",
                    "badly formed hexadecimal uuid string",
                ]
                for pat in error_patterns:
                    if pat in content_lower:
                        errors.append(f"Benchmark/report artifact {file.relative_to(REPO_ROOT)} contains runtime error string: '{pat}'")

                # Check for suspicious placeholder credentials in reports
                placeholders = [
                    "change_me",
                    "your_gemini_api",
                    "your_google_api",
                    "insert_key_here",
                    "placeholder_key",
                ]
                for pl in placeholders:
                    if pl in content_lower:
                        errors.append(f"Report artifact {file.relative_to(REPO_ROOT)} contains unredacted placeholder credential: '{pl}'")

                # Look for raw unredacted keys
                if "AIzaSy" in content and "CHANGE_ME" not in content and "redacted" not in content.lower():
                    # Check if it looks like an actual key or a redacted placeholder
                    if not re.search(r"\[REDACTED\]|\[api_key\]", content, re.IGNORECASE):
                        errors.append(f"Suspicious API Key-like string found in report {file.relative_to(REPO_ROOT)}")
                if "gsk_" in content and "CHANGE_ME" not in content and "redacted" not in content.lower():
                    if not re.search(r"\[REDACTED\]|\[api_key\]", content, re.IGNORECASE):
                        errors.append(f"Suspicious Groq Key-like string found in report {file.relative_to(REPO_ROOT)}")
            except Exception:
                pass
    return errors


def main():
    print("==================================================")
    print("           Clinical GraphRAG Pro Release Audit")
    print("==================================================")
    
    all_errors = []
    all_errors.extend(check_git_tracked_files())
    all_errors.extend(audit_file_content())
    all_errors.extend(check_docs_integrity())
    all_errors.extend(check_benchmark_reports())
    
    print("==================================================")
    if all_errors:
        print(f"❌ RELEASE AUDIT FAILED: Found {len(all_errors)} issues.")
        for err in all_errors:
            print(f"- {err}")
        print("==================================================")
        sys.exit(1)
    else:
        print("🎉 RELEASE INTEGRITY AUDIT PASSED CLEANLY!")
        print("==================================================")
        sys.exit(0)


if __name__ == "__main__":
    main()
