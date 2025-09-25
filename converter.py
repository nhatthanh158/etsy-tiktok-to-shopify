# converter.py
import math
import numpy as np
import pandas as pd
import re
from typing import List, Dict, Any

# ===== Shopify default config (khớp UI trong app.py) =====
DEFAULT_PUBLISHED = False
DEFAULT_STATUS = "draft"
DEFAULT_INVENTORY_TRACKER = "shopify"
DEFAULT_INVENTORY_QTY = ""   # để trống
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

# Các option vẫn GIỮ LẠI nhưng **KHÔNG GÁN SKU**
NO_SKU_OPTIONS = {"digital download", "png"}

# ================= Helpers =================
def slugify(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:100]

def split_list_field(val) -> List[str]:
    if pd.isna(val):
        return []
    return [s.strip() for s in str(val).split(",") if str(s).strip()]

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

def _finalize(df_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not df_rows:
        return pd.DataFrame(columns=SHOPIFY_BASE_COLS)
    all_keys = list({k for row in df_rows for k in row.keys()})
    ordered = [*SHOPIFY_BASE_COLS, *[k for k in all_keys if k not in SHOPIFY_BASE_COLS]]
    df = pd.DataFrame(df_rows)
    for k in ordered:
        if k not in df.columns:
            df[k] = ""
    return df[ordered]

# ====== Token matcher (để gán đúng SKU cho Option1) ======
# Nhận biết: 6M/12M/2T/3T, XS/S/M/L/XL..., 11x14/8x12..., và A-series (A0..A10)
TOKEN_PATTERNS = [
    r"\b\d{1,2}\s*[tTmM]\b",                  # 6M, 12M, 2T, 3T
    r"\b(?:XS|S|M|L|XL|XXL|3XL|4XL)\b",       # size chữ
    r"\b\d{1,2}\s*[x×]\s*\d{1,2}\b",         # 11x14, 8x12
    r"\bA\s*\d{1,2}\b",                       # A0..A10 (A3, A4, ...)
]
TOKEN_RE = re.compile("|".join(TOKEN_PATTERNS), re.I)

def option1_token(val: str) -> str:
    s = str(val or "").upper().strip()
    m = TOKEN_RE.search(s)
    if m:
        tok = m.group(0).replace("×", "X")
        tok = re.sub(r"\s+", "", tok)  # "A 3" -> "A3"
        return tok
    parts = re.findall(r"[A-Z0-9]+", s)
    return parts[-1] if parts else s

def sku_token(sku: str) -> str:
    s = str(sku or "").upper()
    tail = s.split("_")[-1] if "_" in s else s
    m = TOKEN_RE.search(tail)
    if m:
        tok = m.group(0).replace("×", "X")
        return re.sub(r"\s+", "", tok)
    parts = re.findall(r"[A-Z0-9]+", tail)
    return parts[-1] if parts else tail

# ================= Etsy → Shopify =================
def convert_etsy_to_shopify(file_like_or_path, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    """Etsy CSV:
    - GIỮ lại các biến thể 'Digital Download' / 'PNG' nhưng để SKU = trống
    - SKU map theo Variation 1 (Option1) và replicate sang mọi Option2
    - Match SKU theo token (6M/12M/2T/3T, 11x14, A3/A4/...) nếu thứ tự lệch
    """
    etsy = pd.read_csv(file_like_or_path, engine="python")
    rows: List[Dict[str, Any]] = []

    # Tiện ích lấy tối đa 20 ảnh IMAGE1..IMAGE20 (nếu có)
    image_cols = [c for c in etsy.columns if re.fullmatch(r"IMAGE\d{1,2}", str(c).upper())]
    if not image_cols:
        image_cols = [c for c in etsy.columns if "IMAGE" in str(c).upper()]

    for idx, r in etsy.iterrows():
        title = r.get("TITLE", "")
        desc = r.get("DESCRIPTION", "")
        price = r.get("PRICE", "")

        # Ảnh
        images = []
        for c in image_cols:
            v = r.get(c)
            if pd.notna(v) and str(v).strip():
                images.append(str(v).strip())
        images = images[:20]

        # Option names/values
        opt1_name = r.get("VARIATION 1 NAME") or r.get("VARIATION 1 TYPE") or "Option1"
        opt2_name = r.get("VARIATION 2 NAME") or r.get("VARIATION 2 TYPE") or ""
        opt1_all  = split_list_field(r.get("VARIATION 1 VALUES"))
        opt2_all  = split_list_field(r.get("VARIATION 2 VALUES"))
        skus_all  = split_list_field(r.get("SKU"))

        # Nếu không có Option1 => tạo Default Title (Shopify format)
        if not opt1_all:
            opt1_all = ["Default Title"]

        # ===== Map SKU theo Option1 (không loại Digital/PNG) =====
        # (1) Nếu số SKU == số Option1 gốc => dùng mapping theo vị trí trước
        skus_by_pos = skus_all[:len(opt1_all)]
        if len(skus_all) == len(opt1_all):
            skus_by_pos = list(skus_all)

        # (2) Token-based matching ưu tiên
        token_to_sku = {sku_token(s): s for s in skus_all}
        matched_skus: List[str] = []
        used = set()
        for i, o1 in enumerate(opt1_all):
            if o1.strip().lower() in NO_SKU_OPTIONS:
                matched_skus.append("")  # will force empty SKU
                continue

            tok = option1_token(o1)
            sku = token_to_sku.get(tok)
            if sku is None:
                # relaxed contains both ways
                found = None
                for tk, val in token_to_sku.items():
                    if tk in tok or tok in tk:
                        if val not in used:
                            found = val
                            break
                sku = found
            if sku is None and skus_by_pos:
                # fallback vị trí: lấy SKU đầu tiên chưa dùng
                for s in skus_by_pos:
                    if s not in used:
                        sku = s
                        break
            if sku is None:
                sku = f"ETSY-{slugify(title)}-{i+1:02d}"

            used.add(sku)
            matched_skus.append(sku)

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

        v_idx = 0
        have_opt2 = len(opt2_all) > 0
        for i, (o1, o1_sku) in enumerate(zip(opt1_all, matched_skus)):
            # Nếu o1 thuộc nhóm NO_SKU_OPTIONS thì để SKU = trống
            if o1.strip().lower() in NO_SKU_OPTIONS:
                final_sku = ""
            else:
                final_sku = str(o1_sku)

            if have_opt2:
                for o2 in opt2_all:
                    row = base_row()
                    if v_idx == 0:
                        row.update({"Title": title, "Body (HTML)": desc})
                        if images:
                            row["Image Src"] = images[0]; row["Image Position"] = 1
                    row.update({
                        "Option1 Name": str(opt1_name),
                        "Option1 Value": str(o1),
                        "Option2 Name": str(opt2_name) if opt2_name else "",
                        "Option2 Value": str(o2) if opt2_name else "",
                        "Variant SKU": final_sku,
                        "Variant Price": out_price,
                    })
                    rows.append(row); v_idx += 1
            else:
                row = base_row()
                if v_idx == 0:
                    row.update({"Title": title, "Body (HTML)": desc})
                    if images:
                        row["Image Src"] = images[0]; row["Image Position"] = 1
                row.update({
                    "Option1 Name": str(opt1_name),
                    "Option1 Value": str(o1),
                    "Variant SKU": final_sku,
                    "Variant Price": out_price,
                })
                rows.append(row); v_idx += 1

        # Ảnh bổ sung
        for pos, url in enumerate(images[1:], start=2):
            rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})

    return _finalize(rows)

