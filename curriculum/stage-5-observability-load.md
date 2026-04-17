# Stage 5 — Observability & load: Prometheus, Grafana, k6 (1.5 days)

The stage that turns "I built it" into "I measured it." The benchmark
numbers in the README came from this exact toolchain — after this stage
you rerun them yourself and can defend every digit.

## Why this matters

Interviewers trust candidates who talk in histograms and percentiles.
And two of this repo's best war stories (per-process metric corruption;
the connection-pool ceiling found at 500 rps) are observability
stories — you should be able to tell both with the graphs that
revealed them.

## Watch first

- [core] **Understanding Prometheus Histograms** — PromLabs (Julius Volz, Prometheus co-founder) — https://www.youtube.com/watch?v=yYbXak-1hew. Buckets, `le`, histogram_quantile — explains this repo's latency metrics exactly.
- [core] **How Prometheus Monitoring works** — TechWorld with Nana — https://www.youtube.com/watch?v=h4Sl21AKiDg. Pull model, scrape targets, /metrics.
- [core] **Basics of load testing with k6 and Grafana in 20 minutes** — k6 (official) — https://www.youtube.com/watch?v=gvounvDSDGg. Scripting, VUs, thresholds.
- [optional] **Grafana k6 for Beginners** — Grafana — https://www.youtube.com/watch?v=1mtYVDA2_iQ. Load testing inside the observability story.
- [optional] **k6 + Prometheus Remote Write** — k6 — https://www.youtube.com/watch?v=tFsIgbqXbxM. Piping k6 results into this exact stack.
- [reading] **How to visualize Prometheus histograms in Grafana** — Grafana blog — https://grafana.com/blog/2020/06/23/how-to-visualize-prometheus-histograms-in-grafana/.

## Concepts (teacher briefs these before code is shown)

1. Metric types: Counter, Gauge, Histogram — and why latency is a
   histogram, never an average.
2. Histogram mechanics: cumulative `le` buckets;
   `histogram_quantile(0.99, sum(rate(..._bucket[3m])) by (le))` — read
   it inside-out. Why server-side p99 resolution is bounded by bucket
   edges (this repo's first bucket is 5ms; k6 gives the sub-bucket truth).
3. Label discipline: why `route` must come from the route template, and
   how raw-path labels melt Prometheus (the `unmatched` fix).
4. The process model trap: `prometheus_client` registries are
   per-process; `--workers 2` behind one /metrics port = corrupted
   counters. One worker per container; scale containers.
5. RED/USE signals mapped onto the 7 dashboard panels: rate, errors,
   duration, saturation (consumer lag), plus domain signals
   (cache hit ratio, 429s, DLQ).
6. k6: ramping-arrival-rate vs VU loops (open vs closed workload
   models — why arrival-rate is the honest one), thresholds as CI
   gates, Zipf-skewed access patterns.
7. Benchmark honesty: what a laptop-loopback number IS evidence of
   (architecture behavior, relative scaling) and is NOT (production
   capacity). The README's protocol exists for this reason.

Reading order: `app/observability/metrics.py` → `workers/analytics.py`
(worker metrics) → `monitoring/prometheus/prometheus.yml` →
`monitoring/grafana/dashboards/shrtr.json` (skim panel exprs) →
`load/redirect_hot.js`.

## Labs

### Lab 5.1 — PromQL kata (do-together)
With the stack under `make load`, write from scratch in the Prometheus
UI: (a) redirect RPS, (b) p50/p95/p99 redirect latency, (c) cache hit
ratio over 5m, (d) 429 rate, (e) consumer lag. Compare with the
dashboard JSON only afterwards.

### Lab 5.2 — Rerun the benchmark (rebuild-solo ★)
Follow the README protocol end to end: document hardware, `make
seed-load`, `make load`, capture k6 summary + Grafana screenshot into
`benchmarks/<today>/`. Your numbers should be in the same family as
the committed run (0 failures, ~1ms p50 client-side at 500 rps on an
M3 Pro) — investigate any big delta until you can explain it.

### Lab 5.3 — Find the ceiling (do-together)
`TARGET_RPS=1000` (edit or env-inject the k6 options) and raise until
something gives. Identify WHAT gave from the dashboards alone (CPU?
pool waits? event-loop lag showing as p99 inflation?) before reading
any logs. Write the number + bottleneck into your PROGRESS.md.

### Lab 5.4 — Retell the two war stories with graphs (do-together)
(a) Reintroduce `--workers 2` on a branch, run load, and screenshot the
sawtooth/undercounting artifacts in the RPS panel. (b) Explain the 60
MaxConnectionsError 500s from the pre-fix benchmark: why did they only
appear with ONE worker, and why did the blocking pool fix them? Revert.

## Break-it drill

Stop Prometheus for 2 minutes under load, restart, and explain the gap
in every panel (scrape-time data, not event-time). Then stop the
*worker* and watch which panels notice (lag, published-vs-processed
divergence) and which don't — say why.

## Teach-back exam (no code visible)

1. ★ Explain `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[3m])) by (le))`
   token by token. Why rate() before quantile? Why sum by (le)?
2. ★ Why did `--workers 2` corrupt the metrics, mechanically? Two
   fixes existed (multiprocess mode, one-worker-per-container) — argue
   for the one taken.
3. ★ k6 said p50 = 0.87ms but the server histogram says p50 ≈ 2.5ms.
   Reconcile (bucket interpolation; first bucket edge at 5ms).
4. What made the connection pool overflow at 500 rps on one worker but
   not two? Why is a *blocking* pool the right fix for a hot path
   instead of a bigger cap alone?
5. Open vs closed workload model — why does ramping-arrival-rate model
   real traffic more honestly than a fixed VU loop?
6. Why is the load Zipf-skewed, and what would uniform selection
   overstate/understate about the cache?
7. Your p99 threshold is `<250ms` but max was 168ms during a clean run.
   What causes isolated 100ms+ spikes on a loopback benchmark, and how
   would you confirm the hypothesis? (GC/event-loop stalls, container
   scheduling — and the experiment for each.)
