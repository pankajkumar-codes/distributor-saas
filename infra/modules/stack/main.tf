# The whole environment. envs/staging and envs/prod call this with different sizes.
# Deployables (TD-1, HLD §4): the API and worker Lambdas share app.zip, the mailer runs
# outside the VPC with SES only, and the migrator applies migrations as the master.

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
  description = "Directory holding app.zip and migrator.zip from scripts/build_lambda.sh"
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
  app_env = merge(local.db_env, {
    JOBS_QUEUE_URL       = module.jobs.url
    MAIL_QUEUE_URL       = module.mail.url
    UPLOADS_BUCKET       = module.storage.bucket
    AUTH_ISSUER          = module.auth.issuer
    AUTH_CLIENT_ID       = module.auth.client_id
    COGNITO_USER_POOL_ID = module.auth.user_pool_id
    APP_ORIGIN           = var.web_origins[0]
    CODE_HMAC_KEY_PARAM  = aws_ssm_parameter.app_key["code-hmac-key"].name
    RATE_HMAC_KEY_PARAM  = aws_ssm_parameter.app_key["rate-hmac-key"].name
  })
  object_statements = [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = ["${module.storage.bucket_arn}/b/*"] },
    # Without ListBucket a missing key reads as 403, not 404 (S3ObjectStore.head).
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [module.storage.bucket_arn], Condition = { StringLike = { "s3:prefix" = ["b/*"] } } },
    { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = [module.storage.kms_key_arn] },
  ]
  send_statements = [
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [module.jobs.arn, module.mail.arn] },
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
  environment          = local.app_env
  policy_statements = concat(local.object_statements, local.send_statements, [
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [for p in aws_ssm_parameter.app_key : p.arn] },
    # The admin calls LLD-1 §7 lists, plus AdminUpdateUserAttributes to mark the email
    # verified (TD-4); calls made with the user's own token need no IAM.
    # CognitoAuthProvider (S1-c4) confirms the list against what it really calls.
    {
      Effect = "Allow"
      Action = [
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminGetUser",
        "cognito-idp:AdminSetUserPassword",
        "cognito-idp:AdminUpdateUserAttributes",
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
  environment          = local.app_env
  sqs_trigger          = { arn = module.jobs.arn, batch_size = 1 }
  policy_statements    = concat(local.object_statements, local.send_statements)
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

# Worker schedules (TD-25, HLD §4). Only the outbox sweep has a handler today; the purge
# and retention rules exist switched off until the worker handles those tasks.
locals {
  schedules = {
    sweep-outbox = { expression = "rate(1 minute)", task = "sweep_outbox", enabled = true }
    purge        = { expression = "rate(1 hour)", task = "purge_operational", enabled = false }
    retention    = { expression = "cron(30 21 * * ? *)", task = "retention", enabled = false } # 03:00 IST
  }
}

resource "aws_cloudwatch_event_rule" "worker" {
  for_each            = local.schedules
  name                = "${local.name}-${each.key}"
  schedule_expression = each.value.expression
  state               = each.value.enabled ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "worker" {
  for_each = local.schedules
  rule     = aws_cloudwatch_event_rule.worker[each.key].name
  arn      = module.worker.function_arn
  input    = jsonencode({ task = each.value.task })
}

resource "aws_lambda_permission" "schedule" {
  for_each      = local.schedules
  statement_id  = "AllowEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = module.worker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.worker[each.key].arn
}

# Alarms (TD-24): a message in either DLQ is a job or an email that failed five times.
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
  for_each            = { jobs = module.jobs.dlq_name, mail = module.mail.dlq_name }
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
output "objects_bucket" { value = module.storage.bucket }
output "web_bucket" { value = module.cdn.web_bucket }
output "cdn_distribution_id" { value = module.cdn.distribution_id }
