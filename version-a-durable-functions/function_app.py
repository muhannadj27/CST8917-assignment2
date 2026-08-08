"""
Expense Approval Workflow — Azure Durable Functions (Python v2 model)

Pattern: Human Interaction (durable timer + external event race)
https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview

Flow:
  1. HTTP trigger `submit_expense` starts the orchestrator and returns the
     standard Durable Functions status-check payload.
  2. Orchestrator `expense_orchestrator` calls the `validate_expense`
     activity first. Invalid input short-circuits the workflow.
  3. If amount < 100, `auto_approve` activity runs immediately.
  4. If amount >= 100, the orchestrator creates a durable timer (timeout)
     and waits on an external event ("ManagerDecision") with
     `task_all`/`Task.any` semantics. Whichever fires first wins:
       - Manager responds  -> approved / rejected
       - Timer fires first -> auto-approved + escalated flag
  5. `send_notification` activity emails the employee the final outcome.
  6. HTTP trigger `manager_decision` raises the external event that the
     orchestrator is waiting on, simulating a manager clicking
     Approve/Reject in an email or Teams card.
"""

import json
import logging
import os
from datetime import timedelta

import azure.durable_functions as df
import azure.functions as func
from azure.communication.email import EmailClient

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

VALID_CATEGORIES = {"travel", "meals", "supplies", "equipment", "software", "other"}
AUTO_APPROVE_THRESHOLD = 100
MANAGER_RESPONSE_TIMEOUT_MINUTES = 5  # short for demo/testing; use hours/days in prod


