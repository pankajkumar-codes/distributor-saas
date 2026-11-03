# The whole environment. envs/staging and envs/prod call this with different sizes.
# Deployables (TD-1, HLD §4): the API and worker Lambdas share app.zip, the mailer runs
# outside the VPC with SES only, the migrator applies migrations as the master, and the
# PDF renderer runs from its own renderer.zip (TD-1(b) amendment, D-042).

terraform {
  required_providers {
    aws    = { source = "hashicorp/aws" }
    random = { source = "hashicorp/random" }
  }
}

variable "env" { type = string }
variable "project" {
  type    = string
  default = "distsaas"
}
variable "web_origins" {
  description = "The app's origin first (APP_ORIGIN), e.g. https://app.example.in. Before a domain exists, the CloudFront URL from the first apply."
  type        = list(string)
}
variable "cdn_aliases" {
  type    = list(string)
  default = []
}
variable "cdn_certificate_arn" {
  type    = string
  default = ""
}
variable "packages_dir" {
  description = "Directory holding app.zip and migrator.zip (scripts/build_lambda.sh) and renderer.zip (scripts/build_renderer.py)"
  type        = string
}
variable "git_sha" {
  description = "Commit being deployed; the migrator records it with each refdata load"
  type        = string
  default     = "unknown"
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}
variable "db_multi_az" {
  type    = bool
  default = false
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "allow_test_password_login" {
  description = "Allow command-line password sign-in for test users. Keep false in prod."
  type        = bool
  default     = false
}
variable "reserved_concurrency" {
  description = "TD-6 caps per function (api 40, worker 10, migrator 1). Null leaves every function unreserved, for accounts whose Lambda concurrency quota is too small to reserve from."
  type = object({
    api      = number
    worker   = number
    mailer   = number
    migrator = number
  })
  default = null
}
variable "render_max_concurrency" {
  description = "Most PDF renders at once, set on the render queue's trigger (D-042). It caps without reserving, so TD-6's quota of 156 is unchanged."
  type        = number
  default     = 5
}
variable "mail_domain" {
  description = "Domain SES sends from, once chosen. Empty: no SES identity, and the mailer may send nothing."
  type        = string
  default     = ""
}
variable "monthly_budget_usd" {
  type = number
}
variable "budget_alert_emails" {
  type = list(string)
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  name     = "${var.project}-${var.env}"
  app_zip  = "${var.packages_dir}/app.zip"
  vpc      = { subnet_ids = module.network.private_subnet_ids, security_group_ids = [module.network.lambda_security_group_id] }
  reserved = var.reserved_concurrency == null ? { api = -1, worker = -1, mailer = -1, migrator = -1 } : var.reserved_concurrency
}

module "network" {
  source = "../network"
  name   = local.name
}

module "database" {
  source              = "../database"
  name                = local.name
  subnet_ids          = module.network.private_subnet_ids
  security_group_id   = module.network.database_security_group_id
  instance_class      = var.db_instance_class
  multi_az            = var.db_multi_az
  deletion_protection = var.deletion_protection
}

module "auth" {
  source               = "../auth"
  name                 = local.name
  allow_password_login = var.allow_test_password_login
  deletion_protection  = var.deletion_protection
}

module "storage" {
  source       = "../storage"
  name         = local.name
  cors_origins = var.web_origins
}

# Jobs (TD-3): visibility = the worker's timeout + 1 minute, the same as its lease (HLD §7).
module "jobs" {
  source                     = "../queue"
  name                       = "${local.name}-jobs"
  visibility_timeout_seconds = 960
}

# Mail (HLD §7, RM2-28): codes expire in 10 minutes, so the queue keeps a message for 15
# and its DLQ for an hour; a code never lives longer than that anywhere.
module "mail" {
  source                     = "../queue"
  name                       = "${local.name}-mail"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 900
  dlq_retention_seconds      = 3600
}

# Keys the app signs with. Generated here and kept in Parameter Store (free) as
# SecureStrings; the API reads them at start-up through the ssm endpoint.
resource "random_password" "app_key" {
  for_each = toset(["code-hmac-key", "rate-hmac-key"])
  length   = 64
  special  = false
}

resource "aws_ssm_parameter" "app_key" {
  for_each = random_password.app_key
  name     = "/${local.name}/app/${each.key}"
  type     = "SecureString"
  value    = each.value.result
}

resource "aws_sesv2_email_identity" "mail" {
  count          = var.mail_domain == "" ? 0 : 1
  email_identity = var.mail_domain
}

locals {
  db_env = {
    PLATFORM_ENV = var.env
    DB_HOST      = module.database.address
    DB_PORT      = tostring(module.database.port)
    DB_NAME      = module.database.db_name
  }
  # Read by nothing in the app: referencing the migrator's invocation is what makes
  # Terraform update the API and worker only after the migrations ran (HLD §11).
  after_migrations = { MIGRATION_RUN = substr(sha256(aws_lambda_invocation.migrate.result), 0, 12) }
  queue_env = {
    JOBS_QUEUE_URL = module.jobs.url
    MAIL_QUEUE_URL = module.mail.url
    UPLOADS_BUCKET = module.storage.bucket
  }
  api_env = merge(local.db_env, local.queue_env, local.after_migrations, {
    AUTH_ISSUER          = module.auth.issuer
    AUTH_CLIENT_ID       = module.auth.client_id
    COGNITO_USER_POOL_ID = module.auth.user_pool_id
    APP_ORIGIN           = var.web_origins[0]
    CODE_HMAC_KEY_PARAM  = aws_ssm_parameter.app_key["code-hmac-key"].name
    RATE_HMAC_KEY_PARAM  = aws_ssm_parameter.app_key["rate-hmac-key"].name
  })
  # Jobs sign nothing today, so the worker gets no keys and no Parameter Store access.
  # RENDER_QUEUE_URL: the worker asks the PDF renderer for documents (D-042).
  worker_env = merge(local.db_env, local.queue_env, local.after_migrations, { RENDER_QUEUE_URL = module.render.url })
  # Every area but render-input, which the worker writes and only the renderer reads
  # (D-042, worker_render_statements below).
  app_areas = [for a in module.storage.areas : a if a != "render-input"]
  object_statements = [
    # No DeleteObject: nothing in the app deletes a file yet; lifecycle rules expire uploads.
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = [for a in local.app_areas : "${module.storage.bucket_arn}/${a}/b/*"] },
    # Without ListBucket a missing key reads as 403, not 404 (S3ObjectStore.head).
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [module.storage.bucket_arn], Condition = { StringLike = { "s3:prefix" = [for a in local.app_areas : "${a}/b/*"] } } },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = [module.storage.kms_key_arn] },
  ]
  send_statements = [
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [module.jobs.arn, module.mail.arn] },
  ]
  # The worker writes a render input and sends its key to the render queue (D-042). It
  # never reads an input back; the API reads the PDF under documents/ with the grants above.
  worker_render_statements = [
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${module.storage.bucket_arn}/render-input/b/*"] },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [module.render.arn] },
  ]
}

module "api_function" {
  source               = "../function"
  name                 = "${local.name}-api"
  package_path         = local.app_zip
  handler              = "app.api.handler"
  memory_mb            = 1024
  timeout_seconds      = 29 # API Gateway's integration limit
  reserved_concurrency = local.reserved.api
  vpc                  = local.vpc
  db_user              = "app_rw"
  db_resource_id       = module.database.resource_id
  environment          = local.api_env
  policy_statements = concat(local.object_statements, local.send_statements, [
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [for p in aws_ssm_parameter.app_key : p.arn] },
    # Exactly the admin calls CognitoAuthProvider makes (identity/cognito.py). AdminCreateUser
    # marks the email verified itself, so AdminUpdateUserAttributes isn't needed. Calls made
    # with the user's own token (ChangePassword, the TOTP enrolment calls, RevokeToken)
    # aren't governed by IAM.
    {
      Effect = "Allow"
      Action = [
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminGetUser",
        "cognito-idp:AdminSetUserPassword",
        "cognito-idp:AdminInitiateAuth",
        "cognito-idp:AdminRespondToAuthChallenge",
        "cognito-idp:AdminSetUserMFAPreference",
        "cognito-idp:AdminUserGlobalSignOut",
        "cognito-idp:AdminDeleteSoftwareToken",
      ]
      Resource = [module.auth.user_pool_arn]
    },
  ])
}

module "api" {
  source              = "../api"
  name                = local.name
  cors_origins        = var.web_origins
  jwt_issuer          = module.auth.issuer
  jwt_audience        = [module.auth.client_id]
  function_name       = module.api_function.function_name
  function_invoke_arn = module.api_function.invoke_arn
}

module "cdn" {
  source              = "../cdn"
  name                = local.name
  api_endpoint        = module.api.endpoint
  aliases             = var.cdn_aliases
  acm_certificate_arn = var.cdn_certificate_arn
}

# Jobs from SQS and the EventBridge schedules (app.worker.handler). Same zip as the API.
module "worker" {
  source               = "../function"
  name                 = "${local.name}-worker"
  package_path         = local.app_zip
  handler              = "app.worker.handler"
  memory_mb            = 1024
  timeout_seconds      = 900
  reserved_concurrency = local.reserved.worker
  vpc                  = local.vpc
  db_user              = "app_rw"
  db_resource_id       = module.database.resource_id
  environment          = local.worker_env
  sqs_trigger          = { arn = module.jobs.arn, batch_size = 1 }
  policy_statements    = concat(local.object_statements, local.send_statements, local.worker_render_statements)
}

# Outside the VPC, no database, SES only (HLD §4). The handler comes with SqsMailer.
module "mailer" {
  source               = "../function"
  name                 = "${local.name}-mailer"
  package_path         = local.app_zip
  handler              = "app.mailer.handler"
  timeout_seconds      = 30
  reserved_concurrency = local.reserved.mailer
  environment          = { PLATFORM_ENV = var.env, MAIL_FROM_DOMAIN = var.mail_domain }
  sqs_trigger          = { arn = module.mail.arn, batch_size = 10 }
  policy_statements = var.mail_domain == "" ? [] : [
    { Effect = "Allow", Action = ["ses:SendEmail"], Resource = [aws_sesv2_email_identity.mail[0].arn] },
  ]
}

# Applies migrations and refdata as the master. Invoked by the deploy step, never by users.
module "migrator" {
  source               = "../function"
  name                 = "${local.name}-migrator"
  package_path         = "${var.packages_dir}/migrator.zip"
  handler              = "migrator.handler.handler"
  timeout_seconds      = 300
  reserved_concurrency = local.reserved.migrator
  vpc                  = local.vpc
  environment = merge(local.db_env, {
    DB_MASTER_USER           = module.database.master_username
    DB_MASTER_PASSWORD_PARAM = module.database.master_password_parameter
    GIT_SHA                  = var.git_sha
  })
  policy_statements = [
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [module.database.master_password_parameter_arn] },
  ]
}

# Migrations run inside the apply, before the API and worker change (HLD §11). The
# invocation runs again whenever the migrator's code or the deployed commit changes, and
# a function error fails the apply, so a saved plan applies in the right order.
resource "aws_lambda_invocation" "migrate" {
  function_name = module.migrator.function_name
  input         = jsonencode({})
  triggers = {
    code    = module.migrator.source_code_hash
    git_sha = var.git_sha
  }
}

# The retention Lambda (LLD-6 §6.1, L6-5; D-041): same zip as the worker, its own role,
# and the only function that logs in as app_retention, which can execute the retention.*
# functions and nothing else. No S3 rights yet: no rule built so far deletes a file. Left
# unreserved, so TD-6's caps and the prod quota of 156 are unchanged; its two schedules
# never overlap and a second run would find nothing left to delete.
module "retention" {
  source          = "../function"
  name            = "${local.name}-retention"
  package_path    = local.app_zip
  handler         = "app.retention.handler"
  timeout_seconds = 900 # the handler stops itself after 10 minutes (BUDGET_SECONDS)
  vpc             = local.vpc
  db_user         = "app_retention"
  db_resource_id  = module.database.resource_id
  environment     = merge(local.db_env, local.after_migrations)
}

# The PDF renderer (TD-9; TD-1(b) amendment, D-042): WeasyPrint with its own native
# libraries and fonts, from its own zip (scripts/build_renderer.py), so none of that is in
# the API's or the worker's package or cold start. 1024 MB: about 0.3 s warm and 1.3 s
# cold for a one-page invoice in the local measurements, to be re-measured on arm64 on the
# first staging deploy (the self-test task). Outside the VPC, with no database login.
#
# The worker reaches it through the `render` queue (EM decision on #79): the worker
# already sends to SQS through the VPC's SQS endpoint, so this needs no Lambda endpoint
# (about USD 7-8 a month per AZ) and gets SQS's retries and a DLQ. A message carries an
# S3 key under render-input/b/*, never the document body (EM, D-042). The worker may put
# inputs there and send to this queue; the renderer may read and delete them, write PDFs
# under documents/b/*, and use our key only through S3. Unreserved, so TD-6's caps and the
# quota of 156 are unchanged; the trigger caps it at render_max_concurrency.
module "render" {
  source                     = "../queue"
  name                       = "${local.name}-render"
  visibility_timeout_seconds = 360 # AWS's guidance for a Lambda trigger: 6 x the function's timeout
}

module "renderer" {
  source          = "../function"
  name            = "${local.name}-renderer"
  package_path    = "${var.packages_dir}/renderer.zip"
  handler         = "renderer.handler.handler"
  memory_mb       = 1024
  timeout_seconds = 60 # a 1000-line invoice took 12 s locally at this size
  # At most 5 renders at once, so a burst of finalized invoices waits in the queue rather
  # than taking concurrency from the API (2 is the lowest SQS allows).
  sqs_trigger = { arn = module.render.arn, batch_size = 1, maximum_concurrency = var.render_max_concurrency }
  environment = { OBJECTS_BUCKET = module.storage.bucket }
  # D-042: read and then delete render inputs, write PDFs under documents/, and use our
  # key only through S3. Nothing else in the bucket, no other service.
  policy_statements = [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:DeleteObject"], Resource = ["${module.storage.bucket_arn}/render-input/b/*"] },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${module.storage.bucket_arn}/documents/b/*"] },
    # So a message whose input is already gone reads as NoSuchKey (acknowledged), not 403.
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [module.storage.bucket_arn], Condition = { StringLike = { "s3:prefix" = ["render-input/b/*"] } } },
    {
      Effect    = "Allow"
      Action    = ["kms:Decrypt", "kms:GenerateDataKey"]
      Resource  = [module.storage.kms_key_arn]
      Condition = { StringEquals = { "kms:ViaService" = "s3.${data.aws_region.current.name}.amazonaws.com" } }
    },
  ]
}

# Schedules (TD-25, HLD §4, LLD-6 §6.1). The purge and retention rules stay DISABLED until
# Pankaj's staging decision and a dry run there; every rule also ships disabled in
# refdata (retention.<rule>.enabled), so enabling a schedule alone deletes nothing.
locals {
  schedule_targets = {
    worker    = { arn = module.worker.function_arn, name = module.worker.function_name }
    retention = { arn = module.retention.function_arn, name = module.retention.function_name }
  }
  schedules = {
    sweep-outbox = { expression = "rate(1 minute)", target = "worker", task = "sweep_outbox", enabled = true }
    purge        = { expression = "rate(1 hour)", target = "retention", task = "purge_operational", enabled = false }
    retention    = { expression = "cron(0 21 * * ? *)", target = "retention", task = "retention", enabled = false } # 02:30 IST
  }
}

resource "aws_cloudwatch_event_rule" "schedule" {
  for_each            = local.schedules
  name                = "${local.name}-${each.key}"
  schedule_expression = each.value.expression
  state               = each.value.enabled ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "schedule" {
  for_each = local.schedules
  rule     = aws_cloudwatch_event_rule.schedule[each.key].name
  arn      = local.schedule_targets[each.value.target].arn
  input    = jsonencode({ task = each.value.task })
}

resource "aws_lambda_permission" "schedule" {
  for_each      = local.schedules
  statement_id  = "AllowEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = local.schedule_targets[each.value.target].name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule[each.key].arn
}

# Alarms (TD-24): a message in a DLQ is a job, an email or a render that failed five times.
resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "alarms" {
  for_each  = toset(var.budget_alert_emails)
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each            = { jobs = module.jobs.dlq_name, mail = module.mail.dlq_name, render = module.render.dlq_name }
  alarm_name          = "${local.name}-${each.key}-dlq"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

# A failed retention run: the log line names the rule and the exception class only.
resource "aws_cloudwatch_metric_alarm" "retention_errors" {
  alarm_name          = "${local.name}-retention-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = module.retention.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_emails
  }
}

output "app_url" { value = "https://${module.cdn.domain_name}" }
output "api_endpoint" { value = module.api.endpoint }
output "user_pool_id" { value = module.auth.user_pool_id }
output "user_pool_client_id" { value = module.auth.client_id }
output "migrator_function" { value = module.migrator.function_name }
output "renderer_function" { value = module.renderer.function_name }
output "objects_bucket" { value = module.storage.bucket }
output "web_bucket" { value = module.cdn.web_bucket }
output "cdn_distribution_id" { value = module.cdn.distribution_id }
