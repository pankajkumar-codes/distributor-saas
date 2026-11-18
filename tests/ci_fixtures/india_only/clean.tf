provider "aws" {
  region = "ap-south-1"
}

resource "aws_kms_key" "k" {
  multi_region = false
}
