# Protect Claude Code

> **Status: planned.** This page is written on Day 3. The outline below shows what it will cover.

Add keel-gate to Claude Code on your computer or on the web, so every tool call is checked first.

## What this page will cover

- Local: a `PreToolUse` command hook that runs `keel-gate hook` (exit 2 = deny).
- Web (cloud sessions): an `http` hook to the Gate Service with `onFailure: "block"`, and the gate host in the network allow-list.
- Company-wide: managed settings (`allowManagedHooksOnly`, `allowedHttpHookUrls`).
- How to test it: `ls` is allowed, `rm -rf /` is blocked.

Related: [run the Gate Service](run-gate-service.md) · [how it works](../how-it-works.md)
