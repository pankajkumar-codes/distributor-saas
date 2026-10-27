#!/usr/bin/env bash
# Installs the Terraform CLI the CI job validates with, checked against HashiCorp's
# published SHA-256, instead of a third-party setup action (the deploy jobs hold
# id-token: write, so they run no third-party action code).
set -euo pipefail
VERSION=1.10.5
SHA256=0566a24f5332098b15716ebc394be503f4094acba5ba529bf5eb0698ed5e2a90 # linux_amd64, from terraform_1.10.5_SHA256SUMS
dir="$(mktemp -d)"
curl -sSfLo "$dir/terraform.zip" "https://releases.hashicorp.com/terraform/${VERSION}/terraform_${VERSION}_linux_amd64.zip"
echo "$SHA256  $dir/terraform.zip" | sha256sum -c -
unzip -q "$dir/terraform.zip" -d "$dir/bin"
echo "$dir/bin" >> "$GITHUB_PATH"
"$dir/bin/terraform" version
