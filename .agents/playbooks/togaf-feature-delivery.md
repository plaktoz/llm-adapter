---
extends:
when: Use for new behavior in an existing codebase that already has CI, tests and a working verification method.
---

# TOGAF-lite Feature Delivery

Use for: new behavior in an existing codebase that already has CI, tests and a working
verification method. If the codebase lacks those, or the feature would change the architecture,
treat it as new-app work and use `togaf-app-delivery.md` for the foundation first.
Not for: defects (use `togaf-bug-fix.md`), read-only questions (use Investigation),
behavior-preserving cleanup (use Refactoring).

Principles
- The best spec is code. Short documents, inside the repo.
- Every step ends with a pass/fail exit check and evidence.
- Follow existing patterns. A feature that introduces a NEW pattern needs `/architect` and an ADR.
- The lead verifies; it never accepts a worker's claim of success.
- Never take external or irreversible actions without human approval.

Skills used
- pstack: `/how`, `/architect`, `/interrogate`, `blast-radius`, `swarm`, `tdd`, `unslop`,
  Feature playbook, Multi-phase plan, Opening a PR, Babysit.
- Pocock: `grill-me`, `grill-with-docs`, `to-spec` (optional), `to-tickets`. Not used:
  `git-guardrails-claude-code`, because Step 7 pushes and opens a PR.
- Use ONE tdd skill (pstack's by default). Pocock skills are called by name; `poteto-mode`
  does not route to them.

---

## Step 1: Define done (HUMAN APPROVES)

1. Write the goal in one sentence and a pass/fail done condition. Include what is out of scope.
2. If requirements are vague, run `grill-me` (or `grill-with-docs` if domain language is unclear;
   it updates `GLOSSARY.md` and ADRs).
3. Skip `to-spec` for small features. For larger ones, run it only after the human approves the
   content, since it publishes to the issue tracker (external action) without asking.

Exit: goal, out-of-scope list and a pass/fail done condition exist and the human approved them.

## Step 2: Understand the affected code

Run `/how` on the affected area. Record the modules involved, existing patterns to follow,
and the tests that already cover it, citing file paths.

Exit: every claim cites a file path; the existing pattern to reuse is named.

## Step 3: Classify size and design

- SMALL (one PR, follows an existing pattern): go to Step 5.
- MEDIUM (a few PRs, or crosses module/function boundaries): run `/architect` for types,
  signatures and boundaries as code. If the feature adds a new pattern or makes a real decision,
  write an ADR (half a page). Run `/interrogate` on the skeleton if contested.
- LARGE (many PRs, stacked, multi-phase): run the Multi-phase plan playbook; it writes the plan
  and stops. Get human approval, then treat each phase as a MEDIUM feature.

Exit: SMALL: the reuse pattern is named. MEDIUM/LARGE: skeleton compiles, ADR exists when a new
pattern or decision was made, human approved the design.

## Step 4: Decompose into task cards (MEDIUM/LARGE only)

Run `to-tickets` (after explicit human approval of the breakdown, because it publishes to the
tracker) or write the plan in the PR description. Every task is a task card:

```
Title:            <short, uses GLOSSARY.md vocabulary>
Type:             AFK | HITL
Blocked by:       <task ids or "none">
Goal:             <end-to-end behavior, not layers>
Files allowed:    <paths>        Files off-limits: <paths>
Contracts:        <skeleton files / ADR ids to follow>
Acceptance:       - [ ] <pass/fail checks>
Verify with:      <command + verification skill flow>
Evidence needed:  <test output / screenshot / recording>
```

Rules
- Thin vertical slices; each demoable or verifiable alone.
- Tasks with overlapping allowed files are DEPENDENT, even if logically independent.
- Add a final INTEGRATION task that runs the full verification flow on the merged result.
- Show the breakdown to the human; publish issues only after approval.

Exit: each task has acceptance checks, allowed files and blockers; no two parallel tasks share files.

## Step 5: Build

1. Use `tdd`, one vertical slice at a time: failing test first, then the smallest change to pass.
2. Reuse the existing scaffolds and patterns. Do not add a second way to do something.
3. Run the full check command (tests, type-check, lint, build) and the verification skill.

Parallelism
- SMALL: one agent.
- MEDIUM/LARGE: only AFK tasks with no unresolved blockers and no overlapping files, 2 or 3
  workers at a time via `swarm`, each in its own git worktree.
- Each worker starts fresh with its task card plus all later directives and reads the same
  rules file as the lead. Workers report PASS, ISSUES or BLOCKED; the lead re-runs checks and
  reviews the diff itself. "Inconclusive" is not a pass.
- HITL tasks wait for the human.

Exit per task: acceptance checks pass with evidence; CI green.

## Step 6: Verify and review

1. Run the verification skill on the real feature flow, on the surface where the user would see it.
   Attach evidence: test output, plus a screenshot or recording for UI changes.
2. Run `blast-radius` to check what the diff could break outside its scope.
3. Run `/interrogate` on non-trivial diffs (always on MEDIUM/LARGE). Triage findings into act on,
   consider, noted, dismissed with a reason.
4. For MEDIUM/LARGE, run the INTEGRATION task on the merged result.

Exit: done condition from Step 1 passes with evidence; no unresolved review findings.

## Step 7: Land

1. Run `unslop` on the PR description and any docs.
2. Open the PR (Opening a PR) with the evidence attached.
3. Babysit the PR until merge-ready. Merge or deploy only with human approval where required.

Exit: PR is merge-ready with CI green and evidence attached.

## Step 8: Learn

For every correction the human made, ask which layer could have prevented it (structure, then
lint/CI, then rules, then style guide) and add the check. Update ADRs and `GLOSSARY.md`. Delete
any pattern the feature replaced.

Exit: each correction has a new check or an ADR/GLOSSARY change.

---

## Stop and ask the human if
- The done condition cannot be made pass/fail.
- The feature needs a new pattern, a new dependency, or an architecture change not yet approved.
- A step needs an external or irreversible action.

## Final report states
What was built; checks passed with evidence; decisions recorded; what was skipped or deferred.
