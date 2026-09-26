# Dependency Maintenance Runbook

This document defines how dependencies are reviewed, tested, updated, and merged for the Task Manager project.

The goal is to keep dependencies current without automatically introducing changes into production.

Dependency updates are intentionally reviewed before merging. Dependabot identifies available updates and opens pull requests, but it does not decide whether an update is safe for this project.

---

## 1. Dependency Management Strategy

The project uses several dependency ecosystems:

- Python application dependencies
- Docker base images
- Docker Compose service images
- GitHub Actions
- Terraform providers

Routine dependency updates are checked monthly by Dependabot.

Security updates are handled separately through:

- GitHub Dependency Graph
- Dependabot Alerts
- Dependabot Security Updates

Security fixes may therefore appear outside the normal monthly schedule.

Automatic merging is not enabled.

Every dependency pull request must be reviewed before merging.

---

## 2. Update Policy

### Routine updates

Routine dependency checks run monthly.

Minor and patch updates may be grouped to reduce pull request and CI noise.

Examples:

```text
FastAPI 0.139.x → 0.141.x
Grafana 13.1.x → 13.2.x
AWS provider 6.57.x → 6.66.x
```

These still require review and testing.

A minor or patch version number does not guarantee that an update is risk-free.

---

### Major and runtime upgrades

Major platform/runtime upgrades should be handled as dedicated maintenance work rather than routine Dependabot upgrades.

Examples:

```text
Python 3.12 → 3.13 or 3.14
PostgreSQL 17 → 18
Terraform AWS provider 6.x → 7.x
```

These may require migration planning, compatibility review, additional testing, or infrastructure changes.

---

### Security updates

Security updates take priority over the normal monthly schedule.

When Dependabot opens a security update:

1. Review the vulnerability and affected package.
2. Review the proposed patched version.
3. Test the update using the relevant procedure in this document.
4. Merge promptly if testing succeeds.
5. Investigate alternatives if the patched version cannot be adopted.

A security alert may exist without an automatic pull request if Dependabot cannot determine a safe compatible upgrade.

---

## 3. Python Dependency Model

Python dependencies use `pip-tools`.

The project contains:

```text
requirements.in
requirements.txt
```

### `requirements.in`

This file contains direct application dependencies maintained by the project.

Example:

```text
fastapi==...
sqlalchemy==...
psycopg[binary]==...
pytest==...
```

This is the file humans primarily maintain.

### `requirements.txt`

This file is generated from `requirements.in`.

It contains:

- direct dependencies
- transitive dependencies
- exact resolved versions

Do not manually maintain the dependency tree in this file.

---

## 4. Python Dependency Commands

When deliberately changing Python dependencies manually, edit:

```text
requirements.in
```

Then regenerate the lock-style dependency file:

```bash
python -m piptools compile requirements.in
```

Synchronize the local virtual environment:

```bash
python -m piptools sync requirements.txt
```

Verify that the installed dependency graph is valid:

```bash
python -m pip check
```

Run the application test suite:

```bash
python -m pytest -v
```

DO NOT use:

```bash
pip freeze > requirements.txt
```

`pip freeze` records whatever happens to be installed in the current environment and does not preserve the direct-vs-transitive dependency model used by this project.

---

## 5. Dependabot Pull Request Review Workflow

Every Dependabot PR should be reviewed in approximately this order:

```text
1. Identify what is changing
2. Review the version jumps
3. Inspect the changed files
4. Read relevant release notes
5. Check CI
6. Check out the PR locally
7. Run ecosystem-specific tests
8. Investigate any failures
9. Merge only after the update is understood
10. Verify production where appropriate
11. Sync local main
12. Remove temporary local branches
```

A green CI result alone is not sufficient evidence that every dependency update is appropriate.

---

## 6. Understanding Dependabot PR Branches

Dependabot creates its own remote branch.

Example:

```text
dependabot/pip/python-routine-...
```

The PR normally targets:

