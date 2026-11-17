"""Extract factual rate rows from retained FedEx PDFs; preparation needs pypdf.

Run: python scripts/prepare_parcel_data.py --source-dir /path/to/data/air_sources
The running application itself uses only the Python standard library.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def main():
    from pypdf import PdfReader
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_dir / "raw/fedex_export_other_provinces.pdf"
    reader = PdfReader(source)
    services = []
    zones = list("ABCDEFGH") + ["1", "2"]
    for code, page, title in [("IPE", 1, "International Priority Express"), ("IP", 2, "International Priority"), ("IE", 4, "International Economy")]:
        rows = {}
        for line in reader.pages[page - 1].extract_text(extraction_mode="layout").splitlines():
            values = re.findall(r"\d[\d,]*\.\d{2}", line)
            if len(values) != 11:
                continue
            weight = float(values[0])
            if .5 <= weight <= 20.5 and weight * 2 == int(weight * 2):
                # Envelope/Pak rows occur first. The later ordinary-parcel row wins.
                rows[weight] = dict(zip(zones, [float(v.replace(",", "")) for v in values[1:]]))
        expected = [i / 2 for i in range(1, 42)]
        if sorted(rows) != expected:
            raise ValueError(f"Incomplete {code} extraction: {len(rows)} weight rows")
        services.append({"code": code, "name": title, "source_page": page,
                         "rates": [{"weight_kg": w, "zones": rows[w]} for w in expected]})
    reference = json.loads((args.source_dir / "public_rate_samples.json").read_text())
    for record in reference:
        if record["direction"] == "China export":
            assert services[1]["rates"][19]["zones"][record["zone"]] == record["base_transport_charge"]
    output = {"currency": "CNY", "effective_from": "2026-01-05", "collected_on": "2026-11-06",
              "source_url": "https://www.fedex.com/content/dam/fedex/international/rates/fedex-rates-exp-en-cno-2026.pdf",
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "packaging": "customer packaging", "direction": "China export excluding Guangdong/Fujian",
              "rate_type": "published promotional reference; eligibility applies", "services": services}
    path = Path(__file__).resolve().parents[1] / "data/parcel/rates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(f"Extracted {len(services)} services × 41 weights × 10 zones = 1230 rates; IP samples reconciled.")


if __name__ == "__main__":
    main()
