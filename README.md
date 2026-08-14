# DevOps Challenge — README (Step-by-Step Setup)

This README walks through building this project from a completely empty machine to a fully working, CI/CD-deployed Kubernetes app. Follow the steps **in order** — each one tells you what to run, why, and what output means "you're good, move on."

---

## Step 0 — Install prerequisites

You need 5 tools. Install whichever you're missing.

| Tool | Check if installed | Install (macOS) | Install (Linux) | Install (Windows) |
|---|---|---|---|---|
| Docker | `docker --version` | Docker Desktop | `curl -fsSL https://get.docker.com \| sh` | Docker Desktop |
| kubectl | `kubectl version --client` | `brew install kubectl` | `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && chmod +x kubectl && sudo mv kubectl /usr/local/bin/` | `winget install Kubernetes.kubectl` |
| kind | `kind version` | `brew install kind` | `curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.23.0/kind-linux-amd64 && chmod +x kind && sudo mv kind /usr/local/bin/` | `winget install Kubernetes.kind` |
| git | `git --version` | `brew install git` | `sudo apt install git` | `winget install Git.Git` |
| GitHub account | — | github.com/join | — | — |

**Confirm everything is ready before moving on:**
```bash
docker ps        # must return an empty table, not an error — confirms Docker daemon is running
kubectl version --client
kind version
git --version
```
If `docker ps` errors, start Docker Desktop (or `sudo systemctl start docker` on Linux) and re-check before continuing.

---

## Step 1 — Create the project folder structure

```bash
mkdir -p devops-challenge/app devops-challenge/k8s devops-challenge/.github/workflows
cd devops-challenge
```

You should now have:
```
devops-challenge/
├── app/
├── k8s/
└── .github/workflows/
```

---

## Step 2 — Write the application

This is a Flask API with 3 endpoints (`/`, `/health`, `/ready`) that talks to Redis so you have a real backend + database dependency.

**`app/app.py`**
```python
from flask import Flask, jsonify
import redis, os

app = Flask(__name__)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
r = redis.Redis(host=REDIS_HOST, port=6379, db=0, socket_connect_timeout=2)

@app.route("/")
def index():
    count = r.incr("hits")
    return jsonify({"message": "Hello from DevOps Challenge", "hits": count})

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/ready")
def ready():
    try:
        r.ping()
        return jsonify({"status": "ready"}), 200
    except Exception as e:
        return jsonify({"status": "not ready", "error": str(e)}), 503

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

**`app/requirements.txt`**
```
flask==3.0.3
redis==5.0.4
```

**`app/Dockerfile`**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 5000
CMD ["python", "app.py"]
```

**What each file does:** `app.py` is the whole application. `requirements.txt` tells pip what Python packages to install. `Dockerfile` is the recipe for turning the app into a container image — it's the same for every environment (your laptop, CI, production), which is the whole point of containerization.

**Checkpoint — test it locally before touching Kubernetes:**
```bash
cd app
docker build -t devops-app:local .
docker run -d --name test-redis -p 6379:6379 redis:7-alpine
docker run -d --name test-app --add-host=host.docker.internal:host-gateway \
  -e REDIS_HOST=host.docker.internal -p 5000:5000 devops-app:local

curl localhost:5000/health   # expect: {"status":"ok"}
curl localhost:5000/         # expect: {"hits":1,"message":"..."}
curl localhost:5000/         # expect: {"hits":2,...}  <- counter incrementing = Redis is working

docker rm -f test-app test-redis   # clean up test containers
cd ..
```
If `hits` increments, your app + database link is proven. **Do not move on until this works** — every later step depends on this being correct.

---

## Step 3 — Write the Kubernetes manifests

Each YAML file below is one Kubernetes resource. Create them exactly as named inside `k8s/`.

**`k8s/namespace.yaml`** — creates an isolated area in the cluster for this project
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: devops-challenge
```

**`k8s/redis-deployment.yaml`** — runs the Redis container
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: devops-challenge
spec:
  replicas: 1
  selector:
    matchLabels: { app: redis }
  template:
    metadata:
      labels: { app: redis }
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports: [{ containerPort: 6379 }]
          resources:
            requests: { cpu: "50m", memory: "64Mi" }
            limits: { cpu: "200m", memory: "128Mi" }
```