```text
main
```

The Dependabot branch contains the proposed dependency changes before they are merged.

This allows the changes to be tested locally without modifying `main`.

---

## 7. Checking Out a Dependabot PR Locally

Before changing branches, verify that the working tree is clean:

```bash
git status
```

Fetch the latest remote branches:

```bash
git fetch origin
```

List Dependabot branches:

```bash
git branch -r | grep dependabot
```

Create a temporary local branch from the relevant Dependabot branch:

```bash
git switch -c test-dependabot-<type> origin/<dependabot-branch>
```

Examples:

```text
test-dependabot-python
test-dependabot-compose
test-dependabot-terraform
```

Confirm the active branch:

```bash
git branch --show-current
```

The local temporary branch is only for testing.

`main` remains unchanged until the PR is merged.

---

## 8. Python Dependabot PR Testing

For Python dependency PRs, first synchronize the virtual environment with the PR:

```bash
python -m piptools sync requirements.txt
```

Verify dependency compatibility:

```bash
python -m pip check
```

Expected result:

```text
No broken requirements found.
```

Run tests:

```bash
python -m pytest -v
```

Then verify that the production-style application image can still be built from scratch:

```bash
docker compose build --no-cache app
```

Start the local stack:

```bash
docker compose up -d
```

Run database migrations:

```bash
docker compose exec app alembic upgrade head
```

Verify the API:

```bash
curl http://localhost:8000/health
```

All of these should succeed before merging a normal Python dependency PR.

---

## 9. Reviewing Python Release Notes

Focus review attention on dependencies that directly affect application behavior.

Examples:

```text
FastAPI
Pydantic
SQLAlchemy
Alembic
Psycopg
Uvicorn
authentication/security libraries
```

Patch-level utility dependency changes usually require less investigation unless their release notes mention:

- breaking behavior
- deprecations
- security issues
- API changes
- compatibility changes

Do not assume that a SemVer-looking "minor" update is automatically low risk.

Some projects, especially packages below version `1.0`, may introduce significant changes in minor releases.

---

## 10. What to Do When Python Tests Fail

Do not merge the PR.

First determine whether the failure is:

```text
transient/environmental
or
caused by the dependency update
```

If it looks transient, rerun the failing test once.

If it is reproducible:

1. Read the first meaningful error.
2. Identify which updated package is likely involved.
3. Review that package's release notes.
4. Determine whether the project must be updated for the new behavior.

For grouped PRs, multiple packages may have changed at once.

If necessary, isolate the problem by testing smaller groups or individual dependencies manually.

Possible outcomes:

```text
Update is compatible after a code/config change
→ make the compatibility change
→ retest
→ merge

Update is not appropriate yet
→ defer or close the update
→ optionally add an explicit Dependabot rule if necessary
```

The existing `main` branch remains on the known-good versions until the PR is merged.

---

## 11. Docker and Docker Compose Dependency PRs

Container dependency updates require runtime-oriented testing.

Examples include:

```text
Nginx
Prometheus
Grafana
PostgreSQL
Python base image
Node Exporter
Alertmanager
```

Check the PR's Files Changed tab first.

Expected changes should normally be limited to image tags in files such as:

```text
compose.yml
compose.prod.yml
docker/Dockerfile
monitoring compose files
```

Unexpected source-code or infrastructure changes should be investigated.

---

## 12. Docker Compose Validation

Validate the local Compose configuration:

```bash
docker compose -f compose.yml config --quiet
```

Validate production Compose configuration:

```bash
docker compose --env-file .env.prod.example -f compose.prod.yml config --quiet
```

These commands parse and validate the Compose configuration.

They do not deploy production.

---

## 13. Testing Updated Compose Images Locally

Pull updated local services:

```bash
docker compose pull
```

If only specific services changed, pull only those services:

```bash
docker compose pull prometheus grafana
```

Recreate specific services if needed:

```bash
docker compose up -d --force-recreate prometheus grafana
```

