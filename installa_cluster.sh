#!/bin/bash
set -e

BOLD="\033[1m"
RESET="\033[0m"

echo -e "${BOLD}=== 1. Creazione cluster ===${RESET}"
kind create cluster --config=init_cluster.yaml

echo -e "${BOLD}=== 2. Namespace kyma-system ===${RESET}"
kubectl create ns kyma-system

echo -e "${BOLD}=== 3. Namespace oauth-lab ===${RESET}"
kubectl apply -f k8s/namespace.yaml

echo -e "${BOLD}=== 4. PostgreSQL ===${RESET}"
kubectl apply -f k8s/keycloak/postgres.yaml
kubectl -n oauth-lab wait --for=condition=Available deployment/postgres --timeout=300s
kubectl -n oauth-lab wait --for=condition=Ready pod -l app=postgres --timeout=300s

echo -e "${BOLD}=== 5. Keycloak Secret ===${RESET}"
kubectl apply -f k8s/keycloak/keycloak-secret.yaml

echo -e "${BOLD}=== 6. Keycloak ConfigMap ===${RESET}"
kubectl apply -f k8s/keycloak/keycloak-config.yaml

echo -e "${BOLD}=== 7. Keycloak Deployment ===${RESET}"
kubectl apply -f k8s/keycloak/keycloak.yaml
kubectl -n oauth-lab wait --for=condition=Available deployment/keycloak --timeout=300s
kubectl -n oauth-lab wait --for=condition=Ready pod -l app=keycloak --timeout=300s

echo -e "${BOLD}=== 8. Busola Config (ConfigMap, SA, ClusterRoleBinding) ===${RESET}"
kubectl apply -f k8s/busola/

echo -e "${BOLD}=== 9. Metric Server ===${RESET}"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='json' -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

echo -e "${BOLD}=== 10. Busola Dashboard ===${RESET}"
kubectl apply -f https://github.com/kyma-project/busola/releases/download/1.0.50/busola.yaml
kubectl -n default wait --for=condition=Available deployment/busola --timeout=300s
kubectl -n default wait --for=condition=Ready pod -l app=busola --timeout=300s

echo -e "${BOLD}=== 11. Telemetry Manager ===${RESET}"
kubectl apply -f https://github.com/kyma-project/telemetry-manager/releases/latest/download/telemetry-manager.yaml
kubectl apply -f https://github.com/kyma-project/telemetry-manager/releases/latest/download/telemetry-default-cr.yaml -n kyma-system
kubectl -n kyma-system wait --for=condition=Available deployment/telemetry-manager --timeout=300s
kubectl -n kyma-system wait --for=condition=Ready pod -l app.kubernetes.io/name=manager --timeout=300s
kubectl apply -f k8s/telemetria/tracepipeline.yaml

echo -e "${BOLD}=== 11a. cert-manager ===${RESET}"
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl -n cert-manager wait --for=condition=Available deployment/cert-manager --timeout=300s
kubectl -n cert-manager wait --for=condition=Available deployment/cert-manager-webhook --timeout=300s

echo -e "${BOLD}=== 11b. OpenTelemetry Operator (CRD + operatore) ===${RESET}"
kubectl apply -f https://github.com/open-telemetry/opentelemetry-operator/releases/download/v0.161.0/opentelemetry-operator.yaml
kubectl -n opentelemetry-operator-system wait --for=condition=Available deployment/opentelemetry-operator-controller-manager --timeout=300s

echo -e "${BOLD}=== 11c. Instrumentazione automatica OpenTelemetry ===${RESET}"
kubectl apply -f k8s/telemetria/instrumentation.yaml

echo -e "${BOLD}=== 12. Elastic Stack ===${RESET}"
kubectl apply -f k8s/telemetria/elastic.yaml
kubectl -n default wait --for=condition=Ready pod -l app=elasticsearch --timeout=300s
kubectl -n default wait --for=condition=Ready pod -l app=kibana --timeout=300s

echo -e "${BOLD}=== 13. OAuth Client ===${RESET}"
kubectl apply -f k8s/app/deployment.yaml
kubectl apply -f k8s/app/service.yaml
kubectl -n oauth-lab wait --for=condition=Available deployment/oauth-client --timeout=300s
kubectl -n oauth-lab wait --for=condition=Ready pod -l app=oauth-client --timeout=300s

echo ""
echo -e "${BOLD}*****************************************************************************${RESET}"
echo -e "${BOLD}KeyCloak User: admin, Password: admin${RESET}"
echo -e "${BOLD}Keycloak: http://localhost:30081${RESET}"
podman exec kyma-control-plane kubectl config view --raw > kubeconfig
echo -e "${BOLD}Dashboard: usa il file kubeconfig in questa directory per accedere al cluster${RESET}"
echo -e "${BOLD}OAuth Client: http://localhost:30080 ${RESET}"
echo -e "${BOLD}Kibana: http://localhost:30082 ${RESET}"
echo -e "${BOLD}*****************************************************************************${RESET}"