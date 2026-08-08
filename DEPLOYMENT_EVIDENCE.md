# Deployment & Test Evidence

Both versions are deployed to a real Azure subscription ("Azure for Students",
Algonquin tenant) and all 12 required test scenarios (6 per version) were run
against the live endpoints. This file is the CLI/API-based evidence collected
during that run — it does not replace the Azure Portal screenshots and video
still required by the assignment (see `version-b-logic-apps/screenshots/README.md`
and `presentation/video-link.md`), but everything below is real output from
the actual deployed resources, not a simulation.

## Deployed resources

| Resource | Name | Region |
|---|---|---|
| Resource group | `rg-cst8917-expense` | canadacentral (metadata only) |
| Version A Function App | `expense-durable-62838` | southcentralus |
| Version B Function App | `expense-logicfn-62838` | southcentralus |
| Service Bus namespace | `expense-sb-62838` (Standard) | southcentralus |
| Service Bus queue | `expense-requests` | |
| Service Bus topic | `expense-outcomes` | |
| Topic subscriptions | `approved-sub`, `rejected-sub`, `escalated-sub`, `validation-error-sub` (SQL filter on `outcome` property) | |
| Logic App | `expense-approval-logic-62838` | southcentralus |
| Communication Services + Email (Azure Managed Domain) | `expense-acs-62838` / `expense-email-62838` | global |

Regions were constrained by an "Allowed resource deployment regions" policy
on the student subscription (`mexicocentral`, `westus3`, `norwayeast`,
`northcentralus`, `southcentralus` only) — `southcentralus` was used for all
regional resources.

## Version A — Durable Functions: all 6 scenarios, live results

| # | Scenario | Result |
|---|---|---|
| 1 | Auto-approve (<$100) | `runtimeStatus: Completed`, `status: approved`, `reason: auto-approved: amount under $100` |
| 2 | Manager approves | `runtimeStatus: Completed`, `status: approved`, `reason: approved by manager (manager1@example.com)` |
| 3 | Manager rejects | `runtimeStatus: Completed`, `status: rejected`, `reason: Not approved this quarter, budget frozen.` |
| 4 | No manager response (timeout) | `runtimeStatus: Completed`, `status: approved`, `escalated: true`, `reason: auto-approved after timeout: no manager response` |
| 5 | Missing required fields | `runtimeStatus: Completed`, `status: validation_error`, `errors: ["Missing required field: employeeEmail", "Missing required field: managerEmail"]` |
| 6 | Invalid category | `runtimeStatus: Completed`, `status: validation_error`, `errors: ["Invalid category 'entertainment'. Must be one of: equipment, meals, other, software, supplies, travel"]` |

Real emails were sent via Azure Communication Services Email for every
scenario with a valid `employeeEmail` (1, 2, 3, 4, 6), confirmed by ACS
returning `status: Succeeded` with a message ID in the Function's
Application Insights logs.

## Version B — Logic Apps + Service Bus: all 6 scenarios, live results

| # | Scenario | Logic App run status | Topic subscription evidence |
|---|---|---|---|
| 1 | Auto-approve (<$100) | `Succeeded` | `approved-sub` message count incremented |
| 2 | Manager approves (via callback URL) | `Succeeded` | `approved-sub` message count incremented |
| 3 | Manager rejects (via callback URL) | `Succeeded` | `rejected-sub`: 1 message |
| 4 | No manager response (timeout) | `Failed` at the top level* | `escalated-sub`: 1 message |
| 5 | Missing required fields | `Succeeded` | `validation-error-sub` message count incremented |
| 6 | Invalid category | `Succeeded` | `validation-error-sub`: 2 total (5+6) |

Final subscription message counts after all 6 scenarios:
`approved-sub: 2`, `rejected-sub: 1`, `escalated-sub: 1`, `validation-error-sub: 2`.

**\*Scenario 4 finding (real, not a bug):** the Logic App run for the timeout
path shows overall status `Failed`, even though the escalation logic
executed correctly — `Wait_For_Manager_Decision` returned `TimedOut`,
`Compose_Escalated_Outcome` → `Publish_Escalated_To_Topic` →
`Send_Escalated_Email` all ran via `runAfter: ["TimedOut"]` and all show
`Succeeded`, and the escalated message and email both went out. Logic Apps
propagates a `TimedOut` action status up through its parent `If` scope as
`Failed`, regardless of whether a compensating `runAfter` branch handled it
successfully. This is a genuine, observable difference from Durable
Functions, where the equivalent timeout path is just a normal code branch
and the orchestration reports `Completed` — see the "Human Interaction
Pattern" and "Error Handling" sections of the comparison in `README.md`.
Verified via:

```
GET .../workflows/{name}/runs/{run}/actions?api-version=2019-05-01
```

`Wait_For_Manager_Decision` → `status: TimedOut`, `Compose_Escalated_Outcome`
/ `Publish_Escalated_To_Topic` / `Send_Escalated_Email` → all `Succeeded`,
top-level run → `status: Failed`, `error.code: ActionFailed`.

## Bugs found and fixed during live testing

Two real bugs surfaced only once actually deployed and exercised — exactly
the kind of thing that motivates the "Testability" section of the
comparison:

1. **Version A, `send_notification`:** originally called the ACS Email SDK
   unconditionally, including in the validation-error path where
   `employeeEmail` was itself the missing field — ACS correctly rejected
   the request (`BadRequest: recipients.to[0].address`), which failed the
   whole orchestration. Fixed by skipping the send (log instead) when there
   is no usable recipient.
2. **Version A, `expense_orchestrator`:** `decision_task.result` from
   `context.wait_for_external_event(...)` came back as a JSON **string**
   rather than an already-parsed dict, causing `decision.get(...)` to throw
   `'str' object has no attribute 'get'`. Fixed by JSON-decoding the result
   when it's a string before reading `.get("decision")`.

Both fixes are reflected in the committed `function_app.py` for Version A
(and the equivalent recipient guard was applied to Version B's `send_email`
endpoint for consistency).

## Reproducing this

Every command used above is a plain `curl`/`az` call against the deployed
endpoints — see `version-a-durable-functions/test-durable.http` and
`version-b-logic-apps/test-expense.http` for the request shapes. Function
keys and the ACS/Service Bus connection strings are not included here (they
are secrets); retrieve them from the Azure Portal or via `az functionapp
function keys list` / `az servicebus namespace authorization-rule keys list`
against the resource names in the table above.
