import io
import pandas as pd
import streamlit as st
from converter import convert_etsy_to_shopify, convert_tiktok_to_shopify

st.set_page_config(page_title="Etsy/TikTok → Shopify Converter", page_icon="🛒", layout="centered")

st.title("🛒 Etsy/TikTok → Shopify Converter")
st.caption("Chọn nguồn dữ liệu, nhập Vendor & % Markup → Convert → Tải CSV cho Shopify")

# Sidebar: Config
with st.sidebar:
    st.header("⚙️ Cấu hình")
    source = st.radio("Nguồn file", ["Etsy CSV", "TikTok Shop (CSV/XLSX)"])
    vendor = st.text_input("Vendor", value="")
    markup_pct = st.number_input("Markup price (%)", value=0.0, step=1.0, help="Ví dụ 10 = +10%, -10 = giảm 10%")
    st.markdown("---")
    st.write("**Mặc định Shopify** (đã theo yêu cầu):")
    st.code("""
Status = draft
Published = FALSE
Variant Inventory Tracker = shopify (bật tracking)
Variant Inventory Qty = (để trống)
Inventory Policy = continue (hết vẫn cho đặt)
""", language="markdown")

# File uploader depends on source
if source == "Etsy CSV":
    uploaded = st.file_uploader("Tải lên file CSV export từ Etsy", type=["csv"], accept_multiple_files=False)
else:
    uploaded = st.file_uploader("Tải lên file CSV/XLSX export từ TikTok Shop", type=["csv", "xlsx"], accept_multiple_files=False)

col_btn1, col_btn2 = st.columns([1,1])

if col_btn1.button("🚀 Convert", use_container_width=True, disabled=(uploaded is None)):
    if uploaded is None:
        st.warning("Vui lòng tải file lên trước.")
        st.stop()

    try:
        if source == "Etsy CSV":
            df_out = convert_etsy_to_shopify(uploaded, vendor_text=vendor, markup_pct=markup_pct)
            base_name = (uploaded.name or "etsy").rsplit('.', 1)[0]
            out_name = f"shopify_import_from_etsy__{base_name}.csv"
        else:
            df_out = convert_tiktok_to_shopify(uploaded, vendor_text=vendor, markup_pct=markup_pct)
            base_name = (uploaded.name or "tiktok").rsplit('.', 1)[0]
            out_name = f"shopify_import_from_tiktok__{base_name}.csv"

        st.success("✅ Convert thành công! Xem preview & tải xuống bên dưới.")
        st.write("### Preview (tối đa 200 dòng)")
        st.dataframe(df_out.head(200), use_container_width=True)

        csv_bytes = df_out.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="⬇️ Tải CSV cho Shopify",
            data=csv_bytes,
            file_name=out_name,
            mime="text/csv",
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"❌ Lỗi khi convert: {e}")

with col_btn2:
    st.button("🧹 Reset form", use_container_width=True, on_click=lambda: st.experimental_rerun())

st.markdown("---")
st.caption("Built with ❤️ for POD workflows • Streamlit app")
