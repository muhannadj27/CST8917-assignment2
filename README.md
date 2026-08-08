# Expense Approval Workflow: Durable Functions vs. Logic Apps + Service Bus

**Name:** Muhannad Jaber
**Student Number:** _[fill in — replace with your student number]_
**Course:** CST8917 — Serverless Applications, Spring/Summer 2026
**Project:** Assignment 2 — Compare & Contrast: Dual Implementation of an Expense Approval Workflow
**Date:** 2026-08-06

---

## Overview

This repository implements the same business workflow — an expense approval
pipeline — twice, using two different Azure serverless orchestration models:

- **[Version A](version-a-durable-functions/)** — Azure Durable Functions (Python v2, code-first orchestration)
- **[Version B](version-b-logic-apps/)** — Azure Logic Apps + Service Bus (visual/declarative orchestration)

Both versions are deployed and have been exercised end-to-end against real Azure resources — all 12 required test scenarios (6 per version) passed against live endpoints. See **[`DEPLOYMENT_EVIDENCE.md`](DEPLOYMENT_EVIDENCE.md)** for the deployed resource names and real test results (this supplements, not replaces, the Azure Portal screenshots and video still needed for submission).

**Business rules (identical in both versions):**

| Rule | Description |
|---|---|
| Input | employee name, employee email, amount, category, description, manager email |
| Validation | All fields required; category must be one of `travel`, `meals`, `supplies`, `equipment`, `software`, `other` |
| Auto-approve | Amount < $100 → approved immediately, no manager involved |
| Manager approval | Amount ≥ $100 → system waits for a manager decision |
| Timeout | No manager decision within the timeout window → auto-approved and flagged `escalated` |
| Notification | Employee is emailed the final outcome |

---

## Version A Summary — Durable Functions

**[`version-a-durable-functions/`](version-a-durable-functions/)**

Implemented with the Python v2 programming model (`azure.durable_functions`).

- `submit_expense` (HTTP trigger) starts `expense_orchestrator` and returns the standard Durable Functions status-check payload.
- `expense_orchestrator` chains three activities — `validate_expense`, `auto_approve` / manager wait, `send_notification` — and implements the **Human Interaction pattern**: it races `context.wait_for_external_event("ManagerDecision")` against `context.create_timer(...)` using `context.task_any([...])`. Whichever completes first (manager response, or the durable timer) decides the outcome.
- `manager_decision` (HTTP trigger) raises the `ManagerDecision` external event on a given orchestration instance, simulating a manager clicking Approve/Reject.

**Design decisions:**
- The timer/event race is expressed as plain Python control flow (`if winner == decision_task`) rather than nested callbacks — this is the single biggest ergonomic win of the code-first model.
- `MANAGER_RESPONSE_TIMEOUT_MINUTES` is set to 5 minutes for demo/testing purposes; a production deployment would use hours or days.
- Notifications are sent as real email through **Azure Communication Services (ACS) Email** (`send_notification` calls the ACS Email SDK directly with a connection string from `COMMUNICATION_SERVICES_CONNECTION_STRING`/`SENDER_EMAIL`). If those settings aren't configured (e.g. local dev with no ACS resource), it falls back to logging the notification instead of failing the orchestration.

**Challenges:**
- Orchestrator functions must be deterministic (no direct I/O, no `datetime.now()`, no random calls) — all side effects have to go through activities, which took some getting used to coming from normal Python.
- Canceling the "losing" side of a `task_any` race (the timer, or the still-pending event wait) needed explicit handling to avoid orphaned tasks.

---

## Version B Summary — Logic Apps + Service Bus

**[`version-b-logic-apps/`](version-b-logic-apps/)**

- **Service Bus queue** `expense-requests` receives incoming expense JSON.
- **Logic App** (`logicapp/workflow.json`) triggers on new queue messages, calls an Azure Function for validation, branches on amount, and publishes outcomes to a **Service Bus topic** `expense-outcomes`.
- **Azure Function** (`function_app.py`) provides three plain HTTP endpoints: `submit_expense` (test entry point that enqueues onto the queue), `validate_expense` (called by the Logic App's `Validate_Expense` HTTP action, enforcing the exact same rules as Version A), and `notify_manager_webhook` (called by the Logic App's webhook action).
- **Topic subscriptions** `approved-sub`, `rejected-sub`, `escalated-sub`, and `validation-error-sub` use SQL correlation filters (`outcome = '...'`) on a custom application property stamped on each outgoing message. Provisioned via [`infra/provision-service-bus.sh`](version-b-logic-apps/infra/provision-service-bus.sh).
- **Email** is sent via **Azure Communication Services (ACS) Email** for every terminal branch: approved, rejected, escalated, validation error. Originally planned as the Office 365 Outlook connector, but that connector requires an interactive OAuth sign-in per environment that can't be scripted/automated. ACS Email authenticates with a connection string instead, so `Send_..._Email` actions are plain `Http` calls to the Function app's `/api/send-email` endpoint (which wraps the ACS Email SDK) rather than `ApiConnection` actions — keeping the whole Logic App deployable from the CLI with zero manual portal steps.

