#!/bin/sh
# Run traceviz as the unprivileged "traceviz" user (mtr-packet is setuid, so probing still works).
# Started as root (the default): first hand any root-owned files in the data volume to that user,
# e.g. ones written by older images, so the database stays writable.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$TRACEVIZ_DATA_DIR"
  # Best effort: a read-only mount, NFS root_squash etc. can refuse chown. Don't block startup;
  # traceviz reports its own error if it really can't write. -h: never follow symlinks.
  find "$TRACEVIZ_DATA_DIR" -user 0 -exec chown -h traceviz:traceviz {} + 2>/dev/null \
    || echo "warning: could not take ownership of files in $TRACEVIZ_DATA_DIR" >&2
  exec setpriv --reuid=traceviz --regid=traceviz --init-groups -- traceviz "$@"
fi
exec traceviz "$@"
