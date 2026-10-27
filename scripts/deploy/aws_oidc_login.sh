#!/usr/bin/env bash
# Signs the job in to AWS as AWS_DEPLOY_ROLE_ARN with GitHub's OIDC token (TD-20), using
# only the preinstalled AWS CLI. The role's trust policy accepts this repository's
# `staging` environment only (docs/DEPLOYMENT.md). Credentials last an hour and are
# masked in the log.
set -euo pipefail
: "${AWS_DEPLOY_ROLE_ARN:?}" "${ACTIONS_ID_TOKEN_REQUEST_URL:?needs permissions: id-token: write}"
token=$(curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -r .value)
creds=$(aws sts assume-role-with-web-identity --role-arn "$AWS_DEPLOY_ROLE_ARN" \
  --role-session-name "github-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" --web-identity-token "$token" \
  --duration-seconds 3600 --query Credentials --output json)
for pair in AWS_ACCESS_KEY_ID:AccessKeyId AWS_SECRET_ACCESS_KEY:SecretAccessKey AWS_SESSION_TOKEN:SessionToken; do
  value=$(jq -r ".${pair#*:}" <<< "$creds")
  echo "::add-mask::$value"
  echo "${pair%%:*}=$value" >> "$GITHUB_ENV"
done
aws_account=$(AWS_ACCESS_KEY_ID=$(jq -r .AccessKeyId <<< "$creds") AWS_SECRET_ACCESS_KEY=$(jq -r .SecretAccessKey <<< "$creds") \
  AWS_SESSION_TOKEN=$(jq -r .SessionToken <<< "$creds") aws sts get-caller-identity --query Account --output text)
echo "signed in to account ending ${aws_account: -4}"