**Approach chosen for manager approval:**
Logic Apps has no built-in equivalent of Durable Functions' external-event-plus-timer race. Two options were considered:

1. **"Send approval email" (Office 365 connector)** — natively blocks the run until the recipient clicks Approve/Reject in the email itself, but has no configurable timeout, so it can't express "auto-approve and escalate after N minutes" without extra plumbing.
2. **`HttpWebhook` action** — a built-in action type designed exactly for "call out, then pause until an external system calls back *or* a timeout elapses." It exposes `subscribe` (an outbound call carrying a Logic-App-generated `@listCallbackUrl()`), an implicit "someone else calls that URL to resume the run," and a `limit.timeout` (ISO 8601 duration) that fires a `TimedOut` status if nobody calls back in time.

**Option 2 was chosen** (`Wait_For_Manager_Decision` in `workflow.json`) because it is the closest structural analog to Durable Functions' `wait_for_external_event` + `create_timer` race — one action, two exit branches (`Succeeded` / `TimedOut`) — rather than approximating a timeout with a separate delay-and-poll loop.

**Challenges:**
- Logic Apps' Workflow Definition Language JSON is verbose compared to the Python orchestrator — the manager-decision branch alone is roughly 4x the lines of its Durable Functions equivalent.
- The Service Bus API connection is a portal/ARM-provisioned resource with its own ID that doesn't fully serialize into the workflow JSON — `connections.json` has to be generated per-environment and is deliberately excluded from source control (see `logicapp/connections.example.json`). Email sidesteps this entirely by going through a plain HTTP action instead of a managed connector (see "Approach chosen for manager approval" above).
- Because the workflow is declarative, testing the timeout branch means literally waiting out the clock (or dropping `managerTimeout` to a short value for demos), same as Version A.

---

## Comparison Analysis

**Development experience.** Building Version A felt like writing a normal Python program: the orchestrator is a single generator function with `if`/`else` branches, and the human-interaction race (`context.task_any([decision_task, timeout_task])`) reads the same way a developer would describe it in English. Mistakes surfaced as Python exceptions with real stack traces. Version B required thinking in a different medium entirely — a nested JSON tree of `actions`, `runAfter` dependency edges, and `@body('ActionName')` string-expression references. Hand-authoring `workflow.json` (rather than using the visual designer) made the dependency graph explicit, which was useful for this write-up, but it is not how Logic Apps is meant to be developed day-to-day — the designer trades that transparency for drag-and-drop speed. For a developer already comfortable with Python, Version A was faster to reason about and less error-prone to modify; a `runAfter` typo in the JSON fails silently in a way a Python `NameError` never would.

**Testability.** Version A can be unit-tested without touching Azure at all: activity functions are plain Python functions (`validate_expense(expense: dict) -> dict`), so a `pytest` suite can call them directly and assert on the returned dict. The orchestrator itself can also be tested with the Durable Functions Python SDK's orchestrator-testing utilities, which replay a mocked history. Version B has no equivalent local unit-testing story for the workflow itself — the closest thing is testing the two Azure Functions it depends on (`validate_expense`, `notify_manager_webhook`) in isolation, which covers the code but not the orchestration logic (branching, `runAfter` wiring, the webhook race) living in the JSON. Verifying that logic requires an actual deployed run and inspection of run history — meaning defects in wiring surface late, during integration rather than during development.

