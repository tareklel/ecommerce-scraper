import concurrent.futures
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from ecommercecrawl.constants import farfetch_constants
from ecommercecrawl.constants import level_constants
from ecommercecrawl.constants import ounass_constants
from ecommercecrawl.constants.mastercrawl_constants import RUN_ID_DATETIME_FORMAT


logger = logging.getLogger(__name__)


RESULT_SCHEMA_VERSION = "image_download_result_v1"
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_SKIPPED_INVALID = "skipped_invalid"
STATUS_SKIPPED_DUPLICATE = "skipped_duplicate"


SITE_ALIASES = {
    "farfetch": farfetch_constants.NAME,
    "level": level_constants.NAME,
    "level-shoes": level_constants.NAME,
    "level_shoes": level_constants.NAME,
    "ounass": ounass_constants.NAME,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    now = datetime.now(timezone.utc)
    main_part = now.strftime(RUN_ID_DATETIME_FORMAT)
    ms_part = f"{now.microsecond // 1000:03d}"
    return f"{main_part}-{ms_part}"


def normalize_site(site: str) -> str:
    if not site or not site.strip():
        raise ValueError("site is required")

    key = site.strip().lower()
    normalized = SITE_ALIASES.get(key)
    if not normalized:
        supported = ", ".join(sorted(SITE_ALIASES.keys()))
        raise ValueError(f"Unsupported site '{site}'. Supported values: {supported}")
    return normalized


def normalize_image_url(site: str, image_url: str) -> str:
    if not image_url or not image_url.strip():
        raise ValueError("image_url is required")

    raw = image_url.strip()
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("//"):
        return f"https:{raw}"

    # Ounass currently stores image paths without a scheme in crawl output.
    if site == ounass_constants.NAME:
        return f"https://{raw.lstrip('/')}"

    # For all other sites, default to https for scheme-less URLs.
    return f"https://{raw.lstrip('/')}"


def get_site_headers(site: str) -> Dict[str, str]:
    if site == level_constants.NAME:
        return {
            "user-agent": level_constants.API_HEADERS.get("user-agent", "Mozilla/5.0"),
            "referer": level_constants.MAIN_SITE,
        }
    if site == ounass_constants.NAME:
        return {
            "user-agent": "Mozilla/5.0",
            "referer": ounass_constants.MAIN_SITE,
        }
    if site == farfetch_constants.NAME:
        return {
            "user-agent": "Mozilla/5.0",
            "referer": farfetch_constants.MAIN_SITE,
        }
    return {"user-agent": "Mozilla/5.0"}


def build_job_id(site: str, primary_key: str, image_url: str) -> str:
    payload = f"{site}|{primary_key}|{image_url}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def extension_from_url(image_url: str) -> str:
    path = urlparse(image_url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        return suffix
    return ".jpg"


def extension_from_content_type(content_type: Optional[str]) -> Optional[str]:
    if not content_type:
        return None
    value = content_type.lower().split(";")[0].strip()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }
    return mapping.get(value)


def is_image_content_type(content_type: Optional[str]) -> bool:
    if not content_type:
        return True
    return content_type.lower().strip().startswith("image/")


def build_output_path(
    output_dir: str,
    download_run_id: str,
    site: str,
    primary_key: str,
    image_url: str,
    source_run_id: Optional[str] = None,
) -> str:
    run_id = source_run_id or download_run_id
    ext = extension_from_url(image_url)
    url_hash = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:10]
    safe_primary_key = str(primary_key).strip().replace("/", "_")
    file_name = f"{safe_primary_key}_{url_hash}{ext}"
    return os.path.join(output_dir, site, run_id, file_name)


def build_canonical_blob_key(content_sha256: str, ext: str) -> str:
    return f"silver/images/by-hash/{content_sha256}{ext}"


def build_primary_key_pointer_key(site: str, primary_key: str, content_sha256: str, ext: str) -> str:
    return f"silver/images/by-primary/{site}/{primary_key}/{content_sha256}{ext}"


