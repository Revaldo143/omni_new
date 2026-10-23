#!/bin/sh
# Maps the persistent /state volume into the paths the code writes next to itself.
set -eu

mkdir -p /state

# Files: create in volume if missing, then symlink into /app.
for f in omni_memory.db omni_error.log; do
  [ -e "/state/$f" ] || : > "/state/$f"
  ln -sfn "/state/$f" "/app/$f"
done

# .env: real file stays in the volume (never baked into the image).
if [ -e /state/.env ]; then
  ln -sfn /state/.env /app/.env
fi

# Directories: browser daemon profile + screenshots persist across restarts.
for d in browser_profile browser_shots; do
  mkdir -p "/state/$d"
  ln -sfn "/state/$d" "/app/$d"
done

exec "$@"
