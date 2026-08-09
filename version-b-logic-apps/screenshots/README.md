# Screenshots

Captured after deploying Version B to Azure and running the test scenarios in
[`../test-expense.http`](../test-expense.http) against the live
`expense-approval-logic-62838` Logic App.

### 1. Run history — multiple runs, mixed outcomes

![Run history list](01-run-history.png)

### 2. Succeeded run — auto-approve path (Scenario 1)

![Auto-approve run](02-auto-approve-run.png)

### 3. Succeeded run — manager-approval path (Scenario 2)

![Manager-approve run](03-manager-approve-run.png)

### 3b. Succeeded run — manager-rejects path (Scenario 3)

![Manager-reject run](03b-manager-reject-run.png)

### 4. Timed-out `Wait_For_Manager_Decision` — escalation (Scenario 4)

Run shows top-level `Failed` status because the wait action itself timed out,
even though the workflow caught it and sent the auto-approved-after-timeout
email.

![Timeout escalation run](04-timeout-escalation-run.png)

### 5. Validation-error branch (Scenarios 5 & 6)

![Validation error run](05-validation-error-run.png)

![Validation error run 2](05b-validation-error-run-2.png)

### 6. Emails received — approved / rejected / escalated / validation-error

![Emails received](06-emails.png)

### 7. Service Bus topic subscription message counts

`expense-outcomes` topic → subscriptions, showing messages landed in
`approved-sub`, `rejected-sub`, `escalated-sub`, `validation-error-sub`.

![Subscription counts](07-subscription-counts.png)

### Bonus: All deployed resources

Resource Manager "All resources" view showing the full set of deployed
Version A + Version B Azure resources.

![All resources](08-all-resources.png)

---

## Notes on the Condition action durations

The Logic App run canvas collapses `Wait_For_Manager_Decision` inside the
`Condition Is Valid` action's branch, so the screenshots show that action's
elapsed time rather than an expanded inner view:

- Auto-approve (Scenario 1): condition resolves in under a second — no wait.
- Manager approves / rejects (Scenarios 2 & 3): condition takes ~1-2 minutes,
  reflecting the real wait for the manager decision webhook callback.
- Timeout escalation (Scenario 4): condition takes just over 5 minutes,
  matching the configured wait timeout before auto-approve-and-escalate fires.
- Validation errors (Scenarios 5 & 6): resolve near-instantly, since no
  manager wait is reached.
