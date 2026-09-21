#!/usr/bin/env bash
# Smoke test a running instance: wait for the page, verify the bourbon sample, expect Pass.
# Usage: scripts/smoke_test.sh http://localhost:8000
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
SAMPLE="$(dirname "$0")/../samples/bourbon.png"
WAIT_S="${SMOKE_WAIT_S:-120}"
MAX_S="${SMOKE_MAX_S:-5}"

echo "Waiting up to ${WAIT_S}s for ${BASE_URL}/ ..."
for ((i = 0; i < WAIT_S; i += 3)); do
  if curl -fsS "${BASE_URL}/" >/dev/null 2>&1; then
    break
  fi
  sleep 3
done
curl -fsS "${BASE_URL}/" >/dev/null || { echo "Service never became healthy"; exit 1; }

echo "Verifying sample label ..."
body="$(curl -fsS --max-time 30 -w '\n%{time_total}' \
  -F "image=@${SAMPLE};type=image/png" \
  -F "brand_name=OLD TOM DISTILLERY" \
  -F "class_type=Kentucky Straight Bourbon Whiskey" \
  -F "alcohol_content=45%" \
  -F "net_contents=750 mL" \
  -F "bottler=Bottled by Old Tom Distillery, Bardstown, KY" \
  "${BASE_URL}/verify")"

elapsed="$(tail -n1 <<<"$body")"
html="$(sed '$d' <<<"$body")"
overall="$(python3 -c 'import sys; html=sys.stdin.read(); start=html.find("<h2>"); end=html.find("</h2>", start); print(html[start + 4:end].strip() if start != -1 else "")' <<<"$html")"

echo "overall=${overall} time=${elapsed}s"
[[ "$overall" == "Pass" ]] || { echo "Expected Pass"; echo "$html"; exit 1; }
python3 -c "import sys; sys.exit(0 if float('$elapsed') <= float('$MAX_S') else 1)" \
  || { echo "Too slow: ${elapsed}s > ${MAX_S}s"; exit 1; }
