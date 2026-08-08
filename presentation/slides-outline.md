# Slide Deck Outline

This is the content plan behind `slides.pptx` — a finished 7-slide deck,
content-complete, no placeholders left. Both versions are deployed and
tested live (see `../DEPLOYMENT_EVIDENCE.md`); slides 3 and 4 are built to
cut away to a live demo rather than embed screenshots, per the full talk
track in `video-script.md`.

1. **Title** — Expense Approval Workflow: Durable Functions vs. Logic Apps + Service Bus
2. **The Workflow & Business Rules** — inputs, validation, auto-approve threshold, timeout, notification
3. **Version A — Durable Functions** — architecture (client/orchestrator/activity functions), the `task_any` human-interaction race, design decisions, **live demo** of `test-durable.http` scenarios against the deployed app
4. **Version B — Logic Apps + Service Bus** — architecture (queue → Logic App → validation Function → topic/subscriptions → email), the `HttpWebhook` timeout approach and why it was chosen over "Send approval email", why Azure Communication Services replaced the Office 365 connector, **live demo** of the deployed Logic App's run history — including the Failed-on-timeout finding
5. **Comparison Summary** — table across the six dimensions (dev experience, testability, error handling, human interaction, observability, cost); full prose version is in the repo `README.md`
6. **Recommendation** — Durable Functions as the production default, with the Logic Apps carve-out (low-code teams, low volume, visual-observability requirement)
7. **Lessons Learned** — the two real bugs live testing caught, the Failed-on-timeout surprise, and what to do differently next time
