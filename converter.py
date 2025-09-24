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

# Minimal Shopify columns
SHOPIFY_BASE_COLS = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Variant SKU",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Image Src",
    "Image Position",
    "Status",
]

# ---------- helpers ----------
def slugify(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:100]

def split_list_field(val):
    if pd.isna(val):
        return []
    parts = [p.strip() for p in str(val).split(",") if str(p).strip() != ""]
    return parts

def apply_markup(price, markup_pct: float):
    if price is None or (isinstance(price, float) and math.isnan(price)):
        return price
    try:
        p = float(price)
        return round(p * (1 + float(markup_pct) / 100.0), 2)
    except Exception:
        return price

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

# ---------- Etsy converter ----------
def convert_etsy_to_shopify(file_like, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    etsy = pd.read_csv(file_like, engine="python")

    rows = []
    for idx, r in etsy.iterrows():
        title = r.get("TITLE", "")
        desc = r.get("DESCRIPTION", "")
        price = r.get("PRICE", np.nan)
        tags = r.get("TAGS", "")
        materials = r.get("MATERIALS", "")

        # collect images
        images = []
        for k in range(1, 21):
            col = f"IMAGE{k}"
            if col in etsy.columns and pd.notna(r.get(col)):
                images.append(str(r.get(col)))

        # variations
        opt1_name = r.get("VARIATION 1 NAME", np.nan)
        opt1_values = split_list_field(r.get("VARIATION 1 VALUES", np.nan))
        opt2_name = r.get("VARIATION 2 NAME", np.nan)
        opt2_values = split_list_field(r.get("VARIATION 2 VALUES", np.nan))
        sku_list = split_list_field(r.get("SKU", np.nan))

        handle = slugify(title) or f"etsy-{idx+1}"
        vendor = vendor_text or r.get("VENDOR", "") or ""

        # price after markup
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

        if not opt1_values and not opt2_values:
            row = base_row()
            row.update({
                "Title": title,
                "Body (HTML)": desc,
                "Option1 Name": "Title",
                "Option1 Value": "Default Title",
                "Variant Price": out_price,
            })
            if images:
                row["Image Src"] = images[0]
                row["Image Position"] = 1
            if sku_list:
                row["Variant SKU"] = sku_list[0]
            rows.append(row)

            for pos, url in enumerate(images[1:], start=2):
                rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})
        else:
            opt1_name_val = str(opt1_name) if pd.notna(opt1_name) and str(opt1_name).strip() else "Option1"
            opt2_name_val = str(opt2_name) if pd.notna(opt2_name) and str(opt2_name).strip() else ""
            opt1_vals = opt1_values if opt1_values else ["Default"]
            opt2_vals = opt2_values if opt2_values else [None]

            variant_count = len(opt1_vals) * len(opt2_vals)
            def sku_for(i):
                if sku_list and len(sku_list) == variant_count:
                    return sku_list[i]
                return ""

            v_index = 0
            for v1 in opt1_vals:
                for v2 in opt2_vals:
                    row = base_row()
                    if v_index == 0:
                        row.update({
                            "Title": title,
                            "Body (HTML)": desc,
                        })
                        if images:
                            row["Image Src"] = images[0]
                            row["Image Position"] = 1
                    row.update({
                        "Option1 Name": opt1_name_val,
                        "Option1 Value": v1,
                        "Variant Price": out_price,
                        "Variant SKU": sku_for(v_index),
                    })
                    if opt2_name_val:
                        row["Option2 Name"] = opt2_name_val
                        row["Option2 Value"] = "" if v2 is None else v2
                    rows.append(row)
                    v_index += 1
            for pos, url in enumerate(images[1:], start=2):
                rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})

    return _finalize(rows)

# ---------- TikTok converter ----------
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
    desc_col = pick("Description", "Product Description")
    price_col = pick("Price", "Sale Price", "Selling Price", "SKU Price", "Unit Price")
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
                "Variant Price": apply_markup(gprice, markup_pct),
            })
            if images:
                row["Image Src"] = images[0]
                row["Image Position"] = 1
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
                vprice = rr.get(price_col, np.nan) if price_col else np.nan
                vsku = rr.get(sku_col, "")

                row = base_row()
                if v_index == 0:
                    row.update({
                        "Title": title,
                        "Body (HTML)": desc,
                    })
                    if images:
                        row["Image Src"] = images[0]
                        row["Image Position"] = 1
                row.update({
                    "Option1 Name": str(v1_name) if pd.notna(v1_name) else "Option1",
                    "Option1 Value": str(v1_value) if pd.notna(v1_value) else "Default",
                    "Variant SKU": str(vsku) if pd.notna(vsku) else "",
                    "Variant Price": apply_markup(vprice, markup_pct),
                })
                if pd.notna(v2_name) and str(v2_name).strip():
                    row["Option2 Name"] = str(v2_name)
                    row["Option2 Value"] = str(v2_value) if pd.notna(v2_value) else ""
                rows.append(row)
                v_index += 1
            for pos, url in enumerate(images[1:], start=2):
                rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})

    return _finalize(rows)