def _result_blob(
    *,
    status: str,
    reason: str,
    download_run_id: str,
    job_id: Optional[str] = None,
    site: Optional[str] = None,
    primary_key: Optional[str] = None,
    source_run_id: Optional[str] = None,
    image_url: Optional[str] = None,
    normalized_image_url: Optional[str] = None,
    output_path: Optional[str] = None,
    canonical_blob_key: Optional[str] = None,
    primary_key_pointer_key: Optional[str] = None,
    bytes_written: Optional[int] = None,
    content_sha256: Optional[str] = None,
    content_type: Optional[str] = None,
    http_status: Optional[int] = None,
    error: Optional[Exception] = None,
    error_message: Optional[str] = None,
    input_source: Optional[dict] = None,
    details: Optional[dict] = None,
) -> dict:
    blob = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "event_time_utc": utc_now_iso(),
        "download_run_id": download_run_id,
        "job": {
            "job_id": job_id,
            "site": site,
            "primary_key": primary_key,
            "source_run_id": source_run_id,
            "input_source": input_source,
        },
        "request": {
            "image_url": image_url,
            "normalized_image_url": normalized_image_url,
        },
        "storage": {
            "output_path": output_path,
            "canonical_blob_key": canonical_blob_key,
            "primary_key_pointer_key": primary_key_pointer_key,
        },
        "transfer": {
            "bytes": bytes_written,
            "content_sha256": content_sha256,
            "content_type": content_type,
            "http_status": http_status,
        },
        "error": None,
        "details": details or {},
    }
    if error or error_message:
        blob["error"] = {
            "type": type(error).__name__ if error else None,
            "message": error_message or str(error),
        }
    return blob


def extract_jobs_and_skips_from_jsonl(
    path: str,
    site_override: Optional[str] = None,
    download_run_id: Optional[str] = None,
) -> Tuple[List[dict], List[dict]]:
    jobs: List[dict] = []
    skipped: List[dict] = []
    run_id = download_run_id or generate_run_id()
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            row = line.strip()
            if not row:
                continue
            try:
                payload = json.loads(row)
            except json.JSONDecodeError:
                logger.warning("Skipping invalid JSON line %s in %s", line_no, path)
                skipped.append(
                    _result_blob(
                        status=STATUS_SKIPPED_INVALID,
                        reason="invalid_json",
                        download_run_id=run_id,
                        input_source={"jsonl_path": path, "line_no": line_no},
                    )
                )
                continue

            raw_site = site_override or payload.get("site")
            raw_primary_key = payload.get("primary_key") or payload.get("unique_id")
            raw_image_url = payload.get("image_url") or payload.get("image_urls")
            source_run_id = payload.get("source_run_id") or payload.get("run_id")
            if not raw_primary_key and payload.get("portal_itemid") and raw_site:
                # Transitional fallback for older crawler outputs:
                # derive primary_key from portal_itemid + site.
                raw_primary_key = f"{payload.get('portal_itemid')}_{raw_site}"

            if not raw_site or not raw_primary_key or not raw_image_url:
                missing_fields = []
                if not raw_site:
                    missing_fields.append("site")
                if not raw_primary_key:
                    missing_fields.append("primary_key")
                if not raw_image_url:
                    missing_fields.append("image_url/image_urls")

                logger.info(
                    "Skipping line %s: missing one of site/primary_key/image_url",
                    line_no,
                )
                skipped.append(
                    _result_blob(
                        status=STATUS_SKIPPED_INVALID,
                        reason="missing_required_fields",
                        download_run_id=run_id,
                        input_source={"jsonl_path": path, "line_no": line_no},
                        details={"missing_fields": missing_fields},
                    )
                )
                continue

            jobs.append(
                {
                    "site": raw_site,
                    "primary_key": str(raw_primary_key),
                    "image_url": raw_image_url,
                    "source_run_id": source_run_id,
                    "_input_source": {"jsonl_path": path, "line_no": line_no},
                }
            )
    return jobs, skipped


def extract_jobs_from_jsonl(path: str, site_override: Optional[str] = None) -> List[dict]:
    jobs, _ = extract_jobs_and_skips_from_jsonl(
        path=path,
        site_override=site_override,
    )
    return jobs


