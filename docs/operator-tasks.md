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
`403` means the account's temporary password has expired; reset it.<br>
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

### Passwords you set

Passwords set with `create-business`, `add-user` and `reset-password` are temporary by default. At their first login, the user must choose their own password; until then, the API refuses everything else. A temporary password stops working after 7 days; to let the user log in again, reset it.

Add `--permanent` to set a normal password instead, for example for a test account. In the menu, answer `no` to `Must change password at next login?`. The audit log records which kind was set (`temporary=True` or `False`).

### Onboard a business

Creates a business and its first administrator, who becomes the business's leader.

Application instance; one command. It prompts twice for the administrator password; type or paste only the password at each prompt:

```bash
./scripts/operator.sh create-business \
  --name "BUSINESS_DISPLAY_NAME" \
  --slug BUSINESS_SLUG \
  --admin-email ADMIN_EMAIL
```

- `--name`: display name; Hebrew is supported. To correct Hebrew while typing, prefer the menu: this line is edited by the server's shell before the CLI starts.
- `--slug`: part of the business login URL. Lowercase letters, digits and single hyphens, at most 63 characters. Choose it carefully: slugs cannot be renamed. Before a business goes live, an empty business can be deleted and onboarded again.
- Password: 12 to 256 characters; the prompt does not display it. Temporary unless you add `--permanent` (see Passwords you set).

Expected: `Created business 'BUSINESS_SLUG' (id …) with leader ADMIN_EMAIL (user id …). The password is temporary: they must change it within 7 days.`

Send the password through a secure channel, separately from the login URL and email.

### List businesses and their users

Read-only. Application instance; one command. Remove `--business BUSINESS_SLUG` to list every business:

```bash
./scripts/operator.sh list-users --business BUSINESS_SLUG
```

Each line shows the business slug, its name, and one user's id, email, role, and which tasks the user sees and may change: `sees all/own/custom  edits all/own/custom`, or `no users`. Custom means their own tasks plus those of the users granted to them. Terminals may display Hebrew names right-to-left reversed; the stored text is not affected.

The leader's role is shown as `leader`. A `Warning: business … has users but no leader` line means an older version changed the business; fix it with `transfer-leadership`.

### Manage users

The commands below name both the business and the email; a user in another business is not found.

Each business with users has exactly one leader, an admin who always sees and can change every task. The leader cannot be demoted or restricted, and can be removed only as the business's last user; to replace the leader, transfer leadership.

Access to other users' tasks has two parts.<br>
**Seeing** them: admins always see all tasks; members see their own (the default), all, or their own plus chosen users' (grants).<br>
**Changing** them, which includes deleting: everyone may change their own tasks by default; admins and members may also change all tasks (only if they see all) or chosen users' tasks (edit grants, only for tasks they can see).<br>
The leader always sees and changes every task.

**Add a user.** Application instance; one command. It prompts twice for the new user's password (12 to 256 characters; temporary unless you add `--permanent`). Use `--role admin` for an administrator:

```bash
./scripts/operator.sh add-user \
  --business BUSINESS_SLUG --email USER_EMAIL --role member
```

An email already used in that business is refused, ignoring capitals. The same email may exist in another business as a separate account with its own password.

In a business without users, the first user becomes its leader and must be added with `--role admin`.

**Reset a password.** Application instance; one command. It prompts twice for the new password (temporary unless you add `--permanent`). A reset also lets in a user whose temporary password expired:

```bash
./scripts/operator.sh reset-password \
  --business BUSINESS_SLUG --email USER_EMAIL
```

The user's existing logins stop working immediately; they log in again with the new password.

**End a user's logins.** Logs the user out everywhere, without changing the password. If someone else may know the password, reset it instead: a reset also ends the logins. Application instance; one command:

```bash
./scripts/operator.sh end-sessions \
  --business BUSINESS_SLUG --email USER_EMAIL
```

Expected: `Ended every login of USER_EMAIL; they must log in again. Their password is unchanged.`

**Promote or demote.** Application instance; one command. Use `--role admin` or `--role member`:

```bash
./scripts/operator.sh set-role \
  --business BUSINESS_SLUG --email USER_EMAIL --role admin
```

A role change applies the new role's defaults: admins see all tasks, members their own, and both change only their own; the user's grants are removed. Re-apply custom settings afterwards. Transferring leadership applies the admin defaults to the previous leader.

**Transfer leadership.** Makes an admin the business's leader; the previous leader stays an admin. To make a member the leader, promote them first. Application instance; one command:

```bash
./scripts/operator.sh transfer-leadership \
  --business BUSINESS_SLUG --to ADMIN_EMAIL
```

Expected: `ADMIN_EMAIL is now the leader of 'BUSINESS_SLUG'; PREVIOUS_EMAIL remains an admin.` To undo, transfer it back.

**Change task visibility (members).** `--all` shows the member every task in the business; `--own` only their own and removes all their grants. Admins always see all tasks and the leader too, so both are refused. Application instance; one command:

