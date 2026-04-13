# Provider capability matrix (request-processing unification)

This artifact supports Wave **6.1** (connector stream-first cohort planning). It describes how each **backend connector** relates to the **canonical internal handle** and the **stream-first migration framework** (`request_processing_unification.connector_stream_first`), not full connector audits.

## Legend

| Capability | Meaning |
|------------|---------|
| **Native HTTP streaming** | Connector can call upstream with streamed HTTP and expose `StreamingResponseEnvelope`. |
| **Non-stream HTTP** | Connector supports blocking JSON (`ResponseEnvelope`) for `stream=false`. |
| **Stream-first eligible** | Suitable for cohort opt-in under canonical path: manager may set `stream=true` upstream for a non-streaming client when the backend key is listed in `connector_stream_first`; unlisted backends are not implicitly forced. |
| **Framework status** | Whether stream-first is implemented only at the **manager/gate** boundary (current incremental rollout) vs connector-native stream-first return. |

## Matrix

| Backend key (config / routing) | Native HTTP streaming | Non-stream HTTP | Stream-first eligible (cohort) | Framework notes |
|-------------------------------|----------------------|-----------------|-------------------------------|-------------------|
| `openai` | Yes | Yes | Cohort-gated | Boundary framework: forced upstream `stream` only when this backend key is explicitly opted into the cohort (canonical path is always selected). |
| `anthropic` | Yes | Yes | Cohort-gated | Same boundary contract; provider-specific parsing stays in connector/handler layers. |
| `gemini` | Yes | Yes | Cohort-gated | Same. |
| `azure_openai` | Yes | Yes | Cohort-gated | Same. |
| `groq` | Yes | Yes | Cohort-gated | Same. |
| `cohere` | Yes | Yes | Cohort-gated | Same. |
| `mistral` | Yes | Yes | Cohort-gated | Same. |
| `deepseek` | Yes | Yes | Cohort-gated | Same. |
| `xai` | Yes | Yes | Cohort-gated | Same. |
| `ollama` | Yes | Yes | Cohort-gated | Same. |
| `vertex` / `google` | Yes | Yes | Cohort-gated | Same. |
| `bedrock` | Yes | Yes | Cohort-gated | Same. |
| `other / custom` | Varies | Varies | **Off by default** | Opt in per routed `backend` string only when validated for the deployment; otherwise no implicit stream forcing occurs. |

## Connector entry contract (target)

- Upstream transport may be streaming or blocking; the **manager** selects canonical post-processing using explicit `PostBackendProcessingMode`.
- Cohort opt-in is **config-only** and **default off**; absent an explicit backend key entry, stream-first stays disabled. The manager always uses the canonical post-backend path.
- Provider-specific metadata remains on `StreamingResponseEnvelope` / handler metadata until fully absorbed by canonical handles (future waves).

## Maintenance

Update this matrix when a connector is **validated** for stream-first cohort promotion or when native capabilities change.
