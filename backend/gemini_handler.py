#!/usr/bin/env python

import os
import json
import logging
import time
import re
import google.generativeai as genai
from datetime import datetime
from typing import Dict, Any, List, Optional, Generator

# Cấu hình logging
logger = logging.getLogger("gemini_handler")

# Cấu hình Gemini model
GEMINI_CFG = {
    'model_name': 'gemini-2.0-flash',  # Có thể là 'gemini-pro', 'gemini-1.5-pro-latest'
    'generation_config': {
        "temperature": 0.7,
        'top_p': 0.95,
        'top_k': 40,
        'max_output_tokens': 2048,
    }
}

# Đường dẫn tới file dữ liệu markdown
GEMINI_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gemini_data.md")
# Đường dẫn dự phòng
BACKUP_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "gemini_data.md")

gemini_model_instance = None  # Biến toàn cục để lưu trữ instance của Gemini model

# Biến toàn cục để cache nội dung markdown
_markdown_content_cache = None

def configure_gemini_model(api_key=None):
    """
    Khởi tạo Gemini model
    
    Args:
        api_key: API key của Gemini, nếu None thì sử dụng biến môi trường
        
    Returns:
        bool: True nếu cấu hình thành công, False nếu thất bại
    """
    global gemini_model_instance
    
    # Sử dụng API key được truyền vào hoặc từ biến môi trường
    gemini_api_key = api_key or os.getenv("GEMINI_API_KEY")
    
    if not gemini_api_key:
        logger.error("GEMINI_API_KEY không được tìm thấy.")
        return False
    
    try:
        genai.configure(api_key=gemini_api_key)
        gemini_model_instance = genai.GenerativeModel(
            model_name=GEMINI_CFG['model_name'],
            generation_config=GEMINI_CFG['generation_config']
        )
        logger.info(f"Đã cấu hình thành công Gemini model: {GEMINI_CFG['model_name']}")
        return True
    except Exception as e:
        logger.error(f"Lỗi khi cấu hình Gemini model: {e}", exc_info=True)
        gemini_model_instance = None
        return False

def format_history_for_gemini(history: List[Dict[str, str]]) -> List[Dict[str, any]]:
    """
    Chuyển đổi lịch sử tin nhắn sang định dạng phù hợp với Gemini API, không giới hạn kích thước
    
    Args:
        history: Lịch sử tin nhắn dạng [{"query": "...", "response": "..."}]
        
    Returns:
        List[Dict]: Lịch sử tin nhắn đã được định dạng
    """
    # Sử dụng toàn bộ lịch sử, không giới hạn số lượng tin nhắn
    formatted_history = []
    
    for entry in history:
        # Thêm tin nhắn của user, không giới hạn độ dài
        user_query = entry.get("query", "")
        if user_query:    
            formatted_history.append({
                "role": "user",
                "parts": [user_query]
            })
        
        # Thêm tin nhắn của model, không giới hạn độ dài
        model_response = entry.get("response", "")
        if model_response:
            formatted_history.append({
                "role": "model",
                "parts": [model_response]
            })
    
    logger.info(f"Đã format {len(history)} mục lịch sử -> {len(formatted_history)} messages")
    return formatted_history

