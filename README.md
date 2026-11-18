# Parcel Desk — Cross-Border Parcel Preparation

STAT3108 Applied Deep Learning and AI · Fall 2026

A local workspace for one customer-packaged parcel from mainland China to the United States. The customer flow is **shipment details → reference service selection → document checks → preparation summary**. Tracking and source lookup are separate tools; project metrics are in the optional evaluation view.

## Start

The app and Python tests use Python 3.9+ and the standard library.

```bash
python3 app.py
```

Open http://127.0.0.1:8765. On macOS, `zsh run_local.command` starts the same service. Choose **体验示例任务** for a fictional 10 kg Shanghai–Los Angeles request with document items. The example creates a separate task that remains distinguishable in task history.

Without a model key, the app runs its **offline workflow**: it calculates rates, checks documents and responds to a few basic conversational messages. It cannot answer arbitrary questions. The chat shows **尚未连接 AI 模型** and offers **启用 AI 对话**. No model key is included in Git. A local Gemini 3.1 Flash-Lite configuration successfully answered a general question through the app on November 17, 2026; see `results/live_connection_check_20261117.json`. Official sample tracking always uses its saved cache.

Tasks persist in ignored `var/parcel.sqlite3`; the service binds to loopback. The history selector reopens saved tasks. With browser storage available, unsaved package/document drafts are retained per task across navigation and reloads. They are labeled separately from saved task data. Saving sends changed fields only, preserves unrelated newer values, and reports conflicting edits instead of silently overwriting them.

## Workflow and behavior

1. **Record the shipment.** Enter goods, origin, US destination/ZIP, actual weight and dimensions, plus optional budget and deadline. The assistant distinguishes explicit edits from questions and hypothetical comparisons. For example, “如果改成8kg会便宜多少？先不要修改我的10kg需求” calculates a scenario while preserving the saved 10 kg task. An explicit “把重量改成8kg” updates the task. Changing destination without a matching new ZIP clears stale ZIP information.
2. **Compare and select a reference service.** Calculate IPE/IP/IE costs, inspect billable weight and sources, then select an option from the current saved estimate. Editing quote-related fields invalidates the old selection. A selection records a reference plan, not a booking or acceptance by the carrier.
3. **Check the documents.** Bring the existing goods description into editable invoice/packing-list lines; enter actual quantities and prices. Required-field, line-amount, total and quantity errors point to the relevant fields. CSV imports preserve the other document's quantities for comparison. Drafts survive unrelated actions, and unsaved package changes must be resolved before document preview.
4. **Review preparation.** The summary combines the saved shipment, selected reference service, document-check status and outstanding carrier/customs items. Invoice, packing-list and summary previews are printable HTML in the page, with an explicit new-tab/print link. The browser can save them as PDF.

The home view keeps the conversation input and next task action prominent. Current needs, selected service and four-step progress replace development counters on the customer home page. Processing state, draft state and request errors are visible.

## Conversation and model connection

Open **启用 AI 对话** or **AI 设置**, enter the provider's model ID and API key, and choose the API address/format if needed. **保存并启用** applies the configuration immediately; it saves settings, without sending a paid test request. A successful save means the settings are present, not that the provider has accepted the key or model. A later request failure is shown next to the reply with a settings link.

With a configured model, ordinary conversation, study questions, writing requests and shipment questions all reach that model. The prompt asks it to answer the actual question, follow the conversation and avoid steering unrelated messages into a shipment form. Routine statements such as “本轮没有修改已保存需求” are removed from reply templates. Actual shipment changes, trial comparisons and source records remain visible separately.

Each model request includes up to 24 recent messages, bounded to 18,000 history characters, plus selected shipment fields and concise quote/selection/check context. Structured contact, address, phone and item forms are excluded from that automatically supplied context; text entered in the chat is still sent as conversation. Shipment tools continue to enforce explicit edits and isolated scenarios independently of model wording. Conversation quality depends on the configured model and still needs live evaluation.

## Tools and data

| Tool | Current scope |
| --- | --- |
| Rates | IPE/IP/IE; 41 half-kilogram breaks from 0.5–20.5 kg × 10 zones = **1,230 rate cells**; US routes use zones 1 and 2 |
| Weight/charges | Higher of actual/dimensional weight, ceiling to 0.5 kg, source-version US processing fee, explicitly confirmed ODA/residential choices, optional base-freight fuel scenario |
| Retrieval | **13 curated bilingual passages**; keyword, BM25 and BM25 + word/character TF-IDF rank fusion, with source/page/date links |
| Documents | Shared contacts and editable items; CSV import, consistency checks, original printable drafts |
| Tracking | Explicit real-number form with a Ship24-usage checkbox; independently opened cached official example |
| Optional model | Responses or compatible Chat Completions, bounded conversation history and tool rounds, intent-gated writes, staged state and visible connection errors |

