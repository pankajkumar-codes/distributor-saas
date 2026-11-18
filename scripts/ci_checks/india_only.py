#!/usr/bin/env python3
"""Tenant data stays in India (D-094): fail if the code or infrastructure names a region outside Mumbai
(ap-south-1) and Hyderabad (ap-south-2), or builds something that copies data across regions.

Looks at every tracked file under the roots below. Two kinds of finding:
  * a region name that is not ap-south-1 or ap-south-2 (an exception needs a reason in ALLOWED);
  * a construct that moves data between regions: multi-region keys, S3 or RDS replication, AWS Backup,
    cross-region snapshot copy, or a cross-region or global model inference profile id.

    python scripts/ci_checks/india_only.py
"""

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("infra", ".github", "scripts", "app/src", "libs", "web/src", "web/nginx", "demo", "docker-compose", "Dockerfile")
SKIP_PARTS = ("tests/ci_fixtures", "tests/tools")  # the planted files and this check's own tests
SKIP_FILES = {"scripts/ci_checks/india_only.py"}
TEXT_SUFFIXES = {".tf", ".py", ".yaml", ".yml", ".sh", ".json", ".ts", ".tsx", ".toml", ".conf", ".md", ".sql", ".hcl"}
IN_INDIA = {"ap-south-1", "ap-south-2"}

REGION = re.compile(r"\b(?:us|eu|ap|sa|ca|me|af|il|mx|cn)-(?:gov-)?(?:east|west|north|south|central|southeast|northeast|northwest|southwest)-\d\b")
FORBIDDEN = {
    "multi-region key": re.compile(r"multi_region\s*=\s*true"),
    "S3 replication": re.compile(r"aws_s3_bucket_replication_configuration"),
    "RDS replica or cross-region backup": re.compile(r"replicate_source_db|aws_db_instance_automated_backups_replication|aws_rds_cluster_snapshot_copy"),
    "AWS Backup": re.compile(r"\baws_backup_"),
    "cross-region copy": re.compile(r"\bsource_region\b|aws_kms_replica_key|\bkms_key_replica|CopySnapshot|copy_snapshot"),
    "cross-region or global inference profile": re.compile(r"""["'](?:us|eu|apac|global|jp|au)\.anthropic\.|["']global\.[a-z]"""),
}

# (path, region name) -> why this one is allowed. Nothing here holds tenant data.
ALLOWED = {
    ("infra/modules/cdn/main.tf", "us-east-1"): "CloudFront only accepts its public TLS certificate from us-east-1 (D-094, the one deliberate non-India resource)",
    ("libs/platform_common/platform_common/aws.py", "us-east-1"): "a comment: S3 only redirects a browser upload from buckets outside us-east-1",
    ("libs/platform_common/tests/test_s3_presigned_post_host.py", "us-east-1"): "the same remark in the test's docstring",
}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    names = []
    for name in out.splitlines():
        if name in SKIP_FILES or any(part in name for part in SKIP_PARTS):
            continue
        if not any(name == r or name.startswith(r + "/") or (name.startswith(r) and "/" not in name) for r in ROOTS):
            continue
        path = PurePosixPath(name)
        if path.suffix in TEXT_SUFFIXES or path.name.startswith("Dockerfile") or path.name.startswith("docker-compose"):
            names.append(name)
    return names


def check(root: Path, names: list[str] | None = None, allowed: dict | None = None) -> list[tuple[str, int, str]]:
    """(file, line, what) for each finding. `allowed` defaults to ALLOWED."""
    allowed = ALLOWED if allowed is None else allowed
    found = []
    for name in names if names is not None else [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]:
        try:
            lines = (root / name).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            for region in REGION.findall(line):
                if region not in IN_INDIA and (name, region) not in allowed:
                    found.append((name, n, f"region {region} is outside India"))
            for what, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    found.append((name, n, what))
    return found


def unused_allowances(root: Path, names: list[str]) -> list[tuple[str, str]]:
    seen = set()
    for name in names:
        text = (root / name).read_text(encoding="utf-8", errors="ignore")
        seen.update((name, r) for r in REGION.findall(text))
    return [k for k in ALLOWED if k not in seen]


def main() -> int:
    names = tracked()
    problems = check(ROOT, names)
    stale = unused_allowances(ROOT, names)
    for name, n, what in problems:
        print(f"{name}:{n}: {what}")
    for name, region in stale:
        print(f"{name}: allowance for {region} is not needed any more; remove it from ALLOWED")
    print(f"{len(names)} files scanned, {len(problems)} findings, {len(stale)} stale allowances")
    return 1 if problems or stale else 0


if __name__ == "__main__":
    sys.exit(main())
