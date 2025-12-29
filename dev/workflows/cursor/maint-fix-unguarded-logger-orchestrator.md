# Subagent Orchesration Task

Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.

To spawn a subagent please use your regular command execution tools like bash, exec or whatever is provided to you and execute the following command:

```bash
cursor-agent --print --output-format text --force "Please execute workflow from the following file: 'dev\workflows\cursor\maint-fix-unguarded-logger-calls-executor.md'"
```

Wait until it finishes. You may set 15 minutes timeout.

## Orchestrator instructions (READ-ONLY)

- You are a READ-ONLY orchestrator: do not modify the repo. Do not run commands that write files (including formatting/linting/test runs). Only spawn subagents to perform edits, run tests, and commit.
- Branch/remote safety: Do NOT create/switch branches, detach HEAD, or do any operations on remotes.
- Concurrency note: The working tree may be dirty due to other agents; do NOT require a clean `git status`. Focus verification on whether the subagent ran the required tests and produced a commit that includes only the files it touched.
- Use a TODO/Task List tool to track: iteration counter, consecutive "no-fix" count, and post-run verification checks.
- Loop breaker: before spawning any subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating immediately.

## Per-iteration checklist (for i = 1..50)
1) If the stop file exists: break.
2) (Read-only) Before spawning, record current branch: `git rev-parse --abbrev-ref HEAD` (must not be `HEAD`), record current HEAD: `git rev-parse HEAD`, and record `git status --porcelain` for context (may be non-empty).
3) Spawn exactly ONE subagent with the task prompt (replace `{list-of-fixed-files}` with your accumulated list).
4) After the subagent reports back, verify (read-only checks + report review):
   - Branch/HEAD safety: `git rev-parse --abbrev-ref HEAD` is unchanged and not `HEAD`.
   - If the subagent changed any files:
     - Tests: it ran baseline (pre-change) and post-change runs of ALL directly related tests and they passed (commands + PASS result are required).
     - Git: it reported exactly ONE commit hash for its work.
       - Verify the commit exists: `git cat-file -t <commit_hash>` returns `commit`.
       - Verify committed files: `git show --name-only --pretty=oneline <commit_hash>` matches the subagent's reported touched files.
       - Optional sanity check: `git merge-base --is-ancestor <commit_hash> HEAD` succeeds.
   - If the subagent made no changes: do NOT require tests/commit; count this as a "no-fix found" iteration.
5) If (and only if) the subagent changed files and any required gate is missing (baseline tests missing/not green, post-change tests not green, no commit, commit hash missing/mismatch, commit includes extra files): before spawning the follow-up subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating. If the violation would require forbidden git operations to fix (branch switched/detached, history rewritten, or a bad commit that cannot be corrected without rewriting history), STOP iterating and report. Otherwise spawn a follow-up subagent with brief instructions to fix ONLY that (run/fix tests and/or commit hygiene). Do not fix it yourself.
6) If the subagent failed to find at least one issue to fix in three consecutive iterations: stop iterating (job done).
7) Append newly committed files to the "already fixed files" list before the next iteration (only when a commit was created).
