# Plagiarism Report — Lab 4

**Date:** 2026-03-07
**Lab:** Lab 04 (Testing, Front-end, AI Agents)
**Students screened:** 258
**Method:** Automated git history analysis (shared commit SHAs, commit messages, author emails) followed by manual repo investigation (file comparison against template, git timeline, source diffs)

---

## Students involved

| GitHub alias | Email | Group |
|---|---|---|
| AleksKornilov07 | a.kornilov@innopolis.university | B25-DSAI-02 |
| venimu | i.kazantcev@innopolis.university | B25-CSE-05 |
| vya4eslav1k | m.slavik@innopolis.university | B25-CSE-01 |
| whateverwillbewillbe | v.verbovetc@innopolis.university | B25-CSE-01 |

## Summary

| # | Students | Signal | Verdict |
|---|----------|--------|---------|
| 1 | AleksKornilov07 (B25-DSAI-02) ↔ venimu (B25-CSE-05) | 3 shared commit SHAs, 96% file similarity | **Confirmed** |
| 2 | vya4eslav1k (B25-CSE-01) ↔ whateverwillbewillbe (B25-CSE-01) | 2 shared commit SHAs, merged branch from other student | **Confirmed** |

---

## Case 1: AleksKornilov07 ↔ venimu

**Conclusion:** venimu did the work; AleksKornilov07's repo contains venimu's commits.

### Evidence

**Shared commit SHAs (3):**

| SHA | Author | Message |
|-----|--------|---------|
| `a40bf69e` | venimu (GitHub) | Merge pull request #3 from venimu/2-task-back-end-testing |
| `bc0c1f26` | ven1mu@yandex.ru | fix: rename timestamp to created_at in InteractionModel |
| `f727fc7d` | ven1mu@yandex.ru | fix: filter interactions by item_id instead of learner_id |

These commits exist in both repos with identical SHAs — meaning AleksKornilov07's repo contains venimu's actual git objects, including a merge PR referencing venimu's branch.

**File comparison (against template `inno-se-toolkit/se-toolkit-lab-4`):**

- 82 files modified from template are byte-identical between the two repos
- Only 3 files differ: `.env.docker.example` (different API token value), `test_interactions.py` (AleksKornilov07 added extra tests after copying), `package-lock.json`
- 11 identical modified source files including all task-relevant code: `interactions.py`, `interaction.py`, `App.tsx`, `vite.config.ts`, `test_interactions.py` (e2e), `conftest.py`

**Cross-author commits:**

venimu's email (`ven1mu@yandex.ru`) appears as the author of non-merge commits in AleksKornilov07's repo. AleksKornilov07's merge PR was merged by venimu's GitHub account.

**Timeline:**

| Student | First task commit | Last commit | Tasks completed |
|---------|------------------|-------------|-----------------|
| venimu | Feb 28 12:55 | Feb 28 15:12 | Tasks 1, 2, 3 |
| AleksKornilov07 | Feb 28 12:55 (venimu's commit) | Mar 5 14:28 | Tasks 1, 2, 3 |

AleksKornilov07's earliest task commits are venimu's commits (same SHA, same timestamp). AleksKornilov07 later added their own unit test commit on Mar 4-5.

---

## Case 2: vya4eslav1k ↔ whateverwillbewillbe

**Conclusion:** whateverwillbewillbe forked vya4eslav1k's work via a direct branch merge.

### Evidence

**Shared commit SHAs (2):**

| SHA | Author | Message |
|-----|--------|---------|
| `c158783` | krosh.das@bk.ru (vya4eslav1k) | Merge pull request #2 from vya4eslav1k/dev |
| `2dfe02a` | krosh.das@bk.ru (vya4eslav1k) | fix: rename field & add timestamp generation |

**Direct merge from other student:**

whateverwillbewillbe's git log contains:

```
57a4047 verbovecz@list.ru Merge pull request #2 from vya4eslav1k/main
```

This is an explicit merge of vya4eslav1k's main branch into whateverwillbewillbe's repo.

**Shared author email:**

`krosh.das@bk.ru` (vya4eslav1k's email) appears as the author of commits in whateverwillbewillbe's repo.

**Identical commit message:**

Both repos contain `"fix: rename field & add timestamp generation"` — a specific message shared by only these two students.

**File comparison (against template):**

- 78 files modified from template are byte-identical
- Only 7 files differ, all showing minor customizations by whateverwillbewillbe after copying:
  - `App.tsx`: hardcoded IP `10.93.25.2:42002`, different heading text
  - `vite.config.ts`: removed proxy, simplified config
  - `backend/app/main.py`: hardcoded CORS origins instead of using settings
  - `interaction.py`: removed a comment (`#here must have been bug, but it's already fixed XD`)
  - Test files: different extra tests added independently

**Timeline:**

| Student | First task commit | Last commit | Tasks completed |
|---------|------------------|-------------|-----------------|
| vya4eslav1k | Feb 28 (task 1) | Mar 5 (task 3) | Tasks 1, 2, 3 |
| whateverwillbewillbe | Feb 28 (merged vya4eslav1k) | Mar 5 (task 3) | Tasks 1, 2, 3 |

whateverwillbewillbe's earliest task-relevant commits are vya4eslav1k's (inherited via the branch merge). whateverwillbewillbe then made their own frontend modifications on top.

---

## Methodology

### Automated screening

Ran `autochecker batch --plagiarism` for all 258 students with template baseline (`inno-se-toolkit/se-toolkit-lab-4`). The checker compares:

1. **Commit SHAs** across all student repos — if the same SHA exists in two repos (excluding template commits), it means one repo's git history was pushed to or merged into the other.
2. **Commit messages** — identical non-trivial messages shared by few students. Messages shared by >10% of students are filtered (lab-instructed).
3. **Author emails** — a student's git email appearing in non-merge commits on another student's repo.

### Manual investigation

For each flagged pair, cloned both repos and the upstream template, then:

1. Hashed every file and categorized as: unchanged from template (ignored), modified-but-identical between pair (suspicious), or different.
2. Compared git logs to establish timeline — who committed first.
3. Checked for cross-author commits — one student's email as author in the other's repo.
4. Diffed source files that differ between the pair to assess whether differences are substantive or cosmetic.

### Noise filtered

- **Lab-instructed commit messages** shared by 30-114 students (e.g. `"fix: rename timestamp to created_at"`)
- **AI tool commit messages** shared by 5-8 students (e.g. `"Co-authored-by: Qwen-Coder"`, `"Made-with: Cursor"`)
- **PR reviewer emails** appearing via merge commits (expected lab workflow)
- **Prescribed bug fixes** producing identical file hashes across 50+ students
