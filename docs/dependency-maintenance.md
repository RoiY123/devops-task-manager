# Dependency Maintenance Runbook

How to review and merge dependency updates for the Task Manager project.

Dependabot opens update pull requests; it does not decide whether they are safe. Every update is reviewed and merged by hand, one at a time, because every merge to `main` deploys to production.

A normal monthly round should take about an hour of hands-on work, plus waiting for CI and deployments. Sections 1–3 are the routine; the rest is only needed when something is unusual.

---

## 1. Policy

- **Schedule.** Dependabot checks monthly and opens grouped pull requests for Python packages, the Python base image, Compose images, GitHub Actions, and the Terraform AWS provider (`.github/dependabot.yml`).
- **Security first.** Security pull requests can appear at any time. Handle them before routine ones (section 4).
- **Routine means minor and patch.** The Python base image is limited to patch updates; the other ecosystems to minor and patch. Major upgrades (for example Python 3.12 → 3.13, PostgreSQL 17 → 18, AWS provider 6 → 7) are planned as dedicated work, not merged from a routine pull request.
- **One version, one place.** Each pinned version lives in exactly one file that Dependabot updates:

  | Version | Single source | Also used by (read automatically) |
  | --- | --- | --- |
  | Python | `docker/Dockerfile` | CI's `setup-python` |
  | PostgreSQL (local and CI) | `compose.yml` | CI's test database |
  | Alertmanager | `compose-monitoring.prod.yml` | the deployment's config check (`amtool`) |
  | Python packages | `requirements.in` → `requirements.txt` | Docker image, CI |
  | AWS provider | `terraform/.terraform.lock.hcl` | `terraform init` |

  Do not write version numbers into documentation or comments; they go stale. If an update ever needs a version edited somewhere else, treat that as a defect and remove the duplication.
- **Never auto-merge.** A green CI run is necessary, but release notes, Terraform plans, and production checks may reveal what tests do not.

---

## 2. Monthly Checklist

Before starting, local `main` should be clean and up to date.

Local Git Bash, from the repository folder; one line at a time:

```bash
git switch main
git pull origin main
git status
```

List the open Dependabot pull requests on GitHub (**Pull requests** tab). Handle security pull requests first, then the others in any order. Finish each pull request, including its deployment and checks, before starting the next.

For each pull request:

1. **Make sure it is current.** A pull request opened days ago may be behind `main` or offer outdated versions. Local Git Bash; one line at a time, replacing the branch name (shown under the pull request title):

   ```bash
   git fetch origin
   git rev-list --count origin/<dependabot-branch>..origin/main
   ```

   `0` means the branch contains everything on `main`. Anything else, or a pull request older than a few days, comment on the pull request:

   ```text
   @dependabot recreate
   ```

   Dependabot acknowledges with a 👍 reaction, rebuilds the branch on today's `main` with today's newest versions, and CI runs again. If no 👍 appears within about ten minutes, see **Dependabot does not react** in section 5.

2. **Review the changed files.** In the **Files changed** tab, only the expected dependency files should change (section 3). Note each old and new version. If the title and the files disagree, trust the files: titles are not always refreshed by `recreate`.

3. **Read the release notes** for each changed item, looking only for *breaking changes*, *security fixes*, and *behavior changes*. If a breaking change is listed, search our code for the affected feature before deciding it matters. Where to look is listed in section 7.

4. **Check CI.** In the pull request's **Checks**, `versions`, `test`, and `build-and-push` must pass. `deploy` is skipped for pull requests by design; any other skipped job means an earlier job failed.

5. **Run the checks before merging** for the ecosystem (section 3). Only Terraform needs local commands.

6. **Merge** with **Squash and merge**. Keep Dependabot's description. If the title shows the wrong version, correct it in the merge dialog.

7. **Wait for the workflow on `main`** to finish successfully (**Actions** tab). It tests, builds, deploys, and checks HTTPS health.

8. **Run the checks after the deployment** for the ecosystem (section 3).

9. **Sync locally.** Local Git Bash; one line at a time:

   ```bash
   git switch main
   git pull origin main
   ```

   After a Python package update, also synchronize the local virtual environment:

   ```bash
   .venv/Scripts/python -m pip install -r requirements.txt
   .venv/Scripts/python -m pip check
   ```

   Expected: `No broken requirements found.` Do not use `piptools sync` on Windows (section 7).

10. **Clean up** a local test branch if you created one, then prune deleted remote branches:

    ```bash
    git branch -D <test-branch>
    git fetch --prune
    ```

---

## 3. Checks per Ecosystem

These are the required checks. CI already installs the updated dependencies, runs every test on Linux, builds the application image, and validates the production and monitoring Compose files. Deployment validates the Nginx and Alertmanager configuration before switching and stops on failure.

