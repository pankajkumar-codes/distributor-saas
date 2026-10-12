# Private buckets. Files are only ever reached through short-lived presigned URLs
# issued by a service after it has checked tenant access.

variable "name" { type = string }
variable "buckets" {
  description = "Logical bucket names, e.g. uploads, documents"
  type        = list(string)
}
variable "cors_origins" {
  type    = list(string)
  default = []
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "this" {
  for_each = toset(var.buckets)
  bucket   = "${var.name}-${each.key}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_bucket_cors_configuration" "this" {
  for_each = length(var.cors_origins) > 0 ? aws_s3_bucket.this : {}
  bucket   = each.value.id
  cors_rule {
    allowed_methods = ["GET", "PUT"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

output "bucket_names" { value = { for k, b in aws_s3_bucket.this : k => b.bucket } }
output "bucket_arns" { value = { for k, b in aws_s3_bucket.this : k => b.arn } }
