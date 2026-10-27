# One PostgreSQL instance. The app connects as app_rw (and the retention job as
# app_retention) with IAM tokens, so no app password exists. Only the migrator uses the
# master password, which Terraform generates and keeps in a Parameter Store
# SecureString (free) rather than an RDS-managed Secrets Manager secret (USD 0.40 a
# month). It is in Terraform state too, which is why the state bucket is private and
# encrypted.

terraform {
  required_providers {
    aws    = { source = "hashicorp/aws" }
    random = { source = "hashicorp/random" }
  }
}

variable "name" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}
variable "engine_version" {
  type    = string
  default = "16"
}
variable "allocated_storage_gb" {
  type    = number
  default = 20
}
variable "max_allocated_storage_gb" {
  type    = number
  default = 100
}
variable "multi_az" {
  description = "Standby replica for failover. Recommended before live invoices."
  type        = bool
  default     = false
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "backup_retention_days" {
  description = "TD-22: 35 days, RDS's maximum"
  type        = number
  default     = 35
}

resource "random_password" "master" {
  length  = 40
  special = false
}

resource "aws_ssm_parameter" "master_password" {
  name        = "/${var.name}/db/master-password"
  description = "RDS master password; read only by the migrator"
  type        = "SecureString"
  value       = random_password.master.result
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = var.name
  family = "postgres${split(".", var.engine_version)[0]}"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "this" {
  identifier                          = var.name
  engine                              = "postgres"
  engine_version                      = var.engine_version
  instance_class                      = var.instance_class
  allocated_storage                   = var.allocated_storage_gb
  max_allocated_storage               = var.max_allocated_storage_gb
  storage_type                        = "gp3"
  storage_encrypted                   = true
  db_name                             = "saas"
  username                            = "saas_admin"
  password                            = random_password.master.result
  iam_database_authentication_enabled = true
  db_subnet_group_name                = aws_db_subnet_group.this.name
  parameter_group_name                = aws_db_parameter_group.this.name
  vpc_security_group_ids              = [var.security_group_id]
  publicly_accessible                 = false
  multi_az                            = var.multi_az
  backup_retention_period             = var.backup_retention_days
  copy_tags_to_snapshot               = true
  auto_minor_version_upgrade          = true
  deletion_protection                 = var.deletion_protection
  skip_final_snapshot                 = !var.deletion_protection
  final_snapshot_identifier           = var.deletion_protection ? "${var.name}-final" : null
}

output "address" { value = aws_db_instance.this.address }
output "port" { value = aws_db_instance.this.port }
output "db_name" { value = aws_db_instance.this.db_name }
output "resource_id" { value = aws_db_instance.this.resource_id }
output "master_username" { value = aws_db_instance.this.username }
output "master_password_parameter" { value = aws_ssm_parameter.master_password.name }
output "master_password_parameter_arn" { value = aws_ssm_parameter.master_password.arn }
