# EC2 Deployment

## HTTPS

HTTPS is terminated by Nginx using certificates issued by Let's Encrypt.

Certificate files are stored in the Docker named volume:

`certbot_certs`

Using a Docker volume ensures that certificates persist across container recreation and are shared between the Certbot and Nginx containers.

The certificates and private keys must not be committed to Git.

## Initial certificate issuance

This command is required only for the initial certificate issuance.
Future renewals are handled automatically by Certbot.
Run this after DNS points to the EC2 Elastic IP and Nginx is available over port 80:

```bash
docker compose --env-file .env.prod -f compose.prod.yml run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email YOUR_EMAIL \
  --agree-tos \
  --no-eff-email \
  -d roiy.dev \
  -d api.roiy.dev
```

## Test certificate renewal

Verify that future renewals can succeed:

```bash
docker compose --env-file .env.prod -f compose.prod.yml run --rm certbot renew --dry-run
```

A successful dry run confirms that the renewal process is correctly configured without modifying the production certificate.

## Automatic certificate renewal

Certificate renewal is performed by:

`scripts/renew-certificates.sh`

Test it manually:

```bash
./scripts/renew-certificates.sh
```

Install the scheduled job:

```bash
crontab -e
```

```cron
17 2,14 * * * /home/ubuntu/task-manager/scripts/renew-certificates.sh >> /home/ubuntu/task-manager/certbot-renewal.log 2>&1
```

The job runs twice per day.

Certbot renews certificates only when they are close to expiration, so running this job regularly does not request a new certificate every time.

Verify the installed entry:

```bash
crontab -l
```

## Verification

After deployment, verify:

- https://roiy.dev/health
- https://api.roiy.dev/health

Both endpoints should return HTTP 200 over HTTPS.