# --------------------------------------------------------------------------
# HTTP Trigger: submit a new expense -> starts the orchestration
# --------------------------------------------------------------------------
@app.route(route="expenses", methods=["POST"])
@app.durable_client_input(client_name="client")
async def submit_expense(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    instance_id = await client.start_new("expense_orchestrator", client_input=expense)
    logging.info(f"Started orchestration with ID = '{instance_id}'.")

    return client.create_check_status_response(req, instance_id)


# --------------------------------------------------------------------------
# HTTP Trigger: manager approves/rejects -> raises external event
# --------------------------------------------------------------------------
@app.route(route="expenses/{instanceId}/decision", methods=["POST"])
@app.durable_client_input(client_name="client")
async def manager_decision(req: func.HttpRequest, client: df.DurableOrchestrationClient) -> func.HttpResponse:
    instance_id = req.route_params.get("instanceId")

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        return func.HttpResponse(
            json.dumps({"error": "decision must be 'approved' or 'rejected'"}),
            status_code=400,
            mimetype="application/json",
        )

    status = await client.get_status(instance_id)
    if status is None:
        return func.HttpResponse(
            json.dumps({"error": f"No orchestration instance found with ID '{instance_id}'"}),
            status_code=404,
            mimetype="application/json",
        )

    await client.raise_event(instance_id, "ManagerDecision", body)
    logging.info(f"Raised ManagerDecision={decision} for instance '{instance_id}'.")

    return func.HttpResponse(
        json.dumps({"message": f"Decision '{decision}' submitted for instance '{instance_id}'."}),
        status_code=202,
        mimetype="application/json",
    )


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------
@app.orchestration_trigger(context_name="context")
def expense_orchestrator(context: df.DurableOrchestrationContext):
    expense = context.get_input()

    # Step 1: validate input
    validation = yield context.call_activity("validate_expense", expense)
    if not validation["valid"]:
        result = {
            "status": "validation_error",
            "errors": validation["errors"],
            "expense": expense,
        }
        yield context.call_activity("send_notification", {"expense": expense, "result": result})
        return result

    amount = expense["amount"]

    # Step 2: auto-approve small expenses, no human interaction needed
    if amount < AUTO_APPROVE_THRESHOLD:
        approval = yield context.call_activity("auto_approve", expense)
        result = {
            "status": "approved",
            "reason": "auto-approved: amount under $100",
            "expense": expense,
            "escalated": False,
        }
        yield context.call_activity("send_notification", {"expense": expense, "result": result})
        return result

    # Step 3: Human Interaction pattern — race the manager's decision
    # against a durable timer used as a timeout.
    if not context.is_replaying:
        logging.info(f"Waiting up to {MANAGER_RESPONSE_TIMEOUT_MINUTES} min for manager decision.")

    timeout_at = context.current_utc_datetime + timedelta(minutes=MANAGER_RESPONSE_TIMEOUT_MINUTES)
    timeout_task = context.create_timer(timeout_at)
    decision_task = context.wait_for_external_event("ManagerDecision")

    winner = yield context.task_any([decision_task, timeout_task])

    if winner == decision_task:
        # Manager responded in time — cancel the still-pending timer.
        timeout_task.cancel()
        decision = decision_task.result
        if isinstance(decision, str):
            # The durable-functions Python client's raise_event JSON-encodes
            # event_data before sending; the orchestrator can receive it back
            # as a JSON string rather than an already-parsed dict.
            decision = json.loads(decision)
        if decision.get("decision") == "approved":
            result = {
                "status": "approved",
                "reason": f"approved by manager ({expense.get('managerEmail')})",
                "expense": expense,
                "escalated": False,
            }
        else:
            result = {
                "status": "rejected",
                "reason": decision.get("comment", f"rejected by manager ({expense.get('managerEmail')})"),
                "expense": expense,
                "escalated": False,
            }
    else:
        # Timer fired first — no manager response within the window.
        decision_task.cancel() if hasattr(decision_task, "cancel") else None
        result = {
            "status": "approved",
            "reason": "auto-approved after timeout: no manager response",
            "expense": expense,
            "escalated": True,
        }

    # Step 4: notify employee of the final outcome
    yield context.call_activity("send_notification", {"expense": expense, "result": result})

    return result


# --------------------------------------------------------------------------
# Activity: validate_expense
# --------------------------------------------------------------------------
@app.activity_trigger(input_name="expense")
def validate_expense(expense: dict) -> dict:
    errors = []
    required_fields = [
        "employeeName",
        "employeeEmail",
        "amount",
        "category",
        "description",
        "managerEmail",
    ]

    for field in required_fields:
        if not expense.get(field) and expense.get(field) != 0:
            errors.append(f"Missing required field: {field}")

    if "amount" in expense and expense.get("amount") is not None:
        try:
            amount = float(expense["amount"])
            if amount <= 0:
                errors.append("amount must be greater than 0")
        except (TypeError, ValueError):
            errors.append("amount must be a number")

    category = expense.get("category")
    if category and category not in VALID_CATEGORIES:
        errors.append(
            f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        )

    return {"valid": len(errors) == 0, "errors": errors}


# --------------------------------------------------------------------------
# Activity: auto_approve
# --------------------------------------------------------------------------
@app.activity_trigger(input_name="expense")
def auto_approve(expense: dict) -> dict:
    logging.info(f"Auto-approving expense for {expense.get('employeeName')}: ${expense.get('amount')}")
    return {"approved": True, "auto": True}


# --------------------------------------------------------------------------
# Activity: send_notification
# --------------------------------------------------------------------------
@app.activity_trigger(input_name="payload")
def send_notification(payload: dict) -> dict:
    expense = payload["expense"]
    result = payload["result"]

    subject_map = {
        "approved": "Your expense was approved",
        "rejected": "Your expense was rejected",
        "validation_error": "Your expense submission had errors",
    }
    subject = subject_map.get(result["status"], "Expense update")
    if result.get("escalated"):
        subject += " (auto-approved after timeout — escalated)"

    body = (
        f"Hi {expense.get('employeeName', 'there')},\n\n"
        f"Status: {result['status']}\n"
        f"Reason: {result.get('reason', result.get('errors'))}\n\n"
        f"Expense: ${expense.get('amount')} - {expense.get('category')} - {expense.get('description')}\n"
    )

    recipient = expense.get("employeeEmail")
    connection_string = os.environ.get("COMMUNICATION_SERVICES_CONNECTION_STRING")
    sender = os.environ.get("SENDER_EMAIL")

    if not recipient or not connection_string or not sender:
        # No usable recipient (e.g. validation failed because employeeEmail
        # itself was missing/invalid) or ACS not configured: log instead of
        # sending, rather than failing the whole orchestration.
        logging.info(f"[EMAIL to {recipient}] Subject: {subject}\n{body}")
        return {"sent": False, "to": recipient, "subject": subject}

    client = EmailClient.from_connection_string(connection_string)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": recipient}]},
        "content": {"subject": subject, "plainText": body},
    }
    poller = client.begin_send(message)
    send_result = poller.result()
    logging.info(f"Email to {recipient} -> status {send_result['status']}")

    return {"sent": send_result["status"] == "Succeeded", "to": recipient, "subject": subject}
