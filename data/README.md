# Data inventory

Checked against the local project on November 17, 2026. Different record types and overlapping source representations should not be summed as independent shipments or routes.

| Collection | Local raw PDFs / pages | Structured records included here |
| --- | --- | --- |
| air_sources | 8 / 36 | 438 Cargolux schedule rows; 94 dated ANA plans; 20 FedEx 10 kg zone rates; 6 Cathay fuel surcharges; 1 operational event |
| global_sources | 24 / 50 | 34 public ocean rates; 54 standard transit-time records; 8 local charges |
| feasibility_check | 5 / 8 | 35 dated sailing candidates; 12 advisory-index entries; 2 operational events |
| source_discovery | 2 / 12 | Initial samples: 8 standard transit times and 3 local charges |
| ship24 | 0 / 0 | 1 official synthetic shipment with 4 tracking events |
| Total local raw PDFs | **39 / 106** | All 39 files have distinct SHA-256 hashes |

Six FedEx PDFs within air_sources contain import/export rates, service zones, deferred-freight rates/zones, and surcharges. Cargo-airline schedules and ocean data are broader reference collections; the current China-to-US parcel task uses applicable parcel-service material.

## Preparation remaining

- Extract and validate required FedEx weight ranges, US zones, and applicable surcharges.
- Organize parcel-specific rules for retrieval.
- Download dedicated commercial-invoice and packing-list templates; no standalone templates were found during this inventory.
- Build approximately 30 customer test cases and expected outcomes.
- Validate real-shipment lookup when a usable number is available. No customer shipment has yet been queried.

## Files and reproduction

The root-level JSON and Markdown files from each reference collection are included. Raw PDFs, webpages, session captures, ZIP archives, and full-document text remain local. Historical manifests and notes retain original URLs and local paths; referenced raw files are not implied to be present here.

Use official URLs in manifests to obtain original documents and check effective dates and access terms. Earlier download scripts and raw snapshots remain in the local project. The Ship24 fixture was obtained through the live API using an official synthetic number; account-linked internal identifiers are redacted for publication.
