#!/bin/bash
set -e

CLUSTER_NAME="test"
VERSION="v0.30.0"

#######################################
# Check if cluster exists
#######################################
cluster_exists() {
    install_kind
    kind get clusters | grep -q "^${CLUSTER_NAME}$"
}

#######################################
# Install kind if not installed
#######################################
install_kind() {
    if command -v kind &> /dev/null; then
        return
    fi

    echo "Kind not found. Installing..."

    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    case ${ARCH} in
        x86_64) ARCH="amd64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        *) echo "Unsupported architecture: ${ARCH}"; exit 1 ;;
    esac

    echo "Detected platform: ${OS}-${ARCH}"

    curl -Lo ./kind "https://kind.sigs.k8s.io/dl/${VERSION}/kind-${OS}-${ARCH}"
    chmod +x ./kind
    sudo mv ./kind /usr/local/bin/kind
}

#######################################
# Create the cluster
#######################################
create_cluster() {
    if cluster_exists; then
        echo "Cluster '${CLUSTER_NAME}' already exists."
        exit 0
    fi

    install_kind

    echo "Creating cluster '${CLUSTER_NAME}'..."
    kind create cluster --name "${CLUSTER_NAME}"

    echo "✓ Cluster '${CLUSTER_NAME}' created."
    kubectl get nodes
}

#######################################
# Delete the cluster
#######################################
delete_cluster() {
    if ! cluster_exists; then
        echo "Cluster '${CLUSTER_NAME}' does not exist."
        exit 0
    fi

    echo "Deleting cluster '${CLUSTER_NAME}'..."
    kind delete cluster --name "${CLUSTER_NAME}"

    echo "✓ Cluster '${CLUSTER_NAME}' deleted."
}

#######################################
# Show Usage
#######################################
show_usage() {
    echo "Usage: $0 [--create | --delete]"
    echo "  --create    Create the cluster"
    echo "  --delete    Delete the cluster"
    exit 1
}

#######################################
# Main Dispatcher
#######################################
main() {
    case "$1" in
        --create)
            create_cluster
            ;;
        --delete)
            delete_cluster
            ;;
        "")
            show_usage   # safe default
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            ;;
    esac
}

# Call the main function
main "$1"
