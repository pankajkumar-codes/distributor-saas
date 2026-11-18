provider "aws" {
  alias  = "far"
  region = "eu-west-1"
}

resource "aws_kms_key" "k" {
  multi_region = true
}

resource "aws_s3_bucket_replication_configuration" "r" {}

locals {
  profile = "global.anthropic.some-model"
}
