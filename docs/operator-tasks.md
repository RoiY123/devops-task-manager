# Operator Tasks

Routine actions the operator performs on the running production system, other than deploying or recovering. Deployment and recovery are described in [deployment.md](deployment.md).

Commands below run through an interactive SSM session on the application instance; see **Administrative and monitoring access** in [deployment.md](deployment.md#administrative-and-monitoring-access).

## Onboarding a business

Businesses and their first administrators are created by the operator with a command inside the running API container. There is no public endpoint for this.

From a local terminal, open an interactive session on the application instance:

```powershell
./scripts/ssm-shell.ps1 app
```

Then, as `ubuntu`:

```bash
cd /home/ubuntu/task-manager

docker compose --env-file .env.prod -f compose.prod.yml \
  exec api python -m app.backend.cli create-business \
  --name "BUSINESS_DISPLAY_NAME" \
  --slug BUSINESS_SLUG \
  --admin-email ADMIN_EMAIL
```

- `--name` is the display name and may be Hebrew.
- `--slug` becomes part of the business login URL: lowercase letters, digits and single hyphens, at most 63 characters. Choose it carefully; renaming slugs is not yet supported.
- The command prompts twice for the administrator password, at least 12 characters, without displaying it.

Do not add `-T` to `exec`. Without an interactive terminal the command refuses to run, so a password is never echoed or passed through a pipe or shell history.

On success, the command prints the new business and administrator ids and exits with code 0. On rejected input, it prints `Error: ...`, exits with code 1 and creates nothing; correct the input and run it again.

The command only works with an application image that includes it. Use `exec` against the running API container, not an older image.

Deliver the administrator's password through a secure channel, separate from the login URL and email. Do not send it in the same message.
