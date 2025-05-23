import streamlit as st
import google.generativeai as genai
from datetime import datetime
import os
from dotenv import load_dotenv

# Tải biến môi trường từ file .env nếu có
load_dotenv()

# Cấu hình trang Streamlit
st.set_page_config(
    page_title="Gemini Chat Demo với RAG",
    page_icon="💬",
    layout="wide"
)

# API key cố định
GEMINI_API_KEY = "AIzaSyA0BgHLDCU9yoiv7JAbCoUmJrrtzkkWoV4"

# Hàm đọc file data.markdown
def read_markdown_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        return f"Lỗi khi đọc file: {e}"

# Hàm khởi tạo session state
def init_session_state():
    # Sử dụng API key cố định
    if "api_key" not in st.session_state:
        st.session_state.api_key = GEMINI_API_KEY
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "gemini_model" not in st.session_state:
        st.session_state.gemini_model = "gemini-2.0-flash"
    if "temperature" not in st.session_state:
        st.session_state.temperature = 0.7
    if "max_output_tokens" not in st.session_state:
        st.session_state.max_output_tokens = 2048
    if "top_k" not in st.session_state:
        st.session_state.top_k = 40
    if "top_p" not in st.session_state:
        st.session_state.top_p = 0.95
    if "system_prompt" not in st.session_state:
        st.session_state.system_prompt = "Bạn là trợ lý AI hữu ích, lịch sự và trung thực."
    if "full_system_prompt" not in st.session_state:
        st.session_state.full_system_prompt = f"[SYSTEM]: {st.session_state.system_prompt}"
    if "model_configured" not in st.session_state:
        st.session_state.model_configured = False
    if "data_markdown_content" not in st.session_state:
        st.session_state.data_markdown_content = ""
    if "use_rag" not in st.session_state:
        st.session_state.use_rag = True
    if "markdown_file_path" not in st.session_state:
        st.session_state.markdown_file_path = "data.markdown"
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "Chat"
    if "show_markdown_preview" not in st.session_state:
        st.session_state.show_markdown_preview = False

# Khởi tạo session state
init_session_state()

# Hàm khởi tạo model Gemini
def configure_gemini_model():
    try:
        genai.configure(api_key=st.session_state.api_key)
        
        generation_config = {
            "temperature": st.session_state.temperature,
            "max_output_tokens": st.session_state.max_output_tokens,
            "top_k": st.session_state.top_k,
            "top_p": st.session_state.top_p,
        }
        
        # Tạo system prompt và lưu vào session state để sử dụng khi gửi tin nhắn
        base_system_prompt = st.session_state.system_prompt
        
        if st.session_state.use_rag and st.session_state.data_markdown_content:
            # Nếu sử dụng RAG, thêm thông tin từ file markdown vào system prompt
            full_system_prompt = f"""[SYSTEM]: {base_system_prompt}

Bạn có quyền truy cập vào thông tin sau:

{st.session_state.data_markdown_content}

Khi người dùng hỏi về nội dung liên quan đến thông tin trên, hãy sử dụng thông tin này để trả lời. 
Nếu câu hỏi không liên quan đến thông tin này, hãy trả lời dựa trên kiến thức chung của bạn."""
        else:
            # Nếu không sử dụng RAG, sử dụng system prompt gốc
            full_system_prompt = f"[SYSTEM]: {base_system_prompt}"
        
        # Lưu system prompt vào session state
        st.session_state.full_system_prompt = full_system_prompt
        
        model = genai.GenerativeModel(
            model_name=st.session_state.gemini_model,
            generation_config=generation_config
        )
        
        # Tạo chat session nhưng không sử dụng system_instruction
        chat = model.start_chat(history=[])
        
        st.session_state.model = model
        st.session_state.chat = chat
        st.session_state.model_configured = True
        return True
    except Exception as e:
        st.error(f"Lỗi khi cấu hình model Gemini: {e}")
        st.session_state.model_configured = False
        return False

