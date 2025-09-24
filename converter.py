
import sys
import re
import html
import pandas as pd
from pathlib import Path

# -----------------------------
# Config
# -----------------------------
# Options to treat as "non-physical" and drop entirely from variants.
EXCLUDE_OPTIONS = {"digital download"}

# Default Shopify fields & constants
DEFAULTS = {
    "Variant Inventory Policy": "deny",
    "Variant Fulfillment Service": "manual",
    "Variant Requires Shipping": "TRUE",
    "Variant Taxable": "TRUE",
    "Published": "TRUE",
}

# Mapping from Etsy CSV to possible image col names we may want to copy
IMAGE_COL_CANDIDATES = ["IMAGE1", "Image 1", "PRIMARY IMAGE URL", "IMAGE URL"]

# -----------------------------
# Helpers
# -----------------------------
def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:60] if s else ""

def to_list(cell):
    if pd.isna(cell):
        return []
    text = str(cell)
    if not text.strip():
        return []
    # Etsy separates by comma for multi-values
    return [html.unescape(x.strip()) for x in text.split(",") if x.strip()]

def lc(s: str) -> str:
    return s.strip().lower()

def pick_first_existing_col(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def align_skus_after_filter(all_options, keep_mask, skus):
    """
    If len(skus) == len(all_options), we can filter skus by the same keep_mask.
    Else we assume Etsy's SKU count already matches the kept options order (best effort).
    If still short, pad with "" (will be replaced by generated SKU).
    """
    if len(skus) == len(all_options):
        skus_clean = [s for s, keep in zip(skus, keep_mask) if keep]
    else:
        # Best-effort: assume positional mapping to kept options
        skus_clean = skus[:sum(keep_mask)]
    if len(skus_clean) < sum(keep_mask):
        skus_clean += [""] * (sum(keep_mask) - len(skus_clean))
    return skus_clean

# -----------------------------
# Core expansion (supports 1 or 2 variations)
# -----------------------------
def expand_etsy_row(row: pd.Series, image_col: str | None) -> list[dict]:
    title = str(row.get("TITLE", "")).strip()
    handle = slugify(title) or "item"

    price = row.get("PRICE")
    opt1_name = row.get("VARIATION 1 NAME") or row.get("VARIATION 1 TYPE") or ""
    opt1_vals_all = to_list(row.get("VARIATION 1 VALUES"))
    opt2_name = row.get("VARIATION 2 NAME") or row.get("VARIATION 2 TYPE") or ""
    opt2_vals_all = to_list(row.get("VARIATION 2 VALUES"))
    skus_all = to_list(row.get("SKU"))

    # Drop EXCLUDE_OPTIONS (e.g., "Digital Download") from both variation lists if present
    keep1_mask = [lc(v) not in EXCLUDE_OPTIONS for v in opt1_vals_all] if opt1_vals_all else []
    opt1_vals = [v for v, keep in zip(opt1_vals_all, keep1_mask) if keep] if opt1_vals_all else []

    keep2_mask = [lc(v) not in EXCLUDE_OPTIONS for v in opt2_vals_all] if opt2_vals_all else []
    opt2_vals = [v for v, keep in zip(opt2_vals_all, keep2_mask) if keep] if opt2_vals_all else []

    # Decide SKU alignment
    rows = []

    # Case A: Only variation 1
    if opt1_vals and not opt2_vals:
        skus_clean = align_skus_after_filter(opt1_vals_all, keep1_mask, skus_all)
        for i, (opt1, sku) in enumerate(zip(opt1_vals, skus_clean), 1):
            sku_final = sku or f"ETSY-{slugify(title)}-{i:02d}"
            row_out = {
                "Handle": handle,
                "Title": title if i == 1 else "",
                "Option1 Name": opt1_name or "Option",
                "Option1 Value": opt1,
                "Variant SKU": sku_final,
                "Variant Price": price,
            }
            if image_col:
                row_out["Image Src"] = row.get(image_col, "")
            row_out.update(DEFAULTS)
            rows.append(row_out)
        return rows

    # Case B: Only variation 2 (rare but handle)
    if opt2_vals and not opt1_vals:
        skus_clean = align_skus_after_filter(opt2_vals_all, keep2_mask, skus_all)
        for i, (opt2, sku) in enumerate(zip(opt2_vals, skus_clean), 1):
            sku_final = sku or f"ETSY-{slugify(title)}-{i:02d}"
            row_out = {
                "Handle": handle,
                "Title": title if i == 1 else "",
                "Option1 Name": opt2_name or "Option",
                "Option1 Value": opt2,
                "Variant SKU": sku_final,
                "Variant Price": price,
            }
            if image_col:
                row_out["Image Src"] = row.get(image_col, "")
            row_out.update(DEFAULTS)
            rows.append(row_out)
        return rows

    # Case C: Two variations: we try to map SKU list to Cartesian product order.
    if opt1_vals and opt2_vals:
        # Expected total variants after filtering
        total = len(opt1_vals) * len(opt2_vals)

        # If SKUs length matches total, assume row-major order: opt1[i], opt2[j]
        if len(skus_all) == total:
            idx = 0
            for i, opt1 in enumerate(opt1_vals):
                for j, opt2 in enumerate(opt2_vals):
                    sku = skus_all[idx] if idx < len(skus_all) else ""
                    idx += 1
                    sku_final = sku or f"ETSY-{slugify(title)}-{i+1:02d}{j+1:02d}"
                    row_out = {
                        "Handle": handle,
                        "Title": title if idx == 1 else "",
                        "Option1 Name": opt1_name or "Option1",
                        "Option1 Value": opt1,
                        "Option2 Name": opt2_name or "Option2",
                        "Option2 Value": opt2,
                        "Variant SKU": sku_final,
                        "Variant Price": price,
                    }
                    if image_col:
                        row_out["Image Src"] = row.get(image_col, "")
                    row_out.update(DEFAULTS)
                    rows.append(row_out)
            return rows
        else:
            # Fallback: try align along opt1 first; then repeat/pad across opt2
            base_skus = align_skus_after_filter(opt1_vals_all, keep1_mask, skus_all)
            for i, opt1 in enumerate(opt1_vals):
                for j, opt2 in enumerate(opt2_vals):
                    k = i if i < len(base_skus) else -1
                    sku = base_skus[k] if k >= 0 else ""
                    sku_final = sku or f"ETSY-{slugify(title)}-{i+1:02d}{j+1:02d}"
                    row_out = {
                        "Handle": handle,
                        "Title": title if (i == 0 and j == 0) else "",
                        "Option1 Name": opt1_name or "Option1",
                        "Option1 Value": opt1,
                        "Option2 Name": opt2_name or "Option2",
                        "Option2 Value": opt2,
                        "Variant SKU": sku_final,
                        "Variant Price": price,
                    }
                    if image_col:
                        row_out["Image Src"] = row.get(image_col, "")
                    row_out.update(DEFAULTS)
                    rows.append(row_out)
            return rows

    # No variations: single variant row
    sku_single = (to_list(row.get("SKU")) or [""])[0]
    row_out = {
        "Handle": handle,
        "Title": title,
        "Variant SKU": sku_single or f"ETSY-{slugify(title)}-01",
        "Variant Price": price,
    }
    if image_col:
        row_out["Image Src"] = row.get(image_col, "")
    row_out.update(DEFAULTS)
    return [row_out]


def etsy_to_shopify(input_csv: str, output_csv: str):
    df = pd.read_csv(input_csv, low_memory=False)
    # Pick an image column if present
    img_col = pick_first_existing_col(df, IMAGE_COL_CANDIDATES)

    all_rows = []
    for _, row in df.iterrows():
        expanded = expand_etsy_row(row, img_col)
        all_rows.extend(expanded)

    out_df = pd.DataFrame(all_rows)

    # Ensure Shopify mandatory columns exist (at least the common ones)
    mandatory_order = [
        "Handle","Title",
        "Option1 Name","Option1 Value",
        "Option2 Name","Option2 Value",
        "Variant SKU","Variant Price",
        "Variant Inventory Policy","Variant Fulfillment Service",
        "Variant Requires Shipping","Variant Taxable",
        "Image Src","Published",
    ]
    for col in mandatory_order:
        if col not in out_df.columns:
            out_df[col] = ""

    # Sort columns: mandatory first, then the rest
    rest = [c for c in out_df.columns if c not in mandatory_order]
    out_df = out_df[mandatory_order + rest]

    out_df.to_csv(output_csv, index=False, encoding="utf-8")
    return output_csv


def main(argv):
    if len(argv) < 3:
        print("Usage: python converter.py <etsy_input.csv> <shopify_output.csv>")
        sys.exit(1)
    input_csv = argv[1]
    output_csv = argv[2]
    result = etsy_to_shopify(input_csv, output_csv)
    print(f"Converted -> {result}")

if __name__ == "__main__":
    main(sys.argv)
