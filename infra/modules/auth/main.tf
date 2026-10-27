# Sign-in is Cognito, driven only through our API (TD-4): the API signs users in with
# AdminInitiateAuth, so the client allows the admin password flow and not SRP. There is
# no hosted-UI domain, which keeps the pool usable over the Cognito interface endpoint
# (tech plan §4.5). Tokens carry no tenant: the tenant is chosen per request and checked
# against memberships on the server.

variable "name" { type = string }
variable "allow_password_login" {
  description = "Lets scripts sign in with a username and password (USER_PASSWORD_AUTH). For staging testing only."
  type        = bool
  default     = false
}
variable "deletion_protection" {
  type    = bool
  default = true
}

resource "aws_cognito_user_pool" "this" {
  name                     = var.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"
  deletion_protection      = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name                          = "${var.name}-web"
  user_pool_id                  = aws_cognito_user_pool.this.id
  generate_secret               = false
  explicit_auth_flows           = concat(["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"], var.allow_password_login ? ["ALLOW_USER_PASSWORD_AUTH"] : [])
  prevent_user_existence_errors = "ENABLED"
  supported_identity_providers  = ["COGNITO"]
  access_token_validity         = 5 # TD-4b: Cognito's minimum; the session row does the rest
  id_token_validity             = 5
  refresh_token_validity        = 30
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

data "aws_region" "current" {}

output "user_pool_id" { value = aws_cognito_user_pool.this.id }
output "user_pool_arn" { value = aws_cognito_user_pool.this.arn }
output "client_id" { value = aws_cognito_user_pool_client.web.id }
output "issuer" { value = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.this.id}" }
