#!/usr/bin/env python3
"""Build the small, attributed UCI transaction sample used by the fraud data pack."""

from __future__ import annotations

import argparse
import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd


UCI_ARCHIVE_URL = "https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip"
DEFAULT_OUTPUT = Path("data/fraud_detection/transactions/uci_online_retail_sample.csv")
RANDOM_SEED = 20261017


def customer_ref(value: object) -> str:
    if pd.isna(value):
        return ""
    normalized = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    digest = hashlib.sha256(f"uci-online-retail:{normalized}".encode("utf-8")).hexdigest()
    return f"cust_{digest[:12]}"


def download_source() -> pd.DataFrame:
    request = urllib.request.Request(UCI_ARCHIVE_URL, headers={"User-Agent": "nemotron-ops-commander-data-prep/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        archive_bytes = response.read()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        workbook_name = next(name for name in archive.namelist() if name.lower().endswith(".xlsx"))
        with archive.open(workbook_name) as workbook:
            return pd.read_excel(workbook)


def build_sample(frame: pd.DataFrame, sample_size: int = 1000) -> pd.DataFrame:
    df = frame.rename(
        columns={
            "InvoiceNo": "invoice_id",
            "StockCode": "product_id",
            "Description": "product_description",
            "Quantity": "quantity",
            "InvoiceDate": "event_time",
            "UnitPrice": "unit_price_gbp",
            "CustomerID": "customer_id_source",
            "Country": "country",
        }
    ).copy()
    df["invoice_id"] = df["invoice_id"].astype(str)
    df["is_cancellation"] = df["invoice_id"].str.upper().str.startswith("C")
    df["is_nonpositive_quantity"] = df["quantity"] <= 0
    df["is_nonpositive_price"] = df["unit_price_gbp"] <= 0
    positive_prices = df.loc[df["unit_price_gbp"] > 0, "unit_price_gbp"]
    positive_quantities = df.loc[df["quantity"] > 0, "quantity"]
    price_p99 = float(positive_prices.quantile(0.99))
    quantity_p99 = float(positive_quantities.quantile(0.99))
    df["is_high_unit_price_p99"] = df["unit_price_gbp"] >= price_p99
    df["is_high_quantity_p99"] = df["quantity"] >= quantity_p99

    def take(mask: pd.Series, n: int, seed_offset: int) -> pd.DataFrame:
        subset = df.loc[mask]
        return subset.sample(n=min(n, len(subset)), random_state=RANDOM_SEED + seed_offset)

    selected = pd.concat(
        [
            take(df["is_cancellation"], 220, 1),
            take(df["is_nonpositive_price"], 80, 2),
            take(df["is_high_unit_price_p99"], 150, 3),
            take(df["is_high_quantity_p99"], 150, 4),
            take(~(df["is_cancellation"] | df["is_nonpositive_price"] | df["is_high_unit_price_p99"] | df["is_high_quantity_p99"]), 600, 5),
        ],
        ignore_index=False,
    ).drop_duplicates()

    if len(selected) < sample_size:
        remaining = df.drop(index=selected.index, errors="ignore")
        selected = pd.concat(
            [selected, remaining.sample(n=min(sample_size - len(selected), len(remaining)), random_state=RANDOM_SEED + 6)]
        )
    selected = selected.sample(n=min(sample_size, len(selected)), random_state=RANDOM_SEED + 7).copy()
    selected["customer_ref"] = selected["customer_id_source"].map(customer_ref)
    selected["line_total_gbp"] = (selected["quantity"] * selected["unit_price_gbp"]).round(2)
    selected["event_time"] = pd.to_datetime(selected["event_time"]).dt.strftime("%Y-%m-%dT%H:%M:%S")

    def signal(row: pd.Series) -> str:
        labels = []
        if row["is_cancellation"]:
            labels.append("cancellation")
        if row["is_nonpositive_quantity"]:
            labels.append("nonpositive_quantity")
        if row["is_nonpositive_price"]:
            labels.append("nonpositive_price")
        if row["is_high_unit_price_p99"]:
            labels.append("high_unit_price_p99")
        if row["is_high_quantity_p99"]:
            labels.append("high_quantity_p99")
        return "|".join(labels) if labels else "baseline"

    selected["candidate_signal"] = selected.apply(signal, axis=1)
    selected["is_anomaly_candidate"] = selected["candidate_signal"] != "baseline"
    selected["currency"] = "GBP"
    selected["dataset_source"] = "UCI Online Retail (CC BY 4.0)"
    selected = selected.drop(columns=["customer_id_source"])
    columns = [
        "invoice_id",
        "event_time",
        "product_id",
        "product_description",
        "quantity",
        "unit_price_gbp",
        "line_total_gbp",
        "currency",
        "customer_ref",
        "country",
        "is_cancellation",
        "is_nonpositive_quantity",
        "is_nonpositive_price",
        "is_high_unit_price_p99",
        "is_high_quantity_p99",
        "candidate_signal",
        "is_anomaly_candidate",
        "dataset_source",
    ]
    return selected[columns]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=1000)
    args = parser.parse_args()
    frame = download_source()
    sample = build_sample(frame, sample_size=args.sample_size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(args.output, index=False)
    print(f"Wrote {len(sample):,} rows to {args.output}")


if __name__ == "__main__":
    main()
