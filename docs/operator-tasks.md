# Operator Tasks

Runbook for routine production operations. How production is built and deployed: [deployment.md](deployment.md). When something is broken: [recovery.md](recovery.md).

Every command block says where to run it and how to paste it:

- **One command:** paste the block as one; lines ending in `\` continue the same command.
- **One line at a time:** run each line and wait for it to finish.
- A command that prompts for input is always alone in its block; type or paste only the answer at the prompt.

## Before you start

Local requirements: AWS CLI, the Session Manager plugin, and credentials for the `task-manager-terraform` profile.

### Open a session on a server

Local Git Bash, from the repository folder; one command. Use `app` for the application instance or `monitoring` for the monitoring instance:

```bash
./scripts/ssm-shell.sh app
```

In the session:

```bash
cd /home/ubuntu/task-manager
```

On the monitoring instance, use `cd /home/ubuntu/task-manager-monitoring` instead.

All application-instance commands below run from `/home/ubuntu/task-manager` and start with `docker compose --env-file .env.prod -f compose.prod.yml`.

## Status and logs

Application instance; one line at a time:

```bash
docker compose --env-file .env.prod -f compose.prod.yml ps
docker compose --env-file .env.prod -f compose.prod.yml logs --tail=50 api
```

Monitoring instance; one command:

```bash
docker compose --env-file .env.monitoring -f compose-monitoring.prod.yml ps
```

## Check the database revision

Application instance; one command:

```bash
docker compose --env-file .env.prod -f compose.prod.yml \
  run --rm --no-deps api alembic current
```

Expected after a normal deployment: the newest revision in `alembic/versions/`, followed by `(head)`. This only reads the revision. After a rollback, use the procedure in [recovery.md](recovery.md#establish-the-current-state) instead.

## Redeploy without a code change

Deploys the current `main` again, for example after changing a Parameter Store value, which only takes effect on the next deployment.

GitHub → **Actions** → **CI/CD** → **Run workflow** → branch `main` → **Run workflow**. It tests, builds, deploys, and checks HTTPS health; then run the [health and login smoke test](#health-and-login-smoke-test). On any other branch it only tests and builds.

## Health and login smoke test

Run every command in this section in **local Git Bash on your PC**, not in an SSM session: they test the public HTTPS endpoint from outside, and the login check needs the repository's local Python environment.

One command:

```bash
curl -s https://api.roiy.dev/health
```

Expected: `{"status":"healthy"}`.

To check that an account can log in, from the local repository folder. This line prompts for the password; run it alone:

```bash
read -rsp "Password: " ADMIN_PASSWORD; echo
```

Then one command, replacing `ADMIN_EMAIL` and `BUSINESS_SLUG` (the account's business):

```bash
ADMIN_EMAIL='ADMIN_EMAIL' ADMIN_PASSWORD="$ADMIN_PASSWORD" .venv/Scripts/python -c 'import json, os; print(json.dumps({"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}))' \
  | curl -s -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" --data @- https://api.roiy.dev/businesses/BUSINESS_SLUG/login
