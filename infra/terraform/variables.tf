variable "region" {
  default = "me-central-1"
}

variable "price_comparison_bucket" {
  description = "bucket for main scraper tasks"
  type        = string
  default     = "price-comparison-bucket"
}