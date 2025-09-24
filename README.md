# Etsy/TikTok → Shopify Converter (Streamlit)

## Cách chạy (local)
1. Cài Python 3.10+.
2. Cài thư viện:
   ```bash
   pip install -r requirements.txt
   ```
3. Chạy app:
   ```bash
   streamlit run app.py
   ```
4. Mở trình duyệt tại link của Streamlit (thường http://localhost:8501).

## Quy trình 4 bước
1) Chọn nguồn **Etsy CSV** hoặc **TikTok Shop (CSV/XLSX)**.  
2) Nhập **Vendor** và **Markup %** (âm/dương).  
3) Bấm **Convert**.  
4) Xem preview và **Tải CSV** đúng format Shopify.

## Mặc định Shopify
- Status = `draft`  
- Published = `FALSE`  
- Variant Inventory Tracker = `shopify`  
- Variant Inventory Qty = *(để trống)*  
- Inventory Policy = `continue`  

> App tự nhận dạng cột phổ biến; nếu export có tên cột khác thường, cập nhật hàm `pick()` trong `converter.py`.
