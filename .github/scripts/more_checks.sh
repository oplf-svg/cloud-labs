#!/usr/bin/env bash
# Runs checks.sh of every folder that has one. ci.yml calls this after the blocked terms, with no rights
# but to read the code.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# bash reads a script as it goes, and a check could write into this one. So all of it is read before the first one runs.
{

# A branch that must not be merged yet has a file HOLD: one line that says why, and until when. It is looked for before any check
# runs, because a check could move it, and said in the end, so that everything else is seen. A link is not followed, because the
# log is public.
waits=no
why=""
if [ -f HOLD ] && [ ! -L HOLD ]; then
  waits=yes
  why="$(head -n 1 HOLD)"
elif [ -e HOLD ] || [ -L HOLD ]; then
  waits=yes
  why="HOLD is not a plain file."
fi

found=0
for checks in */checks.sh; do
  [ -e "$checks" ] || continue
  found=$((found + 1))
  echo "== $checks"
  bash "$checks"
done
echo "$found folder(s) checked"

if [ "$waits" = yes ]; then
  echo "Not to be merged yet: $why"
  exit 1
fi
exit 0
}
