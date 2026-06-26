# Observability

Quartermaster's job is to deliver *only* the kit content a task needs, keeping
client context small. This document covers the metrics and traces that let you
**measure whether it actually does that** — and how they grow as the catalog
grows.

Telemetry is built on **OpenTelemetry**, so you keep the choice of where the
data goes: push to any OTLP collector (and from there to Prometheus, Grafana
Cloud, Honeycomb, Datadog, …) or scrape a Prometheus endpoint directly. With
nothing configured the instrumentation is inert (a no-op meter and tracer) — it
costs effectively nothing and exports nothing.

> **Privacy.** No task text is ever recorded. Metric labels and span attributes
> carry only counts, latencies, and names drawn from the **catalog vocabulary**
> (trait values, kit names, section ids) — never client input.

---

## 1. Setup

Install the optional extra (bundled in the Docker image) and OpenTelemetry +
`tiktoken` come with it:

```bash
pip install '.[telemetry]'
```

Without the extra the server still runs: traces are no-ops, metrics use a no-op
meter, and token sizes fall back to a `bytes / 4` estimate.

### Export to an OTLP collector (push)

Quartermaster honours the **standard `OTEL_*` environment variables** directly —
there is no Quartermaster-specific wrapper for them. Setting an OTLP endpoint is
all it takes to start exporting **both metrics and traces**:

| Variable | Example | Effect |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://collector:4318` | Enables OTLP push for metrics **and** traces (HTTP/protobuf). |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://collector:4318/v1/traces` | Traces-only endpoint override. |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | `http://collector:4318/v1/metrics` | Metrics-only endpoint override. |
| `OTEL_SERVICE_NAME` | `quartermaster` | Resource `service.name` (defaults to `quartermaster`). |
| `OTEL_RESOURCE_ATTRIBUTES` | `deployment.environment=prod` | Extra resource attributes. |

Traces are emitted **only** when a traces endpoint is configured; otherwise the
tracer is a no-op.

### Scrape with Prometheus (pull)

| Variable | Default | Effect |
|---|---|---|
| `QM_METRICS_PROMETHEUS_ENABLED` | `false` | Mounts `GET /metrics` in Prometheus exposition format. |
| `QM_METRICS_ALLOW_ANONYMOUS` | `false` | When false, `/metrics` requires app-token Basic auth. |
| `QM_METRICS_SECTION_LEVEL` | `false` | Emits per-section metrics (`qm.section.deliveries`). Higher cardinality. |

`/metrics` is **authenticated by default**. Prometheus cannot run an OIDC
browser flow, so it uses **app-token HTTP Basic** — the same per-user app tokens
as `/dav` (mint one via `POST /api/app-tokens` from the web UI). Any username
works; the app token is the password:

```yaml
scrape_configs:
  - job_name: quartermaster
    metrics_path: /metrics
    static_configs:
      - targets: ["qm.example.com:8000"]
    basic_auth:
      username: prometheus
      password: <app-token>
```

If you would rather isolate `/metrics` at the network layer (bind it to an
internal interface, firewall it, or put reverse-proxy auth in front), set
`QM_METRICS_ALLOW_ANONYMOUS=true` and drop the `basic_auth` block. `/metrics`
is exempt from the User-Agent registration gate (it lives outside `/api`).

### Air-gapped token counting

Size is measured in estimated tokens via `tiktoken`'s `cl100k_base` encoding.
`tiktoken` downloads its BPE vocabulary on first use; on an offline host,
pre-seed it and point `TIKTOKEN_CACHE_DIR` at the cache (the Docker image does
this). If the vocab is unavailable the server logs once and falls back to a
`bytes / 4` estimate — metrics keep flowing, slightly coarser.

---

## 2. Metric reference

Every metric is prefixed `qm.`. In Prometheus, dots become underscores and
counters/histograms gain the usual `_total` / `_bucket` / `_sum` / `_count`
suffixes (e.g. `qm_resolve_delivered_tokens_bucket`).

### Catalog mass — *how big is the catalog getting?*

| Metric | Type | Unit | Labels | Meaning |
|---|---|---|---|---|
| `qm.catalog.kits` | gauge | 1 | `domain` | Kits in the catalog, per domain. |
| `qm.catalog.sections` | gauge | 1 | `domain` | Sections in the catalog, per domain. |
| `qm.catalog.total_tokens` | gauge | token | `domain` | Total kit tokens, per domain. |
| `qm.catalog.always_load_tokens` | gauge | token | `domain` | Always-load (force-delivered) tokens, per domain. |

A kit declaring multiple `domains` contributes to each. Gauges are computed
lazily from the catalog and cached by catalog fingerprint, so a scrape recomputes
token counts only when the catalog changes.

### Content delivered — *the headline efficiency metrics*

| Metric | Type | Unit | Labels | Meaning |
|---|---|---|---|---|
| `qm.resolve.delivered_tokens` | histogram | token | — | Tokens inlined per `resolve_kits` call. |
| `qm.resolve.offered_tokens` | histogram | token | — | Tokens left as `fetch_on_demand` per call (byte-estimated). |
| `qm.kit.delivered_tokens` | counter | token | `kit`, `domain`, `disposition` | Cumulative tokens delivered per kit. |

`disposition` ∈ `inlined` (always-load, inlined by `resolve_kits`) · `offered`
(left for on-demand fetch) · `full` / `sections` (`get_kit` returned the whole
kit / specific sections).

### Kit & section usage — *which kits earn their place?*

