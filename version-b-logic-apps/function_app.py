"""
Expense Approval Workflow — Azure Functions support services for Version B
(Logic Apps + Service Bus orchestration).

This Function App is intentionally small. It provides two plain HTTP
services that the Logic App / test client rely on, since Logic Apps is a
declarative orchestrator and needs a code escape hatch for real validation
logic and for accepting the initial HTTP submission:

  1. `submit_expense`   (HTTP POST /api/expenses)
                        Front door for testing. Accepts the raw expense
                        JSON and drops it onto the "expense-requests"
                        Service Bus queue via an output binding. This is
                        what `test-expense.http` calls, and what the Logic
                        App's Service Bus queue trigger picks up.

  2. `validate_expense` (HTTP POST /api/validate)
                        Called BY the Logic App (HTTP action) as its
                        validation step. Same business rules as Version A
                        so both implementations enforce identical
                        semantics. Returns {"valid": bool, "errors": [...]}.

  3. `notify_manager_webhook` (HTTP POST /api/notify-manager)
                        Called BY the Logic App's "HTTP Webhook" action
                        (the human-interaction stand-in — see
                        logicapp/workflow.json and the README for why this
                        pattern was chosen over "Send approval email").
                        The webhook payload includes the Logic-App-issued
                        `callbackUrl` (via @listCallbackUrl()). In a real
                        deployment this function would email the manager
                        a link containing that callback URL. For the
                        assignment/demo it logs the callback URL so it can
                        be copied into `test-expense.http` to simulate the
                        manager clicking Approve/Reject.

  4. `send_email`       (HTTP POST /api/send-email)
                        Called BY the Logic App in place of the Office 365
                        Outlook connector. Office 365's connector needs an
                        interactive OAuth sign-in per environment, which
                        can't be scripted; Azure Communication Services
                        Email uses a connection string instead, so routing
                        every outbound email through this one plain HTTP
                        action keeps the whole Logic App deployable from
                        the CLI with no manual portal step. Body:
                        {"to": "...", "subject": "...", "body": "..."}.
"""

import json
import logging
import os

import azure.functions as func
from azure.communication.email import EmailClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

VALID_CATEGORIES = {"travel", "meals", "supplies", "equipment", "software", "other"}


@app.route(route="expenses", methods=["POST"])
@app.service_bus_queue_output(
    arg_name="msg",
    queue_name="expense-requests",
    connection="ServiceBusConnection",
)
def submit_expense(req: func.HttpRequest, msg: func.Out[str]) -> func.HttpResponse:
    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    msg.set(json.dumps(expense))
    logging.info(f"Queued expense for {expense.get('employeeName')} onto 'expense-requests'.")

    return func.HttpResponse(
        json.dumps({"message": "Expense queued for processing.", "expense": expense}),
        status_code=202,
        mimetype="application/json",
    )


@app.route(route="validate", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    """Called by the Logic App's 'Validate Expense' HTTP action."""
    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"valid": False, "errors": ["Request body must be valid JSON"]}),
            status_code=400,
            mimetype="application/json",
        )

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

    return func.HttpResponse(
        json.dumps({"valid": len(errors) == 0, "errors": errors}),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="notify-manager", methods=["POST"])
def notify_manager_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """
    Called by the Logic App's HTTP Webhook action ('Wait for Manager
    Decision'). The Logic App injects its own callback URL into the
    payload via @listCallbackUrl(). We log it here; in production this
    would trigger a real email via SendGrid/Outlook containing
    Approve/Reject links that hit that callback URL directly.
    """
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(status_code=400)

    callback_url = payload.get("callbackUrl")
    expense = payload.get("expense", {})

    logging.info(
        f"[MANAGER NOTIFICATION] {expense.get('managerEmail')} needs to approve/reject "
        f"${expense.get('amount')} expense from {expense.get('employeeName')}.\n"
        f"Callback URL (POST {{\"decision\": \"approved\"|\"rejected\"}}): {callback_url}"
    )

    # Acknowledge receipt immediately; the actual decision arrives later
    # as a separate POST to `callback_url`, which resumes the paused
    # Logic App run.
    return func.HttpResponse(status_code=200)


@app.route(route="send-email", methods=["POST"])
def send_email(req: func.HttpRequest) -> func.HttpResponse:
    """Called by the Logic App's Send_..._Email HTTP actions."""
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    to = payload.get("to")
    subject = payload.get("subject")
    body = payload.get("body")
    if not subject or not body:
        return func.HttpResponse(
            json.dumps({"error": "subject and body are required"}),
            status_code=400,
            mimetype="application/json",
        )

    connection_string = os.environ.get("COMMUNICATION_SERVICES_CONNECTION_STRING")
    sender = os.environ.get("SENDER_EMAIL")

    if not to or not connection_string or not sender:
        # No usable recipient (e.g. the validation-error path where
        # employeeEmail was itself the missing field) or ACS not configured:
        # log instead of sending, rather than failing the Logic App run.
        logging.info(f"[EMAIL to {to}] Subject: {subject}\n{body}")
        return func.HttpResponse(
            json.dumps({"sent": False, "reason": "no recipient or ACS not configured"}),
            status_code=200,
            mimetype="application/json",
        )

    client = EmailClient.from_connection_string(connection_string)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": to}]},
        "content": {"subject": subject, "plainText": body},
    }
    poller = client.begin_send(message)
    result = poller.result()
    logging.info(f"Email to {to} -> status {result['status']}")

    return func.HttpResponse(
        json.dumps({"sent": result["status"] == "Succeeded", "id": result.get("id")}),
        status_code=200,
        mimetype="application/json",
    )
