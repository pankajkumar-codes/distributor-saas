import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "policy.toml"


@dataclass(frozen=True)
class RoleTemplate:
    name: str
    department: str
    seniority: int
    capabilities: tuple[str, ...]
    max_instances: int
    cost_tier: int
    coding: bool = False
    template_only: bool = False


@dataclass(frozen=True)
class Policy:
    raw: dict
    roles: dict[str, RoleTemplate] = field(default_factory=dict)

    @property
    def review(self) -> dict:
        return self.raw["review"]

    @property
    def review_mode(self) -> str:
        return self.review["mode"]

    @property
    def block_on_nonblocking(self) -> bool:
        return bool(self.review[self.review_mode].get("block_on_nonblocking_findings", False))

    @property
    def execution(self) -> dict:
        return self.raw["execution"]

    @property
    def workforce(self) -> dict:
        return self.raw["workforce"]

    @property
    def monthly_limit(self) -> Decimal | None:
        limit = Decimal(self.raw["budget"]["monthly_limit_usd"])
        return limit if limit > 0 else None

    @property
    def default_execution_budget(self) -> Decimal | None:
        b = Decimal(self.raw["budget"]["default_execution_budget_usd"])
        return b if b > 0 else None

    def tags_for_paths(self, paths: list[str]) -> set[str]:
        tags: set[str] = set()
        for path in paths:
            for marker, marker_tags in self.review["path_tags"].items():
                if path.startswith(marker) or f"/{marker}" in f"/{path}":
                    tags.update(marker_tags)
        return tags

    def with_overrides(self, **sections) -> "Policy":
        """A copy with some keys replaced, e.g. with_overrides(review={"mode": "all_roles"})."""
        raw = {k: dict(v) if isinstance(v, dict) else v for k, v in self.raw.items()}
        for section, values in sections.items():
            raw[section] = {**raw.get(section, {}), **values}
        return from_dict(raw)


def from_dict(raw: dict) -> Policy:
    roles = {
        name: RoleTemplate(
            name=name,
            department=r["department"],
            seniority=r["seniority"],
            capabilities=tuple(r["capabilities"]),
            max_instances=r["max_instances"],
            cost_tier=r["cost_tier"],
            coding=r.get("coding", False),
            template_only=r.get("template_only", False),
        )
        for name, r in raw["roles"].items()
    }
    if raw["review"]["mode"] not in ("seniority", "all_roles"):
        raise ValueError(f"unknown review mode {raw['review']['mode']!r}")
    return Policy(raw=raw, roles=roles)


def load(path: Path | str = DEFAULT_POLICY) -> Policy:
    with open(path, "rb") as f:
        return from_dict(tomllib.load(f))
