# Video Script — Expense Approval Workflow

Target length: 12-14 minutes. Read through once before recording — it's written
to be spoken, not read verbatim, so put it in your own words as you go.
Timestamps are guides, not hard cuts.

---

## 1. Introduction (~1.5 min) — Slide 1-2

"Hi, I'm Muhannad Jaber, and this is my Assignment 2 for CST8917 — comparing
two Azure serverless orchestration approaches by building the same workflow
twice.

The workflow is an expense approval pipeline. An employee submits an expense
with their name, email, amount, category, description, and their manager's
email. The rules are simple: reject anything missing a required field or
using an invalid category — valid categories are travel, meals, supplies,
equipment, software, or other. Anything under $100 gets auto-approved, no
manager needed. $100 or more requires manager approval, and the system waits
for a decision. If the manager doesn't respond in time, it auto-approves
anyway but flags it as escalated. And in every case, the employee gets an
email with the final outcome.

I built this twice: once with Azure Durable Functions — that's code-first,
Python — and once with Azure Logic Apps plus Service Bus — that's the
visual, declarative approach. Both versions are actually deployed to Azure
right now, not just written — I'll show you live runs from both."

---

## 2. Version A — Durable Functions (~3.5 min) — Slide 3

"Version A uses the Python v2 programming model for Durable Functions. There
are three pieces: a client function that starts the orchestration over HTTP,
the orchestrator itself, and a set of activity functions it calls.

The orchestrator is basically a normal Python generator function. It calls
`validate_expense` first — if that fails, it sends a validation-error email
and stops. If the amount's under $100, it auto-approves immediately. If it's
$100 or more, this is where it gets interesting: it uses what Durable
Functions calls the Human Interaction pattern. It creates a durable timer
for a five-minute timeout, and in parallel waits for an external event
called `ManagerDecision`. Whichever finishes first wins — `task_any` races
them. If the manager responds, it's approved or rejected. If the timer wins,
it auto-approves and marks it escalated. Either way, the last step is always
the same: send the employee a real email through Azure Communication
Services.

**[Switch to live demo / terminal]**

Let me show you it actually running. [Walk through one or two curl calls
from `test-durable.http` — e.g. submit a $350 expense, show the
`statusQueryGetUri` response, then POST the manager decision to
`/api/expenses/{id}/decision`, then poll the status URL and show
`runtimeStatus: Completed`, `status: approved`.]

All six required scenarios pass against this live deployment — auto-approve,
manager-approve, manager-reject, timeout-escalation, missing fields, and
invalid category. I've got the full output for all six in
`DEPLOYMENT_EVIDENCE.md` in the repo."

---

## 3. Version B — Logic Apps + Service Bus (~3.5 min) — Slide 4

"Version B does the exact same thing, but declaratively. An expense gets
posted to an Azure Function, which drops it onto a Service Bus queue called
`expense-requests`. A Logic App triggers on that queue, calls another Azure
Function to validate — same rules as Version A, so both versions agree — and
then branches on the amount.

The interesting design decision here was the manager-approval wait. Logic
Apps doesn't have anything like Durable Functions' external-event-plus-timer
pattern built in. I looked at the 'Send approval email' connector, which
blocks until someone clicks approve or reject — but it has no timeout, so it
can't do the escalation requirement on its own. Instead I used the
`HttpWebhook` action type, which is built for exactly this: it calls out to
an external system with a callback URL, then pauses the run until either
that URL gets called back, or a timeout elapses. That's structurally the
closest match to what Durable Functions does natively.

One more decision worth calling out: originally this was going to use the
Office 365 Outlook connector for email, but that connector needs an
interactive OAuth sign-in per environment — it can't be automated from a
script. So I swapped in Azure Communication Services Email instead, which
authenticates with a plain connection string. That let me deploy the entire
Logic App from the command line with zero manual portal clicking.

Once an outcome is decided, it gets published to a Service Bus topic called
`expense-outcomes`, with four filtered subscriptions — approved, rejected,
escalated, and validation-error — each using a SQL filter on a custom
message property.

**[Switch to live demo / Azure Portal]**

