- We are building a luxury clothing price comparison website. See `context/product-brief.md` for the full product vision.
- This repo manages crawler activity and Lambdas related to crawler activity.
- After every commit, append a semi-concise summary of what changed to `context/memory.md`.
- Write comments to explain intent, assumptions, and non-obvious logic. Keep comments concise and specific.
- Before writing changes to files, first explain to me what you plan to do and then do changes once you get agreement.
- Ounass PLP-efficient crawl mode is documented in `docs/ounass_plp_efficient_crawl.md`, which describes how the mode works today. Any change to its behaviour (spider, rules, settings, quality gate, manifest, verifier Lambda, input contracts) must update that doc in the same commit, including its change log. `tests/test_plp_efficient_docs.py` fails if an `OUNASS_PLP_EFFICIENT_*` setting is missing from the doc.
- Run statuses, failure reasons and S3 markers (all crawls) are documented in `docs/crawl_run_status.md`. Any change to them (`pipelines.crawler_run_status`, the verifier Lambda's `FAILURE_REASONS` / markers) must update that doc in the same commit. `tests/test_crawl_run_status_docs.py` fails if a marker, status or failure reason in the verifier is missing from the doc. Quality-gate rule changes must update `docs/fail_quality_contract.md`.

# Security-sensitive actions

This repository is used on a company-managed device. Commands that are technically
legitimate can still resemble credential access, reconnaissance, data exfiltration,
or security-control bypass to endpoint monitoring.

- Never run `make run-api-local` while it exports a certificate from the macOS
  Keychain. Never run `security`, `security find-certificate`, or any equivalent
  Keychain, credential, password, private-key, or certificate export command.
- Never disable or weaken TLS verification (`curl -k`, `--insecure`,
  `verify=False`, `--no-verify-ssl`, or equivalents) and never attempt to bypass
  endpoint, proxy, authentication, or company security controls.
- Prefer ignored offline fixtures for local UI and API development. Starting the
  normal local development environment must not access AWS, query a Keychain, export
  certificates, or download data implicitly.
- Before any action that could reasonably look like credential access, secret
  discovery, Keychain/certificate access, port or network scanning, broad cloud
  enumeration, permission changes, bulk external download/upload, or security-tool
  execution: stop and ask for explicit user approval.
- The approval request must show the exact proposed command or action, explain why it
  is needed, describe the data and systems it will touch, and offer a safer
  alternative when one exists. Do not execute the action until approval is given.
- Never commit credentials, certificates, company proxy material, API keys, or
  downloaded product data and images. Keep local fixtures under ignored paths.
- Normal source inspection, local unit tests, formatting, and builds are allowed when
  they do not access external systems or security-sensitive stores.

# Syncing With GitHub (Laptop and Cloud Sessions)

The user works both on the laptop and in cloud sessions started from the phone.
Cloud sessions clone from GitHub and push there; they never see the laptop.

- At the start of a session, and when resuming after a gap (a few hours or a new
  day), run `git fetch` in all three repos (`ecommerce-scraper`,
  `../scraper-pipeline`, `../price-comparison-web`) and compare each with
  `origin/main`. If one is behind, tell the user what came in (commit subjects,
  merged pull requests) and pull with `git pull --ff-only` before changing
  anything. If the pull would touch uncommitted changes, ask first.
- Also mention open pull requests waiting for the user (`gh pr list`).
- In a cloud session only this repo is cloned, so the siblings can't be
  checked locally; say so, or check them on GitHub with `gh`.
- When work is done, commit and push it, and end the reply with one line naming
  what to pull, e.g. "Pushed to `ecommerce-scraper` `main`: pull on the
  laptop." If the work is on a branch or a pull request, name it and say it
  must be merged before pulling.
- Rules and handoffs belong in repo files (this file, tickets), not only in a
  local memory folder: cloud sessions see only what is on GitHub.

# Working Alongside Other Agents

- Other agent sessions may be working at the same time, in this repo or in sibling
  repos (`../scraper-pipeline`, `../price-comparison-web`). Before starting, check
  for them (list sessions, `git status`, `git worktree list`).
- Before editing files outside this repo, or files another session has claimed,
  send that session a heads-up: what you'll change, which files, and which you'll
  leave alone. Wait for a reply if they may already be working on it.
- When a session gives you a heads-up, reply with what you've already done in that
  area and any context it needs, and keep off the files it claims until it reports
  back.
- Commit only your own changes: stage files by path, never `git add -A`, and leave
  another session's uncommitted work alone.