# Hàm gửi tin nhắn và nhận phản hồi, tích hợp system prompt
def send_message(user_message):
    if not st.session_state.model_configured:
        st.error("Vui lòng cấu hình API key và các thông số trước khi gửi tin nhắn.")
        return
    
    # Thêm tin nhắn người dùng vào lịch sử
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.messages.append({"role": "user", "content": user_message, "timestamp": timestamp})
    
    try:
        # Gửi tin nhắn kết hợp system prompt và user message
        combined_message = f"{st.session_state.full_system_prompt}\n\n[USER]: {user_message}"
        response = st.session_state.chat.send_message(combined_message)
            
        response_text = response.text
        
        # Thêm phản hồi vào lịch sử
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.messages.append({"role": "model", "content": response_text, "timestamp": timestamp})
    except Exception as e:
        st.error(f"Lỗi khi gọi API Gemini: {e}")

# Hàm tải file markdown
def load_markdown_file():
    try:
        file_path = st.session_state.markdown_file_path
        content = read_markdown_file(file_path)
        st.session_state.data_markdown_content = content
        return True, f"Đã tải file {file_path} thành công."
    except Exception as e:
        return False, f"Lỗi khi tải file: {e}"

# Hàm hiển thị tab Cài đặt
def display_settings_tab():
    # Hiển thị thông báo API key đã được cấu hình sẵn
    st.success(f"API Key đã được cấu hình tự động")
    
    # Tăng không gian cho System Prompt bằng cách sử dụng full width
    st.subheader("System Prompt")
    system_prompt = st.text_area("System Prompt:", value=st.session_state.system_prompt, height=300)
    if system_prompt != st.session_state.system_prompt:
        st.session_state.system_prompt = system_prompt
        st.session_state.model_configured = False
    st.info("Lưu ý: Thay đổi System Prompt chỉ có hiệu lực sau khi nhấn 'Áp dụng cài đặt'.")
    
    # Tạo 2 cột cho cài đặt model
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Cài đặt Model")
        model_options = ["gemini-2.5-flash-preview-04-17", "gemini-2.5-pro-preview-05-06", "gemini-2.0-flash"]
        selected_model = st.selectbox("Model:", model_options, index=model_options.index(st.session_state.gemini_model) if st.session_state.gemini_model in model_options else 0)
        if selected_model != st.session_state.gemini_model:
            st.session_state.gemini_model = selected_model
            st.session_state.model_configured = False
    
    with col2:
        with st.expander("Cài đặt nâng cao", expanded=True):
            temperature = st.slider("Temperature:", min_value=0.0, max_value=1.0, value=st.session_state.temperature, step=0.05)
            if temperature != st.session_state.temperature:
                st.session_state.temperature = temperature
                st.session_state.model_configured = False
            
            max_tokens = st.slider("Max Output Tokens:", min_value=100, max_value=8192, value=st.session_state.max_output_tokens, step=100)
            if max_tokens != st.session_state.max_output_tokens:
                st.session_state.max_output_tokens = max_tokens
                st.session_state.model_configured = False
                
            top_k = st.slider("Top K:", min_value=1, max_value=100, value=st.session_state.top_k, step=1)
            if top_k != st.session_state.top_k:
                st.session_state.top_k = top_k
                st.session_state.model_configured = False
                
            top_p = st.slider("Top P:", min_value=0.0, max_value=1.0, value=st.session_state.top_p, step=0.05)
            if top_p != st.session_state.top_p:
                st.session_state.top_p = top_p
                st.session_state.model_configured = False
    
    # Nút cấu hình model
    if st.button("Áp dụng cài đặt", type="primary"):
        with st.spinner("Đang cấu hình model..."):
            if configure_gemini_model():
                st.success("Cấu hình model thành công!")