Check service status:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs prometheus
docker compose logs grafana
```

Look for:

- configuration parsing errors
- fatal startup errors
- container restart loops
- dependency connection failures

Warnings are not automatically failures; determine whether they affect the project.

---

## 14. Local Monitoring vs Production Monitoring

The local environment does not fully reproduce the production monitoring topology.

Local Compose includes services such as:

```text
app
postgres
prometheus
grafana
```

Production monitoring runs on a separate monitoring EC2 instance.

Production also includes targets that may not exist locally, such as Node Exporter.

Therefore, during local testing it may be normal to see:

```text
missing Node Exporter target
missing infrastructure metrics
dashboard panels with no data
different target names
```

Do not interpret those differences as evidence that a Prometheus or Grafana upgrade is broken.

The local acceptance criteria are instead:

```text
Prometheus starts
Grafana starts
Prometheus UI loads
Grafana UI loads
local application metrics can be scraped
Grafana can query Prometheus
no fatal startup/configuration errors exist
```

---

## 15. Port Conflicts During Local Testing

Do not start multiple copies of the same local Compose stack using the same host ports.

Common ports include:

```text
5432 PostgreSQL
8000 application
9090 Prometheus
3000 Grafana
```

Starting a second Compose stack while another is already running can produce:

```text
port is already allocated
```

When testing a dependency PR, prefer recreating the existing affected containers rather than running a second duplicate stack.

---

## 16. Production-Only Images

Some production services are not part of the normal local Compose environment.

For example, Nginx is defined in:

```text
compose.prod.yml
```

and is not normally exercised by the local development stack.

For these dependencies, use several forms of evidence:

```text
release/security notes
exact image tag validation
successful image pull
Compose configuration validation
CI success
production health verification after deployment
```

A successful local application test does not prove that a production-only reverse proxy image is safe.

---

## 17. Release and Security Note Review

Functional testing does not detect every risk.

Before accepting infrastructure-facing dependency updates, review upstream:

- release notes
- changelog
- security advisories

This is particularly important for:

```text
Nginx
PostgreSQL
Docker base images
authentication libraries
Terraform providers
GitHub Actions
```

A dependency may start successfully and still contain a known vulnerability.

The Nginx upgrade reviewed during the initial Dependabot rollout demonstrated this: the proposed image started successfully, but review showed that a newer patched release should be used instead.

---

## 18. Correcting a Version Inside a Grouped Dependabot PR

If most updates in a grouped PR are acceptable but one proposed version should be changed, it is not always necessary to close the entire PR.

Check out the Dependabot PR locally.

Modify only the required version.

Example:

```yaml
image: nginx:<desired-version>
```

Validate the exact image exists:

```bash
docker pull nginx:<desired-version>
```

Validate the Compose configuration again:

```bash
docker compose --env-file .env.prod.example -f compose.prod.yml config --quiet
```

Inspect the change:

```bash
git diff
```

Commit the manual correction on the temporary PR branch:

```bash
git add <changed-file>
git commit -m "fix: use patched Nginx image"
```

Because the local temporary branch name differs from the Dependabot remote branch name, a plain:

```bash
git push
```

may fail under Git's default `simple` push mode.

Push explicitly to the remote Dependabot branch:

```bash
git push origin HEAD:<dependabot-remote-branch>
```

Example:

```bash
git push origin HEAD:dependabot/docker_compose/compose-routine-...
```

This updates the existing PR and triggers new PR checks.

Do not use:

```text
@dependabot recreate
```

after manually modifying a Dependabot PR unless intentionally regenerating the PR, because Dependabot may overwrite the manual changes.

---

## 19. Terraform Provider Dependency PRs

Terraform provider updates require a different validation process.

A Dependabot Terraform PR may only modify:

```text
terraform/.terraform.lock.hcl
```

The file records:

- exact provider version
- provider package checksums

Large checksum changes are normal when the provider version changes.

GitHub may hide the lock-file diff because it considers the file generated.

Use the **Load Diff** button if necessary.

There is normally no value in manually reviewing every provider checksum.

---

## 20. Terraform Provider Validation

Check out the Terraform Dependabot PR locally.

Move into the Terraform directory:

```bash
cd terraform
```

Initialize Terraform:

```bash
terraform init
```

This installs the provider version selected by the PR lock file.

Validate the configuration:

```bash
terraform validate
```

Then create a plan:

```bash
terraform plan
```

The ideal result for a provider-only maintenance update is:

```text
No changes. Your infrastructure matches the configuration.
```

This demonstrates that:

```text
the new provider loads successfully
the Terraform configuration remains valid
Terraform state can be read
real AWS resources can be refreshed
the provider does not propose unexpected infrastructure changes
```

---

## 21. Terraform Plan Review Rules

Never automatically accept unexpected infrastructure changes from a provider update.

If Terraform proposes:

```text
resource replacement
resource deletion
security group change
network change
RDS change
IAM change
EC2 replacement
```

stop and investigate before merging.

This project has previously observed a misleading EC2 public-IP difference when the monitoring EC2 instance was stopped.

If a provider upgrade appears to propose replacement of the monitoring instance because of public-IP behavior:

1. Do not apply.
2. Start the monitoring instance if appropriate.
3. Refresh/re-run the plan.
4. Determine whether the difference is real or only caused by the stopped-instance state.

---

## 22. Do Not Run Terraform Apply for a Provider Review

A routine provider PR is being tested, not deployed.

If:

```bash
terraform plan
```

returns:

```text
No changes. Your infrastructure matches the configuration.
```

there is no reason to run:

```bash
terraform apply
```

Merging the lock-file update does not itself modify AWS infrastructure.

AWS resources only change when Terraform is deliberately applied.

---

## 23. GitHub Actions Dependency Updates

GitHub Actions updates should be reviewed similarly to other CI infrastructure.

Check:

- action name
- old and new major/minor version
- upstream release notes
- breaking changes
- required permission changes
- runtime changes

Major GitHub Action upgrades should be reviewed individually.

The project does not auto-merge GitHub Action updates.

After an Action update, verify that the relevant workflow completes successfully.

---

## 24. CI Behavior for Pull Requests

The workflow intentionally runs:

```yaml
on:
  push:
    branches:
      - main
    tags:
      - "v*.*.*"
  pull_request:
    branches:
      - main
