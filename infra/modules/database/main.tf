# One PostgreSQL instance shared by all services; each service owns its own schema
# and connects as its own IAM-authenticated database user.

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
  type    = number
  default = 7
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
  manage_master_user_password         = true
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
output "master_secret_arn" { value = aws_db_instance.this.master_user_secret[0].secret_arn }
