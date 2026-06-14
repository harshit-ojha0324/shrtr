# Kubernetes — stretch placeholder (NOT implemented)

Nothing here is deployed or claimable yet. Per the project's honesty rules, no Kubernetes
claim goes on the resume until these manifests exist and have been applied to a local
kind/minikube cluster with HPA behavior observed under k6 load.

Planned (`to build`):
- `api-deployment.yaml`, `worker-deployment.yaml` — separate Deployments (independent scaling/rollouts)
- `services.yaml`, `configmap.yaml`, `secret.yaml`
- `hpa.yaml` — CPU-based HorizontalPodAutoscaler for the api Deployment
- kustomization, resource requests/limits, readiness/liveness probes wired to /healthz `/readyz`
- Postgres/Redis as in-cluster dev instances (with a note that production would use managed services)

Acceptance before claiming: `kubectl apply -k k8s/` on kind succeeds; `kubectl get hpa -w`
captured while `make load` runs; output committed to `benchmarks/`.