```

For `pull_request`, the branch filter refers to the PR's **target/base branch**.

Therefore a Dependabot PR works like this:

```text
Dependabot source branch
dependabot/...

          ↓ PR

main
```

The PR triggers CI because its target is `main`.

A push directly to the Dependabot branch does not trigger a second redundant workflow.

---

## 25. CI and Deployment Behavior

The intended workflow is:

```text
feature/Dependabot branch push
→ no standalone push workflow

PR targeting main
→ CI validation

merge into main
→ push workflow
→ tests
→ image build/push
→ production deployment
→ production health check
```

Production deployment is additionally protected by the workflow condition:

```yaml
if: github.event_name == 'push' && github.ref == 'refs/heads/main'
```

PR validation therefore does not deploy production.

---

## 26. Pull Request Checks

Before merging, check the PR's GitHub Actions/Checks section.

A green check means the automated workflow succeeded for that PR.

It does not necessarily prove every runtime or infrastructure behavior.

CI is one source of evidence alongside:

```text
diff review
release-note review
local tests
ecosystem-specific checks
production smoke tests
```

---

## 27. Merge Strategy

Routine Dependabot PRs should normally use:

```text
Squash and merge
```

This creates one logical commit on `main` for one dependency maintenance PR.

Example commit subjects:

```text
chore(deps): bump the python-routine group with 10 updates

chore(deps): update Compose service images

