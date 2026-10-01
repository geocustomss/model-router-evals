#!/usr/bin/env bash
# Run with: bash demo.sh
# Recording helper: prints each command, then runs it. Use PAUSE=0 for an instant run.
set -e
PAUSE=${PAUSE:-1.5}
run() { echo; echo "\$ $*"; sleep "$PAUSE"; "$@"; sleep "$PAUSE"; }
run python -m unittest discover -s tests
run python -m router eval --targets mock/mock-small mock/mock-large --write-routes out/routes.generated.json
run cat out/routes.generated.json
