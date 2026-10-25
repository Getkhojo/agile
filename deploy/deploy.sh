#!/usr/bin/env bash
# Pull the latest site + backend from git and restart services.
# Usage on the server: sudo bash /var/www/agiletechexpert/deploy/deploy.sh
set -euo pipefail

SITE_DIR="/var/www/agiletechexpert"
BRANCH="main"

cd "$SITE_DIR"
git fetch --all --prune
git reset --hard "origin/$BRANCH"
chown -R www-data:www-data "$SITE_DIR/public"
chown -R www-data:www-data "$SITE_DIR/backend"

# Backend deps (only if the venv exists; first-time setup is in docs/BACKEND.md)
if [ -x "$SITE_DIR/backend/venv/bin/pip" ]; then
    "$SITE_DIR/backend/venv/bin/pip" install -q -r "$SITE_DIR/backend/requirements.txt" || true
    systemctl restart agile-api || true
fi

nginx -t
systemctl reload nginx
echo "Deployed commit: $(git rev-parse --short HEAD)"
