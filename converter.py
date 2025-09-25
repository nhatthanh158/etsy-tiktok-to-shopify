
import math
import numpy as np
import pandas as pd
import re

DEFAULT_PUBLISHED = False
DEFAULT_STATUS = "draft"
DEFAULT_INVENTORY_TRACKER = "shopify"
DEFAULT_INVENTORY_QTY = ""
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

EXCLUDE_OPTIONS = {"digital download"}

def slugify(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:100]

def parse_price(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return np.nan
    s = str(value).strip()
    if s == "":
        return np.nan
    m = re.search(r"[+-]?[0-9][0-9\.,]*", s)
    if not m:
        try:
            return float(s)
        except Exception:
            return np.nan
    token = m.group(0)
    if ',' in token and '.' in token:
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

# ---------- helpers for token-based matching ----------
# capture patterns like 6M, 12M, 2T, 3T, XS, S, M, L, XL, XXL, 11x14, 8x12
TOKEN_PATTERNS = [
    r"\b\d{1,2}\s*[tTmM]\b",
    r"\b(?:XS|S|M|L|XL|XXL|3XL|4XL)\b",
    r"\b\d{1,2}\s*[x×]\s*\d{1,2}\b"
]
TOKEN_RE = re.compile("|".join(TOKEN_PATTERNS), re.I)

def opt1_token(val: str) -> str:
    s = str(val or "").upper().strip()
    m = TOKEN_RE.search(s)
    if m:
        return m.group(0).replace(" ", "").replace("×", "X")
    # fallback: last alnum chunk (e.g., "6M" in "Toddler Jersey - 6M")
    parts = re.findall(r"[A-Z0-9]+", s)
    return parts[-1] if parts else s

def sku_token(sku: str) -> str:
    s = str(sku or "").upper()
    # try take substring after last underscore
    if "_" in s:
        tail = s.split("_")[-1]
        m = TOKEN_RE.search(tail)
        if m:
            return m.group(0).replace(" ", "").replace("×", "X")
        return tail
    m = TOKEN_RE.search(s)
    if m:
        return m.group(0).replace(" ", "").replace("×", "X")
    parts = re.findall(r"[A-Z0-9]+", s)
    return parts[-1] if parts else s

def split_list(val):
    if pd.isna(val): return []
    return [str(x).strip() for x in str(val).split(",") if str(x).strip()]

# ---------- Etsy converter (token-match SKU to Option1; replicate across Option2) ----------
def convert_etsy_to_shopify(file_like, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    etsy = pd.read_csv(file_like, engine="python")
    rows = []

    for idx, r in etsy.iterrows():
        title = r.get("TITLE", "")
        desc = r.get("DESCRIPTION", "")
        price = r.get("PRICE", "")

        # images
        images = []
        for k in range(1, 21):
            col = f"IMAGE{k}"
            if col in etsy.columns:
                v = r.get(col)
                if pd.notna(v) and str(v).strip():
                    images.append(str(v).strip())

        opt1_name = r.get("VARIATION 1 NAME") or r.get("VARIATION 1 TYPE") or "Option1"
        opt2_name = r.get("VARIATION 2 NAME") or r.get("VARIATION 2 TYPE") or ""
        opt1_all  = split_list(r.get("VARIATION 1 VALUES"))
        opt2_all  = split_list(r.get("VARIATION 2 VALUES"))
        skus_all  = split_list(r.get("SKU"))

        # filter excluded
        def keep(v): return str(v).strip().lower() not in EXCLUDE_OPTIONS
        opt1 = [v for v in opt1_all if keep(v)] or ["Default"]
        opt2 = [v for v in opt2_all if keep(v)]
        have_opt2 = len(opt2) > 0
        if len(opt1) == 0:
            continue

        # ---- build fast map from SKU tokens to SKU ----
        token_to_sku = {}
        for s in skus_all:
            token_to_sku[sku_token(s)] = s

        # ---- assign SKU per Option1 by token ----
        opt1_skus = []
        used_skus = set()
        for o1 in opt1:
            t = opt1_token(o1)
            sku = token_to_sku.get(t)
            if sku is None:
                # try relaxed contains search
                found = None
                for tk, val in token_to_sku.items():
                    if t in tk or tk in t:
                        found = val; break
                sku = found
            if sku is None:
                # fallback by order (first unused)
                sku = next((s for s in skus_all if s not in used_skus), "")
            used_skus.add(sku)
            opt1_skus.append(sku or f"ETSY-{slugify(title)}-{opt1.index(o1)+1:02d}")

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

        v_index = 0
        for i, (o1, o1_sku) in enumerate(zip(opt1, opt1_skus)):
            if have_opt2:
                for o2 in opt2:
                    row = base_row()
                    if v_index == 0:
                        row.update({"Title": title, "Body (HTML)": desc})
                        if images:
                            row["Image Src"] = images[0]; row["Image Position"] = 1
                    row.update({
                        "Option1 Name": opt1_name,
                        "Option1 Value": o1,
                        "Option2 Name": opt2_name,
                        "Option2 Value": o2,
                        "Variant SKU": o1_sku,
                        "Variant Price": out_price,
                    })
                    rows.append(row); v_index += 1
            else:
                row = base_row()
                if v_index == 0:
                    row.update({"Title": title, "Body (HTML)": desc})
                    if images:
                        row["Image Src"] = images[0]; row["Image Position"] = 1
                row.update({
                    "Option1 Name": opt1_name,
                    "Option1 Value": o1,
                    "Variant SKU": o1_sku,
                    "Variant Price": out_price,
                })
                rows.append(row); v_index += 1

        for pos, url in enumerate(images[1:], start=2):
            rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})

    return _finalize(rows)
