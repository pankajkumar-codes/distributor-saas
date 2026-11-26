# The HTTP API in front of the API Lambda. It is a REGIONAL endpoint in Mumbai and the browser calls it
# directly: the API is not behind CloudFront, because a CDN's edges and caches can sit outside India
# (D-094). With `domain_name` set it is served on a sibling name such as api.<domain>; the web files are on
# <domain> and the two are the same site, so the SameSite=Strict refresh cookie still works. The JWT
# authorizer guards everything except the routes HLD §4 lists as public: /api/v1/auth/* and
# /api/v1/public/*, which the app rate-limits itself (TD-17), and the health check.

variable "name" { type = string }
variable "cors_origins" { type = list(string) }
variable "jwt_issuer" { type = string }
variable "jwt_audience" { type = list(string) }
variable "function_name" { type = string }
variable "function_invoke_arn" { type = string }
variable "domain_name" {
  description = "Custom domain for the API, a sibling of the web name (api.example.in). Empty: only the execute-api name, which is a different site from the web files, so the refresh cookie does not work and it is for a first apply only."
  type        = string
  default     = ""
}
variable "certificate_arn" {
  description = "ACM certificate for domain_name, issued in this stack's region (ap-south-1). Required when domain_name is set."
  type        = string
  default     = ""
  validation {
    condition     = var.certificate_arn == "" || can(regex("^arn:aws:acm:ap-south-1:", var.certificate_arn))
    error_message = "certificate_arn must be an ACM certificate in ap-south-1, the stack's region."
  }
}
variable "throttling_burst_limit" {
  type    = number
  default = 100
}
variable "throttling_rate_limit" {
  type    = number
  default = 50
}
# The sign-in routes are public and each call is a password, code or token check, so they get a lower cap of their
# own (#472). Like the stage default it is shared by every caller: it caps a flood, while the app's own counters per
# email and IP address (refdata auth.*) stop one person guessing.
variable "auth_throttling_burst_limit" {
  type    = number
  default = 20
}
variable "auth_throttling_rate_limit" {
  type    = number
  default = 10
}

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
  # The web app is on another origin (<domain> calls api.<domain>), so CORS is how the browser is let in:
  # only the listed web origins, with credentials (the refresh cookie). Once the custom domain exists the
  # default execute-api name is switched off, so there is one way in.
  disable_execute_api_endpoint = var.domain_name != ""
  cors_configuration {
    allow_origins     = var.cors_origins
    allow_methods     = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers     = ["authorization", "content-type", "idempotency-key", "if-match", "x-background", "x-request-id"]
    expose_headers    = ["etag", "retry-after", "content-disposition"]
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
  # route_settings names a route key, which must exist first.
  depends_on  = [aws_apigatewayv2_route.public]
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.throttling_burst_limit
    throttling_rate_limit  = var.throttling_rate_limit
  }

  route_settings {
    route_key              = "ANY /api/v1/auth/{proxy+}"
    throttling_burst_limit = var.auth_throttling_burst_limit
    throttling_rate_limit  = var.auth_throttling_rate_limit
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

resource "aws_apigatewayv2_domain_name" "this" {
  count       = var.domain_name == "" ? 0 : 1
  domain_name = var.domain_name
  domain_name_configuration {
    certificate_arn = var.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
  lifecycle {
    precondition {
      condition     = var.certificate_arn != ""
      error_message = "domain_name needs certificate_arn (a regional ACM certificate)."
    }
  }
}

# No base path: the routes already start with /api, so the app sees the same paths as before.
resource "aws_apigatewayv2_api_mapping" "this" {
  count       = var.domain_name == "" ? 0 : 1
  api_id      = aws_apigatewayv2_api.this.id
  domain_name = aws_apigatewayv2_domain_name.this[0].id
  stage       = aws_apigatewayv2_stage.default.id
}

output "api_id" { value = aws_apigatewayv2_api.this.id }
output "endpoint" { value = aws_apigatewayv2_api.this.api_endpoint }
# What the browser calls: the custom domain, else the execute-api name.
output "origin" { value = var.domain_name == "" ? aws_apigatewayv2_api.this.api_endpoint : "https://${var.domain_name}" }
# For the DNS record at the registrar: point domain_name (CNAME or alias) at this.
output "regional_domain_name" { value = var.domain_name == "" ? "" : aws_apigatewayv2_domain_name.this[0].domain_name_configuration[0].target_domain_name }
