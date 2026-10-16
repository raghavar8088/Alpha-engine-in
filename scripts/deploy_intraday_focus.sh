#!/usr/bin/env bash
# Scoped rollout: prepare and verify the candidate first; activate in a second call.
set -euo pipefail
phase=${1:?Expected prepare or activate}
release=/home/ubuntu/backups/intraday-focus-20261016
repo=/home/ubuntu/alpha-engine
container=alpha-engine-backend-1
candidate=intraday-focus-backend:20261016
rollback=intraday-focus-backend-rollback:20261016
files=(backend/app/main.py backend/app/services/angel_stream.py
       backend/app/services/intraday_session.py backend/app/services/module_registry.py)
newfiles=(backend/app/services/intraday_focus.py backend/app/services/intraday_focus_rules.py
          backend/app/api/routes/intraday_focus.py backend/tests/intraday_focus/test_focus.py)
mkdir -p "$release"
exec 9>"$release/deploy.lock"
flock -n 9

if [[ "$phase" == prepare ]]; then
  test ! -e "$release/prepared"
  test ! -e "$release/activated"
  # Save the actual running image, not a possibly stale :latest tag.
  docker inspect -f '{{.Image}}' "$container" > "$release/previous-image.txt"
  previous=$(<"$release/previous-image.txt")
  docker tag "$previous" "$rollback"
  mkdir -p "$release/original" "$release/candidate"
  for file in "${files[@]}"; do
    mkdir -p "$release/original/$(dirname "$file")" "$release/candidate/$(dirname "$file")"
    docker cp "$container:/app/$file" "$release/original/$file"
    # Refuse to overwrite server work that is not in the running image.
    cmp "$release/original/$file" "$repo/$file"
    cp "$release/original/$file" "$release/candidate/$file"
  done
  for file in "${newfiles[@]}"; do test ! -e "$repo/$file"; done
  cd "$release/candidate"
  git apply --check "$release/focus-backend.patch"
  git apply "$release/focus-backend.patch"
  docker build --network none --build-arg "BASE_IMAGE=$previous" \
    -f "$release/intraday-focus.Dockerfile" -t "$candidate" .
  docker run --rm --network none "$candidate" python -c \
    'from app.services import intraday_focus as f; from app.api.routes.intraday_focus import router; assert len(f.rules.BY_ID)==5; assert all(s in f.v2.BY_ID for s in f.rules.BY_ID); assert len(router.routes)==1; print("Real dependency imports and five strategy definitions: PASS")'
  touch "$release/prepared"
  echo 'Candidate prepared; production unchanged'
elif [[ "$phase" == activate ]]; then
  test -f "$release/prepared"
  test ! -e "$release/activated"
  previous=$(<"$release/previous-image.txt")
  test "$(docker inspect -f '{{.Image}}' "$container")" = "$previous"
  for file in "${files[@]}"; do cmp "$release/original/$file" "$repo/$file"; done
  for file in "${newfiles[@]}"; do test ! -e "$repo/$file"; done
  rollback_release() {
    trap - ERR
    # Existing source is restored byte-for-byte. New files are retained for diagnosis,
    # but old main.py does not import/start them. No database history is removed.
    restored=true
    for file in "${files[@]}"; do cp "$release/original/$file" "$repo/$file" || restored=false; done
    cd "$repo"
    docker tag "$previous" alpha-engine-backend:latest || restored=false
    docker-compose up -d --no-deps --no-build backend || restored=false
    test "$(docker inspect -f '{{.Image}}' "$container")" = "$previous" || restored=false
    healthy=false
    for attempt in $(seq 1 18); do
      if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null; then healthy=true; break; fi
      sleep 5
    done
    if [[ "$restored" == true && "$healthy" == true ]]; then
      echo 'Release failed; previous backend image/source restored and health verified' >&2
    else
      echo "URGENT: rollback incomplete; inspect $release and container $container" >&2
    fi
    exit 1
  }
  trap rollback_release ERR
  docker tag "$candidate" alpha-engine-backend:latest
  cd "$repo"
  docker-compose up -d --no-deps --no-build backend
  test "$(docker inspect -f '{{.Image}}' "$container")" = "$(docker image inspect -f '{{.Id}}' "$candidate")"
  healthy=false
  for attempt in $(seq 1 18); do
    if curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null; then healthy=true; break; fi
    sleep 5
  done
  test "$healthy" = true
  verified=false
  for attempt in $(seq 1 6); do
    if docker exec -i "$container" python - < "$release/intraday_focus_postflight.py"; then verified=true; break; fi
    sleep 5
  done
  test "$verified" = true
  for file in "${files[@]}" "${newfiles[@]}"; do
    mkdir -p "$repo/$(dirname "$file")"
    cp "$release/candidate/$file" "$repo/$file"
  done
  touch "$release/activated"
  trap - ERR
  echo 'Focus Five backend active; paper accounts verified; rollback image retained'
else
  echo 'Expected prepare or activate' >&2
  exit 2
fi
