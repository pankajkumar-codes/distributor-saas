# The one private bucket for business files (D-036, D-039): uploads, documents, exports
# and branding, each under b/<business>/<area>/. Files are only ever reached through
# short-lived presigned URLs that the API issues after checking the caller's business.
#
# Default encryption is SSE-KMS with our own key (H-4), so a presigned POST names no
# encryption field and a file can't be stored any other way. The bucket key cuts KMS
# requests to roughly one per object instead of one per read or write.

variable "name" { type = string }
variable "cors_origins" {
  description = "Origins the browser POSTs uploads from (the app domain)"
  type        = list(string)
  default     = []
}
variable "noncurrent_version_days" {
  description = "How long an overwritten or deleted object's old version is kept"
  type        = number
  default     = 30
}

data "aws_caller_identity" "current" {}

resource "aws_kms_key" "objects" {
  description             = "${var.name} business files"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "objects" {
  name          = "alias/${var.name}-objects"
  target_key_id = aws_kms_key.objects.key_id
}

resource "aws_s3_bucket" "objects" {
  bucket = "${var.name}-objects-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.objects.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "objects" {
  bucket = aws_s3_bucket.objects.id
  versioning_configuration {
    status = "Enabled"
  }
}

# The 90-day deletion of raw uploads (TD-18) is not here: keys start with the business,
# so no prefix filter selects every upload. See docs/OPEN_QUESTIONS.md (S0b infra).
resource "aws_s3_bucket_lifecycle_configuration" "objects" {
  bucket     = aws_s3_bucket.objects.id
  depends_on = [aws_s3_bucket_versioning.objects]

  rule {
    id     = "old-versions-and-abandoned-uploads"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "objects" {
  bucket = aws_s3_bucket.objects.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.objects.arn, "${aws_s3_bucket.objects.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.objects]
}

# Browser uploads are a presigned POST (H-4); downloads are a redirect, which needs no CORS.
resource "aws_s3_bucket_cors_configuration" "objects" {
  count  = length(var.cors_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.objects.id
  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

output "bucket" { value = aws_s3_bucket.objects.bucket }
output "bucket_arn" { value = aws_s3_bucket.objects.arn }
output "kms_key_arn" { value = aws_kms_key.objects.arn }