| Pull request | Expected files | Before merging | After deployment |
| --- | --- | --- | --- |
| Python packages | `requirements.in`, `requirements.txt` | CI green; release notes of FastAPI, Starlette, Pydantic, SQLAlchemy, Alembic, Psycopg, PyJWT, Uvicorn | Health; login smoke test if FastAPI, Starlette, Pydantic, or PyJWT changed; sync `.venv` |
| Python base image | `docker/Dockerfile` | CI green | Health |
| Compose: Nginx, Certbot, PostgreSQL | `compose.prod.yml`, `compose.yml` | CI green; release notes (security) | Health; Certbot dry run if Certbot changed |
| Compose: monitoring | `compose-monitoring.prod.yml`, `compose.yml` | CI green; release notes | Grafana dashboards show recent data; Prometheus targets `UP` |
| Terraform provider | `terraform/.terraform.lock.hcl` | `terraform plan` shows no changes (below) | None |
| GitHub Actions | `.github/workflows/*.yml` | CI green | None |

The production checks are in [operator-tasks.md](operator-tasks.md):

- Health and login: [Health and login smoke test](operator-tasks.md#health-and-login-smoke-test)
- Certbot dry run: [Certificates: verify renewal](operator-tasks.md#certificates-verify-renewal)
- Grafana and Prometheus: [Monitoring](operator-tasks.md#monitoring-open-grafana-prometheus-or-alertmanager)

### Terraform provider plan

CI does not run Terraform, so the plan is the test. It reads AWS state and changes nothing.

Local Git Bash, from the repository folder; one line at a time:

```bash
git fetch origin
git switch -c test-dependabot-terraform origin/<dependabot-branch>
cd terraform
terraform init
terraform validate
terraform plan
cd ..
```

Expected:

- `terraform init` installs the provider version from the pull request's lock file.
- `terraform validate`: `Success! The configuration is valid.`
- `terraform plan`: `No changes. Your infrastructure matches the configuration.`

Do not run `terraform apply`. Merging the lock file changes nothing in AWS. Any other plan result: see section 5.

---

## 4. Security Pull Requests

A security pull request says it resolves a Dependabot alert. Alerts are listed under the repository's **Security and quality** → **Dependabot alerts**.

1. Read the alert: affected package, vulnerable versions, patched version, and what the vulnerability needs to be exploitable (platform, feature, input).
2. Decide how exposed we are; this sets the urgency, not whether to patch. Patch even with low exposure unless the patched version is incompatible.
3. Follow the normal checklist (section 2) without waiting for the monthly round.
4. After merging, confirm the alert moved to **Closed**. This can take a few minutes.

An alert without a pull request means Dependabot found no compatible fix. Investigate the dependency chain; the fix may need a manual update (section 6) or an upgrade of the package that depends on it.

---

## 5. When Something Goes Wrong

Do not merge a pull request until the problem is understood. `main` stays on the known-good versions meanwhile.

**CI fails.** Read the first meaningful error. Re-run once if it looks transient (network, runner). If it is caused by the update, read that package's release notes and decide:

- make a compatibility change on the pull request branch (below), test, then merge; or
- defer the update: close the pull request, and if it would keep returning, add an `ignore` rule to `.github/dependabot.yml`.

**One update in a group is unsafe.** Change only that version on the pull request branch instead of closing the whole group. Local Git Bash; one line at a time:

```bash
git fetch origin
git switch -c test-dependabot-fix origin/<dependabot-branch>
```

Edit the version, then:

```bash
git diff
git add <changed-file>
git commit -m "fix: use <package> <version>"
git push origin HEAD:<dependabot-branch>
```

A plain `git push` fails because the local branch name differs. After this, Dependabot no longer manages the branch: do not comment `@dependabot recreate` or `rebase`, which would discard your commit. Python packages are changed in `requirements.in`, then `requirements.txt` is regenerated on Linux (section 6).

**A test run shows a new warning.** A warning is not a failure, but find its source before merging. A deprecation warning from a package we do not import directly (for example a pytest plugin of an indirect dependency) is not a blocker; handle it with section 6.

**`terraform plan` shows changes.** Do not apply. Stop and investigate any replacement, deletion, security group, network, RDS, IAM, or EC2 change. A stopped monitoring instance has previously caused a misleading public-IP difference: start it, plan again, and check whether the difference is real.

**Dependabot does not react to a comment.** Without a 👍 reaction, the command was not picked up. Check [githubstatus.com](https://www.githubstatus.com) for a Dependabot incident. Otherwise, start a fresh run: **Insights** → **Dependency graph** → **Dependabot** → the ecosystem → **Recent update jobs** → **Check for updates**. It updates the existing pull request. Do not close the pull request to force an update: closing a grouped pull request tells Dependabot those updates are unwanted.

**Production misbehaves after a merge.** Follow [recovery.md](recovery.md).

---

## 6. Refreshing Indirect Python Dependencies

Dependabot updates the packages listed in `requirements.in`. Packages they pull in (for example `anyio`, `starlette`) only change when something forces them to.

Refresh an indirect package only when there is a reason: a security alert, a warning or failure that points to it, or an update that needs it.

`requirements.txt` must be generated on Linux. On Windows, pip-compile writes Windows-only packages such as `tzdata` into the shared file.

On a new branch from `main`, local Git Bash; one command, replacing the package name and using the Python version from `docker/Dockerfile`. Repeat `--upgrade-package <package>` for each package to refresh:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/work" -w /work \
  -e CUSTOM_COMPILE_COMMAND="pip-compile requirements.in" \
  python:<python-version>-slim-bookworm \
  sh -c "pip install --quiet pip-tools==7.6.1 && pip-compile --upgrade-package <package> requirements.in"
```

`CUSTOM_COMPILE_COMMAND` keeps the header of `requirements.txt` as `pip-compile requirements.in`. Without it, pip-compile records `--no-index` there, a command Dependabot should not repeat.

Check that only the expected package lines changed and the header did not:

```bash
git diff requirements.txt
```

Before opening the pull request, check the packages that depend on the refreshed one: a refresh can surface a new warning from them. Refresh those too when their release notes show no risk for our usage.

Then open a pull request and follow the normal checklist.

---

## 7. Reference

### Python dependency files

- `requirements.in`: the direct dependencies the project uses. Edited by people.
- `requirements.txt`: every direct and indirect dependency with an exact version, generated from `requirements.in` by pip-compile. Never edit it by hand and never create it with `pip freeze`.

### Windows

- Psycopg needs the `tzdata` package on Windows only, so the Linux-generated `requirements.txt` does not list it. `piptools sync` removes everything not listed, including `tzdata`. Use `pip install -r requirements.txt`, which installs the listed versions and removes nothing.
- Never run pip-compile on Windows (section 6).
- `pip install -r` also installs each package's own platform-specific needs, such as `tzdata` on Windows, so new packages with Windows-only needs work without extra steps.

### Adding or removing a direct package

Part of normal development rather than routine maintenance:

1. Add the package to `requirements.in` with an exact version (`package==x.y.z`), or remove its line.
2. Regenerate `requirements.txt` on Linux with the section 6 command, using `pip-compile requirements.in` without `--upgrade-package`. Existing versions stay unchanged; only the added package and its own needs are added, or packages nothing needs anymore are removed.
3. Update the local environment: `.venv/Scripts/python -m pip install -r requirements.txt`. It never uninstalls, so a removed package stays in `.venv` harmlessly; recreate `.venv` if that ever matters.
4. Commit both files in the feature pull request. Dependabot tracks a new direct package from then on.

New indirect packages arrive inside Dependabot's pull requests when an updated package starts needing them. Review a new line in `requirements.txt` during step 2 of the checklist: its `# via` comment shows which package requires it.

### pip and pip-tools

`pip` is not upgraded as a routine task. Production and CI already get current versions: `pip` comes with each Python base image and with CI's `setup-python`, both kept current through Dependabot. Locally, `pip install -r` needs no particular `pip` version, and pip-compile runs in a disposable Linux container with a pinned pip-tools version, avoiding the `pip` and pip-tools version incompatibilities pip-tools is known for. Upgrade `pip` locally only when something requires it.

### Dependabot behavior

- `@dependabot rebase` moves the same changes onto the current `main`.
- `@dependabot recreate` rebuilds the pull request from the current `main` with the newest versions. It discards manual commits.
- Dependabot rebases on its own only when its pull request conflicts with `main`. A pull request that is merely behind stays behind.
- After someone else pushes to its branch, Dependabot stops updating that pull request.
- A 👍 reaction confirms a comment command was accepted.

### CI and deployment

- Pull request: reads pinned versions, runs tests, validates Compose files, and builds the image without pushing. No deployment.
- Merge to `main`: the same, then pushes the image, deploys the application, checks HTTPS health, and deploys monitoring. Pushes that only change `docs/`, `README.md`, or `CLAUDE.md` skip the workflow.

### Where to read release notes

| Dependency | Location |
| --- | --- |
| Python | python.org release page for the version |
| Python packages | the package's GitHub releases or changelog (linked from its PyPI page) |
| Grafana, Prometheus, Alertmanager | GitHub releases of `grafana/grafana`, `prometheus/prometheus`, `prometheus/alertmanager` |
| Nginx | [nginx.org/en/CHANGES](https://nginx.org/en/CHANGES) |
| Certbot | GitHub releases of `certbot/certbot` |
| AWS provider | `CHANGELOG.md` in `hashicorp/terraform-provider-aws` |

### Running the tests inside the application image

Not part of the routine; useful when CI and local results disagree. Requires the local PostgreSQL (`docker compose up -d postgres`). Local Git Bash; build the image, then run the migrations and tests in it:

```bash
docker compose build app
```

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
  -v "$(pwd -W):/work" -w /work \
  -e TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/task_manager_test \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/task_manager_test \
  -e JWT_SECRET_KEY=local-test-only-key-at-least-32-bytes-long \
  app sh -c "alembic upgrade head && python -m pytest -q -p no:cacheprovider"
```
