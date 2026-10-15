"""Reproducible engineering benchmark — OBJECTIVE capability vs ground truth.

Measures CLE's deterministic retrieval/symbol capabilities against ground truth
established from the actual repository structure (NOT from any model's answer).
These tasks use the code index + ripgrep only — no LLM — so results are
reproducible and fully offline.

Ground truth is defined below and is independent of whatever the tools return.

Usage:
    python scripts/bench_engineering.py            # run against this repo (CLE)

Metrics:
    symbol-lookup : did find_symbols() return the known-correct defining file?
    exact-retrieval: recall = (expected files found / expected), precision proxy.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cle.indexing.repository import RepositoryIndex  # noqa: E402
from cle.tools.search import search as exact_search  # noqa: E402

# --- Ground truth (established from the real source, independent of tool output).
# symbol name -> file that DEFINES it.
SYMBOL_GT = {
    "Orchestrator": "cle/models/orchestrator.py",
    "classify_complexity": "cle/models/orchestrator.py",
    "ModelRouter": "cle/models/router.py",
    "ModelRegistry": "cle/models/registry.py",
    "PermissionGuard": "cle/safety/permissions.py",
    "CodingAgent": "cle/agents/coding.py",
    "DebugAgent": "cle/agents/debugging.py",
    "EvidenceSource": "cle/evidence.py",
    "run_tests": "cle/tools/test_runner.py",
    "OllamaProvider": "cle/models/ollama.py",
}

# exact-search pattern -> set of files that SHOULD appear (known relevant).
RETRIEVAL_GT = {
    "class Orchestrator": {"cle/models/orchestrator.py"},
    "ModelNotConfiguredError": {"cle/errors.py", "cle/models/registry.py"},
    "def run_tests": {"cle/tools/test_runner.py"},
    "STATUS_PARTIAL": {"cle/models/orchestrator.py"},
}


def _bench_symbols(index: RepositoryIndex):
    hits = 0
    rows = []
    for name, gt_file in SYMBOL_GT.items():
        start = time.monotonic()
        syms = index.find_symbols(name)
        ms = (time.monotonic() - start) * 1000
        found_files = {s["file_path"] for s in syms}
        ok = gt_file in found_files
        hits += ok
        rows.append((name, gt_file, "HIT" if ok else "MISS", len(syms), round(ms, 1)))
    return hits, rows


def _bench_retrieval(root: Path):
    total_recall = 0.0
    total_prec = 0.0
    rows = []
    for pattern, gt in RETRIEVAL_GT.items():
        start = time.monotonic()
        matches = exact_search(root, pattern, fixed_string=True)
        ms = (time.monotonic() - start) * 1000
        found = {m.path for m in matches}
        hit = gt & found
        recall = len(hit) / len(gt) if gt else 0.0
        # precision proxy: of distinct files returned, how many are relevant.
        precision = (len(hit) / len(found)) if found else 0.0
        total_recall += recall
        total_prec += precision
        rows.append((pattern, f"{len(hit)}/{len(gt)}", round(recall, 2),
                     round(precision, 2), len(found), round(ms, 1)))
    n = len(RETRIEVAL_GT)
    return total_recall / n, total_prec / n, rows


def main() -> int:
    index = RepositoryIndex(ROOT)
    if not index.is_built():
        print("Index not built. Run: cle index")
        return 1

    print("# Engineering benchmark (deterministic, offline, no model)")
    print(f"# repo: {ROOT.name}  symbols-indexed via `cle index`\n")

    print("## Symbol lookup (ground truth = defining file)")
    print(f"{'symbol':<22} {'expected file':<34} {'result':<6} {'n':>3} {'ms':>6}")
    hits, rows = _bench_symbols(index)
    for name, gt, res, n, ms in rows:
        print(f"{name:<22} {gt:<34} {res:<6} {n:>3} {ms:>6}")
    print(f"-> symbol-lookup success: {hits}/{len(SYMBOL_GT)} "
          f"({100 * hits // len(SYMBOL_GT)}%)\n")

    print("## Exact retrieval (ground truth = known relevant files)")
    print(f"{'pattern':<24} {'found/exp':<10} {'recall':>7} {'prec':>6} {'files':>6} {'ms':>6}")
    recall, prec, rrows = _bench_retrieval(ROOT)
    for pat, fe, rc, pr, nf, ms in rrows:
        print(f"{pat:<24} {fe:<10} {rc:>7} {pr:>6} {nf:>6} {ms:>6}")
    print(f"-> mean recall {recall:.2f}, mean precision {prec:.2f}")
    index.close()
    print("\nNote: deterministic tasks only — no LLM. Diagnosis/coding quality is "
          "evaluated separately with real models (see PHASE-16 benchmark doc).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
