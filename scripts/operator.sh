#!/usr/bin/env bash
# Runs an operator CLI command in the production API container.
# Use from an SSM session on the application instance, for example:
#   ./scripts/operator.sh menu
#   ./scripts/operator.sh list-users --business BUSINESS_SLUG

set -euo pipefail

cd /home/ubuntu/task-manager

# Prompts need an interactive terminal; without one (for example, from a
# script) only non-interactive commands such as list-users can work.
if [[ -t 0 ]]; then
  tty_option=()
else
  tty_option=(-T)
fi

# The SSM plugin sends ^H for Backspace, but the container's terminal erases on
# ^?, so set ^H as the erase key for this session's terminal only.
# Arguments are passed as "$@", never pasted into the command string.
exec docker compose --env-file .env.prod -f compose.prod.yml \
  exec "${tty_option[@]}" api \
  sh -c 'stty erase "^H" 2>/dev/null || true; exec python -m app.backend.cli "$@"' \
  operator-cli "$@"