# ================= TikTok → Shopify =================
def convert_tiktok_to_shopify(file_like_or_path, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    """Đọc CSV hoặc XLSX TikTok; gom ảnh; sinh rows chuẩn Shopify."""
    name = getattr(file_like_or_path, 'name', '')
    if name and name.lower().endswith('.csv'):
        tt = pd.read_csv(file_like_or_path)
    elif name and name.lower().endswith(('.xlsx', '.xls')):
        tt = pd.read_excel(file_like_or_path)
    else:
        p = str(file_like_or_path).lower()
        if p.endswith('.csv'):
            tt = pd.read_csv(file_like_or_path)
        else:
            tt = pd.read_excel(file_like_or_path)

    tt.columns = [str(c).strip() for c in tt.columns]

    def pick(*cands):
        for c in cands:
            if c in tt.columns:
                return c
        return None

    title_col = pick("Product Name", "Title", "Name", "Product Title")
    desc_col  = pick("Product description", "Description", "Product Description")
    price_col = pick("Price", "Sale Price", "Selling Price", "SKU Price", "Unit Price")
    if price_col is None:
        for c in tt.columns:
            if "price" in c.lower():
                price_col = c; break

    sku_col = pick("SKU ID", "Seller SKU", "SKU", "Merchant SKU", "Model Number")
    image_cols = [c for c in tt.columns if str(c).lower().startswith("image") or "Main Image" in c or "Images" in c]
    opt1_name_col  = pick("Variant 1 Name", "Option1 Name", "Attribute 1 Name", "Spec 1 Name")
    opt1_value_col = pick("Variant 1 Value", "Option1 Value", "Attribute 1 Value", "Spec 1 Value")
    opt2_name_col  = pick("Variant 2 Name", "Option2 Name", "Attribute 2 Name", "Spec 2 Name")
    opt2_value_col = pick("Variant 2 Value", "Option2 Value", "Attribute 2 Value", "Spec 2 Value")
    product_id_col = pick("Product ID", "SPU ID", "Parent ID", "Item ID")

    if product_id_col is None:
        handle_source_col = title_col
        tt["_product_key_"] = tt[handle_source_col].astype(str)
    else:
        tt["_product_key_"] = tt[product_id_col].astype(str)

    rows: List[Dict[str, Any]] = []
    for key, g in tt.groupby("_product_key_"):
        g0 = g.iloc[0]
        title = str(g0.get(title_col, "")) if title_col else ""
        desc  = g0.get(desc_col, "") if desc_col else ""
        handle = slugify(title) if title else f"tiktok-{key}"
        vendor = vendor_text or ""

        images: List[str] = []
        for col in image_cols:
            vals = g[col].dropna().astype(str).unique().tolist()
            for v in vals:
                parts = re.split(r"[, \t\r\n]+", v.strip())
                for pth in parts:
                    if pth and pth.startswith("http"):
                        images.append(pth)
        seen = set(); uniq = []
        for u in images:
            if u not in seen:
                uniq.append(u); seen.add(u)
        images = uniq[:20]

        has_var = False
        if opt1_value_col and g[opt1_value_col].notna().any():
            has_var = True
        if opt2_value_col and g[opt2_value_col].notna().any():
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
            gsku   = g0.get(sku_col, "") if sku_col else ""
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
            for _, rr in g.iterrows():
                v1_name = rr.get(opt1_name_col, "Option1") if opt1_name_col else "Option1"
                v1_value = rr.get(opt1_value_col, "Default")
                v2_name = rr.get(opt2_name_col, "") if opt2_name_col else ""
                v2_value = rr.get(opt2_value_col, "")
                gprice = rr.get(price_col, np.nan) if price_col else np.nan
                vsku = rr.get(sku_col, "")

                row = base_row()
                if v_index == 0:
                    row.update({"Title": title, "Body (HTML)": desc})
                    if images:
                        row["Image Src"] = images[0]; row["Image Position"] = 1
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