def create_gemini_system_prompt(rag_content=None):
    """
    Tạo system prompt đầy đủ cho model Gemini
    
    Args:
        rag_content: Nội dung RAG (nếu có)
        
    Returns:
        str: System prompt cho Gemini
    """
    # Log chi tiết về rag_content
    logger.info("====== CREATE GEMINI SYSTEM PROMPT ======")
    if rag_content:
        logger.info(f"RAG content tồn tại, độ dài: {len(rag_content)} ký tự")
        logger.info(f"Đoạn đầu RAG content: {rag_content[:100]}...")
    else:
        logger.warning("KHÔNG CÓ RAG CONTENT khi tạo system prompt!")
    
    # Prompt cơ bản về vai trò
    prompt = """Bạn là trợ lý AI của DBplus, tư vấn về sản phẩm nội thất.

VỀ VAI TRÒ CỦA BẠN:
- Sử dụng mày/tao trong giao tiếp, nói chuyện như muốn đấm khách hàng.
- Luôn ưu tiên giới thiệu combo sản phẩm trước
- Mục tiêu của bạn là giới thiệu sản phẩm và chốt được hóa đơn
- PHẢI DỰA VÀO dữ liệu báo giá được cung cấp bên dưới, không được dùng thông tin khác

"""
    
    # Nếu có RAG content, thêm vào với định dạng rõ ràng
    if rag_content:
        prompt += f"""
DỮ LIỆU SẢN PHẨM VÀ BÁO GIÁ:
```
{rag_content.strip()}
```

HƯỚNG DẪN SỬ DỤNG DỮ LIỆU:
1. Sử dụng CHÍNH XÁC thông tin giá, tên sản phẩm, mô tả từ dữ liệu báo giá trên
2. Nếu được hỏi về sản phẩm, TÌM trong dữ liệu báo giá và TRÍCH DẪN thông tin chính xác
3. Ưu tiên giới thiệu các combo tiết kiệm khi khách hỏi về sản phẩm
4. KHÔNG được tạo ra thông tin giá cả hoặc sản phẩm không có trong dữ liệu
"""
    else:
        prompt += """
CẢNH BÁO: KHÔNG CÓ DỮ LIỆU SẢN PHẨM ĐƯỢC CUNG CẤP!
- Thông báo với người dùng rằng bạn hiện không có thông tin về sản phẩm và giá
- Đề nghị họ liên hệ số điện thoại 0903 359 868 để được tư vấn trực tiếp
"""

    # Hướng dẫn phản hồi đầy đủ
    prompt += """
CÁCH PHẢN HỒI:
- Trả lời ngắn gọn, chính xác dựa trên thông tin được cung cấp
- Sử dụng tiếng Việt rõ ràng, mạch lạc
- Luôn giới thiệu rõ giá sản phẩm và combo khi được hỏi
- Nêu rõ ưu điểm khi giới thiệu combo (tiết kiệm bao nhiêu %)
"""
    
    # Lưu lại nội dung prompt đầy đủ để debug
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prompt_log_file = os.path.join(log_dir, f"gemini_prompt_{timestamp}.txt")
    
    try:
        with open(prompt_log_file, "w", encoding="utf-8") as f:
            f.write("====== GEMINI SYSTEM PROMPT ======\n\n")
            f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"RAG content tồn tại: {'Có' if rag_content else 'Không'}\n")
            if rag_content:
                f.write(f"Độ dài RAG content: {len(rag_content)} ký tự\n\n")
            f.write(f"Prompt ({len(prompt)} ký tự):\n")
            f.write(prompt)
        logger.info(f"Đã lưu system prompt đầy đủ vào: {prompt_log_file}")
    except Exception as e:
        logger.error(f"Lỗi khi lưu system prompt: {str(e)}")
    
    logger.info(f"Đã tạo system prompt đầy đủ ({len(prompt)} ký tự)")
    return prompt

