#!/usr/bin/env bash
# Bootstrap a Kind (Kubernetes-in-Docker) cluster for CI use.
# Supports three profiles matching the plan's Kind Job A/B/C.
#
# Usage:
#   scripts/setup-kind.sh [profile]
#
# Profiles:
#   serving    — KServe + Knative (UC9, UC22) — Job A
#   pipelines  — Kubeflow Pipelines + Argo (UC9, UC14) — Job B
#   policy     — Kyverno + KEDA + OPA (UC4, UC7, UC12) — Job C
#
# Defaults to "policy" if no profile given.

set -euo pipefail

PROFILE="${1:-policy}"
CLUSTER_NAME="platform-${PROFILE}"
KUBECTL_VERSION="${KUBECTL_VERSION:-1.30.0}"
HELM_VERSION="${HELM_VERSION:-3.15.0}"

echo "[setup-kind] Profile: ${PROFILE}, cluster: ${CLUSTER_NAME}"

install_dependencies() {
    echo "[setup-kind] Installing kubectl v${KUBECTL_VERSION} ..."
    curl -Lo /usr/local/bin/kubectl \
        "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
    chmod +x /usr/local/bin/kubectl

    echo "[setup-kind] Installing Helm v${HELM_VERSION} ..."
    curl -Lo /tmp/helm.tar.gz \
        "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz"
    tar xzf /tmp/helm.tar.gz -C /tmp
    mv /tmp/linux-amd64/helm /usr/local/bin/helm
    chmod +x /usr/local/bin/helm
}

create_cluster() {
    local config_file="infra/kind/${PROFILE}-cluster.yml"

    if [ ! -f "$config_file" ]; then
        echo "[setup-kind] Config file $config_file not found — using default single-node"
        kind create cluster --name "${CLUSTER_NAME}" --wait 120s
    else
        kind create cluster --name "${CLUSTER_NAME}" --config "$config_file" --wait 120s
    fi

    kubectl cluster-info --context "kind-${CLUSTER_NAME}"
    echo "[setup-kind] Cluster ${CLUSTER_NAME} ready."
}

install_common() {
    # Install cert-manager (required by KServe, Kyverno)
    helm repo add jetstack https://charts.jetstack.io --force-update
    helm upgrade --install cert-manager jetstack/cert-manager \
        --namespace cert-manager --create-namespace \
        --set installCRDs=true \
        --wait --timeout 5m

    echo "[setup-kind] cert-manager installed."
}

install_serving() {
    install_common

    # Knative Serving (required by KServe)
    kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-crds.yaml
    kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-core.yaml

    # KServe
    helm repo add kserve https://kserve.github.io/kserve-charts --force-update
    helm upgrade --install kserve kserve/kserve \
        --namespace kserve --create-namespace \
        -f infra/helm/kserve/values.yml \
        --wait --timeout 10m || {
        echo "[setup-kind] KServe install failed — checking pod status"
        kubectl get pods -n kserve || true
        exit 1
    }

    echo "[setup-kind] KServe installed."
}

install_pipelines() {
    install_common

    # Kubeflow Pipelines (standalone)
    kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=2.2.0"
    kubectl wait crd/applications.app.k8s.io --for=condition=established --timeout=60s
    kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic-pns?ref=2.2.0"
    kubectl wait pods -n kubeflow --all --for=condition=Ready --timeout=300s || {
        echo "[setup-kind] Kubeflow Pipelines not ready — checking..."
        kubectl get pods -n kubeflow
        exit 1
    }

    echo "[setup-kind] Kubeflow Pipelines installed."
}

install_policy() {
    install_common

    # Kyverno
    helm repo add kyverno https://kyverno.github.io/kyverno --force-update
    helm upgrade --install kyverno kyverno/kyverno \
        --namespace kyverno --create-namespace \
        -f infra/helm/kyverno/values.yml \
        --wait --timeout 5m

    # KEDA
    helm repo add kedacore https://kedacore.github.io/charts --force-update
    helm upgrade --install keda kedacore/keda \
        --namespace keda --create-namespace \
        -f infra/helm/keda/values.yml \
        --wait --timeout 5m

    echo "[setup-kind] Kyverno + KEDA installed."
}

# ---- Main ----
install_dependencies

if kind get clusters | grep -q "${CLUSTER_NAME}"; then
    echo "[setup-kind] Cluster ${CLUSTER_NAME} already exists — skipping creation."
else
    create_cluster
fi

case "${PROFILE}" in
    serving)   install_serving ;;
    pipelines) install_pipelines ;;
    policy)    install_policy ;;
    *)
        echo "[setup-kind] Unknown profile: ${PROFILE}" >&2
        exit 1
        ;;
esac

echo "[setup-kind] Setup complete for profile: ${PROFILE}"
kubectl get nodes
