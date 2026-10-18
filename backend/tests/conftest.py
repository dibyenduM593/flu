import os
import sys
from pathlib import Path

# Each test session gets its own SQLite file and no background worker.
DB = Path(__file__).parent / "_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["FLU_WORKER"] = "0"
os.environ["FLU_AI_MODE"] = "heuristic"
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def seeded():
    from app import seed
    seed.main()
    yield
    from app.db import engine
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB) + suffix)
        if p.exists():
            p.unlink()


@pytest.fixture
def db(seeded):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.close()
