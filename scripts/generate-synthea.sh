#!/usr/bin/env bash
# Generate the synthetic patient population this app is loaded with.
#
# Synthea (MITRE) is a Java program. Rather than require a JDK on the host it
# runs under Docker, and the export lands in ./backend/data/synthea/csv —
# where `app/config.py`'s `synthea_csv_dir` expects it, and where
# docker-compose.prod.yml bind-mounts it from (`./backend/data:/srv/data:ro`).
# Nothing is checked in: the export is about 380 MB.
#
# The numbers quoted in README.md and docs/DEMO.md — 2,271 patients, 76 on a
# nephrotoxic medication with impaired kidney function, and so on — come from
# Synthea's rolling master build of 2026-08-18 with the default seed below.
# The seed makes a run repeatable against one Synthea build; a newer build
# generates a different, similar-sized population. Set SYNTHEA_JAR_URL to pin
# a specific release. Synthea also writes the patients who died during their
# simulated lifetime, which is why 2000 living patients comes out as about
# 2,271 rows in patients.csv.
#
#   scripts/generate-synthea.sh            # 2000 living patients, seed 20260921
#   scripts/generate-synthea.sh 500        # a smaller cohort
#
# Then:  cd backend && uv run python -m app.seed --from ./data/synthea/csv
set -euo pipefail

POPULATION="${1:-2000}"
SEED="${SYNTHEA_SEED:-20260921}"
JAR_URL="${SYNTHEA_JAR_URL:-https://github.com/synthetichealth/synthea/releases/latest/download/synthea-with-dependencies.jar}"

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/backend/data/synthea"
mkdir -p "$out"

if [ ! -f "$out/synthea.jar" ]; then
  echo "downloading synthea-with-dependencies.jar (~190 MB) ..."
  curl -sL -o "$out/synthea.jar" "$JAR_URL"
fi

echo "generating $POPULATION patients, seed $SEED (this takes a few minutes) ..."
docker run --rm -v "$out:/work" -w /work eclipse-temurin:21-jdk \
  java -jar synthea.jar -p "$POPULATION" -s "$SEED" \
    --exporter.csv.export true \
    --exporter.fhir.export false \
    --exporter.hospital.fhir.export false \
    --exporter.practitioner.fhir.export false

# Synthea writes to output/csv; flatten that so the path in the docs is short.
rm -rf "$out/csv"
mv "$out/output/csv" "$out/csv"
rm -rf "$out/output"

patients=$(( $(wc -l < "$out/csv/patients.csv") - 1 ))
echo "done: $patients patients in $out/csv"
