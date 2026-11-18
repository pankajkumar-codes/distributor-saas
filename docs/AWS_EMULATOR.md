# Testing against the AWS emulator (R1-M11 prep)

Decision (Pankaj, 2026-11-17): test AWS-facing code against the emulator first. No real AWS actions and no staging spend until he says so.

## What was checked (2026-11-17, from the public repository only)
- `github.com/aws/aws-emulator` exists, is published by AWS, and is licensed CC0-1.0 (its `vendor/` folder is Apache-2.0).
- It is one program that serves an AWS API on HTTPS `127.0.0.1:9297` with a self-signed certificate. You point the SDK at it with environment variables (`AWS_ENDPOINT_URL`). No AWS account is needed. AWS says it is for building and testing only, not production and not security testing.
- Its workspace has one crate per AWS service. Crates exist for the services we use: S3, SQS, Lambda, SES and SES v2, Cognito user pools (`cognitoidentityprovider`), SSM (Parameter Store), Secrets Manager, KMS, and Bedrock runtime.
- **Telemetry is on by default.** Start it with `--telemetry off` (or `EMULATOR_TELEMETRY=off`). The README says it never records request contents, code, credentials or personal data, but we turn it off anyway.
- Linux can build it from source (needs Rust and a lot of disk); Windows and macOS use Docker.

## Not checked yet (do not rely on these)
- That a crate existing means the operations we call work. AWS publishes a fidelity score per service on the repository's releases page; that page and the user guide (docs.aws.amazon.com) were not reachable from this environment. Read the S3, SQS, SES v2, Cognito and SSM scores before trusting a result.
- The Docker image name and how to install a prebuilt package: the user guide was not reachable. Nothing has been installed or started, so **no test has been run against the emulator yet.**
- Presigned POST, KMS default encryption on the bucket, Lambda container behavior, and Cognito token claims (`origin_jti`, see OPEN_QUESTIONS) are exactly the kind of detail an emulator may not match. A pass here does not replace the first run on real staging.

## How to use it
1. Start the emulator on this computer with telemetry off.
2. `make emulator-smoke` with `AWS_ENDPOINT_URL=https://127.0.0.1:9297`, `AWS_CA_BUNDLE` set to its certificate, and dummy credentials. It runs our real adapters (`S3ObjectStore`, `SqsQueue`, `SesSender`) and prints each step. It refuses any endpoint that is not on this computer, so it cannot reach real AWS.
3. It is optional and is not in CI. If the smoke test proves useful, adding the emulator as a CI service is a separate small change.

## What stays on real AWS (release or staging checks)
The things listed under "Facts not verified yet" in OPEN_QUESTIONS (Cognito endpoint and tokens, RDS grants, KMS behavior, WeasyPrint arm64 timing) need the real service. They wait for Pankaj's approval of staging spend.

## Update 2026-11-18: cloned and read, still not run
What was done on 2026-11-18 (still no test has run against the emulator):
- The repository was cloned read-only (1.6 GB, shallow). It has about 438 service crates. Crates exist for everything our code and Terraform use: S3, SQS, SSM, SES v2, Cognito user pools, Lambda, KMS, IAM, STS, CloudWatch Logs, EventBridge, SNS, API Gateway v2, Secrets Manager. Not looked for or not confirmed: RDS behavior, CloudFront, Budgets, VPC and EC2 networking, CloudWatch alarms. A crate existing does not mean our calls work (see "Not checked yet" above).
- It cannot be run on the build machine used here, for three reasons: no Docker daemon, no prebuilt package we could find, and a full source build wants about 100 GB of free disk (the README's figure) while the machine had about 27 GB and 4 cores.
- The planned workaround is a **throwaway scratch build** of the router crate trimmed to the 14 services above, in a clone outside our repository, never pushed. The edit of the scratch clone worked; the `cargo build` of it was refused by the session's permission check, twice, so it was not run. It needs the session owner's approval. Nothing was worked around.
- Terraform: the CLI and the AWS provider zip can be downloaded from releases.hashicorp.com, but registry.terraform.io is blocked from here. Installing the provider from a local mirror to get around that block was also refused, so no `terraform init`, `validate`, `plan` or `apply` has run either. CI's `terraform` job already runs `fmt -check` and `init -backend=false` plus `validate` on bootstrap, staging and prod, so the files are syntax-checked there; a `plan` or `apply` has never run.

## What the emulator is expected to cover, and what it is not (a plan, not a result)
| Area | Plan with the emulator | Stays on real AWS |
|---|---|---|
| S3 adapter, presigned links, exports area | `make emulator-smoke` | Presigned POST limits, KMS default encryption, lifecycle rules |
| SQS: one plain queue, send and receive one message | `make emulator-smoke` does this today. A dead-letter queue, the redrive after repeated failures and the render queue's message shape are not tested yet and would be added to the smoke script | Lambda event source mapping timing and batching, DLQ alarm behavior |
| SES v2 sender | `make emulator-smoke` | Domain verification, sandbox exit, deliverability |
| Parameter Store (SSM) reads | smoke script, to be added | Parameter policies, SecureString KMS behavior |
| Terraform plan/apply against the emulator endpoint | Needs the provider installed and the emulator running | Everything that depends on VPC, RDS, CloudFront, Budgets |
| Lambda packages and the PDF renderer | The renderer zip is built and checked by `make renderer-zip` and `scripts/check_renderer_zip.py` (size, architecture, libraries, optional `--smoke`). There is no script that runs a Lambda function against the emulator's Lambda crate; one would have to be written | Memory, timeout, arm64 and WeasyPrint timing |
| Cognito sign-in and tokens | Only if the user pool crate returns the claims we read | `origin_jti`, hosted behavior, email delivery |
| Postgres (RDS) | Local Postgres, as CI does | RDS grants, parameter groups, backups and the restore test |

A pass on any row is a pass against the emulator only.

## If the emulator stays blocked: the nearest fallback
The Python library `moto` mocks S3, SQS, SES v2, SSM, KMS and Secrets Manager and installs from PyPI. It would cover the adapter smoke tests only. It does not run Terraform, Lambda containers or Cognito token behavior, and its behavior is a community approximation. It is a fallback, not a decision; nothing has been installed.
