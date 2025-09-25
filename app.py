# app.py
import sys
from pathlib import Path
import traceback
import streamlit as st
import pandas as pd

# ===== Ensure we can import local converter.py =====
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from converter import convert_etsy_to_shopify, convert_tiktok_to_shopify, NO_SKU_OPTIONS  # NO_SKU_OPTIONS for diagnostics
except Exception:
    st.set_page_config(page_title="Import to Shopify", page_icon="🛍️", layout="wide")
    st.title("Import to Shopify")
    st.error("Không import được module converter.py. Xem lỗi chi tiết bên dưới.")
    st.code(traceback.format_exc())
    st.stop()

# Fallback nếu converter.py không export NO_SKU_OPTIONS
try:
    NO_SKU_OPTIONS  # noqa
except NameError:
    NO_SKU_OPTIONS = {"digital download", "png"}

# ===== Page setup =====
st.set_page_config(page_title="Import to Shopify", page_icon="🛍️", layout="wide")
st.title("🛍️ Import CSV vào Shopify")

st.caption(
    "• Tab **Etsy CSV**: giữ *Digital Download/PNG* như biến thể thường nhưng **SKU để trống**; "
    "SKU cho biến thể còn lại khớp theo **Option1** và lặp lại cho mọi **Option2**.  \n"
    "• Tab **TikTok CSV/XLSX**: convert chuẩn Shopify.  \n"
    "• File tải về xuất **UTF-8 BOM** để Shopify đọc đúng cột."
)

def _download_button(df: pd.DataFrame, fname: str):
    # Xuất CSV có BOM để Shopify import chắc chắn
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Download Shopify CSV",
        data=csv_bytes,
        file_name=fname,
        mime="text/csv",
        use_container_width=True,
    )

def _preview(df: pd.DataFrame, max_rows: int = 200):
    n = len(df)
    st.write(f"**Tổng dòng:** {n:,}")
    if n > max_rows:
        st.info(f"Hiển thị {max_rows:,}/{n:,} dòng đầu (để nhẹ).")
        st.dataframe(df.head(max_rows), use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)

def _diagnostics_by_handle(df: pd.DataFrame, for_source: str):
    """
    Tạo bảng chẩn đoán theo Handle:
    - rows: số dòng trong CSV (variants + image rows)
    - variants: số dòng có Option1 Value (tức là variant-row)
    - empty_sku_variants: số biến thể có SKU trống
    - digital_or_png_variants: số biến thể có Option1 Value thuộc NO_SKU_OPTIONS
    - first_row_has_title: dòng đầu phải có Title (bắt buộc Shopify)
    - first_row_has_image: dòng đầu có Image Src (khuyến nghị)
    - any_image: sản phẩm có bất kỳ ảnh nào
    """
    safe = df.copy()
    for col in ["Handle","Title","Image Src","Option1 Value","Variant SKU"]:
        if col not in safe.columns:
            safe[col] = ""

    def _lower_series(s):
        return s.fillna("").astype(str).str.strip().str.lower()

    by_handle = []
    for h, g in safe.groupby("Handle"):
        g = g.reset_index(drop=True)
        rows = len(g)
        first = g.iloc[0]
        first_row_has_title = bool(str(first.get("Title", "")).strip())
        first_row_has_image = bool(str(first.get("Image Src", "")).strip())
        any_image = g["Image Src"].fillna("").astype(str).str.strip().ne("").any()

        # variant rows ~ có Option1 Value (Shopify format)
        is_variant_row = _lower_series(g["Option1 Value"]).ne("")
        variants = int(is_variant_row.sum())

        empty_sku_variants = int((_lower_series(g["Variant SKU"]).eq("")) & is_variant_row)
        digital_or_png_variants = int(
            _lower_series(g["Option1 Value"]).isin({s.lower() for s in NO_SKU_OPTIONS}).sum()
        )

        by_handle.append({
            "Handle": h,
            "rows": rows,
            "variants": variants,
            "empty_sku_variants": empty_sku_variants,
            "digital_or_png_variants": digital_or_png_variants,
            "first_row_has_title": first_row_has_title,
            "first_row_has_image": first_row_has_image,
            "any_image": any_image,
        })

    diag = pd.DataFrame(by_handle).sort_values("Handle").reset_index(drop=True)

    # Gợi ý/cảnh báo tổng hợp
    problems = []
    if not diag.empty:
        no_title = diag[~diag["first_row_has_title"]]["Handle"].tolist()
        if no_title:
            problems.append(f"❗ {len(no_title)} sản phẩm thiếu **Title ở dòng đầu** (Shopify sẽ reject).")

        no_any_image = diag[~diag["any_image"]]["Handle"].tolist()
        if no_any_image:
            problems.append(f"🖼️ {len(no_any_image)} sản phẩm **không có ảnh** nào.")

        first_no_img = diag[(diag["any_image"]) & (~diag["first_row_has_image"])]["Handle"].tolist()
        if first_no_img:
            problems.append(f"ℹ️ {len(first_no_img)} sản phẩm có ảnh nhưng **dòng đầu không có `Image Src`** (khuyến nghị thêm).")

        if for_source == "etsy":
            # với Etsy, empty_sku_variants thường do Digital/PNG -> ok
            # nhưng nếu empty_sku_variants > digital_or_png_variants -> có biến thể thường bị trống SKU
            mask_issue = diag["empty_sku_variants"] > diag["digital_or_png_variants"]
            cnt_issue = int(mask_issue.sum())
            if cnt_issue:
                problems.append(f"🔎 {cnt_issue} sản phẩm có **biến thể thường bị trống SKU** (khác Digital/PNG).")

    return diag, problems