| Metric | Type | Unit | Labels | Meaning |
|---|---|---|---|---|
| `qm.kit.deliveries` | counter | 1 | `kit`, `domain`, `disposition` | Deliveries per kit. |
| `qm.section.deliveries` | counter | 1 | `kit`, `section_id`, `disposition` | Deliveries per section (opt-in via `QM_METRICS_SECTION_LEVEL`). |
| `qm.resolve.calls` | counter | 1 | — | `resolve_kits` invocations (the denominator). |

### Selection health

| Metric | Type | Unit | Labels | Meaning |
|---|---|---|---|---|
| `qm.resolve.engine` | counter | 1 | `engine` | Winning inference engine (`llm`/`embedding`/`lexical`). |
| `qm.resolve.confidence` | counter | 1 | `confidence` | Selection confidence (`high`/`medium`/`low`). |
| `qm.resolve.coverage` | histogram | 1 | — | Fraction of trait dimensions covered. |
| `qm.resolve.broadening_recommended` | counter | 1 | — | Resolves where broadening was recommended. |
| `qm.trait.matched` | counter | 1 | `category`, `value` | Inferred traits, by category and value. |
| `qm.gap.requested` | counter | 1 | — | Kit-gap requests filed by clients. |

### Tool latency (every MCP tool)

| Metric | Type | Unit | Labels | Meaning |
|---|---|---|---|---|
| `qm.tool.calls` | counter | 1 | `tool`, `ok` | MCP tool invocations. |
| `qm.tool.duration` | histogram | ms | `tool`, `ok` | MCP tool call duration. |

---

## 3. KPI recipes (PromQL)

**How much extra content per call** — the headline number:

```promql
histogram_quantile(0.95, sum by (le) (rate(qm_resolve_delivered_tokens_bucket[1h])))
```

**Flattening per domain** — the core thesis. Plot catalog growth against
delivered volume per domain. As you add, say, `network-eng` kits, its catalog
series climbs while delivery for `backend` tasks stays flat (those kits are not
selected):

```promql
# Catalog mass per domain (rising as kits are added)
sum by (domain) (qm_catalog_total_tokens)

# Delivered tokens per domain (should stay flat for established domains)
sum by (domain) (rate(qm_kit_delivered_tokens_total{disposition="inlined"}[1d]))
```

**Superfluous / poorly-discovered kit** — present in the catalog but rarely
delivered over a long window:

```promql
sum by (kit) (increase(qm_kit_deliveries_total{disposition="inlined"}[30d]))
```

Kits near zero are either unnecessary or not being discovered (check
`qm.gap.requested` and `qm.resolve.coverage` for the latter).

**Overused / too-broad kit** — delivered on nearly every resolve:

```promql
sum(increase(qm_kit_deliveries_total{disposition="inlined"}[7d])) by (kit)
  / scalar(increase(qm_resolve_calls_total[7d]))
```

Ratios approaching `1.0` suggest applicability that is too broad.

**Dead-weight section** (requires `QM_METRICS_SECTION_LEVEL`):

```promql
sum by (kit, section_id) (increase(qm_section_deliveries_total[30d]))
```

**Selection health at a glance:**

```promql
sum by (engine)     (increase(qm_resolve_engine_total[1d]))      # engine mix
sum by (confidence) (increase(qm_resolve_confidence_total[1d]))  # confidence mix
histogram_quantile(0.5, sum by (le) (rate(qm_resolve_coverage_bucket[1d])))
rate(qm_resolve_broadening_recommended_total[1d])
rate(qm_gap_requested_total[1d])
```

---

## 4. Suggested Grafana dashboard

One board, five rows:

1. **Delivery efficiency** — time-series of `qm.resolve.delivered_tokens` p50/p95
   and `qm.resolve.offered_tokens` p95; a single stat for delivered-tokens p95.
2. **Catalog growth by domain** — stacked time-series of
   `qm.catalog.total_tokens` and `qm.catalog.always_load_tokens` by `domain`,
   overlaid with delivered tokens per domain. *This row tells the flattening
   story.*
3. **Kit & section usage** — a table or heatmap of `qm.kit.deliveries` by `kit`
   (and `qm.section.deliveries` by section when enabled), sorted ascending to
   surface dead weight and descending to surface over-use; a column for the
   delivery/`qm.resolve.calls` ratio.
4. **Selection health** — engine mix, confidence mix, coverage p50, broadening
   rate, gap-request rate.
5. **Tool latency** — `qm.tool.duration` p50/p95 by `tool`, and an error rate
   from `qm.tool.calls{ok="false"}`.

A starter dashboard JSON can be committed here as a follow-up.

---

## 5. Traces

When a traces endpoint is configured, each `resolve_kits` call is a span tree:

```
mcp.tool.resolve_kits          attrs: mcp.tool.name, mcp.session.id
└─ resolve.infer               attrs: engine, trait.count
└─ resolve.select              attrs: candidates, confidence, coverage
└─ resolve.assemble            attrs: kits, delivered_tokens, offered_tokens
```

The outer `mcp.tool.*` span wraps **every** MCP tool (so `get_kit`,
`select_kits`, etc. are traced too) and carries the per-tool duration. Useful
investigations:

- **"Why does kit X always get selected?"** — inspect `resolve.select`
  attributes and the per-kit deliveries to see which traits drove it.
- **"Where is resolve latency going?"** — compare the durations of
  `resolve.infer` (engine cost), `resolve.select`, and `resolve.assemble`.

As with metrics, no task text appears on any span.
