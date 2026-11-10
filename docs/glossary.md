# Glossary

Simple meanings for the words used in this project.

| Word | Meaning |
|---|---|
| **Agent** | An AI model that can use tools (run commands, send email, pay money) to finish a task. |
| **Tool call** | One request from the model to run a tool: a name plus arguments. |
| **Gate** | keel-gate's check that runs before every tool call. |
| **Verdict** | The gate's answer: `allow`, `ask`, `deny` (plus `modify` and `defer`, from the OWASP standard). |
| **Tier** | How risky an action is. T0 read only · T1 can be undone · T2 hard to undo · T3 catastrophic. |
| **Fail closed** | If anything breaks, the answer is "no". The opposite, *fail open*, lets things through on errors. |
| **Approval** | A human's "yes" for one exact call, one time. |
| **Binding code** | A short code (like `K7-42Q`) shown on the approval card and in the agent's message, so you know which request you approve. |
| **call_hash** | A fingerprint (sha256) of the tool name and its arguments. Any change gives a different fingerprint. |
| **Mandate** | A standing "yes" with hard limits: max per call, total budget, allowed payees, number of uses, end date. |
| **Taint** | A mark on a session after the agent reads untrusted text (web, email, tickets) or a secret. It makes risky actions stricter. |
| **Egress** | Data leaving through the network (HTTP, DNS, uploads). |
| **Allow-list** | The only hosts or tools that are permitted. Everything else is blocked. |
| **Manifest** | A short description of each tool: what it does, whether it is risky, and whether its output can be trusted. |
| **Pin / pinning** | Saving a hash of something (a policy file, a tool description), so any change is detected. |
| **Prompt injection** | Hidden instructions inside content the agent reads, trying to make it do something else. |
| **Circuit breaker** | A stop that trips after too many blocked actions, handing control back to a human. |
| **Kill switch** | A manual switch that blocks all non-read actions at once. |
| **Undo journal** | A record of "before" state for reversible actions, used to roll back. |
| **Postcheck** | A check after an action, to confirm it did what was expected. |
| **Audit log** | The list of every decision. Each line holds the hash of the line before it, so edits are detectable. |
| **Hash chain** | Lines linked by hashes. Change one line and every line after it no longer matches. |
| **Vault** | Where keel-gate keeps credentials. The agent never sees them. |
| **Adapter** | A small piece that connects keel-gate to one framework (Claude API, OpenAI, MCP, Claude Code). |
| **Gate Service** | keel-gate running as a web service, for agents on other machines. |
| **MCP** | Model Context Protocol: a standard way to give AI apps tools. |
| **Spec / AC** | The specification of what we build. AC = acceptance criterion: one numbered, testable promise. |
| **ADR** | Architecture Decision Record: a short note about one important decision and why. |
| **OWASP ACS** | OWASP Agent Control Standard: a public standard for controlling agent actions. keel-gate follows its decision shape. |
| **SAIF** | Google's Secure AI Framework. |
| **Observe mode** | keel-gate watches and logs what it *would* do, but still blocks catastrophic actions. Used before switching to enforce. |
| **Safety floor** | The blocks that stay on in every mode and that no custom rule can remove (for example `rm -rf ~`, `DROP TABLE`). |
| **Draft manifest** | Tool descriptions generated from your existing tool definitions, waiting for a human to review them. |
| **Monitor agent** | An optional model that checks each call against the user's task. It has no tools, and it can only make the answer stricter. |
| **Intent** | The user's task for a session, set by your app from the user's own messages. The Monitor agent compares calls with it. |
| **Canary** | A test case with a known right answer. The Monitor agent's self-check uses two of them. |
| **Custom rule** | A rule a human adds in the UI, the CLI, or `policies/custom.yaml`: block, ask, or allow for a tool. |
| **Step-up** | A quick re-confirmation (password or passkey) before changing rules. |
| **Policy admin** | The human role that may change rules and tools. |
