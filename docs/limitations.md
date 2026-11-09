# Limitations

keel-gate makes dangerous actions much harder to do by mistake or by attack. It is **not** a complete safety system.
Here is what it does not do, honestly.

## What it cannot see

- **Intent inside an allowed action.** A refund inside the mandate limits runs, even if it goes to the wrong order.
  *Mitigation:* small default limits, the audit log, undo for reversible tools, and the breaker.
- **Lies in a tool's manifest.** Humans write the manifest, and the gate trusts it. A tool that is described as read-only but
  deletes data will fool the gate. *Mitigation:* manifests are reviewed in git, and tool descriptions are pinned.
- **What happens inside a tool.** If a tool calls other services, the gate sees only the outer call.

## What it is not

- **Not an OS sandbox.** If the agent can run arbitrary programs outside the gate (for example, the agent process itself is
  compromised), the gate cannot stop it. *Use both:* the Claude Code / Codex sandbox, or the Docker agent box (stretch).
- **Not a prompt-injection detector.** Taint tracking makes injected instructions much less dangerous, but it does not find
  them. Detectors can be plugged in later and may only raise risk.
- **Not a replacement for least-privilege credentials.** Give the gate's vault the smallest keys that work.

## Trade-offs we chose

- **Taint is per session, not per value.** Once a session reads untrusted text, more actions need a human. CaMeL-style value
  tracking is stronger but needs control of the agent's planner.
- **Shell parsing covers bash/sh syntax.** PowerShell and Windows `cmd` are treated as "cannot parse" and therefore ask.
- **The hash chain detects tampering; it does not prevent it.** Someone with full access could rewrite the whole file.
  Publishing the latest hash, and signatures (stretch), reduce this.
- **Approvals add delay.** Mandates exist to keep routine work fast.

## Not tested yet

- The Claude Code cloud `http` hook inside the cloud network allow-list (planned check on Day 6).
- Long-running production load (we test speed on a laptop and in CI only).