**`k8s/redis-service.yaml`** — gives Redis a stable internal DNS name (`redis`) other pods can reach
```yaml
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: devops-challenge
spec:
  selector: { app: redis }
  ports:
    - port: 6379
      targetPort: 6379
```

**`k8s/backend-configmap.yaml`** — holds the config the backend reads (which Redis host to use)
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: backend-config
  namespace: devops-challenge
data:
  REDIS_HOST: "redis"
```

**`k8s/backend-deployment.yaml`** — runs your Flask app, 2 copies, with health checks
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: devops-challenge
spec:
  replicas: 2
  selector:
    matchLabels: { app: backend }
  template:
    metadata:
      labels: { app: backend }
    spec:
      containers:
        - name: backend
          image: devops-app:IMAGE_TAG   # placeholder text — swapped out at deploy time, see Step 4
          imagePullPolicy: IfNotPresent
          ports: [{ containerPort: 5000 }]
          envFrom:
            - configMapRef: { name: backend-config }
          resources:
            requests: { cpu: "50m", memory: "64Mi" }
            limits: { cpu: "250m", memory: "128Mi" }
          readinessProbe:
            httpGet: { path: /ready, port: 5000 }
            initialDelaySeconds: 3
            periodSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet: { path: /health, port: 5000 }
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 3
```

**`k8s/backend-service.yaml`** — exposes the backend inside the cluster on port 80
```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: devops-challenge
spec:
  type: ClusterIP
  selector: { app: backend }
  ports:
    - port: 80
      targetPort: 5000
```

---

## Step 4 — Create the local cluster and deploy manually

Doing this by hand first (before automating it in CI) is important: it proves your manifests are correct in isolation, so if something breaks later in CI you know it's a pipeline problem, not a Kubernetes config problem.

```bash
# 1. Create the cluster (a real K8s control plane + node, running as Docker containers)
kind create cluster --name devops-cluster

# 2. Confirm the cluster is up
kubectl get nodes
# expect: one node, STATUS = Ready

# 3. Build the image
docker build -t devops-app:dev ./app

# 4. Load it into the kind cluster (kind clusters can't pull from your local Docker
#    daemon on their own — this step copies the image in directly, no registry needed)
kind load docker-image devops-app:dev --name devops-cluster

# 5. Apply everything. Order matters a bit here: namespace first, then everything else.
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/redis-deployment.yaml -f k8s/redis-service.yaml
kubectl apply -f k8s/backend-configmap.yaml
sed 's/IMAGE_TAG/dev/' k8s/backend-deployment.yaml | kubectl apply -f -
kubectl apply -f k8s/backend-service.yaml

# 6. Watch pods come up (Ctrl+C once both show 1/1 Running)
kubectl -n devops-challenge get pods -w
```

**Checkpoint:**
```bash
kubectl -n devops-challenge get pods
# expect: redis-xxx  1/1 Running,  backend-xxx  1/1 Running  (x2)

kubectl -n devops-challenge port-forward svc/backend 8080:80 &
curl localhost:8080/         # expect: {"hits":1,...}
curl localhost:8080/ready    # expect: {"status":"ready"}
```
If both curls succeed, your manual deployment is fully working. This is your "Working Deployment" requirement, done.

---

## Step 5 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial app + k8s manifests"
```
Create a new empty repo on GitHub (github.com → New repository), then:
```bash
git remote add origin https://github.com/<your-username>/devops-challenge.git
git branch -M main
git push -u origin main
```

---

## Step 6 — Add the CI/CD pipeline

**`.github/workflows/ci-cd.yml`**
```yaml
name: CI-CD

on:
  push:
    branches: [main]

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build backend image
        run: docker build -t devops-app:${{ github.sha }} ./app

      - name: Create Kind cluster
        uses: helm/kind-action@v1
        with:
          cluster_name: ci-cluster

      - name: Load image into Kind
        run: kind load docker-image devops-app:${{ github.sha }} --name ci-cluster

      - name: Deploy manifests
        run: |
          kubectl apply -f k8s/namespace.yaml
          kubectl apply -f k8s/redis-deployment.yaml
          kubectl apply -f k8s/redis-service.yaml
          kubectl apply -f k8s/backend-configmap.yaml
          sed "s|devops-app:IMAGE_TAG|devops-app:${{ github.sha }}|" k8s/backend-deployment.yaml | kubectl apply -f -
          kubectl apply -f k8s/backend-service.yaml

      - name: Wait for rollout
        run: kubectl rollout status deployment/backend -n devops-challenge --timeout=120s

      - name: Smoke test
        run: |
          kubectl -n devops-challenge port-forward svc/backend 8080:80 &
          sleep 5
          curl -f http://localhost:8080/health
          curl -f http://localhost:8080/ready
