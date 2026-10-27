terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in the bucket created by infra/bootstrap. Fill in the bucket name
  # after bootstrapping, then run: terraform init
  backend "s3" {
    key          = "staging/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = "ap-south-1" # Mumbai

  default_tags {
    tags = {
      Project     = "distributor-saas"
      Environment = "staging"
      ManagedBy   = "terraform"
    }
  }
}

variable "web_origins" { type = list(string) }
variable "budget_alert_emails" { type = list(string) }
variable "git_sha" {
  type    = string
  default = "unknown"
}
variable "mail_domain" {
  type    = string
  default = ""
}

module "stack" {
  source              = "../../modules/stack"
  env                 = "staging"
  web_origins         = var.web_origins
  packages_dir        = "${path.root}/../../../build"
  git_sha             = var.git_sha
  mail_domain         = var.mail_domain
  db_instance_class   = "db.t4g.micro"
  db_multi_az         = false # switch on before live invoices
  deletion_protection = false
  # Lets scripts/smoke_test.sh sign in test users from the command line.
  allow_test_password_login = true
  # TD-6's caps are left off here: Lambda keeps 100 of the account's concurrency
  # unreserved, so reserving 56 needs a quota of at least 156, and new accounts often
  # start lower. Prod sets them.
  reserved_concurrency = null
  monthly_budget_usd   = 50 # TD-21
  budget_alert_emails  = var.budget_alert_emails
}

output "api_endpoint" { value = module.stack.api_endpoint }
output "user_pool_id" { value = module.stack.user_pool_id }
output "user_pool_client_id" { value = module.stack.user_pool_client_id }
output "migrator_function" { value = module.stack.migrator_function }
output "app_url" { value = module.stack.app_url }
output "web_bucket" { value = module.stack.web_bucket }
output "cdn_distribution_id" { value = module.stack.cdn_distribution_id }