**Error handling.** Durable Functions activities get automatic retry policies (`RetryOptions`) that can be attached per-`call_activity` call with exponential backoff, and unhandled exceptions propagate up through the orchestrator as normal Python exceptions that can be caught with `try`/`except`. Logic Apps actions have a built-in retry policy (default: 4 retries, exponential backoff) configurable per-action, plus explicit `runAfter` status arrays (`Succeeded`, `Failed`, `Skipped`, `TimedOut`) that let a workflow branch on a specific failure mode — which is precisely how the escalation branch here is wired off `Wait_For_Manager_Decision`'s `TimedOut` status. Both models cover the "retry a flaky call" and "branch on failure" cases; Logic Apps' `runAfter` status-branching is arguably more explicit and visual for compound success/failure logic, while Durable Functions' `try`/`except` is more familiar and more flexible for anything beyond the standard status set. One concrete surprise from actually deploying both (see `DEPLOYMENT_EVIDENCE.md`): when Scenario 4 (timeout) ran for real, the escalation branch executed perfectly — compose, publish-to-topic, and send-email all reported `Succeeded` — but the Logic App **run as a whole still shows top-level status `Failed`**, because a `TimedOut` action status propagates up through its parent scope regardless of whether a `runAfter` branch handled it. Durable Functions has no equivalent gotcha: the same timeout path is just an `if/else` branch, and the orchestration reports `Completed`. For a team relying on "run failed" alerts for on-call paging, that's a real operational difference, not just a style preference.

**Human interaction pattern.** This is where the two approaches diverge most. Durable Functions' `wait_for_external_event` + `create_timer` + `task_any` is a first-class, purpose-built primitive — it is literally named "Human Interaction pattern" in the Microsoft docs and required almost no adaptation to fit the "wait for manager, else timeout" requirement. Logic Apps has no equivalent named pattern; getting the same behavior meant repurposing the `HttpWebhook` action (designed for generic long-running external-system callbacks) and building a small satellite Azure Function (`notify_manager_webhook`) just to shuttle the callback URL to the "manager." It works, and the `Succeeded`/`TimedOut` branching is genuinely clean, but it required knowing that this action type exists and choosing it over the more discoverable but timeout-less "Send approval email" action — a design decision a less experienced team could easily get wrong.

**Observability.** Logic Apps' per-run visual trace — every action as a node, each with its exact input/output JSON, timestamps, and status — is easier to read at a glance than the Durable Functions equivalent, especially for someone who didn't write the workflow. Durable Functions' status comes from `client.get_status()` (custom status / history), Application Insights dependency tracking, and the Durable Functions extension's own diagnostic events, which give the same information but require more assembly — there is no single built-in "here is a diagram of this specific run" view without additional tooling (e.g., the Durable Functions Monitor extension). For quickly explaining to a non-developer stakeholder "here's exactly what happened to expense #4291," Logic Apps wins.

**Cost.** At **~100 expenses/day** (~3,000/month), both stay comfortably inside free-tier allowances: Azure Functions' Consumption plan includes 1M free executions and 400,000 GB-s/month, so Version A's ~4 activities × 3,000 runs/month is negligible; Logic Apps Consumption pricing (~$0.000125/action, first 4,000 actions/month free) means Version B's ~7-9 actions × 3,000 runs/month costs a few dollars, plus a Service Bus Standard namespace at a flat ~$10/month (required for topics — Basic tier is queue-only) and a Function App on Consumption for the validation/webhook endpoints (again free-tier). Total: Version A effectively **$0/month**; Version B **~$10-15/month**, dominated by the Service Bus Standard namespace floor, not by usage. At **~10,000 expenses/day** (~300,000/month), Version A stays on Consumption pricing and remains under $5-10/month (still within or barely past free execution/GB-s allowances). Version B's per-action Logic Apps billing starts to matter: ~7-9 actions × 300,000 ≈ 2.1-2.7M actions/month at $0.000125/action ≈ **$260-340/month**, on top of the same ~$10 Service Bus namespace — Logic Apps Consumption's flat per-action price does not benefit from the same free-execution-bundle economics that Azure Functions Consumption gets, so it scales roughly linearly where Durable Functions' cost grows much more slowly. (Estimated using the [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/); assumes Consumption/Standard tiers, Canada Central region, and does not include Application Insights ingestion or Office 365 connector costs, which are typically bundled with an existing M365 license.)

---

## Recommendation

For a production expense-approval system, I would recommend **Azure Durable Functions**, with one caveat. The Human Interaction pattern is a first-class primitive there — `wait_for_external_event` plus a durable timer is exactly what this workflow needs, it is unit-testable without deploying anything, and its cost scales sub-linearly because Azure Functions Consumption bundles a large free execution allowance that Logic Apps' flat per-action pricing does not. At 10,000 expenses/day the cost gap (roughly $5-10/month vs. $260-340/month) is large enough on its own to decide the question for any team processing that kind of volume. Error handling and retries are also more flexible in code — a team can express arbitrary compensation logic that a purely declarative model would strain to represent cleanly.

