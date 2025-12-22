#!/bin/bash
set -euo pipefail

# Minimal single-threaded PR loop for Claude Code headless + your slash command.
# Requirements: gh, jq, claude, ANTHROPIC_API_KEY set, running from the repo root.
# Slash command expected form: /git-review-merge-dev <branch-name> <pr-number>

REPO_DIR="${REPO_DIR:-$(pwd)}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
SLASH_CMD="${SLASH_CMD:-/git-review-merge-dev}"
MAX_STEPS="${MAX_STEPS:-60}"

# --- Preflight ---
#[[ -n "${ANTHROPIC_API_KEY:-}" ]] || { echo "ERROR: ANTHROPIC_API_KEY not set"; exit 1; }
#command -v gh >/dev/null || { echo "ERROR: 'gh' CLI not found"; exit 1; }
#command -v jq >/dev/null || { echo "ERROR: 'jq' not found"; exit 1; }
#command -v "$CLAUDE_BIN" >/dev/null || { echo "ERROR: '$CLAUDE_BIN' not found"; exit 1; }

cd "$REPO_DIR"
git pull
git checkout dev

# Optional: ensure we're inside a git repo
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "ERROR: Not inside a git repo at $REPO_DIR"; exit 1;
}

# Ctrl-C friendly
trap 'echo; echo "[ABORTED]"; exit 130' INT

declare -A PROCESSED_PRS=()
TOTAL_HANDLED=0
PASS=0