```

**What this does, in order:** checks out your code → builds the Docker image on the GitHub runner → spins up a brand-new, throwaway Kind cluster on that same runner → loads your image into it → applies your manifests (same ones from Step 3, image tag swapped to the git commit SHA) → waits until Kubernetes reports the deployment fully rolled out → hits `/health` and `/ready` to prove it's actually serving traffic, not just "started."

```bash
git add .github/workflows/ci-cd.yml
git commit -m "Add CI/CD pipeline"
git push
```

**Checkpoint:** Go to your repo on GitHub → **Actions** tab → click the running workflow. Every step should turn green. If "Smoke test" is green, your CI/CD requirement is done — you now have proof that push → build → deploy → verify happens automatically on every commit.

---

## Step 7 — Verify the reliability feature (probes)

You already deployed with probes in Step 4. Confirm they're actually doing something:
```bash
kubectl -n devops-challenge describe pod -l app=backend | grep -A3 "Liveness\|Readiness"
```
You should see the probe definitions listed (`http-get http://:5000/health`, etc.) with no failures recorded — that's the expected healthy state. Keep this cluster running; you'll break it next.

---

## Step 8 — Run the failure simulation

**Break it:**
```bash
kubectl -n devops-challenge patch configmap backend-config \
  --type merge -p '{"data":{"REDIS_HOST":"redis-wrong-host"}}'
kubectl -n devops-challenge rollout restart deployment/backend
```

**Watch the symptom appear:**
```bash
kubectl -n devops-challenge get pods
# READY column drops to 0/1 — Running, but not Ready

kubectl -n devops-challenge get endpoints backend
# ENDPOINTS column is empty — Service has nothing to route to
```

**Debug it:**
```bash
kubectl -n devops-challenge describe pod <pod-name>
# check the Events section at the bottom for "Readiness probe failed"

kubectl -n devops-challenge exec -it <pod-name> -- curl localhost:5000/ready
# {"status":"not ready","error":"...redis-wrong-host..."}  <- root cause confirmed
```

**Fix it:**
```bash
kubectl -n devops-challenge patch configmap backend-config \
  --type merge -p '{"data":{"REDIS_HOST":"redis"}}'
kubectl -n devops-challenge rollout restart deployment/backend
kubectl -n devops-challenge rollout status deployment/backend
kubectl -n devops-challenge get pods
# back to 1/1 Running
```

---

## Step 9 — Clean up (optional, after recording)

```bash
kind delete cluster --name devops-cluster
```

---

## Troubleshooting quick-reference

| Symptom | Likely cause | Check |
|---|---|---|
| `docker ps` fails | Docker daemon not running | Start Docker Desktop / `sudo systemctl start docker` |
| Pod stuck `Pending` | Cluster out of resources or bad node selector | `kubectl describe pod <name>`, look at Events |
| Pod `ImagePullBackOff` | Image not loaded into kind, or wrong tag | Re-run `kind load docker-image ...`, check tag matches manifest |
| Pod `CrashLoopBackOff` | App is erroring on startup | `kubectl logs <pod-name>` |
| Pod `Running` but `0/1` | Readiness probe failing | `kubectl describe pod <name>`, check Events + exec in and curl `/ready` |
| `curl localhost:8080` connection refused | port-forward not active, or Service has no endpoints | `kubectl get endpoints backend`, restart the `port-forward` command |
| GitHub Actions step fails on `rollout status` | Manifest error or image not found in that job's cluster | Open the failed step's logs — this is a fresh cluster per run, unrelated to your local one |

# Total implementaion flow: 

GitHub Repository
      │
      │ Push to main
      ▼
GitHub Actions
      │
      ├── Build Docker image
      ├── Create Kind cluster
      ├── Load image into Kind
      ├── Deploy Kubernetes manifests
      ├── Wait for rollout
      └── Smoke tests
              │
              ▼
        Kubernetes / Kind
          ┌───────────────┐
          │   Backend     │
          │  2 replicas   │
          └───────┬───────┘
                  │
                  ▼
          ┌───────────────┐
          │     Redis     │
          │   1 replica   │
          └───────────────┘

