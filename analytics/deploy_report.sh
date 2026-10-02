#!/bin/bash
# Deploy report.html to Firebase Hosting (https://<projectId>.web.app). The sign-in API key is fetched from Google
# Cloud at deploy time and only goes into the deployed copy, never into the repo.
#   ./deploy_report.sh            (needs the Firebase CLI and gcloud, signed in to an account that owns the project)
# The key used is the one named "$KEY_NAME", restricted to the Hosting domains and the sign-in + Firestore APIs.
set -euo pipefail
cd "$(dirname "$0")"
KEY_NAME="${KEY_NAME:-Analytics report (restricted)}"
project=$(python3 -c "import json;print(json.load(open('config.json'))['projectId'])")
key_id=$(gcloud services api-keys list --project "$project" --filter="displayName='$KEY_NAME'" --format="value(name)" | head -1)
[ -n "$key_id" ] || { echo "No API key named '$KEY_NAME' in $project"; exit 1; }
tmp=$(mktemp -d); mkdir -p "$tmp/public"
cp report.html "$tmp/public/index.html"
gcloud services api-keys get-key-string "$key_id" --format="value(keyString)" | python3 -c "
import json,sys; c=json.load(open('config.json')); c['apiKey']=sys.stdin.read().strip(); c.pop('reportUrl',None)
json.dump(c,open('$tmp/public/config.json','w'))"
cat > "$tmp/firebase.json" <<JSON
{ "hosting": { "public": "public", "headers": [ { "source": "**", "headers": [
  { "key": "Cache-Control", "value": "no-store" }, { "key": "X-Robots-Tag", "value": "noindex" },
  { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" } ] } ] } }
JSON
(cd "$tmp" && firebase deploy --only hosting --project "$project" --non-interactive)
rm -rf "$tmp"
