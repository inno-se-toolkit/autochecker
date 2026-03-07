# Skill: Plagiarism Investigation

Investigate suspected plagiarism between student lab submissions.

## Trigger

When the user asks to check plagiarism, investigate suspicious pairs, or run plagiarism screening.

## Reference

Full methodology is documented in `autochecker/README.md` under "Plagiarism Detection". Read it before proceeding.

## Workflow

### 1. Automated screening

```bash
source $(pyenv root)/versions/env313/bin/activate
cd /path/to/autochecker

python main.py batch \
  -s <students_file> -l <lab-id> -p github \
  --plagiarism --threshold 0.5 \
  --template-repo inno-se-toolkit/<repo-suffix> \
  -w 3 -o <output-dir>
```

Review `git_plagiarism_flags.json` first — focus on **critical** (shared commit SHAs). High/medium flags are usually noise unless shared by only 2-3 students.

### 2. Deep investigation of flagged pairs

```bash
python scripts/investigate_pair.py \
  --student-a <name> --student-b <name> \
  --repo <repo-suffix> \
  --template inno-se-toolkit/<repo-suffix>
```

Review the output: file comparison, git timeline, cross-author commits, source diffs.

### 3. Verdict

- Shared SHAs + cross-author emails + identical modified files = **confirmed**
- Many identical files, no shared SHAs = **probable**, check timeline
- Only shared prescribed-fix files or popular commit messages = **not plagiarism**

## Environment

```bash
source $(pyenv root)/versions/env313/bin/activate
# Token: ssh nurios@188.245.43.68 'grep GITHUB ~/autochecker/deploy/.env'
```

## Lab repos

| Lab | Repo suffix | Template |
|-----|-------------|----------|
| lab-03 | se-toolkit-lab-3 | inno-se-toolkit/se-toolkit-lab-3 |
| lab-04 | se-toolkit-lab-4 | inno-se-toolkit/se-toolkit-lab-4 |
| lab-05 | se-toolkit-lab-5 | inno-se-toolkit/se-toolkit-lab-5 |
