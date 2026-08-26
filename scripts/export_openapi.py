#!/usr/bin/env python3
"""Export the FastAPI OpenAPI document to the web client's committed copy.

The committed spec is what `pnpm --filter @hestia/web gen:api` generates the
typed client from; regenerating after an API change and committing both keeps
the contract and the client in one reviewable diff.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "apps" / "web" / "src" / "lib" / "openapi.json"


def main() -> int:
    sys.path.insert(0, str(REPO / "services" / "api"))
    from hestia_api.app import app

    OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
