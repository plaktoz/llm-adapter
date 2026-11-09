---
extends:
when: Use for building a new application from scratch, or treating a missing foundation (no codebase, no CI, no verification harness, no architecture) as a new-app project.
---

# TOGAF-lite New App Delivery

Use for: building a new application from scratch, or treating a missing foundation
(no codebase, no CI, no verification harness, no architecture) as a new-app project.
Not for: a feature in an existing healthy codebase (use `togaf-feature-delivery.md`),
a defect (use `togaf-bug-fix.md`), read-only questions (use Investigation), or
behavior-preserving cleanup (use Refactoring).

Principles
- The best spec is code. Keep documents short and inside the repo.
- Every step ends with an exit check that can pass or fail, with evidence.
- Governance is enforced by structure, lint and CI, not by meetings or guidance alone.
- Contracts first, then slices. Parallel work starts only after the foundation passes (Phase 4).
- The lead verifies; it never accepts a worker's claim of success.
- Never take external or irreversible actions (publish, deploy, send, spend, force-push,
  delete data) without human approval.

Skills used
- pstack: `/how`, `/why`, `/architect`, `/interrogate`, `swarm`, `arena`, `blast-radius`,
  `unslop`, `tdd`, `/create-verification-skill`, Feature playbook, Opening a PR, Babysit.
- Pocock: `setup-matt-pocock-skills`, `grill-me`, `grill-with-docs`, `to-spec`, `to-tickets`,
  `improve-codebase-architecture`, `writing-for-agents`. Optional: `git-guardrails-claude-code`
  (Phase 3, step 3).
