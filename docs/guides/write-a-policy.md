# Write a policy

> **Status: planned.** This page is written on Day 2. The outline below shows what it will cover.

Policies are YAML files in `policies/`. They decide which calls are allowed, asked, or denied.

## What this page will cover

- Rule shape: tool, match (args, command, path, host), verdict, tier, reason.
- Examples: block `git push --force` to `main`; ask for refunds over $100.
- Testing a policy before you use it.
- Who may change policies, and the optional git-only setting: see [manage rules and tools](manage-rules-and-tools.md).

Related: [policy format](../reference/policy-format.md)
