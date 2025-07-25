#!/usr/bin/env python

import os
import json
import logging
import time
import re
import google.generativeai as genai
from google.generativeai import GenerativeModel
from google.generativeai.types import AsyncGenerateContentResponse, GenerationConfig
from datetime import datetime
from typing import Dict, Any, List, Optional, Generator, AsyncGenerator, cast

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

gemini_model_instance: Optional[GenerativeModel] = None

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

def format_history_for_gemini(history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Chuyển đổi lịch sử tin nhắn sang định dạng phù hợp với Gemini API
    
    Args:
        history: Lịch sử tin nhắn dạng [{"query": "...", "response": "..."}]
        
    Returns:
        List[Dict]: Lịch sử tin nhắn đã được định dạng
    """
    formatted_history = []
    
    for entry in history:
        user_query = entry.get("query", "")
        if user_query:    
            formatted_history.append({
                "role": "user",
                "parts": [user_query]
            })
        
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
    prompt = """Bạn là Ngọc, trợ lý ảo của DBplus (công ty thiết kế nội thất) hỗ trợ nhân viên sales của DBPlus. Nhiệm vụ chính của bạn là hỗ trợ nhân viên Sales trong việc tra cứu và báo giá sản phẩm nội thất và dịch vụ thi công (hiện tại chưa có giá thi công nên hãy dựa vào kiến thức thị trường để ước lượng, vui lòng nói rõ đây là thông tin tham khảo).

VỀ VAI TRÒ CỦA BẠN:
- Ngôn ngữ: nghiêm túc, chuyên nghiệp, thân thiện, nhiệt tình.
- Trả lời ngắn gọn, rõ ràng, chính xác.
- Không để khách hàng chờ; luôn chủ động cung cấp thông tin.
- Không yêu cầu người dùng liên hệ với DBplus để có báo giá chính xác, bạn đang nói chuyện với nhân viên DBPlus, chỉ cung cấp thông tin và giá từ dữ liệu hoặc thị trường, chỉ cần nói rõ đây là thông tin tham khảo là được.
"""
    
    # Nếu có RAG content, thêm vào với định dạng rõ ràng
    if rag_content:
        prompt += f"""
DỮ LIỆU SẢN PHẨM VÀ BÁO GIÁ:
```
{rag_content.strip()}
```

HƯỚNG DẪN SỬ DỤNG DỮ LIỆU:
1. Sử dụng CHÍNH XÁC thông tin giá, tên sản phẩm, mô tả từ dữ liệu báo giá trên.
2. Nếu người dùng hỏi về sản phẩm, hãy TÌM trong dữ liệu báo giá và TRÍCH DẪN thông tin chính xác.
3. Nếu sản phẩm hoặc giá KHÔNG CÓ TRONG DỮ LIỆU DBPLUS thì phải luôn trả lời bằng mức GIÁ ƯỚC LƯỢNG THEO THỊ TRƯỜNG, nhưng phải nói rõ: "Giá này là ước lượng thị trường, không phải báo giá chính thức từ DBplus."
4. Không yêu cầu người dùng liên hệ với DBplus để có báo giá chính xác, bạn đang nói chuyện với nhân viên DBPlus, chỉ cung cấp thông tin và giá từ dữ liệu hoặc thị trường, chỉ cần nói rõ đây là thông tin tham khảo là được.
"""
    else:
        prompt += """
CẢNH BÁO: KHÔNG CÓ DỮ LIỆU SẢN PHẨM ĐƯỢC CUNG CẤP!
- Thông báo với người dùng rằng bạn hiện không có thông tin về sản phẩm và giá
- Đề nghị họ liên hệ số điện thoại 0903 359 868 để được tư vấn trực tiếp
"""

    
    # Lưu lại nội dung prompt đầy đủ để debug
    # log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    # os.makedirs(log_dir, exist_ok=True)
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # prompt_log_file = os.path.join(log_dir, f"gemini_prompt_{timestamp}.txt")
    
    # try:
    #     with open(prompt_log_file, "w", encoding="utf-8") as f:
    #         f.write("====== GEMINI SYSTEM PROMPT ======\n\n")
    #         f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    #         f.write(f"RAG content tồn tại: {'Có' if rag_content else 'Không'}\n")
    #         if rag_content:
    #             f.write(f"Độ dài RAG content: {len(rag_content)} ký tự\n\n")
    #         f.write(f"Prompt ({len(prompt)} ký tự):\n")
    #         f.write(prompt)
    #     logger.info(f"Đã lưu system prompt đầy đủ vào: {prompt_log_file}")
    # except Exception as e:
    #     logger.error(f"Lỗi khi lưu system prompt: {str(e)}")
    
    logger.info(f"Đã tạo system prompt đầy đủ ({len(prompt)} ký tự)")
    return prompt

async def query_gemini_llm_streaming(
    prompt_text: str,
    gemini_system_prompt: Optional[str] = None,
    formatted_history: Optional[List[Dict[str, Any]]] = None
) -> AsyncGenerator[str, None]:
    """
    Gửi truy vấn đến Gemini và trả về kết quả dạng streaming
    
    Args:
        prompt_text: Nội dung câu hỏi
        gemini_system_prompt: System prompt cho Gemini (tùy chọn)
        formatted_history: Lịch sử đã định dạng cho Gemini (tùy chọn)
        
    Yields:
        str: Từng phần phản hồi từ Gemini hoặc thông báo lỗi
    """
    global gemini_model_instance
    
    if not gemini_model_instance:
        if not configure_gemini_model():
            yield "Error: Failed to configure Gemini"
            return

    try:
        # Create the full prompt with system prompt if provided
        full_prompt = f"{gemini_system_prompt}\n\n{prompt_text}" if gemini_system_prompt else prompt_text

        # Create generation config
        generation_config = GenerationConfig(
            temperature=0.7,
            max_output_tokens=2048
        )

        # Type check to ensure gemini_model_instance is not None
        if gemini_model_instance is None:
            yield "Error: Gemini model not initialized"
            return

        # Use the streaming method
        response = await gemini_model_instance.generate_content_async(
            contents=full_prompt,
            generation_config=generation_config,
            stream=True
        )

        async for chunk in response:
            if chunk.text:
                yield chunk.text

    except Exception as e:
        logging.error(f"Error in query_gemini_llm_streaming: {str(e)}")
        yield f"Error: {str(e)}"

async def gemini_rag_query(
    query_text: str, 
    rag_content: Optional[str] = None,
    formatted_history: Optional[List[Dict[str, Any]]] = None
) -> AsyncGenerator[str, None]:
    """
    Thực hiện truy vấn Gemini với RAG
    
    Args:
        query_text: Câu hỏi của người dùng
        rag_content: Nội dung RAG đã truy xuất (tùy chọn)
        formatted_history: Lịch sử hội thoại đã định dạng (tùy chọn)
        
    Yields:
        str: Từng phần phản hồi từ Gemini
    """
    logger.info("====== BẮT ĐẦU GEMINI RAG QUERY ======")
    logger.info(f"Query: '{query_text}'")
    logger.info(f"RAG content truyền vào: {'Có, ' + str(len(rag_content)) + ' ký tự' if rag_content else 'Không'}")
    logger.info(f"History: {'Có, ' + str(len(formatted_history)) + ' mục' if formatted_history and len(formatted_history) > 0 else 'Không'}")
    
    if rag_content is None:
        logger.info("Chưa có RAG content, sẽ truy xuất từ nội dung câu hỏi")
        ensure_data_directory()
        rag_content = retrieve_relevant_content(query_text)
        if not rag_content:
            rag_content = "Không có dữ liệu sản phẩm"
    
    if rag_content == "Không có dữ liệu sản phẩm" or not rag_content or len(rag_content) < 100:
        warning_msg = json.dumps({
            "warning": "Không tìm thấy dữ liệu RAG. Phản hồi có thể không đầy đủ hoặc thiếu thông tin chính xác."
        })
        yield warning_msg
        
        logger.warning(f"Không tìm thấy dữ liệu RAG đầy đủ! Content: {rag_content}")
        
        logger.info("Thử tạo và đọc lại dữ liệu mẫu để sử dụng cho RAG")
        create_sample_markdown_data()
        new_rag_content = load_markdown_data()
        if new_rag_content:
            rag_content = new_rag_content
            logger.info(f"Độ dài RAG content sau tạo lại: {len(rag_content)} ký tự")
    
    gemini_system_prompt = create_gemini_system_prompt(rag_content=rag_content)
    
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
                        # log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
                        # os.makedirs(log_dir, exist_ok=True)
                        # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        # debug_log_file = os.path.join(log_dir, f"markdown_content_{timestamp}.txt")
                        
                        # try:
                        #     with open(debug_log_file, "w", encoding="utf-8") as f:
                        #         f.write("=== MARKDOWN RAG CONTENT ===\n\n")
                        #         f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                        #         f.write(f"File path: {GEMINI_DATA_PATH}\n")
                        #         f.write(f"Content length: {len(content)} ký tự\n\n")
                        #         f.write(content)
                        #     logger.info(f"Đã lưu nội dung file markdown vào: {debug_log_file}")
                        # except Exception as e:
                        #     logger.error(f"Lỗi khi lưu debug file: {str(e)}")
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