- Overlap rule: use ONE tdd skill (pstack's by default). Use `/how` to orient on unfamiliar code.
  For a defect: where pstack is installed, use pstack's Bug fix playbook. Where it is not, use
  the bug-fix playbook in this kit (`togaf-bug-fix.md`).
- Call Pocock skills by name inside the steps below; `poteto-mode` does not route to them.

Artifacts (create if missing)
- `docs/architecture/vision.md`
- `docs/architecture/adr/NNNN-title.md` (one per decision, half a page max)
- `docs/architecture/roadmap.md` (task cards, see Phase 5)
- `GLOSSARY.md` (shared domain vocabulary used in all task cards and issue titles)

---

## Phase 0: Vision (HUMAN OWNED)

1. Run `setup-matt-pocock-skills` once to set the issue tracker, triage labels and docs location.
2. Run `grill-me` on the idea until every branch of the decision tree is resolved.
3. Draft `vision.md` (max one page): goal in one sentence; users and the 2-3 main flows;
   constraints (platform, stack, security, deadline, off-limits); a pass/fail done condition.
4. Run `unslop` on it. STOP and ask the human to approve.
5. Optionally run `to-spec` after approval. It publishes to the issue tracker, which is an
   external action: require explicit human approval of the spec content before you invoke it,
   because `to-spec` publishes without asking.

Exit: `vision.md` has all four items, fits on one page, and the human approved it.

## Phase 1: Baseline

Greenfield: skip. Existing partial code: run `/how` on it and add a "Current state" section to
`vision.md`, citing file paths. Run `improve-codebase-architecture` to list structural problems.

Exit: every claim in "Current state" cites a file path.

## Phase 2: Target architecture (HUMAN GATE at end)

1. Run `grill-with-docs` to settle domain language and decisions; it updates `GLOSSARY.md`
   and ADRs as decisions crystallize.
2. Run `/architect`: types, interfaces, function signatures and module boundaries with empty
   bodies. This is the architecture; write it as code, not prose. Use `arena` for the biggest
   choices when comparing designs.
3. Write one ADR per significant choice: stack, auth, data store, state management, API style.
   Each lists context, options considered, decision, consequences.
4. Pick ONE approach for each recurring pattern (routing, data fetching, state, forms, errors,
   logging). Add a scaffold/template for each so the right path is the easy path.
5. Run `/interrogate` on the skeleton and ADRs when a decision is contested or irreversible.
   Never run it on an abstract plan with no code.

Exit: skeleton compiles or type-checks; each ADR has a decision and at least one rejected
alternative; each recurring pattern has exactly one approach and a scaffold; `/interrogate`
findings are resolved or deferred in writing.
HUMAN GATE: show the skeleton and ADR list; wait for approval before building.

## Phase 3: Executable governance

Convert decisions into checks, strongest layer first:
1. Structure: enforce module boundaries with an import-graph checker (e.g. dependency-cruiser,
   import-linter). Forbidden imports fail the build.
2. Static analysis: a lint rule for each recurring mistake and each ADR rule (secrets,
   direct DB calls from UI, banned patterns).
3. Git safety (optional, opt-in): `git-guardrails-claude-code` installs a hook that blocks
   dangerous git commands. It blocks every `git push`, and also `git reset --hard`, `git clean -f`
   and `git branch -D`. It needs `jq`; without `jq` the hook allows every command. Do not install
   it if Phase 6 will push or open PRs (Opening a PR, Babysit). Skip this step when in doubt.
4. Rules file: only what cannot be enforced above.

Exit: for each boundary and lint rule, a deliberately violating change fails CI. Show the
failing output as evidence. If the guardrail hook was installed, it blocks a test dangerous
command.

## Phase 4: Verification harness and walking skeleton

1. Create or confirm ONE command that runs tests, type-check, lint and build.
2. Run `/create-verification-skill` so an agent can launch the app and exercise the main flows
   from `vision.md`. Include a short feature map (screens, navigation, key targets) kept in the repo.
   Use `writing-for-agents` if you need to author or refine it.
3. Build the WALKING SKELETON alone, with no parallel workers: the thinnest end-to-end path
   (e.g. sign in -> one screen -> real data -> deployed to staging), through every layer.
4. Record the Phase 0 done condition as an executable check.

Exit: one command runs everything green; the verification skill runs the skeleton's flow and
produces evidence (output, screenshot or recording); the skeleton is deployed or runnable on
the target environment. PARALLEL WORK IS FORBIDDEN BEFORE THIS PHASE PASSES.

## Phase 5: Decompose into task cards

Run `to-tickets` (or write `roadmap.md`) to split the remaining work into thin vertical slices.
Get explicit human approval of the breakdown before you invoke `to-tickets`, because it publishes
to the tracker (see Rules).
Every task is a task card:

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
- Prefer many thin slices over few thick ones. Each must be demoable or verifiable alone.
- AFK = can be built and merged with no human input. HITL = needs a human decision or review.
  Prefer AFK.
- Two tasks whose allowed files overlap are DEPENDENT, even if logically independent.
- Each card must be self-contained: a fresh worker needs nothing else.
- Add a final INTEGRATION task that runs the full verification flow on the merged result.
- Publishing issues to the tracker needs human approval; show the breakdown first and iterate
  until approved.

Exit: every task has acceptance checks, an allowed-files list, and blockers; no two parallel
tasks share allowed files; the human approved the breakdown.

## Phase 6: Implement

For each task, in dependency order:
1. Run the Feature playbook (or Bug fix / Refactoring if the task is of that type), using `tdd`.
2. Run the full check command and the verification skill.
3. Run `/interrogate` and `blast-radius` on non-trivial diffs.
4. Run `unslop` on all prose; open the PR with evidence (Opening a PR); Babysit until merge-ready.

Parallelism
- Only AFK tasks with no unresolved blockers and no overlapping files run in parallel.
- Start with 2 or 3 workers via `swarm`, each in its own git worktree. Increase only if the merge
  rate stays healthy and rework stays low.
- Each worker starts fresh with the original task card plus all later directives, and reads the
  same rules file as the lead.
- Workers report PASS, ISSUES or BLOCKED. The lead re-runs the checks and reviews the diff itself.
  "Inconclusive" is not a pass.
- HITL tasks wait for the human.

Exit per task: CI green, verification evidence attached, no unresolved review findings.

## Phase 7: Integrate and ship

1. Run the INTEGRATION task: full verification flow on the merged result.
2. Run `/interrogate` and `blast-radius` over the combined change.
3. Ship only with explicit human approval (Shipping playbook).

Exit: the Phase 0 done condition passes on the integrated build, with evidence.

## Phase 8: Learn and tighten (after every batch)

1. List every correction the human made.
2. For each, ask: what is the strongest layer that could have prevented it? Move it up:
   structure, then lint/CI, then rules, then style guide.
3. Update ADRs and `roadmap.md`. Delete any pattern or dependency the new architecture replaced.
4. A recurring review comment means a concern is still stuck at the style-guide layer.

Exit: each correction has a matching new check or an ADR change.

---

## Stop and ask the human if
- A Phase 0 item is missing or the done condition cannot be made pass/fail.
- A decision is irreversible, or a step needs an external action.
- Two tasks conflict or the walking skeleton will not pass.

## Final report states
What was built; which exit checks passed with evidence; decisions recorded; what was skipped
or deferred; what remains.
