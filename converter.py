
import math
import numpy as np
import pandas as pd
import re

# ===== Shopify default config per user's request =====
DEFAULT_PUBLISHED = False
DEFAULT_STATUS = "draft"
DEFAULT_INVENTORY_TRACKER = "shopify"
DEFAULT_INVENTORY_QTY = ""   # keep blank
DEFAULT_INVENTORY_POLICY = "continue"
DEFAULT_FULFILLMENT_SERVICE = "manual"
DEFAULT_REQUIRES_SHIPPING = True
DEFAULT_TAXABLE = True

SHOPIFY_BASE_COLS = [
    "Handle","Title","Body (HTML)","Vendor","Published",
    "Option1 Name","Option1 Value","Option2 Name","Option2 Value",
    "Variant SKU","Variant Inventory Tracker","Variant Inventory Qty",
    "Variant Inventory Policy","Variant Fulfillment Service",
    "Variant Price","Variant Compare At Price","Variant Requires Shipping","Variant Taxable",
    "Image Src","Image Position","Status",
]

# ---- New: options to ALWAYS drop from Etsy variants (case-insensitive) ----
EXCLUDE_OPTIONS = {"digital download"}

def slugify(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:100]

def split_list_field(val):
    if pd.isna(val):
        return []
    parts = [str(p).strip() for p in str(val).split(",") if str(p).strip() != ""]
    return parts

