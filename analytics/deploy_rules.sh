#!/bin/bash
# Deploy firestore.rules with the owner email(s) filled in, so the address never has to be committed.
#   ./deploy_rules.sh you@example.com [more@example.com ...]
# The project comes from config.json (projectId). Needs the Firebase CLI, signed in to an account that owns it.
set -euo pipefail
cd "$(dirname "$0")"
[ $# -ge 1 ] || { echo "usage: $0 owner@email [owner2@email ...]"; exit 1; }
project=$(python3 -c "import json;print(json.load(open('config.json'))['projectId'])")
owners=$(printf "'%s', " "$@"); owners=${owners%, }
tmp=$(mktemp -d)
sed "s/'OWNER_EMAIL'/$owners/" firestore.rules > "$tmp/firestore.rules"
printf '{ "firestore": { "rules": "firestore.rules" } }\n' > "$tmp/firebase.json"
(cd "$tmp" && firebase deploy --only firestore:rules --project "$project" --non-interactive)
rm -rf "$tmp"
