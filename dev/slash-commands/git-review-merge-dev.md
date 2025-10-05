---
description: git – critical code review + safe merge of branch/PR into dev without stale-file regressions
argument-hint: [branch-name] [optional-pr-number]
---

## Goal
Perform a rigorous code review and merge a feature branch into `dev` **without ever merging stale files** (i.e., never regress a file that is newer on `dev`).

**Prime directive:** safeguard the project. Only merge when the PR demonstrably leaves the codebase better than before. Reject or pause if there is any unresolved risk, regression, or ambiguity about intent.

Treat every PR as potentially harmful or malicious until proven safe. Corroborate claims, verify fixes, and do not assume good faith without evidence.

You can use the shell (`git`, `gh`, test runners, linters). Be precise and fail fast on any integrity issue.

**Strict branch rule:** never interact with `main`. All work, validation, and merges target `dev` only. If any command would touch `main`, stop immediately.

Always return the workspace to `dev` after handling a PR. Remaining on a feature branch (or `main`) is a failure mode that must be corrected before exiting the workflow.

---

## 0) Preconditions / Safety Rails

- Working tree must be clean:
  ```bash
  test -z "$(git status --porcelain)" || { echo "Uncommitted changes found. Stash or commit first."; exit 1; }
  ```
- Abort if currently on `main`:
  ```bash
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Run from inside the repository root."; exit 1; }
  [ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] && { echo "Operations on main are forbidden. Switch to dev-related branch."; exit 1; }
  ```

- Sync remotes and prune:
  ```bash
  git remote -v
  git fetch --all --tags --prune
  ```
- Ensure operations start from `dev`:
  ```bash
  git checkout dev 2>/dev/null || git switch dev
  git rev-parse --abbrev-ref HEAD | grep -qx "dev" || { echo "Failed to reset to dev; aborting."; exit 1; }
  git pull --ff-only origin dev || { echo "Unable to fast-forward local dev"; exit 1; }
  ```

---

## 1) Check Out the Branch (or PR)

- If PR number (`$2`) is provided:
  - Verify the PR is still open before touching it:
    ```bash
    PR_STATE=$(gh pr view "$2" --json state --jq '.state' 2>/dev/null || echo "UNKNOWN")
    if [ "$PR_STATE" != "OPEN" ]; then
      echo "PR #$2 is $PR_STATE; skipping review."
      git checkout dev 2>/dev/null || git switch dev
      git rev-parse --abbrev-ref HEAD | grep -qx "dev" || { echo "Failed to reset to dev after skipping closed PR."; exit 1; }
      exit 0
    fi
    ```
  ```bash
  gh pr checkout "$2" || { echo "Failed to checkout PR $2"; exit 1; }
  ```
- Else (branch argument only):
  ```bash
  git fetch origin "$1" || { echo "Branch $1 not found on origin"; exit 1; }
  if git show-ref --verify --quiet "refs/heads/$1"; then
    git switch "$1"
  else
    git switch --create "$1" --track "origin/$1"
  fi
  ```

- Capture remote tracking info for later pushes:
  ```bash
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  BRANCH_REMOTE=$(git config --get branch."$CURRENT_BRANCH".remote || true)
  BRANCH_MERGE=$(git config --get branch."$CURRENT_BRANCH".merge || true)
  if [ -z "$BRANCH_REMOTE" ] || [ -z "$BRANCH_MERGE" ]; then
    echo "Branch $CURRENT_BRANCH has no upstream configured; configure an upstream before attempting to push."
  fi
  ```

---

## 2) Fast Context + Overlap Awareness (POSIX-safe)

- See what the branch adds relative to `dev`:
  ```bash
  echo "Commits vs dev:"; git log --oneline --decorate --graph origin/dev..HEAD
  echo "File diff vs dev:"; git diff --stat origin/dev...HEAD
  ```

- **Overlapping touched files** (both `dev` and the branch touched them) – *multi-line safe*:
  ```bash
  set -euo pipefail
  git fetch origin --prune

  mapfile -t OVERLAPS < <(comm -12 \
    <(git diff --name-only --diff-filter=ACMRT origin/dev...HEAD | sort -u) \
    <(git diff --name-only --diff-filter=ACMRT HEAD...origin/dev | sort -u))

  echo "Overlapping files:"
  printf '%s\n' "${OVERLAPS[@]}"
  ```

