#!/usr/bin/env python3
"""
Qwen Determinism Experiment (stdlib-only version)
===================================================
Sends N identical requests (temperature=0) to a Qwen-compatible API
and measures how deterministic the outputs are.

No external dependencies — uses only Python standard library.

Usage:
    python3 qwen_determinism_experiment_stdlib.py \
      --api-url http://localhost:42005/v1/chat/completions \
      --api-key my-secret-qwen-key \
      --model coder-model \
      --count 20 \
      --output-dir ./results
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

SYSTEM_PROMPT = "You are a senior React/TypeScript developer. Output ONLY the code, no explanations."

USER_PROMPT = """\
I'm working on a lab project. Here's my App.tsx scaffold:

```tsx
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import StudentsPage from "./pages/StudentsPage";
import Dashboard from "./pages/Dashboard";

export default function App() {
  return (
    <BrowserRouter>
      <nav className="flex gap-4 p-4 bg-gray-100">
        <NavLink to="/" className={({isActive}) => isActive ? "font-bold" : ""}>
          Students
        </NavLink>
        <NavLink to="/dashboard" className={({isActive}) => isActive ? "font-bold" : ""}>
          Dashboard
        </NavLink>
      </nav>
      <main className="p-4">
        <Routes>
          <Route path="/" element={<StudentsPage />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
```

The backend exposes these analytics endpoints (all return JSON):
- GET /analytics/scores — returns array of { student_name: string, score: number }
- GET /analytics/pass-rates — returns { passed: number, failed: number }
- GET /analytics/timeline — returns array of { date: string, avg_score: number }
- GET /analytics/groups — returns array of { group_name: string, student_count: number, avg_score: number }

Create a complete `Dashboard.tsx` page component that:
1. Fetches data from all 4 endpoints on mount
2. Displays 4 charts using react-chartjs-2 (v5) and chart.js (v4):
   - Bar chart for scores (student names on x-axis, scores on y-axis)
   - Pie/Doughnut chart for pass rates
   - Line chart for timeline (dates on x-axis, avg scores on y-axis)
   - Bar chart for groups (group names on x-axis, avg_score on y-axis, bar width proportional to student_count)
3. Shows a loading spinner while fetching
4. Handles errors gracefully
5. Uses TypeScript interfaces for all data shapes

