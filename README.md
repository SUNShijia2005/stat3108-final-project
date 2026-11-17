# Parcel Desk — Cross-Border Parcel Assistant

STAT3108 Applied Deep Learning and AI · Fall 2026

A runnable local workspace for one customer-packaged parcel from mainland China to the United States. It keeps a shipment task across turns, calculates source-grounded public-rate estimates, retrieves reference passages, checks invoice/packing-list consistency, and displays tracking events.

## Start

Python 3.9+; no packages needed for the app or tests.

```bash
python3 app.py
```

Open http://127.0.0.1:8765. On macOS, `run_local.command` starts the same server. Select **载入完整演示** for a 10 kg Shanghai–Los Angeles request with fictional contacts, document items and the cached official tracking example. The local demo does not call a model or consume Ship24 shipment allowance.

Tasks persist in ignored `var/parcel.sqlite3`. The last task is restored in the same browser. Updates carry a version to prevent stale requests from overwriting newer records. The server binds to loopback only.

## Current implementation

| Feature | Implementation |
| --- | --- |
| Conversation | Chinese/English workflow, explicit field extraction, missing fields, multi-turn updates and execution trace |
| Rates | IPE/IP/IE, 41 half-kilogram breaks from 0.5–20.5 kg, 10 zones: **1,230 rate cells**; US routes use zones 1 and 2 |
| Weight/charges | Actual vs dimensional weight, ceiling to 0.5 kg, source-version US processing fee, confirmed ODA/residential choices, optional fuel scenario |
| Retrieval | **13 curated bilingual passages**; keyword, BM25, BM25 + word/character TF-IDF rank fusion; source/page/date links |
| Documents | Contacts/items, independent CSV imports, required-field/arithmetic/quantity checks, original printable HTML invoice and packing-list drafts |
| Tracking | Cached official synthetic Ship24 example; separately enabled real-number API lookup |
| Optional LLM | Responses function-calling loop, bounded rounds, tool execution and explicit local fallback |
| Evaluation | **53 offline tests**, 18 retrieval queries and prepared 12-case three-arm model experiment |

The default is **local workflow mode**. No live LLM experiment has run. The UI states its mode. Model transport and function-call handling are tested using mocked responses.

## Checks

```bash
python3 scripts/evaluate.py
```

Writes `results/evaluation.json`; HTTP tests briefly start a loopback server. Recorded result: **53/53 passed**. Retrieval top-1: keyword **16/18**, BM25 **17/18**, hybrid **17/18**; all top-3 **18/18**. The questions are a small developer-authored set, not an independent held-out benchmark or LLM comparison.

## Optional services

Copy `.env.example` to `.env.local`; local config is excluded from Git.

- LLM: `LLM_API_KEY`, `LLM_MODEL`; optional `LLM_BASE_URL` defaults to `https://api.openai.com/v1` and requires compatible HTTPS Responses support. Using the model sends current shipment fields and recent dialogue to that configured provider.
- Ship24: `SHIP24_API_KEY` or local `ship24_key.txt`. The existing outer project key is also recognized. No key is bundled. A real query requires the tracking page's explicit checkbox; the official example always uses the cache.

```bash
python3 scripts/compare_models.py
```

This only prints the prepared scope. When deliberately using model API credits, `python3 scripts/compare_models.py --run` runs 12 synthetic cases in baseline, retrieved-context and tool-enabled arms. `--limit 1` runs one case per arm. Results go to ignored `results/private/` with raw responses, traces, latency, model/prompt/case fingerprints and blank manual scoring fields. No accuracy is prefilled. The tool arm can make up to four model requests per case.

## Data and scope

The wider source collection has **39 local PDFs / 106 pages** plus web snapshots and structured records. Raw PDFs remain local; this repo carries manifests and structured extracts. The app uses applicable FedEx parcel documents, customs-document guidance and one tracking fixture. Ocean-container rates and cargo-airline schedules do not establish parcel prices or arrival dates.

`data/parcel/rates.json` retains the source URL, PDF hash, page numbers, collection date and effective date. It is a **2026 public promotional reference**, subject to account/China-payer eligibility, for export origins outside Guangdong/Fujian. It is not a live account quote. Fuel, taxes, clearance charges, address coverage and arrival commitments require confirmation. Battery/liquid descriptions, nonstandard dimensions, unsupported origins and weights beyond the extracted range route to review.

Fuel scenarios apply a supplied percentage to base freight only; actual fuel percentage and surcharge base remain unverified. ODA tiers are provided explicitly, not inferred from a ZIP code. The calculator covers one customer-packaged parcel, not multi-piece, Envelope/Pak or freight services.

The Ship24 fixture has four **French** events. It demonstrates the API/status workflow and is unrelated to the China–US task. Authentication and an official synthetic request were previously checked through the live API. No customer's real shipment has been tested.

Document drafts are authored for this prototype using official field guidance. They are not downloaded official templates or completed customs submissions. Export opens printable HTML, which the browser can save as PDF.

## Files

| Path | Purpose |
| --- | --- |
| `app.py`, `static/` | Local app and six-view interface |
| `parcel/` | Rates, retrieval, storage, tracking, optional model tools |
| `data/parcel/` | Rate cells and bilingual knowledge passages |
| `scripts/prepare_parcel_data.py` | Re-extract retained PDF rates; optional pypdf dependency |
| `scripts/evaluate.py`, `tests/` | Offline tests and retrieval comparison |
| `scripts/compare_models.py` | Prepared optional three-arm model experiment |
| `results/evaluation.json` | Recorded component results |
| `docs/proposal_zh.md` | Revised proposal and current progress |
| `docs/project_report_zh.md` | Methods, results and remaining research work |
| `docs/demo_zh.md` | Short demonstration walkthrough |
| `data/README.md` | Wider data inventory |

Re-extract with `python3 scripts/prepare_parcel_data.py --source-dir /path/to/data/air_sources`; the retained raw export PDF and original structured 10 kg anchors must be present. See `--help` and script for details.

## Sources

- [FedEx China rates](https://www.fedex.com/en-cn/shipping/rates.html)
- [2026 reference rates](https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-exp-en-cno-2026.pdf)
- [2026 zones](https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-zi-en-cn-2026.pdf)
- [2026 surcharges](https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-sur-en-cn-2026.pdf)
- [FedEx customs documents](https://www.fedex.com/en-cn/new-customer/how-to-prepare-customs-documents.html)
- [Ship24 documentation](https://docs.ship24.com/getting-started)
- [Responses function calling](https://developers.openai.com/api/docs/guides/function-calling)

Third-party sources retain their rights. AI assistance was used for implementation, extraction and documentation. Component tests are separate from future live-model and user evaluations.
