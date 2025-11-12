terraform {
  backend "s3" {
    bucket  = "ecommerce-tf-state-565562062476"
    key     = "global/terraform.tfstate"
    region  = "me-central-1"
    encrypt = true
  }
}