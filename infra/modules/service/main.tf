# One microservice: a Lambda function, its role, its logs, and (optionally) its
# routes on the shared HTTP API and an SQS trigger.

variable "name" { type = string }
variable "service" {
  description = "Short service name, also its URL prefix and database user (svc_<service>)."
  type        = string
}
variable "package_path" {
  description = "Zip built by scripts/build_lambda.sh"
  type        = string
}
variable "handler" {
  type    = string
  default = "app.main.handler"
}
variable "memory_mb" {
  type    = number
  default = 512
}
variable "timeout_seconds" {
  type    = number
  default = 15
}
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "environment" {
  type    = map(string)
  default = {}
}
variable "db_resource_id" {
  description = "RDS resource id, for IAM database authentication. Empty to skip."
  type        = string
  default     = ""
}
variable "extra_policy_statements" {
  type    = list(any)
  default = []
}
variable "api" {
  description = "Attach routes on the shared HTTP API. Null for internal-only services."
  type = object({
    api_id        = string
    execution_arn = string
    authorizer_id = string
  })
  default = null
}
variable "sqs_trigger_arn" {
  type    = string
  default = ""
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  function_name = "${var.name}-${var.service}"
  db_user       = "svc_${var.service}"
  db_statements = var.db_resource_id == "" ? [] : [{
    Effect   = "Allow"
    Action   = ["rds-db:connect"]
    Resource = ["arn:aws:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${var.db_resource_id}/${local.db_user}"]
  }]
  sqs_statements = var.sqs_trigger_arn == "" ? [] : [{
    Effect   = "Allow"
    Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    Resource = [var.sqs_trigger_arn]
  }]
  statements = concat(local.db_statements, local.sqs_statements, var.extra_policy_statements)
}

resource "aws_iam_role" "this" {
  name = local.function_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "vpc" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "this" {
  count  = length(local.statements) > 0 ? 1 : 0
  name   = "service"
  role   = aws_iam_role.this.id
  policy = jsonencode({ Version = "2012-10-17", Statement = local.statements })
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 30
}

resource "aws_lambda_function" "this" {
  function_name    = local.function_name
  role             = aws_iam_role.this.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = var.handler
  filename         = var.package_path
  source_code_hash = try(filebase64sha256(var.package_path), null)
  memory_size      = var.memory_mb
  timeout          = var.timeout_seconds

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  environment {
    variables = merge({ SERVICE_NAME = var.service, DB_USER = local.db_user }, var.environment)
  }

  depends_on = [aws_cloudwatch_log_group.this, aws_iam_role_policy_attachment.vpc]
}

resource "aws_apigatewayv2_integration" "this" {
  count                  = var.api == null ? 0 : 1
  api_id                 = var.api.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "health" {
  count     = var.api == null ? 0 : 1
  api_id    = var.api.api_id
  route_key = "GET /${var.service}/health"
  target    = "integrations/${aws_apigatewayv2_integration.this[0].id}"
}

resource "aws_apigatewayv2_route" "authenticated" {
  count              = var.api == null ? 0 : 1
  api_id             = var.api.api_id
  route_key          = "ANY /${var.service}/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.this[0].id}"
  authorization_type = "JWT"
  authorizer_id      = var.api.authorizer_id
}

resource "aws_lambda_permission" "api" {
  count         = var.api == null ? 0 : 1
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api.execution_arn}/*/*"
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count                   = var.sqs_trigger_arn == "" ? 0 : 1
  event_source_arn        = var.sqs_trigger_arn
  function_name           = aws_lambda_function.this.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
}

output "function_name" { value = aws_lambda_function.this.function_name }
output "function_arn" { value = aws_lambda_function.this.arn }
output "role_name" { value = aws_iam_role.this.name }