The caveat: **Logic Apps + Service Bus is the better choice when the team's primary skill set is integration/no-code, or when non-developers (business analysts, ops) need to read and modify the approval logic themselves.** Its visual run history is genuinely superior for explaining "what happened to this specific request" to a non-technical stakeholder, and the low-code connector ecosystem (Office 365, Service Bus, hundreds of SaaS connectors) can shrink integration-heavy workflows dramatically compared to hand-writing SDK calls. I would also lean toward Logic Apps for a low-volume, connector-heavy workflow (e.g., under ~1,000 events/day, several third-party SaaS touchpoints) where the cost difference is negligible and the visual designer's speed of iteration outweighs Durable Functions' testability edge. For this specific assignment's workflow — moderate-to-high volume, a real human-interaction timeout requirement, and logic worth unit testing — Durable Functions is the stronger production default.

---

## References

- [Azure Durable Functions overview](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview) — Microsoft Learn
- [Durable Functions human interaction & timeouts pattern](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview#human-interaction) — Microsoft Learn
- [Durable Functions Python developer reference](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-reference-python) — Microsoft Learn
- [Logic Apps Workflow Definition Language schema reference](https://learn.microsoft.com/azure/logic-apps/logic-apps-workflow-definition-language) — Microsoft Learn
- [HTTP Webhook action in Logic Apps](https://learn.microsoft.com/azure/logic-apps/logic-apps-workflow-actions-triggers#http-webhook-action) — Microsoft Learn
- [Service Bus topics and subscriptions](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-queues-topics-subscriptions) — Microsoft Learn
- [Service Bus SQL filter / correlation filter syntax](https://learn.microsoft.com/azure/service-bus-messaging/topic-filters) — Microsoft Learn
- [Azure Functions Consumption plan pricing](https://azure.microsoft.com/pricing/details/functions/) — Microsoft Azure
- [Logic Apps pricing](https://azure.microsoft.com/pricing/details/logic-apps/) — Microsoft Azure
- [Service Bus pricing](https://azure.microsoft.com/pricing/details/service-bus/) — Microsoft Azure
- [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) — Microsoft Azure

---

## AI Disclosure

AI assistance (Claude, Anthropic) was used substantially in this assignment:

- **Code generation:** The Durable Functions orchestrator/activities/client code (Version A) and the Logic Apps workflow definition, Azure Function endpoints, and Service Bus provisioning script (Version B) were drafted with AI assistance based on the assignment's stated business rules and official Microsoft documentation for both services.
- **Deployment and testing:** Both versions were deployed with AI assistance to a real Azure subscription (Azure CLI, already authenticated as the student) — resource group, storage accounts, both Function Apps, the Service Bus namespace/queue/topic/subscriptions, Azure Communication Services Email, and the Logic App workflow (via an ARM template deploying the Service Bus API connection + workflow definition together). All 12 test scenarios were run against these live endpoints; two real bugs were found and fixed as a direct result (see `DEPLOYMENT_EVIDENCE.md`).
- **Comparison analysis:** The six-dimension comparison and recommendation were drafted with AI assistance, grounded in the process of designing, deploying, and testing both versions in this repository (e.g., the actual line-count/verbosity difference in the manager-decision branch, the two bugs only surfaced by live testing, the `TimedOut`→`Failed` run-status finding in Version B) and in publicly documented pricing/behavior for each service.
- **What was NOT done by AI:** Capture of the Azure Portal browser screenshots referenced in `version-b-logic-apps/screenshots/` and recording of the video presentation were **not performed** — this AI assistant has no browser/screen-capture tooling. **These two items still need to be completed by the student** before submission — see "Outstanding Work" below.

## Outstanding Work Before Submission

Both versions are deployed and fully tested (see `DEPLOYMENT_EVIDENCE.md`). What's left is visual/human-facing material that couldn't be produced by an AI assistant:

1. Fill in your real student number above.
2. Take the Azure Portal screenshots listed in `version-b-logic-apps/screenshots/README.md` (run history, the timeout/escalation run, emails received, subscription counts) — the underlying runs already exist and can be viewed in the portal for `expense-approval-logic-62838` in resource group `rg-cst8917-expense`.
3. Build `presentation/slides.pptx` from `presentation/slides-outline.md` further if needed (a starter deck with all 6 required sections already exists), record the 10-15 minute video per the assignment spec, and fill in `presentation/video-link.md`.
4. Review the comparison analysis above and adjust it based on your own hands-on impressions — it's grounded in real deployment/testing (including two bugs found live), not just documentation reading, but it's still worth putting in your own words for the presentation.
5. Once you're done presenting (Aug 11), consider tearing down the Azure resources (`az group delete --name rg-cst8917-expense`) if you don't need them running afterward, to stop consuming Azure-for-Students credits.