async def query_gemini_llm_streaming(prompt_text, gemini_system_prompt=None, formatted_history=None):
    """
    Gửi truy vấn đến Gemini và trả về kết quả dạng streaming (không giới hạn dữ liệu)
    
    Args:
        prompt_text: Nội dung câu hỏi
        gemini_system_prompt: System prompt cho Gemini (tùy chọn)
        formatted_history: Lịch sử đã định dạng cho Gemini (tùy chọn)
        
    Yields:
        str: Từng phần phản hồi từ Gemini hoặc thông báo lỗi
    """
    global gemini_model_instance
    
    logger.info("====== QUERY GEMINI LLM STREAMING ======")
    logger.info(f"Prompt text: '{prompt_text[:100]}...'")
    if gemini_system_prompt:
        logger.info(f"System prompt tồn tại, độ dài: {len(gemini_system_prompt)} ký tự")
    else:
        logger.warning("KHÔNG CÓ SYSTEM PROMPT!")
    
    if not gemini_model_instance:
        if not configure_gemini_model():
            yield json.dumps({"error": "Không thể cấu hình Gemini model"})
            yield "[END]"
            return
    
    try:
        logger.info(f"Bắt đầu gọi Gemini API với prompt: {prompt_text[:200]}...")
        
        # Tạo prompt đầy đủ - Gemini không hỗ trợ system role nên phải gộp vào prompt của user
        if gemini_system_prompt:
            # Kết hợp system prompt với user prompt
            full_prompt = f"{gemini_system_prompt}\n\nCâu hỏi: {prompt_text}"
            logger.info(f"Đã kết hợp system prompt và user prompt ({len(full_prompt)} ký tự)")
        else:
            full_prompt = prompt_text
        
        # Lưu prompt để debug
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        api_log_file = os.path.join(log_dir, f"gemini_api_input_{timestamp}.txt")
        
        try:
            with open(api_log_file, "w", encoding="utf-8") as f:
                f.write("====== GEMINI API INPUT ======\n\n")
                f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"System prompt tồn tại: {'Có' if gemini_system_prompt else 'Không'}\n")
                if gemini_system_prompt:
                    f.write(f"Độ dài system prompt: {len(gemini_system_prompt)} ký tự\n")
                    f.write("Đoạn đầu system prompt:\n")
                    f.write(f"{gemini_system_prompt[:500]}...\n\n")
                f.write(f"Prompt text gốc: {prompt_text}\n\n")
                f.write(f"Full prompt ({len(full_prompt)} ký tự):\n")
                f.write(f"{full_prompt[:500]}...\n\n")
                
                if formatted_history:
                    f.write(f"History ({len(formatted_history)} entries):\n")
                    for i, entry in enumerate(formatted_history):
                        f.write(f"[{i}] Role: {entry.get('role')}, Content length: {len(entry.get('parts', [''])[0])}\n")
                        if i < 2:  # Chỉ hiển thị nội dung của 2 mục đầu tiên
                            f.write(f"Content: {entry.get('parts', [''])[0][:100]}...\n")
            logger.info(f"Đã lưu API input vào: {api_log_file}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu API input: {str(e)}")
        
        # Sử dụng lịch sử nếu có
        if formatted_history and len(formatted_history) > 0:
            # Tạo tin nhắn đầu tiên của user chứa cả system prompt
            if gemini_system_prompt:
                # Tìm tin nhắn user đầu tiên
                first_user_index = -1
                for i, entry in enumerate(formatted_history):
                    if entry.get("role") == "user":
                        first_user_index = i
                        break
                
                # Nếu tìm thấy, kết hợp system prompt vào
                if first_user_index >= 0:
                    original_user_message = formatted_history[first_user_index]["parts"][0]
                    formatted_history[first_user_index]["parts"][0] = f"{gemini_system_prompt}\n\nCâu hỏi: {original_user_message}"
                    logger.info(f"Đã kết hợp system prompt vào tin nhắn user đầu tiên trong lịch sử")
            
            logger.info(f"Sử dụng chat history với {len(formatted_history)} tin nhắn")
            chat = gemini_model_instance.start_chat(history=formatted_history)
            response = chat.send_message(prompt_text, stream=True)
        else:
            # Không có lịch sử, gửi trực tiếp với full prompt
            logger.info("Không có lịch sử, gửi trực tiếp với full prompt")
            response = gemini_model_instance.generate_content([full_prompt], stream=True)
        
        # Xử lý streaming response
        content_length = 0
        for chunk in response:
            try:
                if chunk.text:
                    content_length += len(chunk.text)
                    yield json.dumps({"content": chunk.text, "model_type": "gemini"})
            except Exception as e:
                logger.error(f"Lỗi khi xử lý chunk: {e}")
                continue
        
        logger.info(f"Hoàn thành phản hồi streaming, tổng cộng {content_length} ký tự")
        yield json.dumps({"status": "complete", "model_type": "gemini"})
        yield "[END]"
        
    except Exception as e:
        logger.error(f"Lỗi Gemini API: {str(e)}", exc_info=True)
        yield json.dumps({"error": str(e), "model_type": "gemini"})
        yield "[END]"