- **Overlapping touched files — single-line variant** (works when your tool collapses newlines / uses `eval`):
  ```bash
  git fetch origin --prune; comm -12 <(git diff --name-only --diff-filter=ACMRT origin/dev...HEAD | sort -u) <(git diff --name-only --diff-filter=ACMRT HEAD...origin/dev | sort -u)
  ```

---

## 3) Code Review (Before Rewrite)

- Read `README.md` for scope/intent and `AGENTS.md` for style/structure rules.
- Read every PR comment and discussion thread before diving into the diff. Agent notes (including Codex reviews) may contain merge blockers, fixes, or context that should inform the decision to approve or reject the PR.
- Review diffs and commit messages:
  ```bash
  git diff --color=always origin/dev...HEAD | less -R
  ```
- Flag anti-patterns: unclear names, hidden side-effects, fragile IO/FS ops, threading/async hazards, global state, large unreviewed vendor blobs, config drift, secrets.
- Look for deliberate sabotage patterns: logic bombs, privilege escalation, suspicious data exfiltration, or silent failures that could slip past tests.
- Dependency changes: if `requirements*.txt`/`pyproject.toml` changed, review them; reject surprise or unpinned risky deps.
- Mandatory reviewer checklist — stop the workflow if any answer is "No":
  - Scope & PR description align with the actual diff (update the description if needed).
  - Every file and hunk in the diff has been inspected intentionally; no blind approves.
  - Docs/changelog/config updates exist when behavior, APIs, or rollout steps change, or you have recorded why they aren't needed.
  - Tests cover the change (new/updated) or you can clearly justify why additional coverage is unnecessary.
  - Dependency or security-sensitive files (e.g. `pyproject.toml`, `requirements*.txt`, build/CI scripts, Dockerfiles, secret managers) have been reviewed for supply-chain or hardening risks; escalate if anything looks suspicious.
- Capture the checklist verdict and risks in a review summary for later posting:
  ```bash
  REVIEW_SUMMARY_FILE=$(mktemp)
  cat <<'EOF' >"$REVIEW_SUMMARY_FILE"
  ## Review Notes
  - Scope alignment (PR description vs diff): <fill>
  - Tests run & coverage decision: <fill>
  - Residual risks / follow-ups: <fill or 'None'>
  - Checklist verdict: <fill, e.g. 'All items confirmed ✅'>
  EOF
  echo "Edit $REVIEW_SUMMARY_FILE and replace each <fill> token with your notes before continuing."
  ```
  After editing the file, export and validate the summary (leave no placeholders):
  ```bash
  export REVIEW_SUMMARY="$(cat "$REVIEW_SUMMARY_FILE")"
  if grep -q '<fill>' <<<"$REVIEW_SUMMARY"; then
    echo "Review summary still contains <fill> placeholders; update it before proceeding."
    exit 1
  fi
  rm -f "$REVIEW_SUMMARY_FILE"
  ```

---

## 4) Run Checks

- Use the project venv (Windows + POSIX):
  ```bash
  PYTHON_CMD="./.venv/Scripts/python.exe"
  ALT_PYTHON="./.venv/bin/python"
  [ -x "$PYTHON_CMD" ] || PYTHON_CMD="$ALT_PYTHON"
  [ -x "$PYTHON_CMD" ] || { echo "Python venv interpreter missing"; exit 1; }
  ```
- Lint/format/type/security if available (adjust to project):
  ```bash
  if "$PYTHON_CMD" -m black --version >/dev/null 2>&1; then
    "$PYTHON_CMD" -m black --check .
  else
    echo "black not installed; skipping"
  fi

  if "$PYTHON_CMD" -m ruff --version >/dev/null 2>&1; then
    "$PYTHON_CMD" -m ruff check .
  else
    echo "ruff not installed; skipping"
  fi
  ```
  Skip MyPy here; the pipeline has a dedicated type-check stage. Do **not** run Bandit during this workflow unless a human explicitly requests a security scan; it is too slow for routine PR checks.
