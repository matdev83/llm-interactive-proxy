# Request-Processing Promotion Evidence Workflow

This workflow produces a repeatable promotion-evidence bundle for request-processing migration with:

- machine-readable summary (`summary.json`)
- durable human-readable report (`docs/reports/request-processing-promotion-evidence-<run-id>.md`)
- strict pass/fail promotion decision from `PromotionGuardrailEvaluator`

## Scripts

- Benchmark script: `dev/scripts/benchmark_request_processing_migration.py`
- Collector script: `dev/scripts/collect_request_processing_promotion_evidence.py`

## What the collector runs

- Focused pytest groups (guardrail gates, non-stream equivalence, streaming performance, memory/cleanup regressions)
- Non-stream benchmark for p95 and peak-memory deltas
- Optional live proxy streaming capture and CBOR inspection for TTFT evidence
- Strict guardrail evaluation with `strict_missing_evidence=True`

## Quick start

Promotion-ready run (live capture enabled):

```powershell
./.venv/Scripts/python.exe dev/scripts/collect_request_processing_promotion_evidence.py `
  --run-id wave81-promo-001 `
  --baseline-json var/promotion_evidence/previous/summary.json `
  --base-url http://127.0.0.1:8000 `
  --backend openai `
  --model gpt-4o-mini `
  --prompt "Say hello in one short sentence."
```

Informational run without live capture (always blocked due to missing TTFT evidence):

```powershell
./.venv/Scripts/python.exe dev/scripts/collect_request_processing_promotion_evidence.py `
  --run-id wave81-info-001 `
  --skip-live-capture
```

## Output layout

Default output directory:

- `var/promotion_evidence/<run-id>/`

Expected artifacts:

- `summary.json`
- `benchmark_request_processing_migration.json` (unless skipped)
- `pytest/guardrail-gates.xml`
- `pytest/guardrail-nonstream.xml`
- `pytest/guardrail-streaming.xml`
- `pytest/guardrail-memory-cleanup.xml`
- `logs/*.log`
- `captures/current.cbor` and `captures/current_inspection.json` (when live capture runs)
- `docs/reports/request-processing-promotion-evidence-<run-id>.md`

## Guardrail behavior

- Missing required evidence blocks promotion.
- `--skip-live-capture` is supported for informational runs, but promotion remains blocked.
- `summary.json` is always written, including failed runs.
