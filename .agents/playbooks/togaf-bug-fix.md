---
extends:
when: Use for a defect in existing behavior with a known symptom.
---

# TOGAF-lite Bug Fix

Use for: a defect in existing behavior with a known symptom. Not for: new behavior
(use `togaf-feature-delivery.md`), a new app (use `togaf-app-delivery.md`), read-only
questions (use Investigation), behavior-preserving cleanup (use Refactoring).

Principles
- Reproduce first. No reproduction, no fix.
- Prove the fix on the same surface where the bug appeared.
- The lead verifies; it never accepts a worker's claim of success.
- A bug is also information about a missing guardrail: ask which layer should have caught it.
- Never take external or irreversible actions without human approval.

Skills used
- pstack: Bug fix playbook, `/how`, `/why`, `tdd`, `blast-radius`, `/interrogate` (risky fixes
  only), `unslop`, Opening a PR, Babysit, `swarm` (see Parallelism).
- Pocock (optional): `git-guardrails-claude-code` for unattended runs that must not push. It
  blocks every `git push` and needs jq. Do not use it when Step 6 will open a PR.
- Overlap rule: where pstack is installed, use pstack's Bug fix playbook. Where it is not, follow
  Steps 1 to 3 below by hand.

---

## Step 1: Capture the bug

Record: expected behavior, actual behavior, steps to reproduce, environment/version, severity,
and who is affected. If any of this is missing, ask. Link logs, traces or screenshots.

Exit: a written description with a reproducible trigger, or a note that reproduction is pending.

## Step 2: Reproduce (GATE)

1. Create a failing test or a scripted reproduction on the surface where the bug appears
   (unit, integration or via the verification skill for UI flows).
2. Run it and show the failing output.

Exit: the failure is reproduced and the failing output is recorded. If it cannot be reproduced,
STOP and report what was tried. Do not "fix" blind.

## Step 3: Find the root cause

1. Run `/how` on the affected path; use `/why` to trace how the code got this way when helpful.
2. Label every claim as measured, inferred or guessed. Confirm the cause by a measurement
   (log, trace, breakpoint, targeted test), not by reading alone.
3. State the root cause in one or two sentences with file citations, and say why the existing
   tests did not catch it.

Exit: the root cause is confirmed by a measurement, and names files and lines.

## Step 4: Fix

1. Keep the failing test from Step 2 as the regression test.
2. Make the smallest change that fixes the root cause, not the symptom. Follow existing patterns;
   do not add a second way to do something. Do not add comments excusing a workaround.
3. Run the full check command (tests, type-check, lint, build).

Exit: the regression test passes; the full check command is green.

## Step 5: Verify and check blast radius

1. Re-run the original reproduction on the same surface. Show the failing output (before) and the
   passing output (after). "Inconclusive" is not a pass.
2. Run `blast-radius` to see what the diff could break outside its scope; add tests for anything
   it flags.
3. For risky fixes (shared code, data, auth, concurrency, migrations) run `/interrogate` on the diff.

Exit: before/after evidence attached; blast-radius findings handled.

## Step 6: Land

1. Run `unslop` on the PR text. State root cause, fix, and evidence in the PR description.
2. Open the PR (Opening a PR) and Babysit until merge-ready.
3. Deploy or hotfix only with human approval.

Exit: PR is merge-ready with CI green and evidence attached.

## Step 7: Learn (do not skip)

Ask: what is the strongest layer that could have prevented this bug?
1. Structure: could a boundary or type make this state impossible?
2. Static analysis: could a lint rule catch this class of mistake?
3. Rules or a verification-skill step: only if the above cannot work.
4. One-off: if it was truly a one-off, record that and stop.
Add the check in the same PR when small, otherwise open a follow-up task.

Exit: a new check exists, or the bug is recorded as a one-off with a reason.

---

## Parallelism
- One bug, one agent.
- Use `swarm` only for several independent bugs at once (separate worktrees, separate files),
  or as a race of different diagnostic routes when the root cause is unclear. The lead picks the
  confirmed cause and verifies it itself.

## Stop and ask the human if
- The bug cannot be reproduced.
- The fix requires an architecture change, a data migration, or an external/irreversible action.
- The root cause involves a decision that belongs to the product owner.

## Final report states
Root cause; fix; before/after evidence; blast-radius result; the new guardrail added (or why
none); anything deferred.
