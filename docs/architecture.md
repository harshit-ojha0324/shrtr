# Architecture diagram

The README carries the canonical mermaid diagram (GitHub renders it natively).
This ASCII version is the quick terminal reference.

```
            ┌─────────────────────────────────────────────────────────┐
            │                       client / k6                       │
            └────────────┬──────────────────────────┬─────────────────┘
                         │ GET /{code}              │ POST /api/v1/links (X-API-Key)
                         v                          v
            ┌─────────────────────────────────────────────────────────┐
            │        FastAPI api (1 uvicorn worker per container)     │
            │  auth → token-bucket rate limit → handler               │
            └──────┬──────────────────┬───────────────────┬──────────┘
       cache GET/SET│        rl:{key} Lua│          XADD clicks│ (background)
                   v                  v                    v
            ┌─────────────────────────────────────────────────────────┐
            │   Redis: link:{code} · 404:{code} · rl:{id} · clicks    │
            └──────────────────────────────┬──────────────────────────┘
   cache miss │ point read                 │ XREADGROUP analytics
              v                            v
   ┌────────────────────┐      ┌──────────────────────────┐
   │     PostgreSQL     │<─────│  workers ×N (consumer    │
   │ links · rollups ·  │upsert│  group): ledger insert,  │
   │ processed_events   │      │  commit, then XACK; DLQ  │
   └────────────────────┘      └──────────────────────────┘

   Prometheus scrapes api:8000/metrics and worker:9100 → Grafana "shrtr" dashboard
```