chore(deps): bump hashicorp/aws
```

The extended Dependabot description may be retained as the commit body.

This preserves useful information about version changes without creating unnecessary merge commits.

---

## 28. Production Verification After Merge

Merging into `main` triggers the production CI/CD workflow.

After the workflow succeeds, perform checks appropriate to the update.

For application or Nginx changes:

```text
https://api.roiy.dev/health
```

should respond successfully.

For monitoring updates:

- connect to Grafana through the normal SSM tunnel
- verify dashboards load
- verify recent data exists
- verify Prometheus datasource connectivity
- verify expected Prometheus targets are healthy

A successful deployment workflow plus a successful production smoke test completes the update.

---

## 29. Sync Local Main After Merge

After merging a PR on GitHub:

```bash
git switch main
```

Update local `main`:

```bash
git pull origin main
```

For Python dependency updates, also synchronize the virtual environment:

```bash
python -m piptools sync requirements.txt
```

Then verify:

```bash
python -m pip check
```

Check Git state:

```bash
git status
```

Expected:

```text
On branch main
Your branch is up to date with 'origin/main'
nothing to commit, working tree clean
```

---

## 30. Remove Temporary Test Branches

After the PR has been merged and local `main` is synchronized, delete the temporary local test branch.

Examples:

```bash
git branch -D test-dependabot-python
```

```bash
git branch -D test-dependabot-compose
```

```bash
git branch -D test-dependabot-terraform
```

These commands delete only the local temporary branches.

They do not modify the merged PR or `main`.

---

## 31. Clean Stale Remote-Tracking Branches

Dependabot remote branches may still appear in:

```bash
git branch -a
```

even after the PR is merged.

Refresh and prune stale remote references:

```bash
git fetch --prune
```

Then check:

```bash
git branch -a
```

If the remote Dependabot branch no longer exists, its stale local remote-tracking reference will be removed.

If it still appears, GitHub still has the branch and it can safely be left alone.

---

## 32. Monthly Dependency Maintenance Checklist

When the monthly Dependabot scan opens PRs:

```text
Review each PR individually.

Confirm only expected dependency files changed.

Review the proposed versions.

Read relevant release/security notes.

Check GitHub CI.

Check out the PR locally.

Run ecosystem-specific testing.

Do not merge failed or unexplained updates.

For grouped PRs, investigate any unsafe individual dependency before abandoning the entire group.

Use Squash and merge when the PR is approved.

Wait for the main deployment workflow.

Perform production smoke checks where appropriate.

Pull the merged changes into local main.

Synchronize the Python virtual environment when Python dependencies changed.

Delete temporary local test branches.

Prune stale remote branches if desired.
```

---

## 33. Security Update Checklist

When a Dependabot security PR appears:

```text
Read the Dependabot vulnerability information.

Confirm which dependency and versions are affected.

Review the patched target version.

Check whether the update changes a runtime/platform major version.

Review upstream security and release notes.

Run the relevant local validation procedure.

Check CI.

Merge promptly when testing succeeds.

Perform production verification after deployment.
```

Do not ignore security PRs simply because the normal dependency review is monthly.

---

## 34. Dependency Maintenance Principles

The project follows these principles:

**Pinned does not mean frozen forever.**

Versions are pinned for reproducibility, then deliberately upgraded.

**Dependabot is a scout, not an automatic decision-maker.**

It identifies possible upgrades; the project owner decides whether they are appropriate.

**CI passing is necessary but not always sufficient.**

Runtime behavior, security information, Terraform plans, and release notes may reveal issues that tests do not.

**Do not apply infrastructure changes during dependency review unless the infrastructure change itself is intentional.**

Terraform provider review uses `plan`, not automatic `apply`.

**Keep dependency PR noise manageable.**

Routine updates are monthly and grouped where practical.

**Handle large platform changes deliberately.**

Python runtime, PostgreSQL major versions, Terraform major versions, and similar upgrades should be dedicated maintenance tasks.

**Never auto-merge dependency updates into production.**