variable "name" { type = string }
variable "visibility_timeout_seconds" {
  description = "Must be at least the consuming Lambda's timeout."
  type        = number
  default     = 90
}
variable "max_receive_count" {
  type    = number
  default = 5
}
variable "message_retention_seconds" {
  type    = number
  default = 345600 # SQS default, 4 days
}
variable "dlq_retention_seconds" {
  type    = number
  default = 1209600 # 14 days, SQS's maximum
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-dlq"
  message_retention_seconds = var.dlq_retention_seconds
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "this" {
  name                       = var.name
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

output "arn" { value = aws_sqs_queue.this.arn }
output "url" { value = aws_sqs_queue.this.url }
output "dlq_arn" { value = aws_sqs_queue.dlq.arn }
output "dlq_name" { value = aws_sqs_queue.dlq.name }
