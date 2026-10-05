# CLAUDE.md

DevOps learning project: Task Manager API (FastAPI, PostgreSQL + SQLAlchemy/Alembic,
Docker Compose, Terraform on AWS, GitHub Actions). The repository is the source of truth;
docs/project-notes.md records decisions, docs/learning-log.md records milestones.

## Working with me

- My primary goal is learning DevOps. Explain the purpose, operational impact, and tradeoffs of changes in plain language. Explain backend details enough for me to understand and describe the system, without assuming I want to specialize in backend development.
- Start new work with a read-only assessment and a plan; do not edit until I approve it.
- Keep milestones small. For each, list affected files, database migration implications,
  and the tests that prove it.
- Separate verified findings (read in the repo or observed output) from assumptions.
- After a milestone, update docs/project-notes.md and docs/learning-log.md.
- Before editing, check the current branch and working tree. Preserve unrelated
  changes and do not implement directly on main.
- Stop after the approved milestone. Summarize changes, tests actually run,
  unresolved issues, and the suggested Conventional Commit.
- Tell me when we reach a good commit and push point, but wait for my instruction.
- Update documentation with actual results; do not mark unrun tests or
  undeployed changes as verified or deployed.

## Never without my explicit instruction

- Commit, push, merge, tag, or deploy.
- Access AWS, production, RDS, SSM, or run Terraform against real state.
- Read secret files: .env, .env.docker, .env.prod, .env.monitoring, terraform.tfvars,
  *.tfstate (the *.example templates are fine).
- Read or print secrets or credentials, including unlisted secret files.
  Sanitized example files are fine.
- Discard unrelated changes, rewrite Git history, or delete existing databases
  or Docker volumes. Disposable test databases created by the approved tests
  may be cleaned up automatically.
  
## Git workflow

- Feature branch → PR to main → squash merge. Conventional Commits
  (feat, fix, test, ci, docs, infra, refactor).
- Merging to main deploys to production (.github/workflows/ci-cd.yml) and runs
  `alembic upgrade head` on RDS while the old API is still serving — unless every
  changed file is under docs/, README.md, or CLAUDE.md.

## Database migrations

- Hand-write migrations that move data; name every constraint.
- The previous app version runs during the migration and may be restored afterwards:
  keep the schema compatible with it, and document how any temporary measure is removed.
- Test migrations against disposable PostgreSQL databases locally and in CI,
  including populated-data cases where applicable. Never use RDS for tests.
- Provide and test a downgrade where safely reversible. Otherwise explain
  the limitation and recovery strategy before implementation.

## Tests

- Integration tests need PostgreSQL at TEST_DATABASE_URL
  (default localhost:5432/task_manager_test) plus DATABASE_URL and JWT_SECRET_KEY.
- Run `alembic upgrade head` with DATABASE_URL pointing at the test database,
  then `python -m pytest -v`.
