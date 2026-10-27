"""CI never reaches AWS (D-039): the app and worker load without boto3, and the AWS
settings are refused anywhere but Lambda."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import runtime

ROOT = Path(__file__).resolve().parents[2]


def test_the_app_and_worker_load_without_boto3():
    env = {k: v for k, v in os.environ.items() if k not in runtime.AWS_SETTINGS and k != "AWS_LAMBDA_FUNCTION_NAME"}
    env["PLATFORM_ENV"] = "test"
    code = "import sys, app.api, app.worker; print(sorted(m for m in sys.modules if m.split('.')[0] in ('boto3', 'botocore')))"
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT / "app", capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "[]"


@pytest.mark.parametrize("name", runtime.AWS_SETTINGS)
def test_aws_settings_are_refused_off_lambda(monkeypatch, name):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv(name, "set-by-mistake")
    with pytest.raises(RuntimeError, match="Lambda only"):
        runtime.configure()