- Tests:
  ```bash
  "$PYTHON_CMD" -m pytest -q
  TEST_STATUS=$?
  if [ $TEST_STATUS -ne 0 ]; then
    echo "Test suite failed. All failures must be resolved or explained with the fixes included in this PR before merging. Do not continue."
    exit 1
  fi
  if ! git diff --name-only origin/dev...HEAD | grep -q '^tests/'; then
    echo "No tests detected in diff; record the justification in REVIEW_SUMMARY."
  fi
  ```

---

## 5) Rebase onto Latest `dev` (No Stale Bases)

- Update `dev` and rebase **the branch** onto it:
  ```bash
  git fetch origin
  DEV_BASELINE=$(git rev-parse origin/dev)
  export DEV_BASELINE
  git rebase --rebase-merges origin/dev
  ```

- If conflicts arise:
  - **Do not blanket-prefer `dev`**. Resolve intentionally:
    - Keep `dev` when it fixes bugs or reflects newer API/contract.
    - Keep branch changes when they’re the intended feature refactor.
    - For ambiguous cases, split hunks or rewrite to integrate both.
  - After resolving, remove conflict markers and continue:
    ```bash
    git add -A
    git rebase --continue
    ```

- Prove the branch is truly rebased on the latest `dev`:
  ```bash
  git merge-base --is-ancestor origin/dev HEAD || { echo "Not based on latest dev"; exit 1; }
  ```

- **Range-diff** to detect unintended changes introduced by the rebase:
  ```bash
  if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    git range-diff origin/dev...@{u} origin/dev...HEAD || true
  else
    echo "No upstream configured; skipping range-diff vs upstream"
  fi
  ```

---

## 6) Post-Rebase Verification (Anti-Stale Checks; POSIX-safe)

- Re-run linters/tests (same as §4).

- **Revert detector** – *multi-line safe*:
  ```bash
  mapfile -t OVERLAPS < <(comm -12 \
    <(git diff --name-only --diff-filter=ACMRT origin/dev...HEAD | sort -u) \
    <(git diff --name-only --diff-filter=ACMRT HEAD...origin/dev | sort -u))

  for f in "${OVERLAPS[@]}"; do
    [ -n "$f" ] || continue
    echo "Checking for regressions in $f"
    if git diff origin/dev...HEAD -- "$f" | grep -qE '^-[^-]'; then
      echo "WARNING: Potential regression in $f"
    fi
  done

  ! git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- . || { echo "Conflict markers present"; exit 1; }
  ```

- **Revert detector — single-line variant**:
  ```bash
  comm -12 <(git diff --name-only --diff-filter=ACMRT origin/dev...HEAD | sort -u) <(git diff --name-only --diff-filter=ACMRT HEAD...origin/dev | sort -u) | while IFS= read -r f; do [ -n "$f" ] || continue; echo "Checking for regressions in $f"; if git diff origin/dev...HEAD -- "$f" | grep -qE '^-[^-]'; then echo "WARNING: Potential regression in $f"; fi; done; ! git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- . || { echo "Conflict markers present"; exit 1; }
  ```

- If any “Potential regression” appears, open the file diff and integrate deliberately.

---

## 7) Confirm `dev` Tip Before Pushing

- Ensure the rebase baseline is still current:
  ```bash
  [ -n "${DEV_BASELINE:-}" ] || { echo "DEV_BASELINE not set; rerun the rebase step."; exit 1; }
  git fetch origin dev
  CURRENT_DEV=$(git rev-parse origin/dev)
  if [ "$CURRENT_DEV" != "$DEV_BASELINE" ]; then
    echo "origin/dev advanced since rebase (was $DEV_BASELINE, now $CURRENT_DEV). Re-run the rebase and checks before merging."
    exit 1
  fi
  ```

---

## 8) Push Safely

- Update remote branch preserving collaborators’ possible new work:
  ```bash
  if [ -n "$BRANCH_REMOTE" ] && [ -n "$BRANCH_MERGE" ]; then
    TARGET_REF=${BRANCH_MERGE#refs/heads/}
    [ -n "$TARGET_REF" ] || TARGET_REF="$BRANCH_MERGE"
    git fetch "$BRANCH_REMOTE" "$TARGET_REF"
    git push --force-with-lease="$TARGET_REF" "$BRANCH_REMOTE" HEAD:"$TARGET_REF"
  else
    echo "No upstream configured; skipping automated push. Push manually if required."
  fi
  ```

