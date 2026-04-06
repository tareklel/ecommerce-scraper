terraform {
  backend "s3" {
    bucket  = "ecommerce-tf-state-eu-central-1-565562062476"
    key     = "eu-central-1/terraform.tfstate"
    region  = "eu-central-1"
    encrypt = true
  }
}