```bash
./scripts/operator.sh set-task-visibility \
  --business BUSINESS_SLUG --email USER_EMAIL --all
```

Expected: `USER_EMAIL now sees all tasks.`

**Change task editing.** `--all` lets the user change every task in the business, and requires seeing all tasks; `--own` limits them to their own tasks: their edit grants become view grants, or are removed if they see all tasks. Refused for the leader. Application instance; one command:

```bash
./scripts/operator.sh set-task-editing \
  --business BUSINESS_SLUG --email USER_EMAIL --all
```

Expected: `USER_EMAIL now edits all tasks.`

**Let a user see or change another user's tasks.** A grant gives one user access to every task of another user (the owner): a view grant to see them, an edit grant to see and change them. Grants are one-way and stay within the business. Application instance; one command at a time:

```bash
./scripts/operator.sh grant-task-view \
  --business BUSINESS_SLUG --viewer VIEWER_EMAIL --owner OWNER_EMAIL
```

```bash
./scripts/operator.sh revoke-task-view \
  --business BUSINESS_SLUG --viewer VIEWER_EMAIL --owner OWNER_EMAIL
```

```bash
./scripts/operator.sh grant-task-edit \
  --business BUSINESS_SLUG --viewer USER_EMAIL --owner OWNER_EMAIL
```

```bash
./scripts/operator.sh revoke-task-edit \
  --business BUSINESS_SLUG --viewer USER_EMAIL --owner OWNER_EMAIL
```

```bash
./scripts/operator.sh list-task-grants --business BUSINESS_SLUG
```

Expected: `VIEWER_EMAIL now sees the tasks of OWNER_EMAIL (view only).`, `VIEWER_EMAIL no longer sees the tasks of OWNER_EMAIL.`, `USER_EMAIL can now change the tasks of OWNER_EMAIL.`, `USER_EMAIL can no longer change the tasks of OWNER_EMAIL.`, or one line per grant.

A view grant is refused while the user sees all tasks. An edit grant requires that the user can already see the owner's tasks (they see all, or have a view grant), and upgrades a view grant. Revoking an edit grant keeps the view; revoking the view removes the grant entirely. `list-task-grants` shows each grant as `(view)` or `(edit)`. Repeating a grant or revoking a missing one changes nothing. Removing either user deletes their grants.

**Move a user's tasks.** Moves every task of one user to another user in the same business, for example when someone hands over their work. You see only how many tasks move, never their titles; individual tasks are managed by the business's leader and admins. Application instance; one command. It shows how many tasks will move, then asks you to type the receiving email again:

```bash
./scripts/operator.sh reassign-tasks \
  --business BUSINESS_SLUG --from CURRENT_OWNER_EMAIL --to RECEIVING_EMAIL
```

Expected: `Moved N tasks from CURRENT_OWNER_EMAIL to RECEIVING_EMAIL.`

Grants stay with their users: people granted access to the previous owner's tasks stop seeing or changing the moved ones, and the output says how many. The moved tasks are not marked among the receiver's own, so moving them back is done by the business's leader or an admin, who can move specific tasks; the audit log lists their ids.

**Remove a user.** Permanently deletes the user; their existing logins stop working immediately. If they have tasks, you decide what happens to them: move them to another user in the same business, or delete them. Application instance; one command. With `--reassign-to`, the tasks move to that user; without it, the command asks (type the receiving email, or `delete`). It then shows what will happen and asks you to type the user's email again:

```bash
./scripts/operator.sh remove-user \
  --business BUSINESS_SLUG --email USER_EMAIL --reassign-to RECEIVING_EMAIL
```

Expected: `Removed USER_EMAIL from business 'BUSINESS_SLUG'; N tasks moved to RECEIVING_EMAIL.`, or after `delete`, `Removed USER_EMAIL from business 'BUSINESS_SLUG' and deleted N tasks.` Moved tasks behave as in Move a user's tasks: grants stay with their users.

The leader cannot be removed while other users remain; transfer leadership first. Removing the last user, including the leader, is allowed and leaves the business empty.

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

### Read the audit log

Every successful change to users, task access and businesses is recorded, whether it was made with these commands, the menu, or by a business's leader or admin through the API. Each event records when it happened, who made the change (`operator` for these commands), what changed, and for whom. Passwords are never recorded. The application can add events but cannot change or delete them.

Read-only. Application instance; one command. The latest events, oldest to newest, so the last line is the most recent; `--limit` sets how many, 1 to 1000 (default 50):

```bash
./scripts/operator.sh audit-log --business BUSINESS_SLUG --limit 50
```

Each line shows the time in UTC, who, the action, the affected user, and the details. For example: `2026-11-22 10:15:03 UTC  dana@…  edit_granted  noa@…  owner_email=avi@… owner_id=14`.

Events stay after users are removed and after the business is deleted, so a deleted business's history can still be read by its slug. If the slug was later reused by another business, a note line lists both business ids. Changes made while an older version was running, for example during a deploy, are not recorded.

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
