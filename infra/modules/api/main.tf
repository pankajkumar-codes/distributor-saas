# The HTTP API in front of the API Lambda. CloudFront sends /api/* here, so the browser
# sees one origin (tech plan §3). The JWT authorizer guards everything except the
# routes HLD §4 lists as public: /api/v1/auth/* and /api/v1/public/*, which the app
# rate-limits itself (TD-17), and the health check.

variable "name" { type = string }
variable "cors_origins" { type = list(string) }
variable "jwt_issuer" { type = string }
variable "jwt_audience" { type = list(string) }
variable "function_name" { type = string }
variable "function_invoke_arn" { type = string }
variable "throttling_burst_limit" {
  type    = number
  default = 100
}
variable "throttling_rate_limit" {
  type    = number
  default = 50
}

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  # Same-origin through CloudFront needs no CORS; this covers calling the API directly
  # from a listed origin while testing.
  cors_configuration {
    allow_origins     = var.cors_origins
    allow_methods     = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers     = ["authorization", "content-type", "idempotency-key"]
    allow_credentials = true
    max_age           = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    issuer   = var.jwt_issuer
    audience = var.jwt_audience
  }
}

resource "aws_apigatewayv2_integration" "app" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.function_invoke_arn
  payload_format_version = "2.0"
}

locals {
  # API Gateway picks the most specific match, so these win over ANY /api/{proxy+}.
  public_routes = ["ANY /api/v1/auth/{proxy+}", "ANY /api/v1/public/{proxy+}", "GET /api/v1/health"]
}

resource "aws_apigatewayv2_route" "public" {
  for_each  = toset(local.public_routes)
  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.app.id}"
}

resource "aws_apigatewayv2_route" "authenticated" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.app.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = var.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.name}"
  retention_in_days = 30
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.throttling_burst_limit
    throttling_rate_limit  = var.throttling_rate_limit
  }

  # No bodies, no headers, no query strings: codes and tokens never reach this log.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
      sub       = "$context.authorizer.claims.sub"
    })
  }
}

output "api_id" { value = aws_apigatewayv2_api.this.id }
output "endpoint" { value = aws_apigatewayv2_api.this.api_endpoint }
