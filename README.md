# AI Customer Service Agent for Cross-Border Parcel Shipping

STAT3108 Applied Deep Learning and AI · Fall 2026

A Chinese/English logistics assistant for small parcels from China to the United States. The planned workflow combines customer clarification, official-document retrieval, public-rate estimates, document checks, and shipment tracking.

## Progress as of November 17, 2026

- Verified Ship24 authentication by retrieving the courier list.
- Queried SHIP24_SAMPLE_DELIVERED_000 through the API and saved four tracking events. This is an **official synthetic sample**, not a customer's shipment.
- Inventoried **39 local PDF files / 106 pages**, plus web snapshots and structured records. This repository includes structured samples, source manifests, and collection notes; raw documents remain local.
- Updated the proposal around RAG, structured outputs, and executed tools.

The web application, LLM integration, retrieval index, general-purpose rate calculator, document workflows, and evaluation suite are the next tasks.

## Contents

| Path | Contents |
| --- | --- |
| ship24_connection_check.py | Read-only authentication check |
| ship24_sample_check.py | Query an official example and cache its response |
| ship24_key.example.txt | Local credential template |
| data/ship24/ | Official synthetic tracking fixture; internal identifiers redacted |
| data/air_sources/ | Flight plans, FedEx zone-rate samples, fuel surcharges, sources |
| data/global_sources/ | Ocean rates, standard transit times, local fees, sources |
| data/feasibility_check/ | Dated sailings, advisories, and collection checks |
| data/source_discovery/ | Initial verified reference samples and source manifest |
| data/README.md | Inventory and current coverage |
| docs/proposal_zh.md | Updated Chinese proposal |

## Run

Requires Python 3 and the standard library. Obtain a key from the [Ship24 dashboard](https://dashboard.ship24.com/). Copy ship24_key.example.txt to ship24_key.txt and replace the placeholder with your key, or set the SHIP24_API_KEY environment variable. The credential file is excluded by .gitignore.

```bash
python3 ship24_connection_check.py
python3 ship24_sample_check.py
```

The first command reads the courier list without creating a tracker. The second uses the bundled cached fixture if present, so it makes no network call on a fresh checkout. To repeat the live sample request, move that JSON file aside before running. Creating trackers may use the account's shipment allowance; keep the same sample number and payload when repeating the request.

## Planned workflow and evaluation

Collect goods, origin/destination, weight, dimensions, budget, and delivery needs. Retrieve applicable rules, calculate a public-rate estimate with an itemized breakdown, and update the task when the customer changes details. Prepare invoice and packing-list drafts, check quantities and arithmetic, and explain shipment events within the same task.

Compare a baseline chatbot, retrieval-augmented chatbot, and retrieval-plus-tools assistant on approximately 30 fixed cases. Measure calculation accuracy, retrieval relevance, tool/argument correctness, document-error detection, task completion, and latency. Save data timestamps and model/prompt versions.

## Data interpretation

The 20 extracted FedEx rates are 10 kg import/export zone examples, not a full rate calculator or live account quotes. Ocean-container and cargo-airline records are supplementary; they do not establish parcel prices or door-to-door delivery times. Most reference material was collected November 5–6, 2026. Check each source's effective dates.

## Sources and acknowledgements

- [FedEx China rates and zones](https://www.fedex.com/en-cn/shipping/rates.html)
- [FedEx China customs-document guide](https://www.fedex.com/en-cn/new-customer/how-to-prepare-customs-documents.html)
- [Ship24 API](https://docs.ship24.com/getting-started)
- [Ship24 official sample numbers](https://docs.ship24.com/status#ship24-sample-tracking-numbers)

Collection manifests retain other original URLs. Third-party source documents retain their original rights. AI coding assistance was used for API checks and documentation; commits record development and verification.
