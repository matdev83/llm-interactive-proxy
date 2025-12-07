You are analyzing a completed coding session to create a structured summary for future reference.

Respond with ONLY well-formed XML (no prose, no markdown, no code fences) following this template. Escape special characters. Use `UNKNOWN` when evidence is missing. Do not invent files, commits, or tasks that were not mentioned.

<session_summary version="{summary_schema_version}">
  <metadata>
    <session_id>{session_id}</session_id>
    <user_id>{user_id}</user_id>
    <tenant_id>{tenant_id}</tenant_id>
    <project_id>{project_id}</project_id>
    <project_root>{project_root}</project_root>
    <analysis_timestamp>{analysis_timestamp}</analysis_timestamp>
    <model>{model}</model>
    <prompt_version>{summary_prompt_version}</prompt_version>
    <summary_version>{summary_schema_version}</summary_version>
    <branch>{branch}</branch>
    <head_sha>{head_sha}</head_sha>
  </metadata>
  <title>One-sentence description of the session</title>
  <scope>Brief description of the area/component/feature</scope>
  <main_goals>
    <goal>Goal text</goal>
  </main_goals>
  <completion_status>completed|partial|abandoned</completion_status>
  <remaining_tasks>
    <task status="open|blocked">Task description</task>
  </remaining_tasks>
  <touched_files>
    <file status="created|modified|deleted">relative/path</file>
  </touched_files>
  <git_operations>
    <operation type="commit|branch|merge|rebase|cherry-pick" ref="hash-or-name">Details (or UNKNOWN)</operation>
  </git_operations>
  <operations_performed>
    <operation>Notable commands, migrations, or scripts run</operation>
  </operations_performed>
  <tests_run>
    <test status="passed|failed|timeout|skipped">Test name or command</test>
  </tests_run>
  <errors>
    <error>Key exceptions or error messages observed</error>
  </errors>
  <open_questions>
    <item>Assumptions, uncertainties, or clarifications needed</item>
  </open_questions>
  <key_decisions>
    <decision>Important technical/design decision with rationale</decision>
  </key_decisions>
  <risks_or_warnings>
    <item>Risks, blockers, or caveats</item>
  </risks_or_warnings>
  <evidence>
    <item>Specific evidence from the transcript (file paths, errors, outputs)</item>
  </evidence>
</session_summary>

## Session Transcript

{session_transcript}

## Deterministic File Edits (from proxy tool calls)

{deterministic_file_edits}

## Deterministic Git Commits (from proxy tool calls)

{deterministic_git_commits}

Guidelines:

- Use only information explicitly present in the transcript and deterministic lists; if unsure, use UNKNOWN.
- The deterministic lists above are authoritative: copy their entries into `<touched_files>` and `<git_operations>` (augment with brief details if helpful) and do not omit or alter provided paths/hashes.
- When the deterministic file edits list is not "NONE", each file path MUST appear in `<touched_files>` with the corresponding status.
- When the deterministic git commits list is not "NONE", each commit hash MUST appear in `<git_operations>` as a commit operation.
- Keep the title to one sentence.
- Prefer relative paths for files; include commit hashes when mentioned.
- Do not include markdown, JSON, or commentary; return only XML matching the template.
