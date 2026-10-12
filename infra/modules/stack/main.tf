# The whole environment. envs/staging and envs/prod call this with different sizes.

variable "env" { type = string }
variable "project" {
  type    = string
  default = "distsaas"
}
variable "web_origins" {
  description = "Origins allowed to call the API and upload files, e.g. https://app.example.in"
  type        = list(string)
}
variable "packages_dir" {
  description = "Directory holding <service>.zip files from scripts/build_lambda.sh"
  type        = string
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
variable "monthly_budget_usd" {
  type = number
}
variable "budget_alert_emails" {
  type = list(string)
}

locals {
  name = "${var.project}-${var.env}"
  # Services exposed on the API. commerce/imports/documents/reports are skeletons
  # until their blocking decisions (see docs/DECISIONS.md) are made.
  http_services = ["identity", "commerce", "imports", "reports"]
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
  source              = "../auth"
  name                = local.name
  callback_urls       = [for o in var.web_origins : "${o}/auth/callback"]
  logout_urls         = var.web_origins
  deletion_protection = var.deletion_protection
}

module "storage" {
  source       = "../storage"
  name         = local.name
  buckets      = ["uploads", "documents"]
  cors_origins = var.web_origins
}

module "events" {
  source = "../queue"
  name   = "${local.name}-document-events"
}

module "import_jobs" {
  source                     = "../queue"
  name                       = "${local.name}-import-jobs"
  visibility_timeout_seconds = 960
}

module "api" {
  source       = "../api"
  name         = local.name
  cors_origins = var.web_origins
  jwt_issuer   = module.auth.issuer
  jwt_audience = [module.auth.client_id]
}

locals {
  common_env = {
    PLATFORM_ENV = var.env
    DB_HOST      = module.database.address
    DB_PORT      = tostring(module.database.port)
    DB_NAME      = module.database.db_name
  }
  api_attachment = {
    api_id        = module.api.api_id
    execution_arn = module.api.execution_arn
    authorizer_id = module.api.authorizer_id
  }
  service_settings = {
    identity = { env = {}, statements = [] }
    commerce = {
      env        = { DOCUMENT_EVENTS_QUEUE_URL = module.events.url }
      statements = [{ Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [module.events.arn] }]
    }
    imports = {
      env = { UPLOADS_BUCKET = module.storage.bucket_names["uploads"], IMPORT_JOBS_QUEUE_URL = module.import_jobs.url }
      statements = [
        { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = ["${module.storage.bucket_arns["uploads"]}/*"] },
        { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [module.import_jobs.arn] },
      ]
    }
    reports = {
      env        = { DOCUMENTS_BUCKET = module.storage.bucket_names["documents"] }
      statements = [{ Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${module.storage.bucket_arns["documents"]}/*"] }]
    }
  }
}

module "http_service" {
  for_each                = toset(local.http_services)
  source                  = "../service"
  name                    = local.name
  service                 = each.key
  package_path            = "${var.packages_dir}/${each.key}.zip"
  subnet_ids              = module.network.private_subnet_ids
  security_group_ids      = [module.network.lambda_security_group_id]
  db_resource_id          = module.database.resource_id
  environment             = merge(local.common_env, local.service_settings[each.key].env)
  extra_policy_statements = local.service_settings[each.key].statements
  api                     = local.api_attachment
}

# Builds invoice PDFs from queued events; no public routes.
module "documents" {
  source             = "../service"
  name               = local.name
  service            = "documents"
  package_path       = "${var.packages_dir}/documents.zip"
  handler            = "app.main.sqs_handler"
  memory_mb          = 1024
  timeout_seconds    = 60
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.lambda_security_group_id]
  db_resource_id     = module.database.resource_id
  environment        = merge(local.common_env, { DOCUMENTS_BUCKET = module.storage.bucket_names["documents"] })
  sqs_trigger_arn    = module.events.arn
  extra_policy_statements = [
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${module.storage.bucket_arns["documents"]}/*"] },
  ]
}

# Applies SQL migrations as the master user. Invoked by the deploy step, never by users.
module "migrator" {
  source             = "../service"
  name               = local.name
  service            = "migrator"
  package_path       = "${var.packages_dir}/migrator.zip"
  handler            = "migrator.handler.handler"
  timeout_seconds    = 300
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.lambda_security_group_id]
  environment        = merge(local.common_env, { DB_MASTER_SECRET_ARN = module.database.master_secret_arn })
  extra_policy_statements = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [module.database.master_secret_arn] },
  ]
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

output "api_endpoint" { value = module.api.endpoint }
output "user_pool_id" { value = module.auth.user_pool_id }
output "user_pool_client_id" { value = module.auth.client_id }
output "migrator_function" { value = module.migrator.function_name }
output "buckets" { value = module.storage.bucket_names }
