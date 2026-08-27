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
2. **Branch per increment; main is sacred.** main advances only by merging a
   branch whose full verify ladder is green (`pnpm run verify` + the pytest
   suites), only from the primary checkout, only at a clean-tree moment.
   Never force-push. Never rewrite history. Never commit half-finished work
   to main.
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