Here's the run history for the deployed Logic App. [Show the 6 runs, open
the timeout/escalation one.] This one's actually really instructive — watch
this: the run shows top-level status Failed. But if I expand it... the
`Wait_For_Manager_Decision` action timed out as expected, and then the
escalation branch — compose, publish to the topic, send the email — all
succeeded. The business logic worked exactly right. Logic Apps just marks
the whole run Failed whenever any action inside it times out, even when a
`runAfter` branch handles that timeout successfully. That's a real
difference from Durable Functions, where the same situation is just a
normal code path and the orchestration reports Completed. I only found this
by actually deploying and running it — it's not something you'd guess from
the docs.

[Show the Service Bus subscription counts, and the emails received.]"

---

## 4. Comparison Summary (~2.5 min) — Slide 5

"So, across six dimensions, here's what I actually found building both of
these.

Development experience: Version A felt like writing normal Python — real
stack traces, real exceptions. Version B is a nested JSON tree of actions
and `runAfter` dependencies; a typo in there fails silently in a way Python
never would.

Testability: I can unit-test Version A's activity functions directly with
pytest, no Azure required. Version B has no equivalent — the orchestration
logic only gets verified by actually deploying and looking at run history.
That's not theoretical, by the way — I found two real bugs in Version A only
because I deployed it and ran the test scenarios for real. One was
`send_notification` crashing when the employee email itself was the missing
field. The other was the manager's decision coming back as a JSON string
instead of an already-parsed dictionary, which crashed the approve/reject
branch. Both are fixed now, but they only surfaced under live testing.

Error handling: both have retry policies and branch-on-failure support.
Logic Apps' `runAfter` status arrays are honestly pretty elegant for this —
that's literally what handles the escalation branch. But then you hit that
Failed-on-timeout quirk I just showed you, which is a real gotcha for
anyone relying on 'run failed' alerts.

Human interaction: Durable Functions wins outright here — it's a first-class
primitive. Logic Apps required repurposing a generic webhook action, which
works, but it's not obvious, and less experienced teams could easily reach
for the timeout-less approval email instead.

Observability: Logic Apps' visual run trace is genuinely nicer to look at —
every action's exact input and output, right there. Durable Functions needs
more assembly — Application Insights, custom status, that kind of thing.

And cost: at 100 expenses a day, both are basically free. At 10,000 a day,
Version A stays under ten dollars a month because Azure Functions
Consumption bundles a huge free execution allowance. Version B's per-action
billing doesn't get that same bundle, so it comes out to roughly two-fifty
to three-forty a month at that volume — dominated by Logic Apps' flat
per-action price, not by the Service Bus namespace."

---

## 5. Recommendation (~1.5 min) — Slide 6

"My recommendation: for production, I'd default to Durable Functions. The
human-interaction pattern is exactly what this workflow needs, it's
unit-testable, and the cost gap at real volume is large enough on its own to
decide this for most teams.

That said, I'd choose Logic Apps instead if the team is integration-first
rather than developer-first, if non-developers need to read or modify the
approval logic themselves, or if the workflow is genuinely low-volume and
connector-heavy — the visual run history is a real advantage when you need
to explain to a non-technical stakeholder exactly what happened to one
specific request."

---

## 6. Lessons Learned (~1.5 min) — Slide 7

"A few things surprised me. First, how much testability actually matters in
practice — I would not have caught either of those two bugs in Version A
without deploying it for real and running every scenario end to end. Second,
that Failed-on-timeout behavior in Logic Apps — I went in assuming a
successfully-handled timeout would show as success, and it doesn't. And
third, just how much infrastructure ceremony Logic Apps needs before you
write a single line of business logic — API connections, connection
resources, all of it — versus Durable Functions, which is just... a Function
App and code.

If I were doing this again, I'd probably write a small integration test
harness for Version B from day one, even a crude one, specifically because
the declarative model hides so many wiring bugs until you actually run it.

That's the comparison. Thanks for watching."

---

## Delivery notes

- Keep the live-demo cuts short — 20-30 seconds each is plenty; the point is
  "this actually runs," not a full walkthrough of every field.
- The exact run timestamps and which employee name maps to which scenario
  are in the message from this session and in `DEPLOYMENT_EVIDENCE.md` —
  use those to find the right rows in the Azure Portal run history without
  fumbling on camera.
- If you're short on time, the section most okay to compress is #6
  (Lessons Learned) — the rubric weights Comparison (25%) and
  Presentation/demo (25%) highest, so protect those two.
