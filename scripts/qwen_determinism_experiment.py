#!/usr/bin/env python3
"""
Qwen Determinism Experiment
============================
Sends N identical requests (temperature=0) to Qwen 2.5 Coder 32B via OpenRouter
and measures how deterministic the outputs are.

Usage:
    python qwen_experiment.py --api-key YOUR_KEY --count 20 --output-dir ./results
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "qwen/qwen-2.5-coder-32b-instruct"

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


def build_request_body() -> dict:
    return {
        "model": MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
    }


async def send_request(
    client: httpx.AsyncClient,
    api_key: str,
    request_id: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, str | None, float, str | None]:
    """Send one request and return (id, content, duration_seconds, error)."""
    async with semaphore:
        body = build_request_body()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/qwen-determinism-experiment",
            "X-Title": "Qwen Determinism Experiment",
        }

        t0 = time.monotonic()
        try:
            resp = await client.post(
                OPENROUTER_URL,
                json=body,
                headers=headers,
                timeout=120.0,
            )
            elapsed = time.monotonic() - t0

            if resp.status_code != 200:
                error_text = resp.text[:500]
                print(f"  [#{request_id:03d}] FAILED ({resp.status_code}) after {elapsed:.1f}s: {error_text}")
                return (request_id, None, elapsed, f"HTTP {resp.status_code}: {error_text}")

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            print(f"  [#{request_id:03d}] OK — {len(content)} chars, {elapsed:.1f}s")
            return (request_id, content, elapsed, None)

        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  [#{request_id:03d}] ERROR after {elapsed:.1f}s: {exc}")
            return (request_id, None, elapsed, str(exc))


def analyze_responses(responses: dict[int, str]) -> dict:
    """Compare all responses pairwise and return analysis."""
    ids = sorted(responses.keys())
    n = len(ids)

    # Group by SHA-256 hash
    hash_groups: dict[str, list[int]] = defaultdict(list)
    for rid in ids:
        h = hashlib.sha256(responses[rid].encode()).hexdigest()
        hash_groups[h].append(rid)

    # Pairwise similarity (only between different hashes to save time)
    # But we still compute all pairs for a full matrix
    similarities: list[tuple[int, int, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            a_id, b_id = ids[i], ids[j]
            a_text, b_text = responses[a_id], responses[b_id]
            if a_text == b_text:
                ratio = 1.0
            else:
                ratio = SequenceMatcher(None, a_text, b_text).ratio()
            similarities.append((a_id, b_id, ratio))

    # Stats
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


def print_report(analysis: dict) -> None:
    """Print a human-readable analysis report."""
    print("\n" + "=" * 70)
    print("DETERMINISM ANALYSIS REPORT")
    print("=" * 70)

    n = analysis["total_responses"]
    print(f"\nTotal successful responses: {n}")
    print(f"Unique responses (by SHA-256): {analysis['unique_hashes']}")
    print(f"Identical pairs: {analysis['identical_pairs']} / {analysis['total_pairs']}")

    print(f"\nPairwise similarity:")
    print(f"  Min:  {analysis['min_similarity']:.4f}" if analysis["min_similarity"] is not None else "  Min:  N/A")
    print(f"  Max:  {analysis['max_similarity']:.4f}" if analysis["max_similarity"] is not None else "  Max:  N/A")
    print(f"  Mean: {analysis['mean_similarity']:.4f}" if analysis["mean_similarity"] is not None else "  Mean: N/A")
    if analysis["mean_non_identical_similarity"] is not None:
        print(f"  Mean (excluding identical): {analysis['mean_non_identical_similarity']:.4f}")

    print(f"\nByte-identical groups:")
    for i, (h, group) in enumerate(analysis["hash_groups"].items(), 1):
        short_hash = h[:12]
        print(f"  Group {i} (hash {short_hash}...): {len(group)} response(s) — IDs: {group}")

    # Show the most different pair
    if analysis["pairwise_details"]:
        worst = min(analysis["pairwise_details"], key=lambda x: x[2])
        if worst[2] < 1.0:
            print(f"\nMost different pair: #{worst[0]:03d} vs #{worst[1]:03d} — similarity {worst[2]:.4f}")

    # Determinism verdict
    print("\n" + "-" * 70)
    unique = analysis["unique_hashes"]
    if unique == 1:
        print("VERDICT: Perfectly deterministic — all responses are byte-identical.")
    elif unique <= 3:
        print(f"VERDICT: Mostly deterministic — {unique} unique variants out of {n} responses.")
    else:
        print(f"VERDICT: Non-deterministic — {unique} unique variants out of {n} responses.")
    print("-" * 70)


async def main():
    parser = argparse.ArgumentParser(
        description="Test Qwen 2.5 Coder 32B determinism via OpenRouter"
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=20,
        help="Number of identical requests to send (default: 20)",
    )
    parser.add_argument(
        "--api-key", "-k",
        type=str,
        default=os.environ.get("OPENROUTER_API_KEY"),
        help="OpenRouter API key (or set OPENROUTER_API_KEY env var)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="./results",
        help="Directory to save individual responses (default: ./results)",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=5,
        help="Max concurrent requests (default: 5)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: Provide --api-key or set OPENROUTER_API_KEY env var.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Qwen Determinism Experiment")
    print(f"  Model:       {MODEL}")
    print(f"  Temperature: 0")
    print(f"  Requests:    {args.count}")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  Output dir:  {output_dir.resolve()}")
    print()

    semaphore = asyncio.Semaphore(args.concurrency)
    responses: dict[int, str] = {}
    errors: dict[int, str] = {}
    durations: list[float] = []

    t_start = time.monotonic()

    async with httpx.AsyncClient() as client:
        tasks = [
            send_request(client, args.api_key, i, semaphore)
            for i in range(1, args.count + 1)
        ]
        results = await asyncio.gather(*tasks)

    t_total = time.monotonic() - t_start

    for request_id, content, duration, error in results:
        durations.append(duration)
        if content is not None:
            responses[request_id] = content
            filepath = output_dir / f"response_{request_id:03d}.tsx"
            filepath.write_text(content, encoding="utf-8")
        if error is not None:
            errors[request_id] = error

    print(f"\nCompleted {len(responses)} / {args.count} requests in {t_total:.1f}s")
    if errors:
        print(f"Errors: {len(errors)}")
        for rid, err in sorted(errors.items()):
            print(f"  #{rid:03d}: {err[:120]}")

    if len(responses) < 2:
        print("Not enough successful responses to compare. Exiting.")
        sys.exit(1)

    # Run analysis
    print("\nAnalyzing responses...")
    analysis = analyze_responses(responses)
    print_report(analysis)

    # Save machine-readable report (without the huge pairwise_details)
    report_path = output_dir / "analysis.json"
    serializable = {
        k: v for k, v in analysis.items() if k != "pairwise_details"
    }
    report_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    print(f"\nFull analysis saved to {report_path.resolve()}")

    # Also save a pairwise similarity matrix as CSV
    csv_path = output_dir / "similarity_matrix.csv"
    ids = sorted(responses.keys())
    # Build a lookup for fast access
    pair_lookup: dict[tuple[int, int], float] = {}
    for a, b, ratio in analysis["pairwise_details"]:
        pair_lookup[(a, b)] = ratio
        pair_lookup[(b, a)] = ratio

    with open(csv_path, "w") as f:
        f.write("," + ",".join(f"#{rid:03d}" for rid in ids) + "\n")
        for rid_a in ids:
            row = [f"#{rid_a:03d}"]
            for rid_b in ids:
                if rid_a == rid_b:
                    row.append("1.0000")
                else:
                    ratio = pair_lookup.get((rid_a, rid_b), 0.0)
                    row.append(f"{ratio:.4f}")
            f.write(",".join(row) + "\n")

    print(f"Similarity matrix saved to {csv_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
