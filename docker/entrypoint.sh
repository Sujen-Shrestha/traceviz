#!/bin/sh
# Run traceviz as the unprivileged "traceviz" user (mtr-packet is setuid, so probing still works).
# Started as root (the default): first hand any root-owned files in the data volume to that user,
# e.g. ones written by older images, so the database stays writable.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$TRACEVIZ_DATA_DIR"
  find "$TRACEVIZ_DATA_DIR" -user 0 -exec chown traceviz:traceviz {} +
  exec setpriv --reuid=traceviz --regid=traceviz --init-groups -- traceviz "$@"
fi
exec traceviz "$@"
