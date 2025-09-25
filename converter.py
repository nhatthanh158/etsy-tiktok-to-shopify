# ---------- Etsy converter (token-match SKU to Option1; replicate across Option2) ----------
def convert_etsy_to_shopify(file_like, vendor_text: str = "", markup_pct: float = 0.0) -> pd.DataFrame:
    etsy = pd.read_csv(file_like, engine="python")
    rows = []

    def split_list(val):
        if pd.isna(val): return []
        return [str(x).strip() for x in str(val).split(",") if str(x).strip()]

    TOKEN_PATTERNS = [
        r"\b\d{1,2}\s*[tTmM]\b",            # 6M, 12M, 2T, 3T...
        r"\b(?:XS|S|M|L|XL|XXL|3XL|4XL)\b",  # sizes letters
        r"\b\d{1,2}\s*[x×]\s*\d{1,2}\b"     # 11x14, 8x12...
    ]
    TOKEN_RE = re.compile("|".join(TOKEN_PATTERNS), re.I)

    def opt1_token(val: str) -> str:
        s = str(val or "").upper().strip()
        m = TOKEN_RE.search(s)
        if m:
            return m.group(0).replace(" ", "").replace("×", "X")
        parts = re.findall(r"[A-Z0-9]+", s)
        return parts[-1] if parts else s

    def sku_token(sku: str) -> str:
        s = str(sku or "").upper()
        if "_" in s:
            tail = s.split("_")[-1]
            m = TOKEN_RE.search(tail)
            if m: return m.group(0).replace(" ", "").replace("×", "X")
            return tail
        m = TOKEN_RE.search(s)
        if m: return m.group(0).replace(" ", "").replace("×", "X")
        parts = re.findall(r"[A-Z0-9]+", s)
        return parts[-1] if parts else s

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

        # token map
        token_to_sku = {}
        for s in skus_all:
            token_to_sku[sku_token(s)] = s

        # assign SKU per Option1
        opt1_skus = []
        used_skus = set()
        for o1 in opt1:
            t = opt1_token(o1)
            sku = token_to_sku.get(t)
            if sku is None:
                found = None
                for tk, val in token_to_sku.items():
                    if t in tk or tk in t:
                        found = val; break
                sku = found
            if sku is None:
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
