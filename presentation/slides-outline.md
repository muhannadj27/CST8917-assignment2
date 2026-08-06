# Slide Deck Outline

This is the content plan behind `slides.pptx` (already generated as a
starter deck — open it and fill in the `[ DEMO ]` / `[ TODO ]` placeholders
called out in each slide's speaker notes after you deploy and test both
versions).

1. **Title** — Expense Approval Workflow: Durable Functions vs. Logic Apps + Service Bus
2. **The Workflow & Business Rules** — inputs, validation, auto-approve threshold, timeout, notification
3. **Version A — Durable Functions** — architecture (client/orchestrator/activity functions), the `task_any` human-interaction race, design decisions, **live demo** of `test-durable.http` scenarios
4. **Version B — Logic Apps + Service Bus** — architecture (queue → Logic App → validation Function → topic/subscriptions → email), the `HttpWebhook` timeout approach and why it was chosen over "Send approval email", **live demo** of `test-expense.http` scenarios and run history
5. **Comparison Summary** — table across the six dimensions (dev experience, testability, error handling, human interaction, observability, cost); full prose version is in the repo `README.md`
6. **Recommendation** — Durable Functions as the production default, with the Logic Apps carve-out (low-code teams, low volume, visual-observability requirement)
7. **Lessons Learned** — fill in after hands-on deployment; what surprised you, what you'd change, which you'd reach for first next time
