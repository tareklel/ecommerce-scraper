- We are building a luxury clothing price comparison website. See `context/product-brief.md` for the full product vision.
- This repo manages crawler activity and Lambdas related to crawler activity.
- After every commit, append a semi-concise summary of what changed to `context/memory.md`.
- Write comments to explain intent, assumptions, and non-obvious logic. Keep comments concise and specific.
- Before writing changes to files, first explain to me what you plan to do and then do changes once you get agreement.

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
