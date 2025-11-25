# Geth Local

Deploy a local geth dev node, python load tester, and prometheus monitoring stack in k8s

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
  Installs kube-prometheus-stack values override file

- `./run.sh --grafana-port-forward`
  Port-forwards Grafana service to `localhost:8080`

---

### Delete Resources

- `./run.sh --delete-load`
  Removes all load-tester related resources

- `./run.sh --delete-geth-dev`
  Deletes the geth dev statefulset and its namespace

- `./run.sh --delete-monitoring`
  Uninstalls kube-prometheus-stack its `monitoring` namespace.
