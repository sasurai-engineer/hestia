# Working agreement for AI agents in this repository

**Two or more AI agents co-develop this repository. Isolation is structural,
not customary: if a rule here can be broken by forgetting it, propose a
mechanism instead.** The canonical protocol and the shared append-only action
log live at `~/co-claude/` (`PROTOCOL.md`, `ACTIONS.md`) — read the log's tail
before any work block; write CLAIM/DONE/NOTE lines as you work.

The rules, in brief:

1. **One agent per checkout.** The primary checkout belongs to the editor-based
   agent; other agents work in their own `git worktree` on their own branch.
   Never open or modify another agent's working directory.
2. **One issue, one branch, created FROM the issue** (amended by the founder,
   2026-08-27). Every piece of work starts as a tracker issue. The branch is
   created from that issue so it carries the issue's name
   (`<number>-<kebab-title>`, e.g. `15-the-timeline-spine` — GitHub's
   "create a branch for this issue", `gh issue develop`, or the
   createLinkedBranch API), always cut from current main. Work lands on the
   issue branch; done means the full verify ladder is green (`pnpm run
   verify` + the pytest suites), the branch is pushed, and it merges to main
   preserving linear history (rebase merge) — then the issue closes and the
   next one begins. One issue in flight per agent. **No commits to main,
   ever.** Never force-push; never rewrite shared history.
3. **Surface division** (current): editor agent — `services/*`,
   `packages/domain/schema`, `scripts/`, and sole ownership of regenerating
   `apps/web/src/lib/openapi.json` + `api-schema.d.ts`; terminal agent —
   `packages/design`, `apps/web` (except those two generated files), F-series
   design docs. Touching the other side's surface requires a NOTE in the
   action log and an acknowledgment first.
4. **Machine-written files are regenerated, never hand-merged**:
   `openapi.json`, `api-schema.d.ts`, `pnpm-lock.yaml`. After a rebase,
   re-run the generator.
5. **No repo-wide formatters or lint fixes** beyond the paths you claimed —
   another agent has in-flight files.
6. **The issue tracker is the claim board**: comment when starting an issue;
   close via commit message (`closes #N`).
7. **Before every commit**: `git status`; confirm every file in the commit is
   yours; commit with explicit paths — never `git add -A` or `git commit -a`.
8. **The vision test** (founder-approved, 2026-09-05). Every increment answers
   two questions before it is called done: is it correct (the gates), and
   does it move Hestia toward `docs/VISION.md` (the bar, its §6). A no on any
   bar line is a finding; findings rank rather than veto only at mockup
   review, where the founder decides. Tickets state problems, not builds —
   Problem / Acceptance / Hints (non-binding) — and the premise is checked
   before the branch: a ticket can be accurate and still not worth doing.
   Correct is the entry fee, not the deliverable.