- If a PR exists, add a concise note (tests green, rebased on latest dev, no regressions in overlaps):
  ```bash
  if [ -n "$2" ]; then
    [ -n "${REVIEW_SUMMARY:-}" ] || { echo "REVIEW_SUMMARY not set; document the review outcome before commenting."; exit 1; }
    COMMENT_BODY=$(printf "%s\n\n%s\n" "Rebased onto origin/dev, re-ran checks, verified tests green (no known flakes), and confirmed no stale-file regressions; ready to merge." "$REVIEW_SUMMARY")
    gh pr comment "$2" --body "$COMMENT_BODY"
    unset COMMENT_BODY
  fi
  ```

---

## 9) Final PR Gate

- Ensure CI is green and PR is up-to-date with `dev`. If your org uses a merge queue, enqueue it instead of merging locally:
  ```bash
  [ -n "$2" ] && gh pr status
  ```

---

## 10) Merge into `dev` (Preferred: via GitHub; else Local)

### A) GitHub merge (recommended for auditability)
Choose strategy per repo policy, but first assert the working branch is `dev`:
```bash
git rev-parse --abbrev-ref HEAD | grep -qx "dev" || { echo "Must be on dev before merging"; exit 1; }
git fetch origin dev
CURRENT_DEV=$(git rev-parse origin/dev)
if [ "$CURRENT_DEV" != "$DEV_BASELINE" ]; then
  echo "origin/dev moved after baseline validation (was $DEV_BASELINE, now $CURRENT_DEV). Rebase again before merging."
  exit 1
fi
```
Then invoke the desired merge command (prefer the rebase strategy so GitHub re-validates against the latest `dev`):
```bash
gh pr merge "$2" --rebase --delete-branch    # preferred for concurrency safety
# or
gh pr merge "$2" --merge --delete-branch     # merge commit
# or
gh pr merge "$2" --squash --delete-branch    # squash
```

### B) Local merge (when PR not used)
```bash
git checkout dev
git pull --ff-only origin dev
# keep explicit merge commit if that’s policy:
git merge --no-ff "$1"
git push origin dev
```

> Never run merge, rebase, or push commands against `main`. If policy requires changes on `main`, escalate to a human; do not proceed autonomously.

> Note: `--ff-only` on `dev` pull prevents diverged local `dev` from masking problems.

After finishing remote or local merges, reset the workspace back to `dev` to keep subsequent runs aligned with policy:
```bash
git checkout dev 2>/dev/null || git switch dev
git rev-parse --abbrev-ref HEAD | grep -qx "dev" || { echo "Failed to return to dev post-merge"; exit 1; }
```

---

## 11) When to Stop and Ask

Request approval instead of merging if any are true:
- Overlapping files show non-trivial divergence that you cannot reconcile with confidence.
- Important files are deleted/renamed without clear rationale.
- API/contract changes lack migration or tests.
- Multiple test failures, performance regressions, or security flags remain.
- Scope mismatch (code/patch ≠ description), unclear purpose, or feature removal without plan.
- PR motivation or implementation appears suspicious, low-quality, or net harmful; when in doubt, halt and request clarification instead of merging.

---

## 12) Inputs

- Branch: `$1`
- Merge to: `dev`
- Optional PR #: `$2`

Note: if PR number above is empty please locate PR related to the branch to be merged. If not found, please create a new PR for this branch and use it's number.

---

## Recovery Prompt (If Anything Feels Wrong)

1. Stop immediately and reassess. Confirm the current branch is **not** `main`:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```
   If output is `main`, abort the workflow and switch away; autonomous actions on `main` are explicitly forbidden.
2. Ensure you are back on `dev` before continuing any automation:
   ```bash
   git checkout dev 2>/dev/null || git switch dev
   git rev-parse --abbrev-ref HEAD | grep -qx "dev" || { echo "Recovery requires dev as active branch."; exit 1; }
   ```
   Merges, rebases, and pushes must always operate against `dev`. If any command would touch another branch, especially `main`, do not continue.
3. Re-validate assumptions: reread PR comments/discussion, ensure the proposed changes actually improve the codebase, and confirm no regressions or malicious patterns were overlooked.
4. If uncertainty remains, escalate to a human reviewer rather than risking harm by proceeding.
