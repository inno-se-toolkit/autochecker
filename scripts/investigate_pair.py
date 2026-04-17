#!/usr/bin/env python3
"""Deep plagiarism investigation for a pair of student repos.

Clones both repos + the template, then produces a structured report
covering file diffs, git history, timeline, and anomaly detection.

Usage:
    python scripts/investigate_pair.py \
        --student-a AleksKornilov07 --student-b venimu \
        --repo se-toolkit-lab-4 \
        --template inno-se-toolkit/se-toolkit-lab-4 \
        [--token ghp_...] [--output /tmp/investigation]

Requires: git, GITHUB_TOKEN (env or --token).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clone(repo_slug: str, dest: Path, token: str, depth: int = 100) -> bool:
    url = f"https://{token}@github.com/{repo_slug}.git"
    r = subprocess.run(
        ["git", "clone", f"--depth={depth}", url, str(dest)],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def file_hash(path: Path) -> str | None:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:
        return None


def get_files(repo: Path) -> dict[str, str]:
    """Return {relative_path: md5} for every file, skipping .git."""
    result = {}
    for root, dirs, fnames in os.walk(repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in fnames:
            full = Path(root) / f
            rel = str(full.relative_to(repo))
            h = file_hash(full)
            if h:
                result[rel] = h
    return result


def git_log(repo: Path, n: int = 50) -> list[dict]:
    """Return structured commit list."""
    fmt = "%H%n%ae%n%aI%n%s"
    r = subprocess.run(
        ["git", "-C", str(repo), "log", f"--format={fmt}", f"-{n}"],
        capture_output=True, text=True,
    )
    entries = []
    lines = r.stdout.strip().split("\n")
    for i in range(0, len(lines) - 3, 4):
        entries.append({
            "sha": lines[i],
            "email": lines[i + 1],
            "date": lines[i + 2],
            "subject": lines[i + 3],
        })
    return entries


def student_commits(log: list[dict], template_emails: set[str]) -> list[dict]:
    """Filter to commits authored by the student (not template/bot)."""
    return [
        c for c in log
        if c["email"] not in template_emails
        and "noreply.github.com" not in c["email"]
    ]


def find_non_ascii(repo: Path, extensions: set[str]) -> list[dict]:
    """Scan source files for non-ASCII chars (Cyrillic homoglyphs etc)."""
    findings = []
    for root, dirs, fnames in os.walk(repo):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fname in fnames:
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            full = Path(root) / fname
            try:
                text = full.read_text(encoding="utf-8")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for col, ch in enumerate(line):
                    if ord(ch) > 127:
                        cat = unicodedata.category(ch)
                        name = unicodedata.name(ch, "UNKNOWN")
                        # Flag letters that look like ASCII but aren't
                        if cat.startswith("L"):
                            findings.append({
                                "file": str(full.relative_to(repo)),
                                "line": lineno,
                                "col": col,
                                "char": ch,
                                "codepoint": f"U+{ord(ch):04X}",
                                "name": name,
                                "context": line.strip()[:120],
                            })
    return findings


# ---------------------------------------------------------------------------
# Main investigation
# ---------------------------------------------------------------------------

def investigate(
    student_a: str,
    student_b: str,
    repo_suffix: str,
    template_slug: str,
    token: str,
    output_dir: Path,
    work_dir: Path | None = None,
):
    work = work_dir or Path("/tmp/plagiarism-investigate")
    work.mkdir(parents=True, exist_ok=True)

    dir_a = work / student_a
    dir_b = work / student_b
    dir_t = work / "_template"

    # ------------------------------------------------------------------
    # 1. Clone
    # ------------------------------------------------------------------
    print(f"Cloning repos into {work} ...")
    for d, slug in [
        (dir_a, f"{student_a}/{repo_suffix}"),
        (dir_b, f"{student_b}/{repo_suffix}"),
        (dir_t, template_slug),
    ]:
        if d.exists():
            shutil.rmtree(d)
        depth = 1 if d == dir_t else 100
        ok = clone(slug, d, token, depth=depth)
        if not ok:
            print(f"  FAILED to clone {slug}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # 2. File comparison
    # ------------------------------------------------------------------
    print("Comparing files ...")
    files_a = get_files(dir_a)
    files_b = get_files(dir_b)
    files_t = get_files(dir_t)

    common = set(files_a) & set(files_b)
    identical_template = []
    identical_modified = []
    different = []

    for f in sorted(common):
        ha, hb = files_a[f], files_b[f]
        ht = files_t.get(f)
        if ha == hb:
            if ht and ha == ht:
                identical_template.append(f)
            else:
                tag = "new" if f not in files_t else "modified"
                identical_modified.append((f, tag))
        else:
            different.append(f)

    only_a = sorted(set(files_a) - set(files_b))
    only_b = sorted(set(files_b) - set(files_a))

    file_report = {
        "common_total": len(common),
        "identical_template": len(identical_template),
        "identical_modified": len(identical_modified),
        "different": len(different),
        "only_a": len(only_a),
        "only_b": len(only_b),
        "identical_modified_files": [
            {"file": f, "tag": t} for f, t in identical_modified
        ],
        "different_files": different,
        "only_a_files": only_a[:30],
        "only_b_files": only_b[:30],
    }

    # ------------------------------------------------------------------
    # 3. Source file diffs (for files that differ)
    # ------------------------------------------------------------------
    print("Generating diffs for differing source files ...")
    src_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html"}
    diffs = {}
    for f in different:
        if not any(f.endswith(e) for e in src_exts):
            continue
        r = subprocess.run(
            ["diff", "-u", str(dir_a / f), str(dir_b / f)],
            capture_output=True, text=True,
        )
        diffs[f] = r.stdout[:5000] if r.stdout else "(binary or empty diff)"

    # ------------------------------------------------------------------
    # 4. Git history analysis
    # ------------------------------------------------------------------
    print("Analyzing git history ...")
    log_a = git_log(dir_a)
    log_b = git_log(dir_b)

    template_emails = {
        "br4ch1st0chr0n3@gmail.com",
        "nursultan@outlook.com",
    }
    # Add any email from template commits
    log_t = git_log(dir_t, n=1)
    for c in log_t:
        template_emails.add(c["email"])

    sc_a = student_commits(log_a, template_emails)
    sc_b = student_commits(log_b, template_emails)

    # Shared SHAs (excluding template)
    shas_a = {c["sha"] for c in log_a}
    shas_b = {c["sha"] for c in log_b}
    shas_t = {c["sha"] for c in log_t}
    shared_shas = (shas_a & shas_b) - shas_t

    # Filter to student-authored shared SHAs
    student_shared_shas = []
    for sha in shared_shas:
        for c in log_a:
            if c["sha"] == sha and c["email"] not in template_emails \
                    and "noreply.github.com" not in c["email"]:
                student_shared_shas.append(c)
                break

    # Cross-author: does A's email appear in B's log (or vice versa)?
    emails_a = {c["email"] for c in sc_a}
    emails_b = {c["email"] for c in sc_b}
    a_email_in_b = [c for c in log_b if c["email"] in emails_a and c["email"] not in emails_b]
    b_email_in_a = [c for c in log_a if c["email"] in emails_b and c["email"] not in emails_a]

    # Shared commit messages
    msgs_a = {c["subject"] for c in sc_a}
    msgs_b = {c["subject"] for c in sc_b}
    shared_msgs = msgs_a & msgs_b

    git_report = {
        "student_a_commits": len(sc_a),
        "student_b_commits": len(sc_b),
        "student_shared_shas": [
            {"sha": c["sha"][:8], "email": c["email"], "subject": c["subject"]}
            for c in student_shared_shas
        ],
        "a_email_in_b": [
            {"sha": c["sha"][:8], "email": c["email"], "subject": c["subject"]}
            for c in a_email_in_b[:10]
        ],
        "b_email_in_a": [
            {"sha": c["sha"][:8], "email": c["email"], "subject": c["subject"]}
            for c in b_email_in_a[:10]
        ],
        "shared_messages": sorted(shared_msgs),
        "timeline_a": [
            {"sha": c["sha"][:8], "date": c["date"], "subject": c["subject"]}
            for c in sc_a
        ],
        "timeline_b": [
            {"sha": c["sha"][:8], "date": c["date"], "subject": c["subject"]}
            for c in sc_b
        ],
    }

    # ------------------------------------------------------------------
    # 5. Non-ASCII / homoglyph scan
    # ------------------------------------------------------------------
    print("Scanning for non-ASCII characters in source files ...")
    anomalies_a = find_non_ascii(dir_a, src_exts)
    anomalies_b = find_non_ascii(dir_b, src_exts)

    # ------------------------------------------------------------------
    # 6. Assemble report
    # ------------------------------------------------------------------
    report = {
        "pair": [student_a, student_b],
        "repo": repo_suffix,
        "template": template_slug,
        "files": file_report,
        "diffs": diffs,
        "git": git_report,
        "non_ascii_a": anomalies_a,
        "non_ascii_b": anomalies_b,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{student_a}_vs_{student_b}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # 7. Print summary
    # ------------------------------------------------------------------
    print()
    print("=" * 70)
    print(f"INVESTIGATION: {student_a} vs {student_b}")
    print(f"Repo: {repo_suffix} | Template: {template_slug}")
    print("=" * 70)

    print(f"\n--- Files ---")
    print(f"  Common:                    {file_report['common_total']}")
    print(f"  Identical (template):      {file_report['identical_template']}")
    print(f"  Identical (modified/new):  {file_report['identical_modified']}")
    print(f"  Different:                 {file_report['different']}")
    print(f"  Only in {student_a}: {file_report['only_a']}")
    print(f"  Only in {student_b}: {file_report['only_b']}")

    if identical_modified:
        src_mod = [(f, t) for f, t in identical_modified
                   if any(f.endswith(e) for e in src_exts)]
        if src_mod:
            print(f"\n  Suspicious identical source files:")
            for f, t in src_mod:
                print(f"    [{t}] {f}")

    print(f"\n--- Git ---")
    print(f"  {student_a} commits: {git_report['student_a_commits']}")
    print(f"  {student_b} commits: {git_report['student_b_commits']}")
    print(f"  Shared student SHAs: {len(git_report['student_shared_shas'])}")
    if git_report["student_shared_shas"]:
        for c in git_report["student_shared_shas"]:
            print(f"    {c['sha']} ({c['email']}): {c['subject']}")
    print(f"  {student_a} email in {student_b}'s log: {len(git_report['a_email_in_b'])}")
    if git_report["a_email_in_b"]:
        for c in git_report["a_email_in_b"]:
            print(f"    {c['sha']} ({c['email']}): {c['subject']}")
    print(f"  {student_b} email in {student_a}'s log: {len(git_report['b_email_in_a'])}")
    if git_report["b_email_in_a"]:
        for c in git_report["b_email_in_a"]:
            print(f"    {c['sha']} ({c['email']}): {c['subject']}")
    print(f"  Shared commit messages: {len(git_report['shared_messages'])}")
    for m in git_report["shared_messages"]:
        print(f"    \"{m}\"")

    print(f"\n--- Timeline ---")
    print(f"  {student_a}:")
    for c in git_report["timeline_a"]:
        print(f"    {c['date']}  {c['subject']}")
    print(f"  {student_b}:")
    for c in git_report["timeline_b"]:
        print(f"    {c['date']}  {c['subject']}")

    if anomalies_a or anomalies_b:
        print(f"\n--- Non-ASCII anomalies ---")
        for label, anomalies in [
            (student_a, anomalies_a), (student_b, anomalies_b)
        ]:
            if anomalies:
                print(f"  {label}:")
                for a in anomalies:
                    print(f"    {a['file']}:{a['line']}:{a['col']}  "
                          f"{a['codepoint']} ({a['name']})")
                    print(f"      {a['context']}")

    if diffs:
        print(f"\n--- Source diffs ({len(diffs)} files) ---")
        for f, d in diffs.items():
            print(f"\n  === {f} ===")
            for line in d.split("\n")[:30]:
                print(f"  {line}")
            if d.count("\n") > 30:
                print(f"  ... ({d.count(chr(10))} lines total)")

    print(f"\nFull report: {out_path}")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Deep plagiarism investigation for a student pair"
    )
    parser.add_argument("--student-a", required=True)
    parser.add_argument("--student-b", required=True)
    parser.add_argument("--repo", required=True, help="Repo suffix, e.g. se-toolkit-lab-4")
    parser.add_argument("--template", required=True, help="Template repo, e.g. inno-se-toolkit/se-toolkit-lab-4")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--output", default=None, help="Output dir (default: ./reports/investigations)")
    parser.add_argument("--work-dir", default=None, help="Temp dir for clones")

    args = parser.parse_args()

    if not args.token:
        print("ERROR: GITHUB_TOKEN not set. Use --token or set GITHUB_TOKEN env var.")
        sys.exit(1)

    output = Path(args.output) if args.output else Path("reports/investigations")

    investigate(
        student_a=args.student_a,
        student_b=args.student_b,
        repo_suffix=args.repo,
        template_slug=args.template,
        token=args.token,
        output_dir=output,
        work_dir=Path(args.work_dir) if args.work_dir else None,
    )


if __name__ == "__main__":
    main()
