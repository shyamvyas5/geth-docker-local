#!/bin/bash
set -e

NAMESPACE="geth-dev"
YAML_FILE="./k8s/geth-dev-statefulset.yaml"
# GETH_DEV_DASHBOARD="load-tester-dashboard-configmap.yaml"

# Load tester YAML files
LOAD_CONFIGMAP="./k8s/load-tester-configmap.yaml"
LOAD_DEPLOYMENT="./k8s/load-tester-deployment.yaml"
LOAD_DASHBOARD="./k8s/load-tester-dashboard-configmap.yaml"

MONITORING_NAMESPACE="monitoring"
MONITORING_VALUES_OVERRIDE_FILE="./k8s/values-override-kube-prometheus-stack.yaml"

#######################################
# Check if namespace exists
#######################################
ns_exists() {
    kubectl get ns "${NAMESPACE}" >/dev/null 2>&1
}

#######################################
# Create geth namespace + apply YAML
#######################################
geth_create() {
    if ns_exists; then
        echo "Namespace '${NAMESPACE}' already exists."
        exit 0
    fi

    echo "Creating namespace '${NAMESPACE}'..."
    kubectl create ns "${NAMESPACE}"

    echo "Applying ${YAML_FILE}..."
    kubectl apply -n "${NAMESPACE}" -f "${YAML_FILE}"
    # kubectl apply -n "${NAMESPACE}" -f "${GETH_DEV_DASHBOARD}"

    echo "Geth resources created."
}

#######################################
# Delete geth namespace
#######################################
geth_delete() {
    if ! ns_exists; then
        echo "Namespace '${NAMESPACE}' does NOT exist."
        exit 0
    fi

    echo "Deleting ${YAML_FILE}..."
    kubectl delete -n "${NAMESPACE}" -f "${YAML_FILE}"
    sleep 5
    echo "Deleting namespace '${NAMESPACE}'..."
    kubectl delete ns "${NAMESPACE}" >/dev/null

    echo "Namespace '${NAMESPACE}' deleted."
}

is_geth_dev_up() {
    echo "Waiting for pod geth-dev-0 in namespace $NAMESPACE to be Running..."

    while true; do
        STATUS=$(kubectl get pod geth-dev-0 -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)

        if [ "$STATUS" = "Running" ]; then
            echo "Pod is Running!"
            return 0
        fi

        echo "Current status: $STATUS"
        sleep 2
    done
}

