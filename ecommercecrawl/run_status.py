"""
Plain-language explanations of run failure reasons, used in the crawler's
end-of-run log lines (pipelines.PostCrawlPipeline) so a failure explains
itself where it's met. The verifier Lambda can't import this package (it is
deployed as its own zip), so it keeps an identical copy in
lambda/bronze_manifest_verifier/handler.py (FAILURE_REASONS);
tests/test_run_status_explanations.py fails if the two differ.
Reference: docs/crawl_run_status.md.
"""

RUN_STATUS_DOC = "docs/crawl_run_status.md#failure-markers"

FAILURE_EXPLANATIONS = {
    "aborted": {
        "meaning": "The crawl was stopped before it finished (Ctrl+C, ECS task stopped, timeout); its rows are not published.",
        "what_to_do": "Re-run the crawl. If it keeps happening, check why the task was stopped.",
    },
    "startup_check": {
        "meaning": "The PLP-efficient crawl stopped before making any request because a startup check failed.",
        "what_to_do": "Run `make preflight-ounass-plp-efficient` to list every failed check.",
    },
    "access": {
        "meaning": "Nothing was written because the site blocked our requests through every retry round.",
        "what_to_do": "See the manifest's access block for which hostnames and errors; check Zyte routing (CRAWLER_API_ZYTE_GEOLOCATION_BY_HOST); re-run later.",
    },
    "quality": {
        "meaning": "The rows failed the quality gate, or nothing was written for a reason other than blocking.",
        "what_to_do": "Read metadata/quality_report.json; check the seed URLs still exist and the page format hasn't changed.",
    },
    "verification": {
        "meaning": "The data file failed verification (missing, hash or row-count mismatch, unreadable manifest, or the publish copy failed).",
        "what_to_do": "Check the verifier Lambda's logs, then re-run the crawl.",
    },
}

# Degraded runs publish everything they wrote; the manifest lists each skip.
DEGRADED_MEANING = ("Some work was skipped (listed below); everything the run wrote "
                    "is still published.")
