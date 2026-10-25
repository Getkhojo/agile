#!/usr/bin/env bash
# Pull the latest site from git and reload nginx.
# Usage on the server: sudo bash /var/www/agiletechexpert/deploy/deploy.sh
set -euo pipefail

SITE_DIR="/var/www/agiletechexpert"
BRANCH="main"

cd "$SITE_DIR"
git fetch --all --prune
git reset --hard "origin/$BRANCH"
chown -R www-data:www-data "$SITE_DIR/public"
nginx -t
systemctl reload nginx
echo "Deployed commit: $(git rev-parse --short HEAD)"
