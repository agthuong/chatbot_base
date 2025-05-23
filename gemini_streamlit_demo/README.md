# Gemini Chat Demo với RAG

Ứng dụng chat Streamlit tích hợp Google Gemini API, cho phép tùy chỉnh prompt, lưu lịch sử hội thoại và sử dụng chức năng RAG (Retrieval Augmented Generation) với file markdown.

## Tính năng

- Tích hợp API của Google Gemini (đã có sẵn API Key)
- Tùy chỉnh prompt trên giao diện
- Lưu lịch sử hội thoại
- **Chức năng RAG** với file markdown (không cần chia chunk)
- Nhiều tùy chọn cấu hình model (temperature, max tokens...)
- Giao diện thân thiện với người dùng

## Cài đặt

1. Clone repository này và chuyển đến thư mục dự án:

```bash
cd gemini_streamlit_demo
```

2. Cài đặt các thư viện phụ thuộc:

```bash
pip install -r requirements.txt
```

3. Chạy ứng dụng Streamlit:

```bash
streamlit run app.py
```

## Cách sử dụng

1. ~~Đăng ký và lấy API key của Google AI (Gemini) tại: https://ai.google.dev/~~
2. ~~Nhập API key của bạn vào ô "API Key" trong thanh bên của ứng dụng~~
3. API Key đã được cấu hình sẵn, bạn không cần nhập thủ công
4. Tùy chỉnh các thông số model theo nhu cầu
5. **Sử dụng RAG**:
   - Đảm bảo tùy chọn "Sử dụng RAG" được chọn
   - Nhập đường dẫn đến file markdown cần sử dụng
   - Nhấn "Tải file markdown"
   - Xem nội dung file markdown trong mục mở rộng "Xem nội dung file markdown"
6. Nhấn "Áp dụng cài đặt" để áp dụng cấu hình
7. Nhập prompt của bạn trong ô chat ở cuối trang
8. Tương tác với AI và xem lịch sử hội thoại

## Chức năng RAG

RAG (Retrieval Augmented Generation) cho phép mô hình AI trả lời câu hỏi dựa trên dữ liệu cụ thể bạn cung cấp. Trong ứng dụng này:

- **Không cần chia nhỏ (chunking)**: Toàn bộ nội dung file markdown sẽ được sử dụng làm ngữ cảnh
- **Tương tích với nhiều định dạng markdown**: Bảng, danh sách, tiêu đề, etc.
- **Tùy chọn bật/tắt**: Có thể tắt RAG để sử dụng Gemini với kiến thức sẵn có của nó
- **Dễ dàng thay đổi tài liệu**: Chỉ cần tải file markdown khác để thay đổi ngữ cảnh

## Cài đặt nâng cao

- **System Prompt**: Định nghĩa vai trò và hành vi của AI. System prompt được gửi kèm với mỗi tin nhắn của người dùng, giúp duy trì vai trò nhất quán của AI. Bạn cần nhấn "Áp dụng cài đặt" sau khi thay đổi system prompt để nó có hiệu lực.
- **Temperature**: Kiểm soát tính ngẫu nhiên của đầu ra (0-1)
- **Max Output Tokens**: Số lượng tối đa token cho mỗi phản hồi
- **Top K, Top P**: Điều chỉnh độ đa dạng của nội dung được tạo

## Yêu cầu

- Python 3.8+
- ~~API key của Google AI (Gemini)~~ (đã được cấu hình sẵn)
- Kết nối internet 