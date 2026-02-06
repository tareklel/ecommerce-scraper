```mermaid
flowchart TD
  subgraph A_Scraper_Runtime
    A1[Spider / Spiders] --> A2[Item Pipeline: normalize + content_hash]
    A2 --> A3[products.jsonl.gz]
    A2 --> A5[metadata/manifest.json]
    A1 -. spider_closed .-> A6[Finalize run: flush + counts]
    A6 --> A7[Uploader: retry/backoff]
  end

  subgraph B_GCS_Bronze
    B1[(bronze/crawls/app_env/crawler/date/run_id)]
    B1m[(bronze/crawls/metadata/app_env/crawler/date/run_id)]
    B2[products.jsonl.gz]
    B4[manifest.json]
    B5{{Verify hashes and rowcounts}}
    B6[_SUCCESS]
  end

  subgraph C_Silver_Products
    C1[ETL: JSONL → Parquet + Extract Image URLs]
    C2[(silver/products/ingest_date)]
    C3[products.parquet]
    C4[_SUCCESS]
  end

  subgraph D_Image_Processing
    D1[Image Downloader]
    D2[(silver/images/ingest_date/run_id)]
  end

  A7 --> B1
  A7 --> B1m
  B1 --> B2
  B1m --> B4
  B4 --> B5
  B2 --> B5
  B5 -->|OK| B6
  B5 -->|FAIL| A7

  B6 -. trigger .-> C1
  C1 --> C2 --> C3 --> C4
  C1 -. triggers .-> D1
  D1 --> D2
