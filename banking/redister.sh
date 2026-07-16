#!/usr/bin/env bash
set -euo pipefail
: "${ENABLEBANKING_REGISTER_TOKEN:?Set ENABLEBANKING_REGISTER_TOKEN before running this script}"

curl -X POST -H "Authorization: Bearer ${ENABLEBANKING_REGISTER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"test\",\"certificate\":\"$(cat public.crt | tr '\n' '|' | sed 's/|/\\n/g')\",\"environment\":\"SANDBOX\",\"redirect_urls\":[\"https://localhost:8004/\"]}" \
  https://enablebanking.com/api/applications