is_grafana_up() {
    GRAFANA_POD_NAME=$(kubectl -n "$MONITORING_NAMESPACE" get po | grep grafana | awk '{print $1}')
    echo "Waiting for pod $GRAFANA_POD_NAME in namespace $MONITORING_NAMESPACE to be Running..."

    while true; do
        STATUS=$(kubectl get pod "$GRAFANA_POD_NAME" -n "$MONITORING_NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)

        if [ "$STATUS" = "Running" ]; then
            echo "Grafana pod is Running!"
            return 0
        fi

        echo "Current status: $STATUS"
        sleep 2
    done
}

#######################################
# Monitor block production
#######################################
check_blocks() {
    if ! ns_exists; then
        echo "Namespace '${NAMESPACE}' does NOT exist. Cannot monitor."
        exit 1
    fi

    if ! is_geth_dev_up; then
        echo "Geth-dev is not up yet, cannot check blocks."
        exit 1
    fi

    echo "Monitoring block production..."
    sleep 5
    PREV_TIME=""

    while true; do
        payload=$(printf '{"jsonrpc":"2.0","method":"eth_getBlockByNumber","params":["latest",false],"id":1}')
        RESULT=$(kubectl -n "${NAMESPACE}" exec geth-dev-0 -- wget -qO- \
            --post-data="$payload" \
            --header='Content-Type: application/json' http://localhost:8545 2>/dev/null)

        BLOCK_HEX=$(echo "$RESULT" | grep -o '"number":"0x[0-9a-f]*"' | cut -d'"' -f4)
        TIME_HEX=$(echo "$RESULT" | grep -o '"timestamp":"0x[0-9a-f]*"' | cut -d'"' -f4)

        BLOCK_NUM=$(printf "%d" "$BLOCK_HEX")
        TIMESTAMP=$(printf "%d" "$TIME_HEX")

        if [ -n "$PREV_TIME" ]; then
            DIFF=$((TIMESTAMP - PREV_TIME))
            echo "$(date '+%H:%M:%S') | Block: $BLOCK_NUM | Since last: ${DIFF}s"
        else
            echo "$(date '+%H:%M:%S') | Block: $BLOCK_NUM | Starting..."
        fi

        PREV_TIME=$TIMESTAMP
        sleep 2
    done
}

#######################################
# Create load tester resources
#######################################
load_create() {
    if ! is_geth_dev_up; then
        echo "Geth-dev is not up yet, cannot create load-test."
        exit 1
    fi

    echo "Applying load tester YAMLs..."

    kubectl apply -f "${LOAD_CONFIGMAP}"
    kubectl apply -f "${LOAD_DEPLOYMENT}"
    kubectl apply -f "${LOAD_DASHBOARD}"

    sleep 5
    echo "Load tester resources created."
}

#######################################
# Delete load tester resources
#######################################
load_delete() {
    echo "Deleting load tester resources..."

    kubectl delete -f "${LOAD_DASHBOARD}" >/dev/null 2>&1 || true
    kubectl delete -f "${LOAD_DEPLOYMENT}" >/dev/null 2>&1 || true
    kubectl delete -f "${LOAD_CONFIGMAP}" >/dev/null 2>&1 || true

    echo "Load tester resources deleted."
}

#######################################
# deploy prometheus monitoring stack
#######################################
deploy_monitoring() {
    echo "=== Deploying Prometheus Monitoring Stack ==="

    if kubectl get ns ${MONITORING_NAMESPACE} >/dev/null 2>&1; then
        echo "Namespace '${MONITORING_NAMESPACE}' already exists"
    else
        kubectl create ns ${MONITORING_NAMESPACE}
    fi

    echo "adding prometheus-community helm chart repo"
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

    echo "running helm repo update"
    helm repo update

    echo "installing kube-prometheus-stack using kube-prometheus-stack with version 79.7.1"
    helm upgrade --install monitoring \
        -f ${MONITORING_VALUES_OVERRIDE_FILE} \
        prometheus-community/kube-prometheus-stack \
        --namespace ${MONITORING_NAMESPACE} \
        --version 79.7.1 2>/dev/null

    echo "Prometheus monitoring stack deployed"
}

#######################################
# grafana svc port-forward
#######################################
grafana_port_forward() {
    if ! is_grafana_up; then
        echo "Grafana pod is not up yet, cannot port-forward."
        exit 1
    fi
    echo "Port-forwarding Grafana on http://localhost:8080 ..."
    kubectl -n "${MONITORING_NAMESPACE}" port-forward svc/monitoring-grafana 8080:80
}

#######################################
# delete prometheus monitoring stack
#######################################
delete_monitoring() {
    echo "=== Deleting Prometheus Monitoring Stack ==="

    if ! kubectl get ns ${MONITORING_NAMESPACE} >/dev/null 2>&1; then
        echo "Namespace '${MONITORING_NAMESPACE}' does not exist so nothing to delete"
        return
    fi

    helm -n ${MONITORING_NAMESPACE} delete monitoring
    kubectl -n ${MONITORING_NAMESPACE} delete pvc prometheus-monitoring-kube-prometheus-prometheus-db-prometheus-monitoring-kube-prometheus-prometheus-0
    kubectl delete ns ${MONITORING_NAMESPACE}

    echo "Prometheus stack deleted"
}


#######################################
# Usage helper
#######################################
show_usage() {
    echo "Usage: $0 <command>"
    echo ""
    echo "Geth deployment:"
    echo "  --create-geth-dev      Create geth namespace + apply statefulset"
    echo "  --delete-geth-dev      Delete geth namespace"
    echo "  --check-blocks     Monitor block production"
    echo ""
    echo "Load tester:"
    echo "  --create-load      Apply load tester YAML files"
    echo "  --delete-load      Delete load tester resources"
    echo ""
    echo "Monitoring stack deploy:"
    echo "  --create-monitoring      Install Prometheus monitoring stack using helm chart with custom values override yaml file"
    echo "  --grafana-port-forward   port-forward grafana svc on port 8080"
    echo "  --delete-monitoring      Delete Prometheus monitoring stack using helm command"
    exit 1
}

#######################################
# Main dispatcher
#######################################
main() {
    case "$1" in
        --create-geth-dev)   geth_create ;;
        --delete-geth-dev)   geth_delete ;;
        --check-blocks)  check_blocks ;;
        --create-load)   load_create ;;
        --delete-load)   load_delete ;;
        --create-monitoring)   deploy_monitoring ;;
        --grafana-port-forward) grafana_port_forward ;;
        --delete-monitoring)   delete_monitoring ;;
        "" )             show_usage ;;
        * )              echo "Unknown option: $1"; show_usage ;;
    esac
}

main "$1"
