"""The renderer's locks and Terraform (TD-9, D-042), read as text. The zip itself is
built and checked by the CI job `renderer` (scripts/check_renderer_zip.py)."""

import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "renderer"
sys.path.insert(0, str(RENDERER))
from renderer import inputs  # noqa: E402  imports neither boto3 nor weasyprint
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
    assert re.search(r"sqs_trigger\s*=\s*\{\s*arn\s*=\s*module\.render\.arn,\s*batch_size\s*=\s*1,"
                     r"\s*maximum_concurrency\s*=\s*var\.render_max_concurrency\s*\}", module)
    queue = re.search(r'module "render" \{(.*?)\n\}', STACK, re.S).group(1)
    assert re.search(r'source\s*=\s*"\.\./queue"', queue)
    assert re.search(r"visibility_timeout_seconds\s*=\s*360\b", queue)  # 6 x the renderer's 60 s
    assert re.search(r"render\s*=\s*module\.render\.dlq_name", STACK)


def _statements(block: str) -> list[tuple[str, str]]:
    """(actions, resources) of each statement, as written."""
    return list(zip(re.findall(r"Action\s*=\s*\[([^\]]*)\]", block), re.findall(r"Resource\s*=\s*\[([^\]]*)\]", block),
                    strict=True))


def test_the_renderer_reads_and_deletes_inputs_writes_documents_and_uses_the_key_only_through_s3():
    """D-042 (EM): nothing beyond these, and no broader wildcard."""
    module = re.search(r'module "renderer" \{(.*?)\n\}', STACK, re.S).group(1)
    policy = re.search(r"policy_statements = \[(.*?)\n  \]", module, re.S).group(1)
    bucket = "${module.storage.bucket_arn}"
    assert _statements(policy) == [
        ('"s3:GetObject", "s3:DeleteObject"', f'"{bucket}/render-input/b/*"'),
        ('"s3:PutObject"', f'"{bucket}/documents/b/*"'),
        ('"s3:ListBucket"', "module.storage.bucket_arn"),
        ('"kms:Decrypt", "kms:GenerateDataKey"', "module.storage.kms_key_arn"),
    ]
    assert '"s3:prefix" = ["render-input/b/*"]' in policy
    assert '"kms:ViaService" = "s3.${data.aws_region.current.name}.amazonaws.com"' in policy
    assert "*" not in policy.replace("render-input/b/*", "").replace("documents/b/*", "")
    assert re.search(r"environment\s*=\s*\{\s*OBJECTS_BUCKET\s*=\s*module\.storage\.bucket\s*\}", module)


def test_the_worker_may_only_put_render_inputs_and_send_to_the_render_queue():
    block = re.search(r"worker_render_statements = \[(.*?)\n  \]", STACK, re.S).group(1)
    assert _statements(block) == [
        ('"s3:PutObject"', '"${module.storage.bucket_arn}/render-input/b/*"'),
        ('"sqs:SendMessage"', "module.render.arn"),
    ]
    worker = re.search(r'module "worker" \{(.*?)\n\}', STACK, re.S).group(1)
    assert "local.worker_render_statements" in worker
    assert STACK.count("local.worker_render_statements") == 1  # the API gets none of it
    assert "RENDER_QUEUE_URL = module.render.url" in STACK
    api = re.search(r'module "api_function" \{(.*?)\n\}', STACK, re.S).group(1)
    assert "worker_env" not in api


def test_render_input_grants_are_only_the_workers_put_and_the_renderers_read():
    assert re.search(r'app_areas\s*=\s*\[for a in module\.storage\.areas : a if a != "render-input"\]', STACK)
    objects = re.search(r"object_statements = \[(.*?)\n  \]", STACK, re.S).group(1)
    assert "module.storage.areas" not in objects and objects.count("local.app_areas") == 2
    assert STACK.count('/render-input/b/*"') == 2  # the worker's PutObject, the renderer's Get/Delete


def test_no_other_function_ships_the_renderer_zip():
    assert STACK.count('/renderer.zip"') == 1


def test_render_concurrency_is_capped_at_about_five_through_a_stack_variable():
    var = re.search(r'variable "render_max_concurrency" \{(.*?)\n\}', STACK, re.S).group(1)
    assert re.search(r"default\s*=\s*5\b", var)
    function = (ROOT / "infra" / "modules" / "function" / "main.tf").read_text()
    assert "maximum_concurrency = optional(number)" in function
    assert re.search(r'dynamic "scaling_config" \{.*?maximum_concurrency\s*=\s*scaling_config\.value', function, re.S)
    assert ">= 2 && var.sqs_trigger.maximum_concurrency <= 1000" in function


def test_render_input_expires_after_a_day_with_its_old_versions():
    storage = (ROOT / "infra" / "modules" / "storage" / "main.tf").read_text()
    assert re.search(r'^\s*"render-input"\s*=\s*\{\s*expire_days\s*=\s*1,\s*noncurrent_days\s*=\s*1\s*\}', storage, re.M)


class FakeS3:
    def __init__(self):
        self.deleted = []

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)
        return {}


def _key(area="render-input", name="input.json"):
    return f"{area}/b/{uuid.uuid4()}/{uuid.uuid4()}/{name}"


def test_delete_after_render_deletes_the_input_and_is_safe_to_repeat():
    s3, key = FakeS3(), _key()
    inputs.delete_after_render(s3, "bucket", key)
    inputs.delete_after_render(s3, "bucket", key)  # a redelivered message
    assert s3.deleted == [{"Bucket": "bucket", "Key": key}] * 2
    assert inputs.business_of(key) == key.split("/")[2]


@pytest.mark.parametrize("key", [
    _key("documents"), _key("uploads"), "render-input/b/x", "render-input/b/../documents/b/x",
    f"render-input/b/{uuid.uuid4()}", f"/render-input/b/{uuid.uuid4()}/{uuid.uuid4()}", "", None, 42,
    f"render-input/b/{uuid.uuid4()}/{uuid.uuid4()}/../../x",
])
def test_delete_after_render_refuses_any_other_key(key):
    s3 = FakeS3()
    with pytest.raises(ValueError):
        inputs.delete_after_render(s3, "bucket", key)
    assert s3.deleted == []
