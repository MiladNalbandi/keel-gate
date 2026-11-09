# FAQ

**Is keel-gate an AI agent?**
No. It is a safety layer that sits between any agent and its tools.

**Does it use an AI model to decide?**
No. Decisions are deterministic rules, so they are fast, testable, and cannot be talked out of a "no". Optional AI detectors
may be added later, and they could only make a decision *stricter*.

**Which agents does it work with?**
The Claude API, the Claude Agent SDK, Claude Code (on your computer and on the web), OpenAI apps, and any MCP client
(for example claude.ai custom connectors). It can also run as a web service for agents on other machines.

**Will it slow my agent down?**
The check runs in your process and targets less than 1 ms for 99% of calls. Only "ask a human" waits, and that wait is the point.

**What happens when something is blocked?**
The model receives a normal tool error with the reason, so it can choose a safer path or ask you.

**Can the agent approve its own request?**
No. Approvals need a human login, which agent keys can never use. Text like "APPROVED" in a web page or email has no effect.

**Why is there no "always allow" button?**
Because people end up approving everything. Instead, you set a **mandate**: a "yes" with hard limits (amount, budget,
payees, uses, end date).

**What if keel-gate itself crashes?**
It fails closed: the answer is "no". Read-only work keeps flowing, and the reason is clear in the log.

**Can I see what my agents did?**
Yes. Every decision is in a tamper-evident log, and `keel-gate report` turns it into a readable timeline.

**Is it free?**
Yes, MIT licensed.
