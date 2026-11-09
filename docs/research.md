# Research: what the industry does

We read the guidance from Google, Anthropic, and OpenAI, looked at how real coding and customer-service agents handle
risky actions, and studied real accidents. This page is the short version, with sources. Items we could not confirm are
marked *(unverified)*.

## 1. Everyone agrees on one core idea

> A **deterministic policy engine outside the model** must decide allow / ask / deny **before** each tool call.

- **Google**, "An introduction to Google's approach for secure AI agents" (2025):
  - Layer 1 is a policy engine outside the model.
  - It weighs reversibility, money, and whether untrusted data was read recently.
  - [research.google](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/)
- **Google SAIF for agents:** three controls: user control, least-privilege permissions, and observability. [saif.google](https://saif.google/focus-on-agents)
- **Anthropic, Claude Code:**
  - Permission rules are "enforced by Claude Code, not by the model".
  - Deny is checked first, then ask, then allow.
  - Bash argument patterns "are fragile". [docs](https://code.claude.com/docs/en/permissions)
- **OpenAI**, "Safety in building agents": "always enable tool approvals". The Agents SDK has `needsApproval`. [docs](https://developers.openai.com/api/docs/guides/agent-builder-safety)
- **OWASP Agent Control Standard v0.1** (Sep 2026):
  - A `toolCallRequest` hook with allow / deny / modify / ask / defer.
  - A deterministic engine before any LLM layer.
  - **keel-gate follows this shape.** [GitHub](https://github.com/GenAI-Security-Project/agent-control-standard)

## 2. Ideas we adopted, and where they come from

| Idea in keel-gate | Source |
|---|---|
| Taint tracking: after untrusted input, risky tools get stricter | Google DeepMind **CaMeL** ([arXiv 2503.18813](https://arxiv.org/abs/2503.18813)); "Design Patterns for Securing LLM Agents" ([arXiv 2506.08837](https://arxiv.org/abs/2506.08837)) |
| Parse shell commands; unparseable = ask | Claude Code docs; Antigravity permissions; Cursor dropped its string denylist after bypasses |
| Protect agent config and policy files | Claude Code and Codex protected paths; CVEs in Copilot, Cursor, and Codex where agents edited their own config |
| One-time approval bound to exact args; server-side state; atomic use | OpenAI Agents SDK human-in-the-loop security notes; Auth0 CIBA + RAR (`binding_message`, `authorization_details`) |
| Standing mandates with limits | Google **AP2** open payment mandates; Stripe Shared Payment Tokens (`usage_limits`, `expires_at`) |
| The agent never holds credentials | Claude Code sandbox credential injection; MCP auth spec ("no token passthrough"); Stripe restricted keys |
| Egress: block private and metadata IPs; separate read and write hosts | Claude Code sandbox proxy; Codex network proxy; Chrome agent "origin sets" |
| Circuit breaker: 3 in a row / 20 total | Anthropic Claude Code auto mode ([blog](https://www.anthropic.com/engineering/claude-code-auto-mode)) |
| Outgoing promises are actions | Air Canada chatbot ruling (2024 BCCRT 149) |
| Detectors can only raise risk | Google Layer 2; ElevenLabs guardrails *(fail-open report unverified)* |

## 3. How real coding agents control risky actions

| Agent | Main controls |
|---|---|
| Claude Code | permission modes; deny > ask > allow rules; hooks; optional OS sandbox (Seatbelt / bubblewrap) with a domain allow-list |
| OpenAI Codex | sandbox modes (read-only / workspace-write / full); network off by default; `.git` and `.codex` read-only |
| Cursor | auto-run in a sandbox with no network (v2.0); the old denylist was removed after bypasses |
| GitHub Copilot coding agent | pushes only to `copilot/*` branches; firewall (does not cover MCP processes or setup steps) |
| Replit Agent | after the July 2025 incident: the agent cannot change the production DB; separate dev/prod databases; checkpoints |
| Gemini CLI / Antigravity | sandbox options; Off / Auto / Turbo terminal modes; deny > ask > allow |
| Amazon Q / Kiro | trusted tools list; a `permissions.yaml` replaced prefix matching |
| Windsurf | Disabled / Allowlist / Auto / Turbo; prefix matching (`git` allows `git add -A`) |

**Lesson:** string lists fail; you need parsing, an OS sandbox as a backstop, and secrets out of the agent's reach.

## 4. Real incidents (the red-team suite is built from these)

| When | What happened | Root cause | Source |
|---|---|---|---|
| Jul 2025 | Replit agent wiped a production DB during a "code freeze" | the freeze was only prompt text; the agent had prod creds | [The Register](https://www.theregister.com/2025/07/22/replit_saastr_response/) |
| Jul 2025 | Gemini CLI overwrote user files after a failed `mkdir` | no check after writes | [Ars Technica](https://arstechnica.com/information-technology/2025/07/ai-coding-assistants-chase-phantoms-destroy-real-user-data) |
| Jul 2025 | Amazon Q extension shipped a wiper prompt | over-scoped token in the build | [AWS bulletin](https://aws.amazon.com/security/security-bulletins/AWS-2025-015/) |
| May 2025 | GitHub MCP: a public issue made the agent leak private repos | untrusted input + broad token | [Invariant Labs](https://invariantlabs.ai/blog/mcp-github-vulnerability) |
| Jul 2025 | Supabase MCP leaked tokens through a support ticket | service-role key + untrusted text | [General Analysis](https://generalanalysis.com/blog/supabase-mcp-blog) |
| Aug 2025 | Nx "s1ngularity" malware ran agents with all checks off | supply chain | [Wiz](https://www.wiz.io/blog/s1ngularity-supply-chain-attack) |
| Nov 2025 | Antigravity "clear cache" deleted a whole drive | Turbo mode ran a destructive command | [The Register](https://www.theregister.com/2025/12/01/google_antigravity_wipes_d_drive/) |
| Mar 2026 | Claude Code got around an `npx` deny rule via `/proc/self/root/...` | string matching | [Ona](https://ona.com/stories/how-claude-code-escapes-its-own-denylist-and-sandbox) |
| Apr 2026 | Cursor agent deleted a production volume with one `curl` | it found an over-scoped token in a file | [The Register](https://www.theregister.com/software/2026/04/27/cursor-opus-agent-snuffs-out-startups-production-database/5224442) |
| 2024 | Air Canada bot invented a refund policy; the airline had to pay | text promises are actions | [McCarthy Tétrault](https://www.mccarthy.ca/en/insights/blogs/techlex/moffatt-v-air-canada-misrepresentation-ai-chatbot) |

Also: CVE-2025-53773 (Copilot writes its own auto-approve setting), CVE-2025-59944 (Cursor `.CURSOR/mcp.json` case trick),
CVE-2025-61260 (Codex repo-local config), CVE-2025-55284 (Claude Code DNS exfiltration through `ping`).

## 5. Customer-facing and payment agents

| Service | Control worth copying |
|---|---|
| Intercom Fin | "Loop in teammate": pause, show data, required timeout, first answer wins ([help](https://www.intercom.com/help/en/articles/14468561-human-in-the-loop-approvals-for-fin-procedures)) |
| Sierra | account tools stay hidden until the customer is verified |
| Zendesk | approval per action; refunds stay approval-gated |
| Agentforce | the action runs as the agent or as the user; PII masking |
| Auth0 for AI agents | CIBA async approval on the user's device; RAR details bound to the token ([docs](https://auth0.com/docs/get-started/authentication-and-authorization-flow/client-initiated-backchannel-authentication-flow/user-authorization-with-ciba)) |
| Google AP2 | open and closed payment mandates: cap, budget, payees, uses, expiry ([spec](https://ap2-protocol.org/ap2/payment_mandate/)) |
| Stripe Shared Payment Tokens | seller-scoped, amount-limited, expiring, revocable ([docs](https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens)) |

## 6. Where keel-gate fits

| Kind of product | Examples | What is missing |
|---|---|---|
| Customer-service platforms | Intercom, Zendesk, Sierra, Agentforce | approval is not bound to the exact action; locked to one platform |
| Detectors | Lakera, Prompt Shields, NeMo Guardrails, LlamaFirewall | they guess (probabilistic); some fail open |
| Gateways | AWS AgentCore Policy (Cedar), Kong, Docker MCP Gateway | allow/deny only; no human approval, no undo |
| Standards | CIBA, AP2, Stripe SPT | no enforcement point |

**keel-gate:** one vendor-neutral, fail-closed point with **policy + action-bound approval + undo + a verifiable log**.

## Not verified

- The exact OWASP Agentic Top 10 names (we read them from secondary sources).
- Whether Claude Code `http` hooks obey the cloud network allow-list.
- Whether managed settings reach Claude Code cloud sessions.
- Sierra and Decagon refund limits; ElevenLabs failing open; Visa's controls schema.