def download_one_job(
    job: dict,
    output_dir: str,
    download_run_id: str,
    timeout_seconds: int = 20,
) -> dict:
    try:
        site = normalize_site(job["site"])
        primary_key = str(job["primary_key"]).strip()
        normalized_url = normalize_image_url(site, job["image_url"])
        source_run_id = job.get("source_run_id")
        input_source = job.get("_input_source")
    except Exception as e:
        return _result_blob(
            status=STATUS_ERROR,
            reason="invalid_job_input",
            download_run_id=download_run_id,
            error=e,
            details={"job": job},
        )

    output_ext = extension_from_url(normalized_url)
    output_path = build_output_path(
        output_dir=output_dir,
        download_run_id=download_run_id,
        site=site,
        primary_key=primary_key,
        image_url=normalized_url,
        source_run_id=source_run_id,
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    headers = get_site_headers(site)
    job_id = build_job_id(site, primary_key, normalized_url)

    try:
        response = requests.get(normalized_url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type") if getattr(response, "headers", None) else None
        if not is_image_content_type(content_type):
            return _result_blob(
                status=STATUS_ERROR,
                reason="non_image_content_type",
                download_run_id=download_run_id,
                job_id=job_id,
                site=site,
                primary_key=primary_key,
                source_run_id=source_run_id,
                image_url=job["image_url"],
                normalized_image_url=normalized_url,
                input_source=input_source,
                content_type=content_type,
                http_status=getattr(response, "status_code", None),
                error_message=f"Expected image content type, got {content_type}",
            )

        content = response.content
        content_sha256 = hashlib.sha256(content).hexdigest()
        content_ext = extension_from_content_type(content_type) or output_ext
        canonical_blob_key = build_canonical_blob_key(content_sha256=content_sha256, ext=content_ext)
        primary_pointer_key = build_primary_key_pointer_key(
            site=site,
            primary_key=primary_key,
            content_sha256=content_sha256,
            ext=content_ext,
        )

        with open(output_path, "wb") as f:
            f.write(content)
    except Exception as e:
        return _result_blob(
            status=STATUS_ERROR,
            reason="request_failed",
            download_run_id=download_run_id,
            job_id=job_id,
            site=site,
            primary_key=primary_key,
            source_run_id=source_run_id,
            image_url=job.get("image_url"),
            normalized_image_url=normalized_url,
            input_source=input_source,
            error=e,
        )

    return _result_blob(
        status=STATUS_OK,
        reason="downloaded",
        download_run_id=download_run_id,
        job_id=job_id,
        site=site,
        primary_key=primary_key,
        source_run_id=source_run_id,
        image_url=job["image_url"],
        normalized_image_url=normalized_url,
        input_source=input_source,
        output_path=output_path,
        canonical_blob_key=canonical_blob_key,
        primary_key_pointer_key=primary_pointer_key,
        bytes_written=len(content),
        content_sha256=content_sha256,
        content_type=content_type,
        http_status=getattr(response, "status_code", None),
    )


def download_jobs(
    jobs: List[dict],
    output_dir: str = "output/images",
    max_workers: int = 10,
    timeout_seconds: int = 20,
    download_run_id: Optional[str] = None,
) -> List[dict]:
    run_id = download_run_id or generate_run_id()
    results: List[dict] = []
    deduped: List[dict] = []
    seen_job_ids = set()

    for job in jobs:
        try:
            site = normalize_site(job["site"])
            image_url = normalize_image_url(site, job["image_url"])
            primary_key = str(job["primary_key"]).strip()
            job_id = build_job_id(site, primary_key, image_url)
        except Exception as e:
            results.append(
                _result_blob(
                    status=STATUS_SKIPPED_INVALID,
                    reason="invalid_job_input",
                    download_run_id=run_id,
                    error=e,
                    details={"job": job},
                )
            )
            continue

        if job_id in seen_job_ids:
            results.append(
                _result_blob(
                    status=STATUS_SKIPPED_DUPLICATE,
                    reason="duplicate_job",
                    download_run_id=run_id,
                    job_id=job_id,
                    site=site,
                    primary_key=primary_key,
                    source_run_id=job.get("source_run_id"),
                    image_url=job.get("image_url"),
                    normalized_image_url=image_url,
                    input_source=job.get("_input_source"),
                )
            )
            continue
        seen_job_ids.add(job_id)
        deduped.append(job)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                download_one_job,
                job=job,
                output_dir=output_dir,
                download_run_id=run_id,
                timeout_seconds=timeout_seconds,
            )
            for job in deduped
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results
