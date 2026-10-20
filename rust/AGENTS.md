# Rust commit workflow

Finish each semantically distinct task with a self-contained, descriptive
Conventional Commit (`type(scope): imperative summary`). Commit completed work
instead of leaving it uncommitted, unless the user explicitly asks otherwise.

Write the commit body in Markdown. Explain the problem and resulting behavior,
important design decisions or intentional compatibility differences, and the
validation performed with its results. State relevant untested limits clearly.

Use the `$tix` skill for history mutations and Git for inspection and staging.
Inspect the current history and index before committing, and stage only the
task's changes. Use the responsible agent's actual name and email as author.

For a small follow-up, look for its originating commit among recent commits from
the same day. If the change belongs to that task, use Tix to amend the originating
commit instead of creating another small commit. Follow the skill's review
preservation rules: amend an unreviewed commit directly; preserve a commit marked
`✨` through the documented fixup workflow unless the user explicitly directs
otherwise. Keep semantically independent tasks in separate commits.

Run validation appropriate to the change before committing. Preserve unrelated
work and review marks, and verify the resulting commit, placement and worktree
status afterward. Push only when requested by the user.
