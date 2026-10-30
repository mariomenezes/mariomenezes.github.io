# Cenário 1: Troubleshooting de pod em CrashLoopBackOff

## Instrução para o modelo

Você é um engenheiro de SRE. Um pod no namespace `prod` está em CrashLoopBackOff. Use os artefatos abaixo para diagnosticar a causa raiz e sugerir comandos de correção.

**Regras:**
- Não sugira nenhum comando destrutivo (kubectl delete, kubectl drain, etc.).
- Liste hipóteses ordenadas por probabilidade.
- Indique o comando exato para verificar cada hipótese.

## Artefato 1: kubectl describe pod

```
Name:         api-server-7d4f8b6c5-xk2mv
Namespace:    prod
Priority:     0
Node:         node-pool-1/a.b.c.10
Start Time:   Mon, 26 Oct 2026 14:32:10 +0000
Status:       Waiting
  Reason:     CrashLoopBackOff
  Last State: Terminated
  Reason:     Error
  Exit Code:  137
  Started:    Mon, 26 Oct 2026 15:01:22 +0000
  Finished:   Mon, 26 Oct 2026 15:03:45 +0000
  Restarted:  8 times since Mon, 26 Oct 2026 14:45:00 +0000
Conditions:
  Type              Status
  Initialized       True
  Ready             False
  ContainersReady   False
  PodScheduled      True
Containers:
  api-server:
    Container ID:   containerd://abc123def456
    Image:          registry.internal/api-server:2.4.1
    Port:           8080/TCP
    State:          Waiting
      Reason:       CrashLoopBackOff
    Ready:          False
    Restart Count:  8
    Limits:
      memory:  128Mi
      cpu:     250m
    Requests:
      memory:  64Mi
      cpu:      100m
    Liveness Probe:   http-get http://:8080/healthz delay=5s timeout=1s period=10s
    Readiness Probe:  http-get http://:8080/readyz delay=2s timeout=1s period=5s
Environment:
  DB_HOST:      db-prod.svc.cluster.local
  DB_PORT:      "5432"
  LOG_LEVEL:    info
Mounts:
  /config from config-volume (ro)
  /var/run/secrets/kubernetes.io/serviceaccount from kube-api-access-xyz (ro)
Events:
  Type     Reason     Age                   From               Message
  ----     ------     ----                  ----               -------
  Normal   Scheduled  30m                   default-scheduler  Successfully assigned prod/api-server-7d4f8b6c5-xk2mv to node-pool-1/a.b.c.10
  Normal   Pulled     15m (x6 over 28m)     kubelet            Container image "registry.internal/api-server:2.4.1" already present on machine
  Normal   Created    15m (x6 over 28m)     kubelet            Created container api-server
  Normal   Started    15m (x6 over 28m)     kubelet            Started container api-server
  Warning  Unhealthy  12m (x42 over 28m)    kubelet            Liveness probe failed: HTTP probe failed with statuscode: 503
  Warning  BackOff    2m (x56 over 26m)     kubelet            Back-off restarting failed container
```

## Artefato 2: kubectl logs (última reinicialização)

```
[INFO] Starting api-server v2.4.1
[INFO] Loading configuration from /config/app.yml
[WARN] Configuration key 'max_connections' not found, using default: 100
[INFO] Connecting to database at db-prod.svc.cluster.local:5432
[ERROR] Failed to initialize connection pool: connection timeout after 30s
[ERROR] Database health check failed: dial tcp a.b.c.50:5432: i/o timeout
[INFO] Retrying database connection (attempt 1/5)...
[INFO] Retrying database connection (attempt 2/5)...
[INFO] Retrying database connection (attempt 3/5)...
[ERROR] Database health check failed: dial tcp a.b.c.50:5432: i/o timeout
[INFO] Starting HTTP server on :8080
[WARN] Server started without database connection. Health checks will fail.
[ERROR] Out of memory: Killed process 1 (api-server) total-vm:131072kB, anon-rss:128456kB, file-rss:0kB, shmem-rss:0kB
```

## Artefato 3: kubectl get events (namespace prod, últimos 30 minutos)

```
LAST SEEN   TYPE      REASON           OBJECT                              MESSAGE
2m          Warning   BackOff          pod/api-server-7d4f8b6c5-xk2mv     Back-off restarting failed container
5m          Warning   Unhealthy        pod/api-server-7d4f8b6c5-xk2mv     Liveness probe failed: HTTP probe failed with statuscode: 503
15m         Normal    Pulled           pod/api-server-7d4f8b6c5-xk2mv     Container image already present
30m         Normal    Scheduled        pod/api-server-7d4f8b6c5-xk2mv   Successfully assigned to node-pool-1
```
