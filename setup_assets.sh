#!/bin/bash
# Ensure india_compliance CSS/JS assets are symlinked into sites/assets
ASSETS_DIR="/home/frappe/frappe-bench/sites/assets/india_compliance"
PUBLIC_DIR="/home/frappe/frappe-bench/apps/india_compliance/india_compliance/public"

mkdir -p "$ASSETS_DIR"

# Only create if source exists and symlink is missing/broken
if [ -d "$PUBLIC_DIR/css" ]; then
  ln -sfn "$PUBLIC_DIR/css" "$ASSETS_DIR/css"
fi
if [ -d "$PUBLIC_DIR/js" ]; then
  ln -sfn "$PUBLIC_DIR/js" "$ASSETS_DIR/js"
fi

# Hand off to the original command
exec "$@"
