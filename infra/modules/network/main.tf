# Private-only VPC. There is no internet or NAT gateway: Lambdas reach S3 through a
# free gateway endpoint and SQS / Secrets Manager through interface endpoints.

variable "name" { type = string }
variable "cidr" {
  type    = string
  default = "10.20.0.0/16"
}
variable "az_count" {
  description = "Private subnets to create. RDS needs at least two AZs."
  type        = number
  default     = 2
}
variable "endpoint_az_count" {
  description = "AZs that get interface endpoints. Each endpoint costs per AZ-hour, so 1 keeps cost down."
  type        = number
  default     = 1
}
variable "interface_endpoints" {
  type    = list(string)
  default = ["sqs", "secretsmanager"]
}

data "aws_region" "current" {}
data "aws_availability_zones" "available" { state = "available" }

resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = var.name }
}

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr, 4, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags              = { Name = "${var.name}-private-${count.index}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "lambda" {
  name        = "${var.name}-lambda"
  description = "Service Lambdas"
  vpc_id      = aws_vpc.this.id

  egress {
    description = "Only private destinations exist in this VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "endpoints" {
  name        = "${var.name}-endpoints"
  description = "Interface endpoints"
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }
}

resource "aws_security_group" "database" {
  name        = "${var.name}-database"
  description = "PostgreSQL, reachable only from service Lambdas"
  vpc_id      = aws_vpc.this.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(var.interface_endpoints)
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = slice(aws_subnet.private[*].id, 0, var.endpoint_az_count)
  security_group_ids  = [aws_security_group.endpoints.id]
}

output "vpc_id" { value = aws_vpc.this.id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "lambda_security_group_id" { value = aws_security_group.lambda.id }
output "database_security_group_id" { value = aws_security_group.database.id }
