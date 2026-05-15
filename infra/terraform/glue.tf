# -------------------------------------------------------
# Glue Data Catalog tables for the image pipeline
# -------------------------------------------------------
# These tables are written by:
#   image_download_status  → run_image_pipeline.py
#   raw_image              → scripts/image_quality_checker.py
# -------------------------------------------------------

resource "aws_glue_catalog_table" "image_download_status" {
  name          = "image_download_status"
  database_name = var.glue_database_name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"       = "json"
    "compressionType"      = "gzip"
    "typeOfData"           = "file"
    "EXTERNAL"             = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${var.price_comparison_bucket}/bronze/images/download_status/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "site"
      type = "string"
    }
    columns {
      name = "primary_key"
      type = "string"
    }
    columns {
      name = "url"
      type = "string"
    }
    columns {
      name = "run_id"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "s3_blob_key"
      type = "string"
    }
  }

  partition_keys {
    name = "dt"
    type = "string"
  }
}

resource "aws_glue_catalog_table" "raw_image" {
  name          = "raw_image"
  database_name = var.glue_database_name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification"       = "json"
    "compressionType"      = "gzip"
    "typeOfData"           = "file"
    "EXTERNAL"             = "TRUE"
  }

  storage_descriptor {
    location      = "s3://${var.price_comparison_bucket}/bronze/images/raw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
      parameters = {
        "serialization.format" = "1"
      }
    }

    columns {
      name = "site"
      type = "string"
    }
    columns {
      name = "primary_key"
      type = "string"
    }
    columns {
      name = "image_url"
      type = "string"
    }
    columns {
      name = "s3_blob_key"
      type = "string"
    }
    columns {
      name = "sha256"
      type = "string"
    }
    columns {
      name = "width"
      type = "int"
    }
    columns {
      name = "height"
      type = "int"
    }
    columns {
      name = "format"
      type = "string"
    }
    columns {
      name = "run_id"
      type = "string"
    }
  }

  partition_keys {
    name = "dt"
    type = "string"
  }
}