while true; do
  PASS=$((PASS+1))
  echo "[INFO] Gathering open PRs… (pass $PASS)"
  prs_json="$(gh pr list --state open --limit 100 --json number,headRefName,title,url,baseRefName)"
  total_open="$(jq 'length' <<<"$prs_json")"

  if [[ "$total_open" -eq 0 ]]; then
    if [[ "$TOTAL_HANDLED" -eq 0 ]]; then
      echo "[INFO] No open PRs. Done."
    else
      echo "[INFO] No remaining open PRs."
    fi
    break
  fi

  mapfile -t pr_entries < <(jq -c 'sort_by(.number | tonumber)[]' <<<"$prs_json")

  new_entries=()
  for pr in "${pr_entries[@]}"; do
    pr_num_tmp="$(jq -r '.number' <<<"$pr")"
    if [[ -n "${PROCESSED_PRS[$pr_num_tmp]:-}" ]]; then
      continue
    fi
    new_entries+=("$pr")
  done

  new_count=${#new_entries[@]}

  if [[ "$new_count" -eq 0 ]]; then
    echo "[INFO] No unprocessed PRs remain (total open: $total_open). Done."
    break
  fi

  echo "[INFO] Found $new_count unprocessed PR(s) this pass (total open: $total_open). Starting (sorted oldest → newest)…"

  i=0
  for pr in "${new_entries[@]}"; do
    i=$((i+1))
    pr_num="$(jq -r '.number' <<<"$pr")"
    pr_branch="$(jq -r '.headRefName' <<<"$pr")"
    pr_title="$(jq -r '.title' <<<"$pr")"
    pr_url="$(jq -r '.url' <<<"$pr")"
    pr_base="$(jq -r '.baseRefName' <<<"$pr")"

    echo
    echo "────────────────────────────────────────────────────────"
    echo "[PR $i/$new_count] #$pr_num  ($pr_branch)"
    echo "Title: $pr_title"
    echo "URL:   $pr_url"
    echo "Base:  $pr_base"
    echo "────────────────────────────────────────────────────────"

    if [[ "$pr_base" != "dev" ]]; then
      echo "[WARN] PR #$pr_num currently targets '$pr_base'. dev is required as the base branch."
    fi

    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${ts}] Claude → ${SLASH_CMD} ${pr_branch} ${pr_num}"

    cd "$REPO_DIR"
    git pull
    git checkout dev

    # Keep the prompt short; your slash command does the real work.
    PROMPT=$(cat <<EOF
Execute the following slash command for this repository using the SlashCommand tool, running non-interactively. If it asks for confirmation, assume yes when safe.

Non-negotiable guardrails before and during execution:
- Start by running: gh pr view "$pr_num" --json baseRefName -q '.baseRefName'. If the base is not "dev", correct it before continuing.
- Never target, merge into, or check out the main branch.
- When opening pull requests, always run: gh pr create --base dev --fill (or provide dev explicitly when setting title/body).
- Before attempting any merge, run: gh pr view "$pr_num" --json baseRefName -q '.baseRefName' and exit immediately if the result is not "dev".
- If the base branch is reported as "main", either run: gh pr edit "$pr_num" --base dev and rerun the necessary validation, or abort and request human confirmation instead of merging. Merging while the base is main is forbidden.

$SLASH_CMD $pr_branch $pr_num

Report a brief success/failure summary at the end.
EOF
)

    set +e
    "$CLAUDE_BIN" \
      -p "$PROMPT" \
      --allowed-tools "Task,Bash,Glob,Grep,ExitPlanMode,Read,Edit,Write,NotebookEdit,WebFetch,TodoWrite,WebSearch,BashOutput,SlashCommand" \
      --max-turns "$MAX_STEPS" \
      --output-format "stream-json" --verbose
    rc=$?
    set -e

    if [[ $rc -eq 0 ]]; then
      echo "[OK] PR #$pr_num handled."
    else
      echo "[WARN] Claude exited with code $rc on PR #$pr_num."
    fi

    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "$current_branch" != "dev" ]]; then
      echo "[WARN] Current branch is '$current_branch' after handling PR #$pr_num; expected 'dev'. Running recovery prompt…"

      RECOVERY_PROMPT=$(cat <<EOF
You started working on reviewing and possibly merging PR #$pr_num (branch "$pr_branch") into dev, but the session was interrupted. The working tree is no longer on dev and may be dirty. Re-run the review and decide whether to merge, fix, or reject.

Absolute rules you must follow:
- Begin by running: gh pr view "$pr_num" --json baseRefName -q '.baseRefName'. If the base is not "dev", correct it before doing anything else.
- Restore the working tree to dev before finishing.
- Never target, merge, or switch to main.
- When opening a replacement PR use: gh pr create --base dev --fill (or explicitly set dev as the base).
- Before merging, run: gh pr view "$pr_num" --json baseRefName -q '.baseRefName' and stop immediately if the base is not "dev".
- If the base branch is "main", either run: gh pr edit "$pr_num" --base dev and rerun validation, or abort and request confirmation instead of merging. Merging while the base is main is forbidden.

If you reject the PR, update PR #$pr_num with the reason, close it, and ensure the local repo is back on dev. If you merge, use a rebase merge into dev, update the PR status, and finish with the local branch on dev.
EOF
)

      set +e
      "$CLAUDE_BIN" \
        -p "$RECOVERY_PROMPT" \
        --allowed-tools "Task,Bash,Glob,Grep,ExitPlanMode,Read,Edit,Write,NotebookEdit,WebFetch,TodoWrite,WebSearch,BashOutput,SlashCommand" \
        --max-turns "$MAX_STEPS" \
        --output-format "stream-json" --verbose
      recovery_rc=$?
      set -e

      if [[ $recovery_rc -eq 0 ]]; then
        echo "[OK] Recovery prompt completed for PR #$pr_num."
      else
        echo "[WARN] Recovery prompt exited with code $recovery_rc on PR #$pr_num."
      fi

      post_recovery_branch="$(git rev-parse --abbrev-ref HEAD)"
      if [[ "$post_recovery_branch" != "dev" ]]; then
        echo "[ERROR] Branch remains '$post_recovery_branch' after recovery for PR #$pr_num; exiting to prevent undefined state." >&2
        exit 1
      fi
    fi

    echo "------------------------------------------------------------"

    PROCESSED_PRS["$pr_num"]=1
    TOTAL_HANDLED=$((TOTAL_HANDLED+1))
  done
done

echo
echo "[DONE] Processed $TOTAL_HANDLED PR(s)."
