# Contributing

Keep changes small, preserve the strict read-only boundary, and run the locked
checks before you submit a change. Automated tests must not use Garmin
credentials or contact Garmin.

## Verify a change

From the repository root, run the same commands as CI:

```sh
uv sync --frozen
uv run ruff check .
uv run mypy
uv run pytest
```

Don't add credentials, OAuth tokens, Garmin response payloads, activity routes,
or health values to tests, fixtures, snapshots, issues, or commits.

## Upgrade a dependency

Dependency upgrades require manual review. Never enable or use automatic merge
for a dependency pull request. Treat a Dependabot pull request as an update
notification, not approval to merge.

For a `garminconnect` upgrade, review the read-only policy before you accept the
new lock file:

1. Read the upstream release notes and source changes between the pinned and
   proposed versions. Identify authentication changes, request helpers,
   downloads, GraphQL access, and direct or composite `POST`, `PUT`, `PATCH`,
   and `DELETE` operations.
2. Change the exact `garminconnect` version in `pyproject.toml` to the proposed
   version.
3. Update only that dependency and its required transitive dependencies:

   ```sh
   uv lock --upgrade-package garminconnect
   ```

4. Compare every public callable on `garminconnect.Garmin` with the entries in
   `src/garmin_fitness/policy.py`. Classify each added callable exactly once as
   an allowed structured read or a denied method with a specific reason.
5. Review existing callables for changed behavior. Move any callable that can
   mutate remote state, issue an unreviewed request, run arbitrary GraphQL, or
   return a deferred binary download to the denied ledger.
6. Update `PINNED_GARMINCONNECT_VERSION` only after the callable and behavior
   reviews are complete. Update the policy tests' expected counts and mutation
   set when the reviewed surface changes.
7. Run the locked verification commands from [Verify a change](#verify-a-change).
   Don't authenticate or run live requests as part of dependency verification.
8. Inspect the complete `pyproject.toml`, `uv.lock`, policy, and test diff. Ask a
   human reviewer to approve both the dependency change and every policy
   classification.
9. Merge the pull request manually only after CI and the explicit policy review
   pass. If a callable is unclear, deny it or postpone the upgrade until its
   behavior is understood.

For another dependency, update its declared constraint and lock entry, inspect
its direct and transitive diff, and run the same locked verification commands.
Keep automatic merge disabled and require a human review before merging.
