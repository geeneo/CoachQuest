#!/usr/bin/env bash
# The GitHub checks of a commit: prints success, failure, pending or unknown (and why, on stderr).
# Usage: bash scripts/ci-status.sh <commit sha>
# A private repository needs GITHUB_TOKEN in .env (a fine-grained token with read access to "Checks"
# or "Commit statuses" and "Contents" on this repository).
set -uo pipefail
sha=${1:?commit}
url=$(git remote get-url origin 2>/dev/null)
repo=$(sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##' <<<"$url")
auth=()
token=${GITHUB_TOKEN:-${GIT_TOKEN:-}}  # the git access token (below) does if it may read checks
[[ -n $token ]] && auth=(-H "Authorization: Bearer $token")
body=$(curl -fsS --max-time 20 "${auth[@]}" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$repo/commits/$sha/check-runs?per_page=100" 2>/dev/null) || {
  echo "unknown"
  echo "GitHub didn't answer for $repo@$sha (a private repository needs GITHUB_TOKEN in .env)" >&2
  exit 0
}
python3 - "$body" <<'PY'
import json, sys
runs = json.loads(sys.argv[1]).get("check_runs", [])
if not runs:
    print("pending"); print("no checks have started for this commit yet", file=sys.stderr)
elif any(r["status"] != "completed" for r in runs):
    print("pending"); print("checks still running", file=sys.stderr)
elif all(r["conclusion"] in ("success", "skipped", "neutral") for r in runs):
    print("success")
else:
    bad = [r["name"] for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
    print("failure"); print("failed: " + ", ".join(bad), file=sys.stderr)
PY
