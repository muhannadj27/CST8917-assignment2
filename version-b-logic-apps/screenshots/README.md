# Screenshots

This folder is a placeholder. After deploying Version B to Azure and running
the six scenarios in [`../test-expense.http`](../test-expense.http), add
screenshots here covering:

- [ ] Logic App **run history** list showing multiple runs (mixed outcomes)
- [ ] A **succeeded run** detail view, expanded, for the auto-approve path (Scenario 1)
- [ ] A **succeeded run** detail view for the manager-approval path (Scenario 2), showing the `Wait_For_Manager_Decision` action and `Condition_Manager_Responded` branch
- [ ] A **timed-out** `Wait_For_Manager_Decision` action (Scenario 4 escalation)
- [ ] The **validation-error branch** (Condition_Is_Valid = false) expanded (Scenario 5 or 6)
- [ ] **Emails received** for approved / rejected / escalated / validation-error outcomes
- [ ] Service Bus **topic subscription message counts** in the Azure Portal (Service Bus namespace → `expense-outcomes` topic → subscriptions), showing messages landed in `approved-sub`, `rejected-sub`, `escalated-sub`, `validation-error-sub`

Suggested naming: `01-run-history.png`, `02-auto-approve-run.png`,
`03-manager-approve-run.png`, `04-timeout-escalation-run.png`,
`05-validation-error-run.png`, `06-emails.png`, `07-subscription-counts.png`.