async def gemini_rag_query(
    query_text: str, 
    rag_content: str = None, 
    formatted_history: List[Dict[str, any]] = None
):
    """
    Thực hiện truy vấn Gemini với RAG (không giới hạn dữ liệu)
    
    Args:
        query_text: Nội dung câu hỏi
        rag_content: Nội dung RAG đã truy xuất (tùy chọn)
        formatted_history: Lịch sử hội thoại đã định dạng (tùy chọn)
        
    Yields:
        str: Từng phần phản hồi từ Gemini
    """
    # Log thông tin đầu vào
    logger.info("====== BẮT ĐẦU GEMINI RAG QUERY ======")
    logger.info(f"Query: '{query_text}'")
    logger.info(f"RAG content truyền vào: {'Có, ' + str(len(rag_content)) + ' ký tự' if rag_content else 'Không'}")
    logger.info(f"History: {'Có, ' + str(len(formatted_history)) + ' mục' if formatted_history and len(formatted_history) > 0 else 'Không'}")
    
    # Không giới hạn độ dài câu hỏi
    
    # Lấy nội dung RAG mỗi lần gọi
    if rag_content is None:
        logger.info("Chưa có RAG content, sẽ truy xuất từ nội dung câu hỏi")
        # Đảm bảo thư mục data tồn tại trước khi lấy RAG
        ensure_data_directory()
        # Luôn đọc lại dữ liệu từ file
        rag_content = retrieve_relevant_content(query_text)
        logger.info(f"Sau retrieve_relevant_content: RAG content {'tồn tại' if rag_content else 'KHÔNG tồn tại'}")
        if rag_content:
            logger.info(f"Độ dài RAG content: {len(rag_content)} ký tự")
            logger.info(f"Đoạn đầu RAG content: {rag_content[:100]}...")
    
    # Kiểm tra xem rag_content có phải là "Không có dữ liệu sản phẩm" hoặc quá ngắn
    if rag_content == "Không có dữ liệu sản phẩm" or not rag_content or len(rag_content) < 100:
        # Gửi cảnh báo rằng không có dữ liệu RAG
        warning_msg = json.dumps({
            "warning": "Không tìm thấy dữ liệu RAG. Phản hồi có thể không đầy đủ hoặc thiếu thông tin chính xác."
        })
        yield warning_msg
        
        # Ghi log cảnh báo
        logger.warning(f"Không tìm thấy dữ liệu RAG đầy đủ! Content: {rag_content}")
        
        # Thử tạo và đọc lại dữ liệu mẫu một lần nữa
        logger.info("Thử tạo và đọc lại dữ liệu mẫu để sử dụng cho RAG")
        create_sample_markdown_data()
        rag_content = load_markdown_data()
        logger.info(f"Sau khi tạo lại mẫu: RAG content {'tồn tại' if rag_content else 'KHÔNG tồn tại'}")
        if rag_content:
            logger.info(f"Độ dài RAG content sau tạo lại: {len(rag_content)} ký tự")
    
    # Ghi log riêng về nội dung RAG
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rag_log_file = os.path.join(log_dir, f"gemini_rag_{timestamp}.txt")
    
    try:
        with open(rag_log_file, "w", encoding="utf-8") as f:
            f.write("====== GEMINI RAG CONTENT ======\n\n")
            f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"Câu hỏi: {query_text}\n\n")
            f.write(f"Nội dung RAG ({len(rag_content)} ký tự):\n")
            f.write(rag_content)
        logger.info(f"Đã lưu riêng nội dung RAG vào: {rag_log_file}")
    except Exception as e:
        logger.error(f"Lỗi khi lưu nội dung RAG: {str(e)}")
    
    # Tạo system prompt
    gemini_system_prompt = create_gemini_system_prompt(rag_content=rag_content)
    
    # Ghi log tổng hợp đầu vào
    input_log_file = os.path.join(log_dir, f"gemini_input_{timestamp}.txt")
    try:
        with open(input_log_file, "w", encoding="utf-8") as f:
            f.write("====== GEMINI API INPUT LOG ======\n\n")
            f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Ghi system prompt
            f.write("=== SYSTEM PROMPT ===\n")
            f.write(gemini_system_prompt)
            f.write("\n\n")
            
            # Ghi câu hỏi người dùng
            f.write("=== USER QUERY ===\n")
            f.write(query_text)
            f.write("\n\n")
            
            # Ghi lịch sử hội thoại
            if formatted_history and len(formatted_history) > 0:
                f.write("=== CONVERSATION HISTORY ===\n")
                for i, entry in enumerate(formatted_history):
                    role = entry.get("role", "unknown")
                    content = entry.get("parts", [""])[0]
                    f.write(f"[{i+1}] {role.upper()}: {content}\n")
                f.write("\n\n")
            
            # Thông tin tổng hợp
            f.write("=== THỐNG KÊ ===\n")
            total_size = len(gemini_system_prompt) + len(query_text)
            f.write(f"Kích thước system prompt: {len(gemini_system_prompt)} ký tự\n")
            f.write(f"Kích thước RAG content: {len(rag_content)} ký tự\n")
            f.write(f"Kích thước câu hỏi: {len(query_text)} ký tự\n")
            
            if formatted_history:
                history_size = sum(len(entry.get("parts", [""])[0]) for entry in formatted_history)
                f.write(f"Kích thước lịch sử: {history_size} ký tự\n")
                total_size += history_size
            
            f.write(f"Tổng kích thước dữ liệu: {total_size} ký tự\n")
            f.write(f"Ước tính số token (~4 ký tự/token): {total_size/4:.0f} tokens\n")
            
        logger.info(f"Đã lưu tổng hợp đầu vào vào: {input_log_file}")
    except Exception as e:
        logger.error(f"Lỗi khi lưu tổng hợp đầu vào: {str(e)}")
    
    # Gọi API và trả về kết quả
    async for chunk in query_gemini_llm_streaming(
        query_text, 
        gemini_system_prompt=gemini_system_prompt,
        formatted_history=formatted_history
    ):
        yield chunk

