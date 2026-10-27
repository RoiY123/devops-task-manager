# Recovery

What to do when a deployment fails or production misbehaves. How production is built and deployed is described in [deployment.md](deployment.md); routine commands, including opening SSM sessions, are in [operator-tasks.md](operator-tasks.md).

Rollback restrictions for each schema change are recorded in its migration's docstring under `alembic/versions/`. The general rules are in **Database compatibility and rollback** in [deployment.md](deployment.md#database-compatibility-and-rollback).

Normal deployments should use GitHub Actions. Manual recovery is an operator action, not an automatic rollback provided by the deployment script.

Run application commands in Bash through an authorized SSM session on the application EC2 instance as `ubuntu`:

```bash
cd /home/ubuntu/task-manager

docker compose --env-file .env.prod -f compose.prod.yml ps
docker compose --env-file .env.prod -f compose.prod.yml logs --tail=50 api
```

## Establish the current state

Before changing the running application or database:

1. Pause new deployments and ensure no deployment is still running.
2. Review the failed workflow logs to identify whether migration, application startup, Nginx configuration, or a later step failed.
3. Record the actual API image and the database revision. Do not assume `.env.prod` identifies the running image: it is regenerated before migrations and application startup.
4. Select a known-good commit-tagged image and confirm it supports the current schema and runtime configuration. Review migrations applied since that image was built, including their documented compatibility measures and rollback restrictions.
5. Confirm the selected image is available. Local pruning may remove unused images; registry retention does not preserve every historical SHA image.

To inspect the database revision, use an image containing its migration history. Replace the placeholder with a full commit-SHA image tag before running:

```bash
SCHEMA_IMAGE_TAG='sha-REPLACE_WITH_COMMIT_CONTAINING_CURRENT_MIGRATIONS'

IMAGE_TAG="$SCHEMA_IMAGE_TAG" docker compose \
  --env-file .env.prod -f compose.prod.yml pull api
```

After a successful pull:

```bash
IMAGE_TAG="$SCHEMA_IMAGE_TAG" docker compose \
  --env-file .env.prod -f compose.prod.yml \
  run --rm --no-deps api alembic current
```

This reads the revision; it does not apply migrations. If the image cannot locate the current revision, select an image with the matching migration history before proceeding.

## Choose the recovery action

| Situation | Action |
| --- | --- |
| Migration failed before commit | Inspect the actual database state and logs. For transactional migrations, changes normally roll back; do not assume this after an interrupted connection or for nontransactional operations. Fix forward after verifying the state. |
| Migration succeeded but the new app is faulty | Restore a compatible previous application image, leaving the schema in place. |
| No previous image supports the current schema | Prefer a reviewed fix-forward change. Assess database downgrade or backup recovery separately. |
| Failure is in Nginx, certificates, or monitoring | Diagnose that component; an API image rollback may not address the failure. |

The previous API container is not deliberately stopped before migrations, but its health must still be checked after a failure. A fresh instance may have no previous container to retain.

## Restore a compatible application image

This operation can briefly interrupt requests while the single API container is replaced. It changes the application image only; it does not restore database contents, secrets, or older Compose/Nginx configuration.

Replace the placeholder with the verified rollback image tag. Run each command separately and stop if it fails:

```bash
ROLLBACK_IMAGE_TAG='sha-REPLACE_WITH_KNOWN_GOOD_FULL_COMMIT_SHA'

IMAGE_TAG="$ROLLBACK_IMAGE_TAG" docker compose \
  --env-file .env.prod -f compose.prod.yml pull api
```

After the pull succeeds:

```bash
IMAGE_TAG="$ROLLBACK_IMAGE_TAG" docker compose \
  --env-file .env.prod -f compose.prod.yml \
  up -d --no-deps api
```

Wait for the API to start and check its status and logs. If Nginx is running, validate its configuration and then reload it so it resolves the replacement API container:

```bash
IMAGE_TAG="$ROLLBACK_IMAGE_TAG" docker compose \
  --env-file .env.prod -f compose.prod.yml exec -T nginx nginx -t
```

Only if validation succeeds:

```bash
IMAGE_TAG="$ROLLBACK_IMAGE_TAG" docker compose \
  --env-file .env.prod -f compose.prod.yml exec -T nginx nginx -s reload
```

If Nginx is not running, investigate and restore it separately. Finish with the checks in **Verify after recovery** below.

The explicit image selection applies to each command without editing `.env.prod`. Continue using it for any subsequent manual commands intended to use the rollback image. An unqualified Compose command may select the failed deployment's tag still stored in `.env.prod`.

Do not run `alembic upgrade head` with an older image that lacks the database's current revision. Application rollback deliberately leaves the schema unchanged. The next normal deployment regenerates `.env.prod` and applies its selected release, so agree on the next deployment commit before resuming deployments.

## Database downgrade or backup recovery

These require a separate recovery decision. There is no universal safe downgrade command.

Before downgrading, identify the exact current and target revisions, inspect every intervening downgrade, and assess which records or relationships would be lost. Passing a downgrade test does not establish that reverting real production data is safe.

If a downgrade is approved:

1. Confirm the required migration image and compatible target application image are available before starting downtime.
2. Stop the API and any other writers before removing schema elements they may use.
3. Execute the reviewed downgrade with an image containing the current revision and the complete downgrade path.
4. Verify the resulting revision and required data. If the operation fails, establish the actual database state before starting any application image.
5. Start the compatible application, refresh Nginx resolution, and verify service behavior.

An RDS restore requires its own cutover plan, including the recovery point, potential loss of newer writes, restored-instance configuration, and application connection changes. A snapshot is not a guarantee of lossless recovery.

Record the recovered image, database revision, checks performed, and unresolved issues. These procedures are guidance; they are not evidence of a completed production recovery drill.

## Verify after recovery

After an application-only rollback, the database may intentionally remain newer than the running application. Inspect its revision using an image that contains that revision. Confirm the selected application image supports the current schema by reviewing the applied migrations and their documented rollback restrictions; the older image's migration head does not need to match the database revision.

After manual recovery, check public HTTPS health and verify login and task access with a designated test account (see **Health and login smoke test** in [operator-tasks.md](operator-tasks.md)), plus any operation affected by the failure. A health response alone does not prove the full application works.