Reference rates come from a **2026 public promotional table**, subject to account/China-payer eligibility and export origins outside Guangdong/Fujian. They are not current account quotes. Date and scope are retained in `data/parcel/rates.json`, along with the source PDF hash and page numbers. Taxes, clearance charges, fuel, address coverage and arrival commitments remain separate checks. Unsupported origins, special goods, nonstandard dimensions and weights beyond the extracted range route to review.

Advanced surcharge fields are optional confirmed inputs. ODA is not inferred from ZIP alone. Fuel scenarios apply a supplied percentage to base freight only; the actual percentage and applicable surcharge base are unverified. The calculator covers a single customer-packaged parcel, not multi-piece, Envelope/Pak or freight services.

The wider collection remains **39 local PDFs / 106 pages** plus web snapshots and structured records. Raw PDFs stay local. Ocean-container rates and cargo-airline schedules do not establish parcel prices or arrival dates.

The official Ship24 fixture contains four **French** events and is unrelated to the China–US task. Chat does not substitute that example for an unspecified real shipment. Real queries require an entered number and the tracking form's checkbox. Authentication and an official synthetic request were previously tested live; no customer's real shipment has been verified.

## Verification

```bash
python3 scripts/evaluate.py
node tests/drafts.test.cjs
```

The current Python status, totals, categories and individual outcomes are recorded in `results/evaluation.json` by the command above. The separate JavaScript draft-state suite has **17 checks** and requires Node.js; the app itself does not require Node. Cases include conversational routing, negated/hypothetical requests, protected model writes and rollback, model context and protocol handling, configuration persistence, selection invalidation, document issue locations, draft merges and conflict rebasing.

On the unchanged 18-question retrieval set, top-1 is keyword **16/18**, BM25 **17/18**, hybrid **17/18**; all top-3 are **18/18**. This is a small developer-authored set, not a held-out benchmark. Component totals are separate from browser interaction checks and do not establish end-user completion or live-model accuracy.

No live LLM comparison has run. Model transport and function-call contracts use mocked responses in the offline suite.

## Optional services and model experiment

Use the chat settings panel, or copy `.env.example` to `.env.local`. Configuration and runtime data are ignored by Git.

- LLM: `LLM_API_KEY`, `LLM_MODEL`; optional HTTPS `LLM_BASE_URL` defaults to `https://api.openai.com/v1`. `LLM_API_STYLE` is `responses` by default or `chat_completions` for compatible providers. The key is saved only in project-local `.env.local` with owner-only permissions; it is not returned by the settings API, written into task records or stored in browser storage. Changing the endpoint requires entering a key for that endpoint.
- Ship24: `SHIP24_API_KEY` or ignored local `ship24_key.txt`. The existing outer project key is also recognized. No credential is bundled.

`python3 scripts/compare_models.py` prints the prepared scope without requesting a model. Deliberate execution uses `python3 scripts/compare_models.py --run` for 12 synthetic cases in baseline, retrieved-context and tool-enabled arms; `--limit 1` limits it to one case per arm. Raw responses, tool traces, latency, model/prompt/case fingerprints and blank manual scores are written to ignored `results/private/`. The tool arm can make up to four model requests per case.

## Project files

| Path | Purpose |
| --- | --- |
| `app.py`, `static/`, `parcel/` | Local application, customer flow and business tools |
| `static/drafts.js`, `tests/drafts.test.cjs` | Browser draft merging/storage helpers and Node checks |
| `data/parcel/` | Rate cells and bilingual reference passages |
| `scripts/prepare_parcel_data.py` | Re-extract retained PDF rates; optional pypdf dependency |
| `scripts/evaluate.py`, `tests/test_*.py` | Python regression tests and retrieval comparison |
| `scripts/compare_models.py` | Prepared optional model experiment |
| `results/evaluation.json`, `results/README.md` | Recorded results and interpretation |
| `docs/demo.md` | Current walkthrough and interaction regression checks |
| `data/README.md` | Wider data inventory |

Earlier proposal/report documents and PDF exports are retained development snapshots; use the current walkthrough and generated results for the rewritten interface. Document drafts are project-authored from official field guidance, not downloaded official templates or completed customs submissions.

## Sources

- [FedEx China rates](https://www.fedex.com/en-cn/shipping/rates.html)
- [2026 reference rates](https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-exp-en-cno-2026.pdf)
- [2026 zones](https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-zi-en-cn-2026.pdf)
- [2026 surcharges](https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-sur-en-cn-2026.pdf)
- [FedEx customs documents](https://www.fedex.com/en-cn/new-customer/how-to-prepare-customs-documents.html)
- [Ship24 documentation](https://docs.ship24.com/getting-started)
- [Responses function calling](https://developers.openai.com/api/docs/guides/function-calling)

Third-party sources retain their rights. AI assistance was used for implementation, extraction and documentation. This prototype prepares information; it does not book shipments or submit customs documents.