def parse_price(value):
    """Parse price that may contain currency symbols or thousand separators."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return np.nan
    s = str(value).strip()
    if s == "":
        return np.nan
    # extract first numeric token
    m = re.search(r"[+-]?[0-9][0-9\.,]*", s)
    if not m:
        try:
            return float(s)
        except Exception:
            return np.nan
    token = m.group(0)
    # heuristic: if token has both '.' and ',', assume '.' is thousand sep if comma appears last
    if ',' in token and '.' in token:
        # remove thousand sep
        if token.rfind(',') > token.rfind('.'):
            token = token.replace('.', '').replace(',', '.')
        else:
            token = token.replace(',', '')
    else:
        token = token.replace(',', '')
    try:
        return float(token)
    except Exception:
        return np.nan

def apply_markup(price, markup_pct: float):
    p = parse_price(price)
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return ""
    try:
        return round(p * (1 + float(markup_pct) / 100.0), 2)
    except Exception:
        return ""

def _finalize(df_rows: list[dict]) -> pd.DataFrame:
    if not df_rows:
        return pd.DataFrame(columns=SHOPIFY_BASE_COLS)
    all_keys = list({k for row in df_rows for k in row.keys()})
    ordered = [*SHOPIFY_BASE_COLS, *[k for k in all_keys if k not in SHOPIFY_BASE_COLS]]
    df = pd.DataFrame(df_rows)
    for k in ordered:
        if k not in df.columns:
            df[k] = ""
    return df[ordered]

# ---------- Etsy converter (UPDATED: drop Digital Download + align SKUs) ----------
def convert_etsy_to_shopify(file_like, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    etsy = pd.read_csv(file_like, engine="python")
    rows = []

    for idx, r in etsy.iterrows():
        title = r.get("TITLE", "")
        desc = r.get("DESCRIPTION", "")
        price = r.get("PRICE", np.nan)

        # Collect up to 20 image URLs if available
        images = []
        for k in range(1, 21):
            col = f"IMAGE{k}"
            if col in etsy.columns:
                v = r.get(col)
                if pd.notna(v) and str(v).strip():
                    images.append(str(v).strip())

        # Read options & SKU list
        opt1_name_raw = r.get("VARIATION 1 NAME", np.nan)
        opt1_values_all = split_list_field(r.get("VARIATION 1 VALUES", np.nan))
        opt2_name_raw = r.get("VARIATION 2 NAME", np.nan)
        opt2_values_all = split_list_field(r.get("VARIATION 2 VALUES", np.nan))
        sku_list_all   = split_list_field(r.get("SKU", np.nan))

        # Normalize option names
        opt1_name_val = str(opt1_name_raw) if pd.notna(opt1_name_raw) and str(opt1_name_raw).strip() else "Option1"
        opt2_name_val = str(opt2_name_raw) if pd.notna(opt2_name_raw) and str(opt2_name_raw).strip() else ""

        # Build original cartesian grid for mask derivation
        orig_opt1 = opt1_values_all if opt1_values_all else ["Default"]
        orig_opt2 = opt2_values_all if opt2_values_all else [None]

        orig_pairs = [(a, b) for a in orig_opt1 for b in orig_opt2]
        orig_count = len(orig_pairs)

        # Build keep masks by excluding EXCLUDE_OPTIONS (case-insensitive) on each axis
        def keep_opt1(v): return str(v).strip().lower() not in EXCLUDE_OPTIONS
        def keep_opt2(v): return (str(v).strip().lower() not in EXCLUDE_OPTIONS) if v is not None else True

        kept_opt1 = [v for v in orig_opt1 if keep_opt1(v)]
        kept_opt2 = [v for v in orig_opt2 if keep_opt2(v)]

        # If after filtering there are no variants (e.g., only Digital Download), skip the product entirely
        if len(kept_opt1) == 0 or len(kept_opt2) == 0:
            continue

        # New variant grid after filtering
        new_pairs = [(a, b) for a in kept_opt1 for b in kept_opt2]
        new_count = len(new_pairs)

        # Map SKU list to original grid order (row-major: opt1 x opt2), then drop those that were excluded
        skus_from_orig = sku_list_all if len(sku_list_all) == orig_count else None
        kept_skus = []
        if skus_from_orig is not None:
            for (a, b), sku in zip(orig_pairs, skus_from_orig):
                if keep_opt1(a) and keep_opt2(b):
                    kept_skus.append(sku)
        else:
            # Fallback: assume SKU list already corresponds to remaining variants in row-major (best effort)
            kept_skus = sku_list_all[:new_count]

        # Pad SKUs if short; will auto-generate later
        if len(kept_skus) < new_count:
            kept_skus += [""] * (new_count - len(kept_skus))

        handle = slugify(title) or f"etsy-{idx+1}"
        vendor = vendor_text or r.get("VENDOR", "") or ""
        out_price = apply_markup(price, markup_pct)

        def base_row():
            return {
                "Handle": handle,
                "Vendor": vendor,
                "Published": DEFAULT_PUBLISHED,
                "Variant Inventory Tracker": DEFAULT_INVENTORY_TRACKER,
                "Variant Inventory Qty": DEFAULT_INVENTORY_QTY,
                "Variant Inventory Policy": DEFAULT_INVENTORY_POLICY,
                "Variant Fulfillment Service": DEFAULT_FULFILLMENT_SERVICE,
                "Variant Requires Shipping": DEFAULT_REQUIRES_SHIPPING,
                "Variant Taxable": DEFAULT_TAXABLE,
                "Status": DEFAULT_STATUS,
            }

        # Emit variant rows
        for i, ((v1, v2), sku_val) in enumerate(zip(new_pairs, kept_skus)):
            row = base_row()
            if i == 0:
                row.update({"Title": title, "Body (HTML)": desc})
                if images:
                    row["Image Src"] = images[0]; row["Image Position"] = 1

            row.update({
                "Option1 Name": opt1_name_val,
                "Option1 Value": v1,
                "Variant Price": out_price,
                "Variant SKU": str(sku_val) if sku_val else "",
            })
            if opt2_name_val:
                row["Option2 Name"] = opt2_name_val
                row["Option2 Value"] = "" if v2 is None else v2

            # Auto-generate SKU if missing
            if not row["Variant SKU"]:
                # create a stable index like 01, 02...
                row["Variant SKU"] = f"ETSY-{slugify(title)}-{i+1:02d}"

            rows.append(row)

        # Emit remaining images as separate rows with only handle + image
        for pos, url in enumerate(images[1:], start=2):
            rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})

    return _finalize(rows)

# ---------- TikTok converter (kept as-is from user's previous version) ----------
def convert_tiktok_to_shopify(file_like, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    name = getattr(file_like, 'name', '')
    if name and name.lower().endswith('.csv'):
        tt = pd.read_csv(file_like)
    else:
        tt = pd.read_excel(file_like)

    tt.columns = [str(c).strip() for c in tt.columns]

    def pick(*candidates):
        for c in candidates:
            if c in tt.columns:
                return c
        return None

    title_col = pick("Product Name", "Title", "Name", "Product Title")
    desc_col = pick("Product description", "Description", "Product Description")

    price_col = pick("Price", "Sale Price", "Selling Price", "SKU Price", "Unit Price")
    if price_col is None:
        # fallback: first column that contains 'price' (case-insensitive)
        for c in tt.columns:
            if "price" in c.lower():
                price_col = c
                break

    sku_col = pick("SKU ID", "Seller SKU", "SKU", "Merchant SKU", "Model Number")
    image_cols = [c for c in tt.columns if str(c).lower().startswith("image") or "Main Image" in c or "Images" in c]

    opt1_name_col = pick("Variant 1 Name", "Option1 Name", "Attribute 1 Name", "Spec 1 Name")
    opt1_value_col = pick("Variant 1 Value", "Option1 Value", "Attribute 1 Value", "Spec 1 Value")
    opt2_name_col = pick("Variant 2 Name", "Option2 Name", "Attribute 2 Name", "Spec 2 Name")
    opt2_value_col = pick("Variant 2 Value", "Option2 Value", "Attribute 2 Value", "Spec 2 Value")

    product_id_col = pick("Product ID", "SPU ID", "Parent ID", "Item ID")

    if product_id_col is None:
        handle_source_col = title_col
        tt["_product_key_"] = tt[handle_source_col].astype(str)
    else:
        tt["_product_key_"] = tt[product_id_col].astype(str)

    rows = []
    for key, group in tt.groupby("_product_key_"):
        g0 = group.iloc[0]
        title = str(g0.get(title_col, "")) if title_col else ""
        desc = g0.get(desc_col, "") if desc_col else ""
        handle = slugify(title) if title else f"tiktok-{key}"
        vendor = vendor_text or ""

        images = []
        for col in image_cols:
            vals = group[col].dropna().astype(str).unique().tolist()
            for v in vals:
                parts = re.split(r"[,\\s]\\s*", v.strip())
                for p in parts:
                    if p and p.startswith("http"):
                        images.append(p)
        seen = set(); uniq = []
        for u in images:
            if u not in seen:
                uniq.append(u); seen.add(u)
        images = uniq[:20]

        has_var = False
        if opt1_value_col and group[opt1_value_col].notna().any():
            has_var = True
        if opt2_value_col and group[opt2_value_col].notna().any():
            has_var = True

        def base_row():
            return {
                "Handle": handle,
                "Vendor": vendor,
                "Published": DEFAULT_PUBLISHED,
                "Variant Inventory Tracker": DEFAULT_INVENTORY_TRACKER,
                "Variant Inventory Qty": DEFAULT_INVENTORY_QTY,
                "Variant Inventory Policy": DEFAULT_INVENTORY_POLICY,
                "Variant Fulfillment Service": DEFAULT_FULFILLMENT_SERVICE,
                "Variant Requires Shipping": DEFAULT_REQUIRES_SHIPPING,
                "Variant Taxable": DEFAULT_TAXABLE,
                "Status": DEFAULT_STATUS,
            }

        if not has_var:
            gprice = g0.get(price_col, np.nan) if price_col else np.nan
            gsku = g0.get(sku_col, "") if sku_col else ""
            row = base_row()
            row.update({
                "Title": title,
                "Body (HTML)": desc,
                "Option1 Name": "Title",
                "Option1 Value": "Default Title",
                "Variant SKU": str(gsku) if pd.notna(gsku) else "",
                "Variant Price": round(parse_price(gprice) * (1 + float(markup_pct)/100.0), 2) if pd.notna(gprice) else "",
            })
            if images:
                row["Image Src"] = images[0]; row["Image Position"] = 1
            rows.append(row)
            for pos, url in enumerate(images[1:], start=2):
                rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})
        else:
            v_index = 0
            for _, rr in group.iterrows():
                v1_name = rr.get(opt1_name_col, "Option1") if opt1_name_col else "Option1"
                v1_value = rr.get(opt1_value_col, "Default")
                v2_name = rr.get(opt2_name_col, "") if opt2_name_col else ""
                v2_value = rr.get(opt2_value_col, "")
                gprice = rr.get(price_col, np.nan) if price_col else np.nan
                vsku = rr.get(sku_col, "")

                row = base_row()
                if v_index == 0:
                    row.update({"Title": title, "Body (HTML)": desc})
                    if images: row["Image Src"] = images[0]; row["Image Position"] = 1
                row.update({
                    "Option1 Name": str(v1_name) if pd.notna(v1_name) else "Option1",
                    "Option1 Value": str(v1_value) if pd.notna(v1_value) else "Default",
                    "Variant SKU": str(vsku) if pd.notna(vsku) else "",
                    "Variant Price": round(parse_price(gprice) * (1 + float(markup_pct)/100.0), 2) if pd.notna(gprice) else "",
                })
                if pd.notna(v2_name) and str(v2_name).strip():
                    row["Option2 Name"] = str(v2_name)
                    row["Option2 Value"] = str(v2_value) if pd.notna(v2_value) else ""
                rows.append(row); v_index += 1
            for pos, url in enumerate(images[1:], start=2):
                rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})
    return _finalize(rows)