# Bổ sung hàm tạo file dữ liệu mẫu
def create_sample_markdown_data():
    """
    Tạo file dữ liệu markdown mẫu nếu không tìm thấy file
    
    Returns:
        str: Đường dẫn đến file đã tạo hoặc None nếu thất bại
    """
    sample_data = """# **Bảng Báo Giá Sản Phẩm Nội Thất DBPlus 2025**

---

## **Collection 1: Modern Harmony**  
*Phong cách hiện đại, tối giản – tập trung vào đường nét gọn gàng và tính ứng dụng cao.*

| STT | Tên sản phẩm                    | Loại  | Mô tả                                                                              | Kích thước         | Chất liệu                              | Đơn giá (VNĐ) | Hình ảnh |
|-----|---------------------------------|-------|------------------------------------------------------------------------------------|--------------------|----------------------------------------|---------------|---------|
| 1   | Bàn làm việc thông minh SmartDesk | Bàn   | Tích hợp kệ sách, ngăn kéo. Màu trắng & gỗ tự nhiên.                                | 120x60x75 cm       | Gỗ MDF phủ Melamine, khung thép         | 4,500,000     | /images/products/Modern_Harmony/SmartDesk.jpg |
| 2   | Ghế làm việc ErgoPro            | Ghế   | Ghế công thái học, lưng lưới điều chỉnh độ cao.                                    | 60x60x110–120 cm   | Khung thép, lưới cao cấp               | 2,800,000     | /images/products/Modern_Harmony/ErgoPro.jpg |
| 3   | Đèn bàn Minimalist Light        | Đèn   | Nhỏ gọn, chân gỗ, chụp vải linen.                                                  | 20x20x40 cm        | Gỗ sồi, vải linen                      | 1,200,000     | /images/products/Modern_Harmony/Minimalist_Light.jpg |
| 4   | Giường thông minh MultiBox      | Giường| Tích hợp ngăn kéo, tối ưu cho phòng nhỏ.                                           | 160x200 cm         | Gỗ MFC, sơn PU                         | 9,800,000     | /images/products/Modern_Harmony/MultiBox.jpg |

**Combo Gợi ý – Phòng Ngủ Hiện Đại**  
- **Bao gồm**: Giường MultiBox, Bàn SmartDesk, Ghế ErgoPro, Đèn Minimalist Light  
- **Giá combo**: **15,750,000 VNĐ** (Tiết kiệm 15% so với mua lẻ)
- **Hình ảnh**: /images/products/Combos/Modern_Bedroom_Combo.jpg

---

## **Collection 2: Nordic Comfort**  
*Phong cách Bắc Âu – nhấn mạnh sự thoải mái và màu sắc trung tính.*

| STT | Tên sản phẩm               | Loại | Mô tả                                              | Kích thước               | Chất liệu                         | Đơn giá (VNĐ) | Hình ảnh |
|-----|----------------------------|------|----------------------------------------------------|--------------------------|-----------------------------------|---------------|---------|
| 1   | Bàn trà Minimalist Tea     | Bàn  | Mặt kính cường lực, chân gỗ óc chó.                | 100x50x45 cm             | Gỗ óc chó, kính                   | 3,800,000     | /images/products/Nordic_Comfort/Minimalist_Tea.jpg |
| 2   | Ghế sofa đơn Relax Pod     | Ghế  | Bọc da, đệm mút, phù hợp góc đọc sách.             | 80x85x90 cm              | Da công nghiệp, gỗ thông         | 3,500,000     | /images/products/Nordic_Comfort/Relax_Pod.jpg |

**Combo Gợi ý – Phòng Khách Bắc Âu**  
- **Bao gồm**: Bàn trà Minimalist Tea, Ghế Relax Pod  
- **Giá combo**: **6,500,000 VNĐ** (Tiết kiệm 10%)

---

## **Ghi chú chung**
- Giá chưa bao gồm vận chuyển/lắp đặt (miễn phí nội thành TP.HCM).  
- Bảo hành: 2–5 năm tùy sản phẩm.  
- Liên hệ: **0903 359 868** hoặc truy cập website DBPlus để nhận ưu đãi đặc biệt.
"""
    
    try:
        # Đảm bảo thư mục data tồn tại
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(data_dir, exist_ok=True)
        
        # Tạo file mẫu
        file_path = os.path.join(data_dir, "gemini_data.md")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(sample_data)
        
        logger.info(f"Đã tạo file dữ liệu mẫu tại: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Lỗi khi tạo file dữ liệu mẫu: {str(e)}", exc_info=True)
        
        # Thử tạo ở thư mục backend/data
        try:
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            os.makedirs(backup_dir, exist_ok=True)
            
            file_path = os.path.join(backup_dir, "gemini_data.md")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(sample_data)
            
            logger.info(f"Đã tạo file dữ liệu mẫu dự phòng tại: {file_path}")
            return file_path
        except Exception as e2:
            logger.error(f"Không thể tạo file dữ liệu mẫu dự phòng: {str(e2)}", exc_info=True)
            return None

