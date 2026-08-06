#!/usr/bin/env bash
# Provisions the Service Bus namespace, queue, topic, and filtered
# subscriptions used by Version B (Logic Apps + Service Bus).
#
# Usage:
#   RESOURCE_GROUP=cst8917-assignment2 LOCATION=canadacentral \
#   NAMESPACE=expense-approval-ns ./provision-service-bus.sh
#
# Requires: az CLI, logged in (`az login`), Standard tier namespace
# (topics/subscriptions require Standard or Premium — Basic tier is
# queue-only).

set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:?Set RESOURCE_GROUP}"
LOCATION="${LOCATION:-canadacentral}"
NAMESPACE="${NAMESPACE:?Set NAMESPACE (must be globally unique)}"
QUEUE_NAME="expense-requests"
TOPIC_NAME="expense-outcomes"

echo "Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

echo "Creating Service Bus namespace '$NAMESPACE' (Standard tier)..."
az servicebus namespace create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$NAMESPACE" \
  --location "$LOCATION" \
  --sku Standard \
  --output none

echo "Creating queue '$QUEUE_NAME'..."
az servicebus queue create \
  --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$NAMESPACE" \
  --name "$QUEUE_NAME" \
  --output none

echo "Creating topic '$TOPIC_NAME'..."
az servicebus topic create \
  --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$NAMESPACE" \
  --name "$TOPIC_NAME" \
  --output none

# --- Filtered subscriptions, one per outcome -------------------------------
# The Logic App stamps a custom application property "outcome" on every
# message it publishes to the topic (see logicapp/workflow.json). Each
# subscription below uses a SQL correlation filter on that property so
# only the matching outcome type lands in it.

for OUTCOME in approved rejected escalated validation_error; do
  SUB_NAME="${OUTCOME//_/-}-sub"
  echo "Creating subscription '$SUB_NAME' filtered on outcome='$OUTCOME'..."

  az servicebus topic subscription create \
    --resource-group "$RESOURCE_GROUP" \
    --namespace-name "$NAMESPACE" \
    --topic-name "$TOPIC_NAME" \
    --name "$SUB_NAME" \
    --output none

  az servicebus topic subscription rule create \
    --resource-group "$RESOURCE_GROUP" \
    --namespace-name "$NAMESPACE" \
    --topic-name "$TOPIC_NAME" \
    --subscription-name "$SUB_NAME" \
    --name "outcome-is-$OUTCOME" \
    --filter-sql-expression "outcome = '$OUTCOME'" \
    --output none
done

echo "Done. Connection string:"
az servicebus namespace authorization-rule keys list \
  --resource-group "$RESOURCE_GROUP" \
  --namespace-name "$NAMESPACE" \
  --name RootManageSharedAccessKey \
  --query primaryConnectionString \
  --output tsv
