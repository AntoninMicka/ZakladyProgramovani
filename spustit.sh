#!/usr/bin/env bash
# Rozcestník funguje i při spuštění z jiného pracovního adresáře.
set -euo pipefail
adresar=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$adresar/spustit.py" "$@"