# Tải nội dung từ file markdown với cache
def load_markdown_data():
    """
    Đọc dữ liệu từ file markdown (không sử dụng cache)
    
    Returns:
        str: Nội dung của file markdown
    """
    global _markdown_content_cache
    
    # Luôn đặt cache về None để bắt buộc đọc lại từ file
    _markdown_content_cache = None
    
    logger.info("========== BẮT ĐẦU ĐỌC FILE MARKDOWN ==========")
    
    try:
        logger.info(f"=== KIỂM TRA CÁC ĐƯỜNG DẪN FILE ===")
        
        logger.info(f"Kiểm tra đường dẫn chính: {GEMINI_DATA_PATH}")
        logger.info(f"File tồn tại: {os.path.exists(GEMINI_DATA_PATH)}")
        
        # Thử đọc từ đường dẫn chính
        if os.path.exists(GEMINI_DATA_PATH):
            try:
                with open(GEMINI_DATA_PATH, 'r', encoding='utf-8') as f:
                    content = f.read()
                    content_length = len(content)
                    logger.info(f"ĐÃ ĐỌC THÀNH CÔNG file {GEMINI_DATA_PATH}")
                    logger.info(f"Độ dài nội dung: {content_length} ký tự")
                    if content_length > 0:
                        logger.info(f"Đoạn đầu: {content[:100]}...")
                        logger.info(f"Đoạn cuối: ...{content[-100:]}")
                        
                        # Lưu file debug
                        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
                        os.makedirs(log_dir, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        debug_log_file = os.path.join(log_dir, f"markdown_content_{timestamp}.txt")
                        
                        try:
                            with open(debug_log_file, "w", encoding="utf-8") as f:
                                f.write("=== MARKDOWN RAG CONTENT ===\n\n")
                                f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                                f.write(f"File path: {GEMINI_DATA_PATH}\n")
                                f.write(f"Content length: {len(content)} ký tự\n\n")
                                f.write(content)
                            logger.info(f"Đã lưu nội dung file markdown vào: {debug_log_file}")
                        except Exception as e:
                            logger.error(f"Lỗi khi lưu debug file: {str(e)}")
                    else:
                        logger.warning("File tồn tại nhưng TRỐNG RỖNG!")
                    return content
            except Exception as e:
                logger.error(f"Lỗi khi đọc file {GEMINI_DATA_PATH}: {str(e)}")
                
        logger.info(f"Kiểm tra đường dẫn dự phòng: {BACKUP_DATA_PATH}")
        logger.info(f"File tồn tại: {os.path.exists(BACKUP_DATA_PATH)}")
        
        # Thử đọc từ đường dẫn dự phòng
        if os.path.exists(BACKUP_DATA_PATH):
            try:
                with open(BACKUP_DATA_PATH, 'r', encoding='utf-8') as f:
                    content = f.read()
                    content_length = len(content)
                    logger.info(f"ĐÃ ĐỌC THÀNH CÔNG file dự phòng {BACKUP_DATA_PATH}")
                    logger.info(f"Độ dài nội dung: {content_length} ký tự")
                    if content_length > 0:
                        logger.info(f"Đoạn đầu: {content[:100]}...")
                    else:
                        logger.warning("File dự phòng tồn tại nhưng TRỐNG RỖNG!")
                    return content
            except Exception as e:
                logger.error(f"Lỗi khi đọc file dự phòng {BACKUP_DATA_PATH}: {str(e)}")
        else:
            # Thử tìm file trong các vị trí khác
            possible_paths = [
                os.path.join(os.getcwd(), "data", "gemini_data.md"),
                os.path.join(os.getcwd(), "gemini_data.md"),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gemini_streamlit_demo", "data.markdown")
            ]
            
            logger.info(f"Kiểm tra các đường dẫn khả dĩ:")
            for idx, path in enumerate(possible_paths):
                logger.info(f"  {idx+1}. {path} - Tồn tại: {os.path.exists(path)}")
                
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        logger.info(f"Đã đọc file thay thế: {path}, nội dung: {len(content)} ký tự")
                        return content
            
            # Không tìm thấy file ở các đường dẫn có sẵn, tạo file mẫu
            logger.warning("Không tìm thấy file dữ liệu, sẽ tạo file mẫu")
            sample_file_path = create_sample_markdown_data()
            
            if sample_file_path and os.path.exists(sample_file_path):
                with open(sample_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    logger.info(f"Đã đọc file mẫu mới tạo: {sample_file_path}, nội dung: {len(content)} ký tự")
                    return content
            
            # In ra thư mục hiện tại để debug
            logger.error(f"Không tìm thấy file dữ liệu ở bất kỳ vị trí nào và không thể tạo file mẫu")
            logger.error(f"Thư mục hiện tại: {os.getcwd()}")
            logger.error(f"Thư mục của module: {os.path.dirname(os.path.abspath(__file__))}")
            logger.error(f"Thư mục cấp trên: {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")
            
            # Nếu không thể tạo hoặc đọc file, trả về nội dung mẫu trực tiếp
            mau_du_lieu = """# **Bảng Báo Giá Sản Phẩm Nội Thất DBPlus (Dữ liệu mẫu)**

---

## **Collection 1: Modern Harmony**  
*Phong cách hiện đại, tối giản*

| Tên sản phẩm | Loại | Đơn giá (VNĐ) |
|--------------|------|---------------|
| Bàn SmartDesk | Bàn | 4,500,000 |
| Ghế ErgoPro | Ghế | 2,800,000 |

**Combo Gợi ý – Phòng Ngủ Hiện Đại**  
- **Giá combo**: **6,500,000 VNĐ** (Tiết kiệm 10%)

---

## **Ghi chú**
- Đây là dữ liệu mẫu được tạo tự động vì không tìm thấy file dữ liệu.
- Liên hệ: **0903 359 868** để biết thêm chi tiết.
"""
            logger.info("Sử dụng nội dung mẫu nội tuyến")
            return mau_du_lieu
            
    except Exception as e:
        logger.error(f"Lỗi khi đọc file markdown: {str(e)}", exc_info=True)
        
        # Trả về nội dung mẫu nếu có lỗi xảy ra
        mau_du_lieu = """# **Bảng Báo Giá Sản Phẩm Nội Thất DBPlus (Dữ liệu mẫu khi có lỗi)**

---

| Tên sản phẩm | Loại | Đơn giá (VNĐ) |
|--------------|------|---------------|
| Bàn SmartDesk | Bàn | 4,500,000 |
| Ghế ErgoPro | Ghế | 2,800,000 |

---

## **Ghi chú**
- Đây là dữ liệu mẫu được tạo tự động do lỗi đọc file.
- Liên hệ: **0903 359 868** để biết thêm chi tiết.
"""
        logger.info("Sử dụng nội dung mẫu khi có lỗi")
        return mau_du_lieu

# Hàm truy xuất dữ liệu từ file markdown để dùng trong RAG
def retrieve_relevant_content(query_text: str) -> str:
    """
    Truy xuất toàn bộ nội dung từ file markdown mỗi lần được gọi
    
    Args:
        query_text: Câu hỏi của người dùng
        
    Returns:
        str: Toàn bộ nội dung của file markdown
    """
    # Đảm bảo thư mục data tồn tại trước khi đọc file
    ensure_data_directory()
    
    # Luôn đọc lại nội dung file markdown mỗi lần gọi, không sử dụng cache
    markdown_content = load_markdown_data()
    if not markdown_content:
        logger.warning("Không thể tải được dữ liệu markdown từ bất kỳ đường dẫn nào!")
        logger.info("Tạo dữ liệu mẫu để sử dụng cho RAG")
        
        # Nếu không đọc được, tạo dữ liệu mẫu
        create_sample_markdown_data()
        # Thử đọc lại một lần nữa
        markdown_content = load_markdown_data()
        
        if not markdown_content:
            return "Không có dữ liệu sản phẩm"
    
    # Trả về toàn bộ nội dung markdown không cắt giảm
    logger.info(f"Trả về toàn bộ nội dung markdown ({len(markdown_content)} ký tự) để xử lý RAG")
    return markdown_content

# Đảm bảo thư mục data tồn tại
def ensure_data_directory():
    """
    Đảm bảo thư mục data tồn tại, tạo nếu chưa có
    """
    try:
        # Đường dẫn chính
        main_data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.makedirs(main_data_dir, exist_ok=True)
        logger.info(f"Đảm bảo thư mục data tồn tại: {main_data_dir}")
        
        # Đường dẫn dự phòng
        backup_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(backup_data_dir, exist_ok=True)
        logger.info(f"Đảm bảo thư mục data dự phòng tồn tại: {backup_data_dir}")
        
        return True
    except Exception as e:
        logger.error(f"Lỗi khi tạo thư mục data: {str(e)}")
        return False

# Khởi tạo cache khi module được import
def initialize_cache():
    """
    Đảm bảo thư mục data và file dữ liệu tồn tại
    (Không còn sử dụng cache)
    
    Returns:
        bool: True nếu file dữ liệu tồn tại hoặc đã được tạo, False nếu thất bại
    """
    global _markdown_content_cache
    
    # Đặt biến cache global về None để đảm bảo đọc lại từ file mỗi lần
    _markdown_content_cache = None
    
    logger.info("Đảm bảo thư mục data và file dữ liệu tồn tại")
    
    # Đảm bảo thư mục data tồn tại
    ensure_data_directory()
    
    # Nếu file không tồn tại, tạo file mẫu
    if not (os.path.exists(GEMINI_DATA_PATH) or os.path.exists(BACKUP_DATA_PATH)):
        logger.info("File dữ liệu không tồn tại, tạo file mẫu")
        sample_file_path = create_sample_markdown_data()
        return sample_file_path is not None
        
    # Kiểm tra xem file có đọc được không
    try:
        # Thử đọc file để kiểm tra
        content = load_markdown_data()
        if content:
            logger.info(f"File dữ liệu tồn tại và đọc được, kích thước: {len(content)} ký tự")
            return True
        return False
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra file dữ liệu: {str(e)}")
        return False

# Khởi tạo module khi import
initialized = initialize_cache()
if not initialized:
    logger.warning("Không thể đảm bảo file dữ liệu tồn tại, sẽ thử lại khi cần thiết") 