```

Expected: `200`.<br>
`401` means the email, password, or business slug is wrong.<br>
`429` means too many recent attempts from your IP; wait a minute and retry.<br>
`422` with `.venv/Scripts/python: No such file or directory` means the command ran outside the local repository folder, so no credentials were sent.

Then one command:

```bash
unset ADMIN_PASSWORD
```

## Businesses and users

There is no public endpoint for any of these tasks. Input is checked before any prompt, so on `Error: ...` nothing was changed; correct the input and run it again. Ctrl+C at any prompt cancels without saving.

Every command in this section runs on the application instance, from `/home/ubuntu/task-manager`, through `./scripts/operator.sh`. The script runs the operator CLI in the API container and makes Backspace work at its prompts in an SSM session from Windows, where Backspace is sent as `^H`. Deployments install and update it.

Hebrew can be typed and corrected with Backspace at any prompt (menu answers, passwords, confirmations). Arrow keys do not move the cursor at these prompts: they insert characters shown as `^[[D`, which Backspace removes. At password prompts nothing is shown, so a password containing them is refused with `contains control characters`. If you ever see `could not be read`, part of a character was lost on the way in; retype the answer without corrections, or paste it.

### Operator menu

Every task in this section is also available from an interactive menu, which asks for each value instead of requiring a filled-in command. Application instance; one command:

```bash
./scripts/operator.sh menu
```

Choose a number and answer the questions. A blank answer cancels the current action without changes; after each action or error the menu returns. `0` or Ctrl+C exits. The menu runs the same checks, password prompts and confirmations as the commands below.

### Onboard a business

Creates a business and its first administrator.

Application instance; one command. It prompts twice for the administrator password; type or paste only the password at each prompt:

```bash
./scripts/operator.sh create-business \
  --name "BUSINESS_DISPLAY_NAME" \
  --slug BUSINESS_SLUG \
  --admin-email ADMIN_EMAIL
```

- `--name`: display name; Hebrew is supported. To correct Hebrew while typing, prefer the menu: this line is edited by the server's shell before the CLI starts.
- `--slug`: part of the business login URL. Lowercase letters, digits and single hyphens, at most 63 characters. Choose it carefully: slugs cannot be renamed. Before a business goes live, an empty business can be deleted and onboarded again.
- Password: at least 12 characters; the prompt does not display it.

Expected: `Created business 'BUSINESS_SLUG' (id …) with administrator ADMIN_EMAIL (user id …).`

Send the password through a secure channel, separately from the login URL and email.

### List businesses and their users

Read-only. Application instance; one command. Remove `--business BUSINESS_SLUG` to list every business:

```bash
./scripts/operator.sh list-users --business BUSINESS_SLUG
```

Each line shows the business slug, its name, and one user's id, email and role, or `no users`. Terminals may display Hebrew names right-to-left reversed; the stored text is not affected.

### Manage users

The commands below name both the business and the email; a user in another business is not found. Type emails in lowercase: login matches the email exactly as it was created.

**Add a user.** Application instance; one command. It prompts twice for the new user's password (at least 12 characters). Use `--role admin` for an administrator:

```bash
./scripts/operator.sh add-user \
  --business BUSINESS_SLUG --email USER_EMAIL --role member
```

An email already used in that business is refused, ignoring capitals. The same email may exist in another business as a separate account with its own password.

**Reset a password.** Application instance; one command. It prompts twice for the new password:

```bash
./scripts/operator.sh reset-password \
  --business BUSINESS_SLUG --email USER_EMAIL
```

Logins made before the reset stay valid until their tokens expire (`ACCESS_TOKEN_EXPIRE_MINUTES`). To cut off access immediately, remove the user instead.

**Promote or demote.** Application instance; one command. Use `--role admin` or `--role member`:

```bash
./scripts/operator.sh set-role \
  --business BUSINESS_SLUG --email USER_EMAIL --role admin
```

**Remove a user.** Permanently deletes the user and all their tasks; their existing logins stop working immediately. Application instance; one command. It shows how many tasks will be deleted, then asks you to type the email again:

```bash
./scripts/operator.sh remove-user \
  --business BUSINESS_SLUG --email USER_EMAIL
```

A business that has users must keep an admin: removing or demoting its only admin is refused while other users remain. Promote another user first. Removing the last user of a business is allowed.

### Manage businesses

**Rename a business.** Changes the display name only; the slug, users and logins are unaffected. Application instance; one command:

```bash
./scripts/operator.sh rename-business \
  --slug BUSINESS_SLUG --name "NEW_DISPLAY_NAME"
```

Expected: `Renamed business 'BUSINESS_SLUG' from '…' to '…'.` To undo, rename it back.

**Delete an empty business.** Permanently deletes a business that has no users; a business with users is refused, so remove its users first. Application instance; one command. It asks you to type the slug again:

```bash
./scripts/operator.sh delete-business --slug BUSINESS_SLUG
```

Expected: `Deleted business 'BUSINESS_SLUG'.`

## Certificates: verify renewal

Renewal runs automatically; see **Automatic certificate renewal** in [deployment.md](deployment.md#automatic-certificate-renewal).

Inspect the installed schedule and cron service. Application instance; one line at a time:

```bash
sudo cat /etc/cron.d/task-manager-certificates
systemctl is-active cron
systemctl is-enabled cron
```

Test renewal against Let's Encrypt's staging service without replacing production certificates. Application instance; one command:

```bash
docker compose --env-file .env.prod -f compose.prod.yml \
  run --rm --no-deps certbot renew \
  --dry-run \
  --no-random-sleep-on-renew \
  --verbose
```

This skips the randomized delay and prints progress directly. It does not test the Nginx reload or prove cron triggered the job.

To run the real renewal script, including the Nginx reload, as `ubuntu`. Application instance; one command:

```bash
/home/ubuntu/task-manager/scripts/renew-certificates.sh \
  >> /home/ubuntu/task-manager/certbot-renewal.log 2>&1
```

It may take several minutes and print nothing, because output goes to the log and Certbot keeps its randomized delay. It renews certificates if they are due. Then one command:

```bash
tail -n 40 /home/ubuntu/task-manager/certbot-renewal.log
```

Expected: a successful renewal-check message and a successful Nginx-reload message. To confirm scheduled runs, check the log after a scheduled execution.

## Monitoring: open Grafana, Prometheus or Alertmanager

These interfaces listen only on the monitoring instance itself and are reached through SSM port forwarding.

| Service | Port | Local URL |
| --- | --- | --- |
| Grafana | 3000 | http://localhost:3000 |
| Prometheus | 9090 | http://localhost:9090 |
| Alertmanager | 9093 | http://localhost:9093 |

Local Git Bash, from the repository folder; one command. Use `grafana`, `prometheus`, or `alertmanager`:

```bash
./scripts/ssm-tunnel.sh grafana
```

Then open the local URL from the table. Keep the terminal open while using the service; use a separate terminal for each tunnel and press Ctrl+C to close it. If the local port is already in use (for example by the local Compose Grafana), add a free port as a second argument, such as `./scripts/ssm-tunnel.sh grafana 13000`, and open that port instead.