Output the full Dashboard.tsx file.
"""


def send_request(api_url, api_key, model, request_id):
    """Send one request and return (id, content, duration_seconds, error)."""
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(api_url, data=body, headers=headers, method="POST")

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            elapsed = time.monotonic() - t0
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            print(f"  [#{request_id:03d}] OK — {len(content)} chars, {elapsed:.1f}s")
            return (request_id, content, elapsed, None)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"  [#{request_id:03d}] ERROR after {elapsed:.1f}s: {exc}")
        return (request_id, None, elapsed, str(exc))


def analyze_responses(responses):
    """Compare all responses pairwise and return analysis."""
    ids = sorted(responses.keys())
    n = len(ids)

    hash_groups = defaultdict(list)
    for rid in ids:
        h = hashlib.sha256(responses[rid].encode()).hexdigest()
        hash_groups[h].append(rid)

    similarities = []
    for i in range(n):
        for j in range(i + 1, n):
            a_id, b_id = ids[i], ids[j]
            a_text, b_text = responses[a_id], responses[b_id]
            if a_text == b_text:
                ratio = 1.0
            else:
                ratio = SequenceMatcher(None, a_text, b_text).ratio()
            similarities.append((a_id, b_id, ratio))

    ratios = [s[2] for s in similarities]
    non_identical = [r for r in ratios if r < 1.0]

    return {
        "total_responses": n,
        "unique_hashes": len(hash_groups),
        "hash_groups": {h: group for h, group in hash_groups.items()},
        "identical_pairs": sum(1 for r in ratios if r == 1.0),
        "total_pairs": len(ratios),
        "min_similarity": min(ratios) if ratios else None,
        "max_similarity": max(ratios) if ratios else None,
        "mean_similarity": sum(ratios) / len(ratios) if ratios else None,
        "mean_non_identical_similarity": (
            sum(non_identical) / len(non_identical) if non_identical else None
        ),
        "pairwise_details": similarities,
    }


def print_report(analysis):
    print("\n" + "=" * 70)
    print("DETERMINISM ANALYSIS REPORT")
    print("=" * 70)

    n = analysis["total_responses"]
    print(f"\nTotal successful responses: {n}")
    print(f"Unique responses (by SHA-256): {analysis['unique_hashes']}")
    print(f"Identical pairs: {analysis['identical_pairs']} / {analysis['total_pairs']}")

    print(f"\nPairwise similarity:")
    if analysis["min_similarity"] is not None:
        print(f"  Min:  {analysis['min_similarity']:.4f}")
        print(f"  Max:  {analysis['max_similarity']:.4f}")
        print(f"  Mean: {analysis['mean_similarity']:.4f}")
    if analysis["mean_non_identical_similarity"] is not None:
        print(f"  Mean (excluding identical): {analysis['mean_non_identical_similarity']:.4f}")

    print(f"\nByte-identical groups:")
    for i, (h, group) in enumerate(analysis["hash_groups"].items(), 1):
        print(f"  Group {i} (hash {h[:12]}...): {len(group)} response(s) — IDs: {group}")

    if analysis["pairwise_details"]:
        worst = min(analysis["pairwise_details"], key=lambda x: x[2])
        if worst[2] < 1.0:
            print(f"\nMost different pair: #{worst[0]:03d} vs #{worst[1]:03d} — similarity {worst[2]:.4f}")

    print("\n" + "-" * 70)
    unique = analysis["unique_hashes"]
    if unique == 1:
        print("VERDICT: Perfectly deterministic — all responses are byte-identical.")
    elif unique <= 3:
        print(f"VERDICT: Mostly deterministic — {unique} unique variants out of {n} responses.")
    else:
        print(f"VERDICT: Non-deterministic — {unique} unique variants out of {n} responses.")
    print("-" * 70)


def main():
    parser = argparse.ArgumentParser(description="Test Qwen determinism")
    parser.add_argument("--count", "-n", type=int, default=20)
    parser.add_argument("--api-url", type=str, default="http://localhost:42005/v1/chat/completions")
    parser.add_argument("--api-key", "-k", type=str, default="my-secret-qwen-key")
    parser.add_argument("--model", "-m", type=str, default="coder-model")
    parser.add_argument("--output-dir", "-o", type=str, default="./qwen_experiment_results")
    parser.add_argument("--concurrency", "-c", type=int, default=3)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Qwen Determinism Experiment")
    print(f"  API URL:     {args.api_url}")
    print(f"  Model:       {args.model}")
    print(f"  Temperature: 0")
    print(f"  Requests:    {args.count}")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  Output dir:  {output_dir.resolve()}")
    print()

    responses = {}
    errors = {}
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(send_request, args.api_url, args.api_key, args.model, i): i
            for i in range(1, args.count + 1)
        }
        for future in as_completed(futures):
            request_id, content, duration, error = future.result()
            if content is not None:
                responses[request_id] = content
                filepath = output_dir / f"response_{request_id:03d}.tsx"
                filepath.write_text(content, encoding="utf-8")
            if error is not None:
                errors[request_id] = error

    t_total = time.monotonic() - t_start
    print(f"\nCompleted {len(responses)} / {args.count} requests in {t_total:.1f}s")
    if errors:
        print(f"Errors: {len(errors)}")
        for rid, err in sorted(errors.items()):
            print(f"  #{rid:03d}: {err[:120]}")

    if len(responses) < 2:
        print("Not enough successful responses to compare.")
        sys.exit(1)

    print("\nAnalyzing responses...")
    analysis = analyze_responses(responses)
    print_report(analysis)

    report_path = output_dir / "analysis.json"
    serializable = {k: v for k, v in analysis.items() if k != "pairwise_details"}
    report_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    print(f"\nAnalysis saved to {report_path}")


if __name__ == "__main__":
    main()
