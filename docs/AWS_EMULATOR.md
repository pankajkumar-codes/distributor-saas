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