# ===== Tabs =====
tab1, tab2 = st.tabs(["🧵 Etsy CSV → Shopify", "🎵 TikTok CSV/XLSX → Shopify"])

with tab1:
    st.subheader("Etsy → Shopify")
    uploaded = st.file_uploader("Upload Etsy CSV", type=["csv"], key="etsy_uploader")
    colA, colB = st.columns([2, 1])
    with colA:
        vendor = st.text_input("Vendor (tuỳ chọn)", value="")
    with colB:
        markup = st.number_input("% Markup (tuỳ chọn)", min_value=0.0, max_value=1000.0, value=0.0, step=0.1)

    st.caption(
        f"• Hỗ trợ tự khớp SKU theo **Option1** (size/age như 6M, 12M, 2T… hoặc 11x14).  "
        f"• **{', '.join(sorted(NO_SKU_OPTIONS)).title()}** vẫn giữ biến thể nhưng SKU **để trống**."
    )

    show_diag = st.checkbox("🔧 Show advanced diagnostics", value=True)

    if uploaded:
        if st.button("🚀 Convert Etsy → Shopify", use_container_width=True):
            try:
                uploaded.seek(0)  # đảm bảo đọc từ đầu stream
                df_out = convert_etsy_to_shopify(uploaded, vendor_text=vendor, markup_pct=markup)

                st.success("Convert thành công!")
                if show_diag:
                    st.write("### 🔍 Diagnostics (Etsy)")
                    diag, problems = _diagnostics_by_handle(df_out, for_source="etsy")
                    if problems:
                        for p in problems:
                            st.warning(p)
                    st.dataframe(diag, use_container_width=True, height=300)

                st.write("### 👀 Xem trước dữ liệu")
                _preview(df_out)

                _download_button(df_out, "shopify_import_from_etsy.csv")

            except Exception:
                st.error("Có lỗi khi convert Etsy. Xem chi tiết bên dưới.")
                st.code(traceback.format_exc())

with tab2:
    st.subheader("TikTok → Shopify")
    uploaded_tt = st.file_uploader("Upload TikTok CSV/XLSX", type=["csv", "xlsx", "xls"], key="tiktok_uploader")
    colA2, colB2 = st.columns([2, 1])
    with colA2:
        vendor_tt = st.text_input("Vendor (tuỳ chọn)", value="", key="vendor_tt")
    with colB2:
        markup_tt = st.number_input("% Markup (tuỳ chọn)", min_value=0.0, max_value=1000.0, value=0.0, step=0.1, key="markup_tt")

    show_diag_tt = st.checkbox("🔧 Show advanced diagnostics (TikTok)", value=False, key="diag_tt")

    if uploaded_tt:
        if st.button("🚀 Convert TikTok → Shopify", use_container_width=True):
            try:
                uploaded_tt.seek(0)
                df_out_tt = convert_tiktok_to_shopify(uploaded_tt, vendor_text=vendor_tt, markup_pct=markup_tt)

                st.success("Convert thành công!")
                if show_diag_tt:
                    st.write("### 🔍 Diagnostics (TikTok)")
                    diag_tt, problems_tt = _diagnostics_by_handle(df_out_tt, for_source="tiktok")
                    if problems_tt:
                        for p in problems_tt:
                            st.warning(p)
                    st.dataframe(diag_tt, use_container_width=True, height=300)

                st.write("### 👀 Xem trước dữ liệu")
                _preview(df_out_tt)

                _download_button(df_out_tt, "shopify_import_from_tiktok.csv")

            except Exception:
                st.error("Có lỗi khi convert TikTok. Xem chi tiết bên dưới.")
                st.code(traceback.format_exc())
