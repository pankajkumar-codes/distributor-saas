# One Lambda function: its role, its logs, and optionally its VPC placement, its IAM
# database user and an SQS trigger. The API's routes live in the api module.

variable "name" {
  description = "Function name, e.g. distsaas-staging-api"
  type        = string
}
variable "package_path" {
  description = "Zip built by scripts/build_lambda.sh"
  type        = string
}
variable "handler" { type = string }
variable "memory_mb" {
  type    = number
  default = 512
}
variable "timeout_seconds" {
  type    = number
  default = 15
}
variable "reserved_concurrency" {
  description = "TD-6 connection caps. -1 leaves the function unreserved (see the env's note on account quotas)."
  type        = number
  default     = -1
}
variable "vpc" {
  description = "Subnets and security groups, or null to run outside the VPC (the mailer)."
  type = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}
variable "environment" {
  type    = map(string)
  default = {}
}
variable "db_user" {
  description = "Database login this function connects as with an IAM token, or empty for none."
  type        = string
  default     = ""
}
variable "db_resource_id" {
  type    = string
  default = ""
}
variable "policy_statements" {
  description = "IAM statements as objects; `any` because statements with and without a Condition differ in type."
  type        = any
  default     = []
}
variable "sqs_trigger" {
  description = "Queue to consume, with ReportBatchItemFailures, or null."
  type = object({
    arn        = string
    batch_size = number
  })
  default = null
}
variable "log_retention_days" {
  type    = number
  default = 30
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  db_statements = var.db_user == "" ? [] : [{
    Effect   = "Allow"
    Action   = ["rds-db:connect"]
    Resource = ["arn:aws:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${var.db_resource_id}/${var.db_user}"]
  }]
  sqs_statements = var.sqs_trigger == null ? [] : [{
    Effect   = "Allow"
    Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    Resource = [var.sqs_trigger.arn]
  }]
  statements = concat(local.db_statements, local.sqs_statements, var.policy_statements)
}

resource "aws_iam_role" "this" {
  name = var.name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Logs only; the VPC policy adds the network-interface rights a VPC function needs.
resource "aws_iam_role_policy_attachment" "base" {
  role       = aws_iam_role.this.name
  policy_arn = var.vpc == null ? "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" : "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "this" {
  count  = length(local.statements) > 0 ? 1 : 0
  name   = "function"
  role   = aws_iam_role.this.id
  policy = jsonencode({ Version = "2012-10-17", Statement = local.statements })
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  function_name                  = var.name
  role                           = aws_iam_role.this.arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = var.handler
  filename                       = var.package_path
  source_code_hash               = try(filebase64sha256(var.package_path), null)
  memory_size                    = var.memory_mb
  timeout                        = var.timeout_seconds
  reserved_concurrent_executions = var.reserved_concurrency

  dynamic "vpc_config" {
    for_each = var.vpc == null ? [] : [var.vpc]
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  environment {
    variables = merge(var.db_user == "" ? {} : { DB_USER = var.db_user }, var.environment)
  }

  depends_on = [aws_cloudwatch_log_group.this, aws_iam_role_policy_attachment.base]
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count                   = var.sqs_trigger == null ? 0 : 1
  event_source_arn        = var.sqs_trigger.arn
  function_name           = aws_lambda_function.this.arn
  batch_size              = var.sqs_trigger.batch_size
  function_response_types = ["ReportBatchItemFailures"]
}

output "function_name" { value = aws_lambda_function.this.function_name }
output "function_arn" { value = aws_lambda_function.this.arn }
output "invoke_arn" { value = aws_lambda_function.this.invoke_arn }
output "role_name" { value = aws_iam_role.this.name }
