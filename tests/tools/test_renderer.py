"""The renderer's locks and Terraform (TD-9, D-042), read as text. The zip itself is
built and checked by the CI job `renderer` (scripts/check_renderer_zip.py)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "renderer"
STACK = (ROOT / "infra" / "modules" / "stack" / "main.tf").read_text()
SHA256 = re.compile(r"[0-9a-f]{64}")


def _rows(name):
    return [line.split() for line in (RENDERER / name).read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def test_every_wheel_is_pinned_and_hashed():
    text = (RENDERER / "requirements.txt").read_text()
    entries = [e for e in re.split(r"\n(?=\S)", text) if e and not e.startswith("#")]
    assert any(e.startswith("weasyprint==") for e in entries)
    for entry in entries:
        assert re.match(r"[a-z0-9-]+==\S+ \\", entry), entry
        assert re.findall(r"--hash=sha256:([0-9a-f]{64})", entry), entry


def test_native_packages_come_from_conda_forge_with_a_hash_for_both_platforms():
    rows = _rows("natives.lock")
    for subdir, name, version, build, sha256, url, licence in rows:
        assert subdir in ("linux-aarch64", "linux-64")
        assert SHA256.fullmatch(sha256), name
        assert url == f"https://conda.anaconda.org/conda-forge/{subdir}/{name}-{version}-{build}.conda"
        assert licence
    by_platform = {s: {r[1] for r in rows if r[0] == s} for s in ("linux-aarch64", "linux-64")}
    assert by_platform["linux-aarch64"] == by_platform["linux-64"]
    assert {"libpango", "libharfbuzz", "fontconfig", "libglib"} <= by_platform["linux-aarch64"]


def test_fonts_are_pinned_to_a_commit_and_carry_the_ofl():
    rows = _rows("fonts.lock")
    names = {name for _, _, name in rows}
    assert {"NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSansDevanagari-Regular.ttf",
            "NotoSansDevanagari-Bold.ttf", "OFL.txt"} == names
    for sha256, url, _ in rows:
        assert SHA256.fullmatch(sha256)
        assert re.match(r"https://raw\.githubusercontent\.com/notofonts/notofonts\.github\.io/[0-9a-f]{40}/", url), url


def test_the_renderer_function_runs_its_own_zip_with_no_database_or_vpc():
    module = re.search(r'module "renderer" \{(.*?)\n\}', STACK, re.S).group(1)
    assert re.search(r'package_path\s*=\s*"\$\{var\.packages_dir\}/renderer\.zip"', module)
    assert re.search(r'handler\s*=\s*"renderer\.handler\.handler"', module)
    assert re.search(r"memory_mb\s*=\s*1024\b", module)
    for absent in ("vpc", "db_user", "reserved_concurrency"):
        assert not re.search(rf"^\s*{absent}\s*=", module, re.M), f"renderer should have no {absent} yet"
    assert (RENDERER / "renderer" / "handler.py").read_text().count("def handler(") == 1


def test_the_renderer_is_fed_by_the_render_queue_whose_dlq_has_an_alarm():
    module = re.search(r'module "renderer" \{(.*?)\n\}', STACK, re.S).group(1)
    assert re.search(r"sqs_trigger\s*=\s*\{\s*arn\s*=\s*module\.render\.arn,\s*batch_size\s*=\s*1\s*\}", module)
    queue = re.search(r'module "render" \{(.*?)\n\}', STACK, re.S).group(1)
    assert re.search(r'source\s*=\s*"\.\./queue"', queue)
    assert re.search(r"visibility_timeout_seconds\s*=\s*360\b", queue)  # 6 x the renderer's 60 s
    assert re.search(r"render\s*=\s*module\.render\.dlq_name", STACK)


def test_the_renderer_reads_only_render_input_and_decrypts_only_through_s3():
    """D-042 (EM): GetObject on render-input/b/* and kms:Decrypt via S3, nothing else
    until S4 adds the documents/b/* write."""
    module = re.search(r'module "renderer" \{(.*?)\n\}', STACK, re.S).group(1)
    policy = re.search(r"policy_statements = \[(.*?)\n  \]", module, re.S).group(1)
    assert re.findall(r'Action\s*=\s*\[([^\]]*)\]', policy) == ['"s3:GetObject"', '"kms:Decrypt"']
    resources = re.findall(r'Resource\s*=\s*\[([^\]]*)\]', policy)
    assert resources == ['"${module.storage.bucket_arn}/render-input/b/*"', "module.storage.kms_key_arn"]
    assert '"kms:ViaService" = "s3.${data.aws_region.current.name}.amazonaws.com"' in policy
    assert "*" not in policy.replace("render-input/b/*", "")


def test_no_other_function_ships_the_renderer_zip():
    assert STACK.count('/renderer.zip"') == 1
