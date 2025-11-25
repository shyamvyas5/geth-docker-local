# Geth Local

Deploy a local geth dev node, python load tester, and prometheus monitoring stack in k8s

## Prerequisites
- kubectl
- helm

## Commands

### Installs kind if not installed and creates the cluster named "test"
- `./setup-kind.sh --create`
  Installs kind if not installed and creates kind cluster named "test"

- `./setup-kind.sh --delete`
  Deletes kind cluster named "test"

### Create Resources

- `./run.sh --create-geth-dev`
  Deploys geth with --dev mode which creates statefulset and the namespace

- `./run.sh --check-blocks`
  Checks latest block production from the geth pod

- `./run.sh --create-load`
  Deploys the load-tester configmap, deployment, and grafana dashboard configmap

- `./run.sh --create-monitoring`
  Installs kube-prometheus-stack with values override file

- `./run.sh --grafana-port-forward`
  Port-forwards Grafana service to `localhost:8080`

---

### Delete Resources

- `./run.sh --delete-load`
  Removes all load-tester related resources

- `./run.sh --delete-geth-dev`
  Deletes the geth dev statefulset and its namespace

- `./run.sh --delete-monitoring`
  Uninstalls kube-prometheus-stack its `monitoring` namespace

### To check persistence of geth dev mode
1. Scale `geth-dev` statefulset's replica to 0 and do 1 again to check whether it is starting from the same block or not
```bash
kubectl -n geth-dev scale sts/geth-dev --replicas=0
kubectl -n geth-dev scale sts/geth-dev --replicas=1
```

### To run

1. Installs kind if not installed and creates kind cluster named "test"
  ```bash
  ./setup-kind.sh --create
  ```
2. Deploys geth with --dev mode which creates statefulset and the namespace
  ```bash
  ./run.sh --create-geth-dev
  ```
3. Checks latest block production from the geth pod and check 6 sec block production
  ```bash
  ./run.sh --check-blocks
  ```
4. Deploys the load-tester configmap, deployment, and grafana dashboard configmap
  ```bash
  ./run.sh --create-load
  ```
5. Installs kube-prometheus-stack with values override file
  ```bash
  ./run.sh --create-monitoring
  ```
6. Port-forwards Grafana service to `localhost:8080` and login in grafana with admin as password and go to Dashboard section
  ```bash
  ./run.sh --grafana-port-forward
  ```
7. Login in Grafana after port-forward with `admin` as username and password and go to `Dashboard` section

8. Removes all load-tester related resources
  ```bash
  ./run.sh --delete-load
  ```
9. Deletes the geth dev statefulset and its namespace
  ```bash
  ./run.sh --delete-geth-dev
  ```
10. Uninstalls kube-prometheus-stack its `monitoring` namespace
  ```bash
  ./run.sh --delete-monitoring
  ```
11. Deletes kind cluster named "test" which was created in the 1st step
  ```bash
  ./setup-kind.sh --delete
  ```

### Python script (run.py)
1. Geth dev mode comes with one pre-funded dev account, the script uses that dev pre-funded account and uses it as a sender to create and fund other test accounts
2. Then further transfers are done using those test accounts in continuous manner for load-testing geth `--dev` mode
3. Python script exposes metrics at `/metrics` from where Prometheus will scrape metrics

### Design
1. Used multiple test accounts as a single account cannot generate high TPS and can face nonce issues and multiple accounts can send transactions in parallel in `run.py`
2. Used Prometheus for monitoring and scrape the metrics from `/metrics` endpoint of python script and `/debug/metrics/prometheus` of geth-dev
3. Used `grafana_dashboard` label key and value with `load_tester` to auto load the dashboard in Grafana
4. Made python script (`run.py`) to make it running and keep trying connecting with geth dev rpc and also update the metrics and show failed count metrics increasing and showing it as `disconnected` with rpc
