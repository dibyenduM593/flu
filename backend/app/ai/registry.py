"""Prompt registry: app/ai/prompts/<name>_v<n>.md with a small YAML-style header.

The header names the model role (main | fast), effort, eval set and eval status. Outside dev mode
the registry refuses a version whose eval has not passed (PRD: no new version without an eval run).
The bundled v1 prompts have `eval_status: not_run` because the labelled eval sets do not exist yet."""
import re
from functools import lru_cache
from pathlib import Path

from ..config import settings

PROMPTS = Path(__file__).parent / "prompts"


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    header = {k.strip(): v.strip() for k, v in (line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)}
    return {"name": path.stem.rsplit("_v", 1)[0], "version": path.stem, "header": header, "body": m.group(2).strip()}


@lru_cache
def load(name: str) -> dict:
    versions = sorted(PROMPTS.glob(f"{name}_v*.md"), key=lambda p: int(re.search(r"_v(\d+)$", p.stem).group(1)))
    for path in reversed(versions):
        p = _parse(path)
        if p["header"].get("eval_status") == "passed" or settings.dev_mode:
            return p
    raise LookupError(f"no evaluated prompt version for {name}")


def all_prompts() -> list[dict]:
    return [{k: v for k, v in _parse(p).items() if k != "body"} for p in sorted(PROMPTS.glob("*_v*.md"))]