# Hàm hiển thị tab RAG
def display_rag_tab():
    st.subheader("Cài đặt RAG")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        use_rag = st.checkbox("Sử dụng RAG", value=st.session_state.use_rag)
        if use_rag != st.session_state.use_rag:
            st.session_state.use_rag = use_rag
            st.session_state.model_configured = False
        
        markdown_file_path = st.text_input("Đường dẫn file markdown:", value=st.session_state.markdown_file_path)
        if markdown_file_path != st.session_state.markdown_file_path:
            st.session_state.markdown_file_path = markdown_file_path
        
        if st.button("Tải file markdown", type="primary"):
            success, message = load_markdown_file()
            if success:
                st.success(message)
                # Reset model_configured để buộc cấu hình lại model với RAG mới
                st.session_state.model_configured = False
                # Hiển thị preview
                st.session_state.show_markdown_preview = True
            else:
                st.error(message)
    
    with col2:
        if st.session_state.data_markdown_content:
            st.subheader("Preview file markdown")
            st.info("Hiển thị 500 ký tự đầu tiên. Nhấn nút 'Xem đầy đủ' để xem toàn bộ nội dung.")
            st.code(st.session_state.data_markdown_content[:500] + "..." if len(st.session_state.data_markdown_content) > 500 else st.session_state.data_markdown_content)
            
            if st.button("Xem đầy đủ nội dung markdown"):
                st.session_state.show_markdown_preview = True
    
    # Hiển thị markdown đầy đủ trong modal
    if st.session_state.show_markdown_preview and st.session_state.data_markdown_content:
        with st.expander("Nội dung đầy đủ của file markdown", expanded=True):
            st.markdown(st.session_state.data_markdown_content)
            if st.button("Đóng preview"):
                st.session_state.show_markdown_preview = False

# Hàm hiển thị tab Chat
def display_chat_tab():
    # Hiển thị lịch sử tin nhắn
    col1, col2 = st.columns([5, 1])
    with col1:
        st.subheader("Lịch sử hội thoại")
    with col2:
        # Nút xóa lịch sử đặt ở đây, bên cạnh tiêu đề lịch sử hội thoại
        if st.button("Xóa lịch sử", type="primary"):
            st.session_state.messages = []
            st.success("Đã xóa lịch sử hội thoại!")
            st.experimental_rerun()

    chat_container = st.container(height=500)

    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.write(f"**{msg['timestamp']}**")
                    st.markdown(msg["content"])
            else:
                with st.chat_message("assistant"):
                    st.write(f"**{msg['timestamp']}**")
                    st.markdown(msg["content"])

# Giao diện chính
st.title("💬 Gemini Chat Demo" + (" với RAG" if st.session_state.use_rag else ""))

# Tạo tabs cho điều hướng giữa các chức năng
tab_chat, tab_rag, tab_settings = st.tabs(["Chat", "Cài đặt RAG", "Cài đặt Model"])

# Hiển thị nội dung theo tab được chọn
with tab_chat:
    display_chat_tab()
    
with tab_rag:
    display_rag_tab()
    
with tab_settings:
    display_settings_tab()

# Đặt chat_input ở mức top-level, bên ngoài tabs
st.subheader("Nhập câu hỏi")
user_input = st.chat_input("Nhập tin nhắn của bạn...")

# Xử lý input của người dùng
if user_input:
    if not st.session_state.model_configured:
        # Tự động cấu hình model nếu chưa được cấu hình
        with st.spinner("Đang cấu hình model..."):
            if configure_gemini_model():
                send_message(user_input)
                st.experimental_rerun()
            else:
                st.error("Có lỗi khi cấu hình model. Vui lòng kiểm tra lại cài đặt.")
    else:
        send_message(user_input)
        st.experimental_rerun()

# Hiển thị thông tin về ứng dụng
st.sidebar.markdown("---")
st.sidebar.caption("Gemini Chat Demo với RAG")
st.sidebar.caption("Tạo bởi Streamlit và Gemini API") 