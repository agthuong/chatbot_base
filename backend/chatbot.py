
import streamlit as st
import os
import re
import json
import logging
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from department_info_tool import DepartmentInfoTool
import time
import inspect

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("chatbot_rag.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("chatbot_rag")

# Khởi tạo thư mục data/logs nếu chưa tồn tại
os.makedirs('data/logs', exist_ok=True)

# Cấu hình Qwen LLM
LLM_CFG = {
    'model': 'qwen3-8b',
    'model_server': 'http://192.168.0.43:1234/v1'
}

def create_system_prompt(sub_phase=None, department=None):
    """
    Tạo system prompt thống nhất cho tất cả các truy vấn
    
    Args:
        sub_phase: Giai đoạn con liên quan (nếu có)
        department: Phòng ban liên quan (nếu có)
    
    Returns:
        str: System prompt chuẩn cho LLM
    """
    base_prompt = """
Bạn là trợ lý AI chuyên về công việc của các phòng ban trong công ty. 
Nhiệm vụ: phân tích thông tin về các task trong phòng ban và cung cấp thông tin hữu ích.

DỰ ÁN ĐƯỢC CHIA THÀNH CÁC GIAI ĐOẠN CHÍNH (theo thứ tự cố định):
1. MKT-SALES: Giai đoạn Marketing và Bán hàng
2. PROPOSAL: Giai đoạn đề xuất
3. CONSTRUCTION: Giai đoạn thi công
4. DEFECT-HANDOVER: Giai đoạn xử lý lỗi và bàn giao
5. AFTERSALE-MAINTENANCE: Giai đoạn sau bán hàng và bảo trì

Giai đoạn MKT-SALES bao gồm các sub-phases theo thứ tự:
1. Branding MKT: Marketing thương hiệu
2. Sales Sourcing: Tìm kiếm nguồn bán hàng
3. Data Qualification: Phân loại dữ liệu
4. Approach: Tiếp cận (bước chuyển tiếp)

Các giai đoạn khác có sub-phases tương ứng, với bước chuyển tiếp cuối cùng là Done.

QUY TẮC NGHIÊM NGẶT:
1. KHÔNG TỰ TẠO mối liên hệ giữa giai đoạn và phòng ban
2. KHÔNG LIỆT KÊ phòng ban nào tham gia vào giai đoạn nào
3. CHỈ TẬP TRUNG vào thông tin của một phòng ban cụ thể
4. KHÔNG ĐỀ CẬP đến mối quan hệ giữa các phòng ban
5. Khi hỏi về mối liên hệ giữa giai đoạn và phòng ban, CHỈ trả lời: "Vui lòng hỏi về một phòng ban cụ thể để biết thêm chi tiết"

KHI TRẢ LỜI:
1. Ngắn gọn, súc tích nhưng đầy đủ thông tin
2. Nếu không tìm thấy thông tin, thông báo và gợi ý các phòng ban có sẵn
3. Liệt kê task theo thứ tự giai đoạn và giai đoạn con
4. Hiển thị đúng thứ tự các sub-phase trong MKT-SALES
5. Với câu hỏi chào hỏi/không liên quan, trả lời hài hước, cợt nhả, spam icon

Trả lời bằng tiếng Việt, ngay cả khi người dùng hỏi bằng tiếng Anh.
"""
    return base_prompt

def create_llm_prompt(query, dept_info, session_id=None, basic_response=None):
    """
    Tạo LLM prompt thống nhất cho tất cả các truy vấn
    
    Args:
        query: Câu hỏi của người dùng
        dept_info: Thông tin về phòng ban
        session_id: ID của phiên hiện tại (nếu có)
        basic_response: Phản hồi cơ bản (nếu có)
        
    Returns:
        str: LLM prompt chuẩn
    """
    # Log các thông tin quan trọng để debug
    logger.info(f"Tạo prompt LLM cho phòng ban: {dept_info['department']}, session_id: {session_id}")
    logger.info(f"Số task: {dept_info['task_count']}")
    
    # Lấy lịch sử hội thoại từ session_id
    conversation_history = ""
    history = [] # Khởi tạo history để tránh lỗi nếu không lấy được
    if session_id:
        logger.info(f"Lấy lịch sử hội thoại từ phiên {session_id}")
        try:
            # Import hàm get_session_history từ websocket_server nếu hàm này tồn tại ở đó
            try:
                from server import get_session_history
                history = get_session_history(session_id)
                logger.info(f"[create_llm_prompt] Đã lấy được {len(history)} bản ghi lịch sử từ websocket_server.get_session_history cho session {session_id}.")
                if history:
                    logger.debug(f"[create_llm_prompt] Lịch sử mẫu: {history[:2]}")
            except ImportError:
                logger.warning("[create_llm_prompt] Không thể import get_session_history từ websocket_server. Thử get_chat_history (cục bộ).")
                # Sử dụng get_chat_history trong chatbot.py nếu có (Lưu ý: hàm này có thể không theo session_id cụ thể)
                history = get_chat_history() # Đây là hàm của Streamlit, có thể không phù hợp cho backend
                logger.info(f"[create_llm_prompt] Đã lấy được {len(history)} bản ghi lịch sử từ get_chat_history (cục bộ).")
                if history:
                    logger.debug(f"[create_llm_prompt] Lịch sử mẫu (cục bộ): {history[:2]}")
            except Exception as e_hist:
                 logger.error(f"[create_llm_prompt] Lỗi khi lấy lịch sử hội thoại cho session {session_id} bằng get_session_history: {str(e_hist)}")

            # Lấy 5 cuộc hội thoại gần đây nhất (thay vì 2-3)
            recent_history = history[-5:] if len(history) > 5 else history
            
            if recent_history:
                conversation_history = "Lịch sử tin nhắn:\\n"
                # Duyệt ngược để hiển thị tin nhắn gần nhất cuối cùng
                for idx, item in enumerate(recent_history):
                    # Thêm câu hỏi của người dùng
                    conversation_history += f"Người dùng: {item['query']}\\n"
                    
                    # Xóa phần thêm thông tin phòng ban
                    # if item.get('department'):
                    #     conversation_history += f"(Phòng ban: {item['department']})\\n"
                    
                    # KHÔNG thêm phản hồi của trợ lý, để đồng bộ với xử lý trong websocket_server.py
                
                # Thêm thông tin tổng kết về phòng ban đã nhắc đến gần đây
                mentioned_departments = [item.get('department') for item in recent_history if item.get('department')]
                if mentioned_departments:
                    last_department = mentioned_departments[-1]
                    conversation_history += f"\\n**LƯU Ý**: Phòng ban được nhắc đến gần đây nhất là: **{last_department}**\\n\\n"
                
                # Log lịch sử tin nhắn được thêm vào prompt
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                history_log_path = f"data/logs/chatbot_history_prompt_{timestamp}.txt"
                os.makedirs(os.path.dirname(history_log_path), exist_ok=True)
                
                with open(history_log_path, 'w', encoding='utf-8') as f:
                    f.write(f"=== LỊCH SỬ TIN NHẮN CHO SESSION {session_id} ===\n\n")
                    f.write(f"{conversation_history.replace('\\n', '\n')}\n\n")
                    f.write(f"=== CÂU HỎI HIỆN TẠI ===\n\n")
                    f.write(f"{query}\n\n")
                    f.write(f"=== PHÒNG BAN ===\n\n")
                    f.write(f"{dept_info['department']}\n\n")
                
                logger.info(f"[create_llm_prompt] Đã lưu lịch sử tin nhắn vào file: {history_log_path}")
                logger.info(f"[create_llm_prompt] Đã thêm {len(recent_history)} hội thoại vào prompt cho session {session_id}")
        except Exception as e:
            logger.error(f"[create_llm_prompt] Lỗi tổng quát khi xử lý lịch sử hội thoại cho session {session_id}: {str(e)}")
    else:
        logger.info("[create_llm_prompt] Không có session_id, không lấy lịch sử hội thoại.")
    
    # Hàm lọc thông tin quan trọng từ full_details
    def extract_important_details(full_details):
        if not full_details:
            return ""
            
        important_info = ""
        
        # Tìm và trích xuất các phần quan trọng
        import re
        
        # Tìm phần Đầu ra
        output_match = re.search(r'#{5}\s*Đầu ra:(.*?)(?=#{5}|$)', full_details, re.DOTALL)
        if output_match and output_match.group(1).strip():
            important_info += "Đầu ra: " + output_match.group(1).strip() + "\n\n"
            
        # Tìm phần Mô tả
        desc_match = re.search(r'#{5}\s*Mô tả:(.*?)(?=#{5}|$)', full_details, re.DOTALL)
        if desc_match and desc_match.group(1).strip():
            important_info += "Mô tả: " + desc_match.group(1).strip() + "\n\n"
            
        # Tìm phần Mục tiêu
        goal_match = re.search(r'#{5}\s*Mục tiêu:(.*?)(?=#{5}|$)', full_details, re.DOTALL)
        if goal_match and goal_match.group(1).strip():
            important_info += "Mục tiêu: " + goal_match.group(1).strip()
            
        return important_info.strip()
    
    # Tạo phần dữ liệu về task - chỉ giữ những thông tin cần thiết
    tasks_json = json.dumps([{
        'id': task['id'],
        'name': task['name'],
        'phase': task['phase'],
        'sub_phase': task['sub_phase'],
        # Loại bỏ description vì đã có trong phần Mô tả của full_details
        'full_details': extract_important_details(task.get('full_details', ''))
    } for task in dept_info['task_list']], ensure_ascii=False, indent=2)
    
    # Giới hạn kích thước JSON để tránh lỗi 400 Bad Request
    if len(tasks_json) > 100000:  # Giới hạn ~100KB
        logger.warning(f"JSON quá lớn ({len(tasks_json)} bytes), giới hạn số lượng tasks")
        # Chọn tối đa 15 tasks
        truncated_tasks = dept_info['task_list'][:15]
        tasks_json = json.dumps([{
            'id': task['id'],
            'name': task['name'],
            'phase': task['phase'],
            'sub_phase': task['sub_phase'],
            'full_details': extract_important_details(task.get('full_details', ''))
        } for task in truncated_tasks], ensure_ascii=False, indent=2)
        logger.info(f"Đã giới hạn xuống {len(tasks_json)} bytes với {len(truncated_tasks)} tasks")
    

    return f"""
    Vai trò: Trợ lý thông minh cung cấp thông tin về phòng ban và công việc trong công ty.

    {conversation_history}
    Câu hỏi người dùng: "{query}"

    THÔNG TIN PHÒNG BAN {dept_info['department']}:
    - Số lượng tasks: {dept_info['task_count']}
    - Các giai đoạn: {', '.join(dept_info['phases'])}

    HƯỚNG DẪN QUAN TRỌNG:
    1. TRẢ LỜI TRỰC TIẾP câu hỏi trước tiên
    2. Sử dụng thông tin về các task làm dữ liệu hỗ trợ
    3. Tránh chỉ liệt kê công việc mà không trả lời câu hỏi
    4. LỌC THÔNG TIN theo câu hỏi:
    - Nếu hỏi về giai đoạn cụ thể, CHỈ trả lời về tasks thuộc giai đoạn đó
    - Nếu hỏi về giai đoạn con cụ thể, CHỈ trả lời về tasks thuộc giai đoạn con đó
    - Nếu hỏi về phòng ban nói chung, cung cấp tổng quan theo giai đoạn
    5. XỬ LÝ NHIỀU PHÒNG BAN/GIAI ĐOẠN:
    - GIẢI THÍCH RÕ RÀNG tại sao bạn liệt kê thông tin (nếu câu hỏi đề cập đến nhiều phần)
    - Phân nhóm câu trả lời theo giai đoạn để dễ so sánh
    6. LƯU Ý ĐẶC BIỆT:
    - Phòng ban "Thi công" khác với giai đoạn "CONSTRUCTION"
    - Với câu hỏi không liên quan đến công việc, trả lời bình thường
    - Trả lời bằng Markdown, rõ ràng, súc tích, Tiếng Việt
    - Nếu mục tiêu có "nếu bước không đạt được mục tiêu, quay về task X", PHẢI thông báo rõ ràng

    Thông tin về các task:
    {tasks_json}
    """

# Prompt hệ thống cho LLM
SYSTEM_PROMPT = create_system_prompt()

def query_llm(prompt: str, system_prompt: str, max_tokens=16000, stream=True) -> str:
    """
    Gửi truy vấn đến mô hình LLM
    
    Args:
        prompt: Câu hỏi của người dùng
        system_prompt: Prompt hệ thống
        max_tokens: Số tokens tối đa trong phản hồi
        stream: Có sử dụng chế độ streaming hay không
        
    Returns:
        Phản hồi của LLM
    """
    try:
        url = f"{LLM_CFG['model_server']}/chat/completions"
        
        # Kiểm tra kích thước prompt
        prompt_size = len(prompt)
        system_size = len(system_prompt)
        total_size = prompt_size + system_size
        
        logger.info(f"Kích thước prompt: {prompt_size} ký tự")
        logger.info(f"Kích thước system prompt: {system_size} ký tự") 
        logger.info(f"Tổng kích thước: {total_size} ký tự")
        
        # Log full prompt trước khi gửi đến LLM
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        full_prompt_log_path = f"data/logs/llm_full_prompt_{timestamp}.txt"
        os.makedirs(os.path.dirname(full_prompt_log_path), exist_ok=True)
        
        with open(full_prompt_log_path, 'w', encoding='utf-8') as f:
            f.write("=== SYSTEM PROMPT ===\n\n")
            f.write(f"{system_prompt}\n\n")
            f.write("=== USER PROMPT ===\n\n")
            f.write(f"{prompt}\n\n")
        
        logger.info(f"Đã lưu full prompt vào file: {full_prompt_log_path}")
        
        # Log full content của prompt để debug (phần đầu)
        logger.info(f"System prompt: {system_prompt[:200]}...")
        logger.info(f"User prompt: {prompt[:200]}...")
        
        # Giảm max_tokens nếu prompt quá lớn
        if total_size > 50000:
            max_tokens = min(max_tokens, 4000)
            logger.warning(f"Prompt quá lớn ({total_size} ký tự), giảm max_tokens xuống {max_tokens}")
            
        payload = {
            "model": LLM_CFG['model'],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": False  # Sử dụng giá trị tham số stream
        }
        
        logger.info(f"Gửi truy vấn đến LLM API tại {url} với stream={stream}")
        response = requests.post(url, json=payload)
        
        # Log thông tin response status
        logger.info(f"Mã phản hồi từ API: {response.status_code}")
        
        # Nếu gặp lỗi 400, thử lại với prompt ngắn hơn
        if response.status_code == 400:
            logger.error("Lỗi 400 Bad Request, thử lại với prompt ngắn hơn")
            
            # Hiển thị thông báo cho người dùng về việc giảm kích thước prompt
            st.warning("⚠️ Câu hỏi quá dài và phức tạp. Đang giảm kích thước câu hỏi để xử lý... Có thể thiếu dữ liệu ở những giai đoạn cuối")
            
            # Cắt ngắn prompt để giảm kích thước
            shortened_prompt = prompt[:int(len(prompt) * 0.6)]  # Giữ 60% prompt ban đầu
            
            logger.info(f"Thử lại với prompt ngắn hơn: {len(shortened_prompt)} ký tự")
            
            payload["messages"][1]["content"] = shortened_prompt
            response = requests.post(url, json=payload)
            response.raise_for_status()
        else:
            response.raise_for_status()
        
        result = response.json()
        # Ghi log phản hồi để debug
        response_content = result['choices'][0]['message']['content']
        logger.info(f"Phản hồi gốc từ LLM API (200 ký tự đầu): {response_content[:200]}")
        
        # Ghi log đầy đủ vào file
        log_file_path = f"data/logs/llm_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        with open(log_file_path, 'w', encoding='utf-8') as f:
            f.write(response_content)
        logger.info(f"Đã lưu phản hồi đầy đủ vào file: {log_file_path}")
        
        return response_content
    except Exception as e:
        logger.error(f"Lỗi khi gọi LLM: {str(e)}")
        return f"Đã xảy ra lỗi khi xử lý truy vấn: {str(e)}"

def handle_general_query(query: str, use_llm=True, session_id: Optional[str] = None) -> str:
    """
    Xử lý các câu hỏi chung về quy trình, giai đoạn, phòng ban
    
    Args:
        query: Câu hỏi của người dùng
        use_llm: Có sử dụng LLM để xử lý phản hồi hay không
        session_id: ID phiên hiện tại (nếu có)
        
    Returns:
        Phản hồi cho câu hỏi chung
    """
    logger.info(f"Xử lý câu hỏi chung cho session_id: {session_id}")
    
    # Thông tin giai đoạn và giai đoạn con
    phases_info = {
        "MKT-SALES": {
            "description": "Giai đoạn Marketing và Bán hàng",
            "sub_phases": ["Branding MKT", "Sales Sourcing", "Data Qualification", "Approach (Bước chuyển tiếp)"],
            "departments": ["Marketing", "Kinh doanh"]
        },
        "PROPOSAL": {
            "description": "Giai đoạn đề xuất",
            "sub_phases": ["Proposal"],
            "departments": ["Kinh doanh", "Dự toán", "Thiết kế", "Team dự án"]
        },
        "CONSTRUCTION": {
            "description": "Giai đoạn thi công",
            "sub_phases": ["Construction"],
            "departments": ["Thi công", "Thiết kế", "Mua hàng", "Đặt hàng", "Team dự án"]
        },
        "DEFECT-HANDOVER": {
            "description": "Giai đoạn xử lý lỗi và bàn giao",
            "sub_phases": ["Defect & Handover", "After Sales & Maintenance (Bước chuyển tiếp)"],
            "departments": ["Thi công", "Kinh doanh", "Kế toán", "Khách hàng"]
        },
        "AFTERSALE-MAINTENANCE": {
            "description": "Giai đoạn sau bán hàng và bảo trì",
            "sub_phases": ["After Sales & Maintenance"],
            "departments": ["Kinh doanh", "Thi công"]
        }
    }
    
    # Thông tin phòng ban
    department_tool = DepartmentInfoTool()
    departments = department_tool.get_departments()
    
    # Tạo thông tin tổng hợp cho câu hỏi chung
    basic_response = f"""### Thông tin tổng quan về quy trình và giai đoạn

#### Giai đoạn chính trong quy trình:
1. **MKT-SALES**: {phases_info['MKT-SALES']['description']}
2. **PROPOSAL**: {phases_info['PROPOSAL']['description']}
3. **CONSTRUCTION**: {phases_info['CONSTRUCTION']['description']}
4. **DEFECT-HANDOVER**: {phases_info['DEFECT-HANDOVER']['description']}
5. **AFTERSALE-MAINTENANCE**: {phases_info['AFTERSALE-MAINTENANCE']['description']}

#### Giai đoạn con:
- **MKT-SALES**: {", ".join(phases_info['MKT-SALES']['sub_phases'])}
- **PROPOSAL**: {", ".join(phases_info['PROPOSAL']['sub_phases'])}
- **CONSTRUCTION**: {", ".join(phases_info['CONSTRUCTION']['sub_phases'])}
- **DEFECT-HANDOVER**: {", ".join(phases_info['DEFECT-HANDOVER']['sub_phases'])}
- **AFTERSALE-MAINTENANCE**: {", ".join(phases_info['AFTERSALE-MAINTENANCE']['sub_phases'])}

#### Các phòng ban tham gia theo giai đoạn:
- **MKT-SALES**: {", ".join(phases_info['MKT-SALES']['departments'])}
- **PROPOSAL**: {", ".join(phases_info['PROPOSAL']['departments'])}
- **CONSTRUCTION**: {", ".join(phases_info['CONSTRUCTION']['departments'])}
- **DEFECT-HANDOVER**: {", ".join(phases_info['DEFECT-HANDOVER']['departments'])}
- **AFTERSALE-MAINTENANCE**: {", ".join(phases_info['AFTERSALE-MAINTENANCE']['departments'])}

#### Danh sách phòng ban:
Công ty có {len(departments)} phòng ban: {", ".join(departments)}

Để biết thêm chi tiết về nhiệm vụ và công việc cụ thể của một phòng ban, vui lòng hỏi riêng về phòng ban đó. 
Ví dụ: "Phòng Kinh doanh làm gì trong giai đoạn PROPOSAL?" hoặc "Phòng Thi công tham gia những bước nào?"
"""
    
    # Nếu không sử dụng LLM, trả về basic response
    if not use_llm:
        return basic_response
    # Nếu sử dụng LLM, tạo prompt và gửi cho LLM
    system_prompt = f"""
Bạn là trợ lý AI chuyên về quy trình và giai đoạn trong công ty.

CÁC PHÒNG BAN THAM GIA THEO GIAI ĐOẠN:
- MKT-SALES: {", ".join(phases_info['MKT-SALES']['departments'])}
- PROPOSAL: {", ".join(phases_info['PROPOSAL']['departments'])}
- CONSTRUCTION: {", ".join(phases_info['CONSTRUCTION']['departments'])}
- DEFECT-HANDOVER: {", ".join(phases_info['DEFECT-HANDOVER']['departments'])}
- AFTERSALE-MAINTENANCE: {", ".join(phases_info['AFTERSALE-MAINTENANCE']['departments'])}

DANH SÁCH PHÒNG BAN:
{chr(10).join([f"- {dept}" for dept in departments])}

QUY TẮC NGHIÊM NGẶT:
1. KHÔNG TỰ TẠO mối liên hệ giữa các phòng ban
2. CHỈ TẬP TRUNG mô tả giai đoạn và nêu phòng ban nào phụ trách
3. LUÔN LUÔN KẾT THÚC câu trả lời bằng gợi ý: "Để biết chi tiết công việc cụ thể, vui lòng hỏi về một phòng ban cụ thể, ví dụ: Phòng X làm gì trong giai đoạn Y?"

KHI TRẢ LỜI:
1. Ngắn gọn, chỉ trả lời về cấu trúc giai đoạn và quy trình
2. Không giải thích phòng ban nào làm gì trong giai đoạn nào
3. LUÔN gợi ý người dùng hỏi về một phòng ban cụ thể thay vì hỏi chung
4. Trả lời bằng tiếng Việt, dưới dạng Markdown
5. Nếu công hỏi không liên quan dến quy trình, phong ban, công viêc, hãy trả lời một cách vui vẻ, cợt nhả, spam icon và không nhắc tới công việc.
"""
    
    user_prompt = f"""
Câu hỏi: "{query}"

Đây là câu hỏi chung về quy trình hoặc giai đoạn làm việc.

Thông tin cơ bản:
{basic_response}

KHÔNG TỰ TẠO MỐI LIÊN HỆ GIỮA GIAI ĐOẠN VÀ PHÒNG BAN.
Không giải thích phòng ban nào làm việc trong giai đoạn nào.
Chỉ trả lời về cấu trúc giai đoạn và quy trình.
"""
    
    try:
        logger.info(f"Gọi LLM để trả lời câu hỏi chung cho session_id: {session_id}")
        
        # Lưu prompt vào file txt để debug
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prompt_file_path = f"data/logs/prompt_general_{timestamp}.txt"
        with open(prompt_file_path, 'w', encoding='utf-8') as f:
            f.write(f"=== SYSTEM PROMPT ===\n\n{system_prompt}\n\n=== USER PROMPT ===\n\n{user_prompt}")
        logger.info(f"Đã lưu prompt vào file: {prompt_file_path}")
        
        # Gọi LLM để xử lý
        final_response = query_llm(user_prompt, system_prompt)
        
        # Lưu log truy vấn
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "response": final_response,
            "session_id": session_id # Thêm session_id vào log
        }
        log_file = f"data/logs/query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
            
        # Xử lý phản hồi để loại bỏ các header không cần thiết
        cleaned_response = final_response
        if "# Trả lời câu hỏi:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời câu hỏi:", "")
        
        # Hiển thị phản hồi đã xử lý
        st.write(cleaned_response)
        
        # Trả về phản hồi đã xử lý cho việc lưu vào lịch sử
        return cleaned_response
            
    except Exception as e:
        logger.error(f"Lỗi khi gọi LLM để trả lời câu hỏi chung cho session_id: {session_id}: {str(e)}")
        return basic_response

def smart_rag_query(query: str, sub_phase: str = None, department: str = None, session_id: str = None) -> str:
    """
    Truy vấn RAG thông minh (với LLM filtering)
    
    Args:
        query: Câu hỏi của người dùng
        sub_phase: Giai đoạn con liên quan
        department: Phòng ban liên quan
        session_id: ID phiên hiện tại
        
    Returns:
        Phản hồi của LLM
    """
    
    logger.info(f"Truy vấn Smart RAG - Giai đoạn: {sub_phase}, Phòng ban: {department}, Session: {session_id}")
    llm_info = st.session_state.get('llm_info', {})
    llm_url = llm_info.get('url', '')
    llm_model = llm_info.get('model', '')
    
    # Khởi tạo công cụ thông tin phòng ban
    department_tool = DepartmentInfoTool()
    
    start_time = time.time()
    
    # Tạo prompt hệ thống
    system_prompt = create_system_prompt(sub_phase, department)
    
    # Lấy thông tin phòng ban - lưu ý: chỉ truyền tham số department
    if department:
        dept_info = department_tool.get_department_info(department)
    else:
        dept_info = {"department": "Không xác định", "task_count": 0, "phases": [], "task_list": []}
    
    # Tạo prompt cho LLM - truyền thêm session_id
    prompt = create_llm_prompt(query, dept_info, session_id)
    
    try:
        logger.info(f"Gọi LLM: {llm_model} tại {llm_url}")
        
        # Lưu prompt để debug
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs("data/logs", exist_ok=True)
        prompt_file_path = f"data/logs/prompt_{timestamp}.txt"
        with open(prompt_file_path, 'w', encoding='utf-8') as f:
            f.write(f"System Prompt:\n{system_prompt}\n\nUser Prompt:\n{prompt}")
        logger.info(f"Đã lưu prompt vào file: {prompt_file_path}")
        
        # Gọi LLM
        final_response = query_llm(prompt, system_prompt)
        
        # Lưu response để debug
        os.makedirs("data/logs", exist_ok=True)
        response_file_path = f"data/logs/response_{timestamp}.txt"
        with open(response_file_path, 'w', encoding='utf-8') as f:
            f.write(final_response)
        logger.info(f"Đã lưu response vào file: {response_file_path}")
        
        # Tính thời gian truy vấn
        query_time = time.time() - start_time
        logger.info(f"Thời gian truy vấn LLM: {query_time:.2f} giây")
        
        # Lưu thông tin truy vấn
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "sub_phase": sub_phase,
            "department": department,
            "session_id": session_id,
            "response": final_response,
            "query_time": query_time
        }
        
        log_file = f"data/logs/query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
            
        # Xử lý phản hồi để loại bỏ các header không cần thiết
        cleaned_response = final_response
        if "# Trả lời câu hỏi:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời câu hỏi:", "")
        if "# Trả lời:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời:", "")
            
        # Hiển thị phản hồi đã xử lý
        st.write(cleaned_response)
        
        # Nếu phòng ban được chỉ định, hiển thị thông tin liên quan
        if department:
            related_info = department_tool.get_department_info(department)
            if related_info:
                with st.expander("📋 Thông tin liên quan"):
                    st.write(related_info)
        
        return cleaned_response
            
    except Exception as e:
        error_msg = f"Lỗi khi gọi LLM: {str(e)}"
        logger.error(error_msg)
        return f"Đã xảy ra lỗi khi xử lý câu hỏi: {str(e)}"

def traditional_rag_query(query: str, sub_phase: str = None, department: str = None, session_id: Optional[str] = None) -> str:
    """
    Truy vấn RAG truyền thống (search & retrieve)
    
    Args:
        query: Câu hỏi của người dùng
        sub_phase: Giai đoạn con liên quan
        department: Phòng ban liên quan
        session_id: ID phiên hiện tại (nếu có)
        
    Returns:
        Phản hồi của LLM
    """
    logger.info(f"Truy vấn Traditional RAG - Giai đoạn: {sub_phase}, Phòng ban: {department}, session_id: {session_id}")
    
    # Khởi tạo công cụ thông tin phòng ban
    department_tool = DepartmentInfoTool()
    
    # Tạo prompt hệ thống
    system_prompt = create_system_prompt(sub_phase, department)
    
    # Trích xuất thông tin từ công cụ - Lưu ý: chỉ truyền tham số department
    if department:
        department_info = department_tool.get_department_info(department)
    else:
        department_info = "Không có thông tin phòng ban cụ thể."
    
    # Tạo prompt cho LLM
    prompt = f"""
Câu hỏi: "{query}"

Đây là thông tin liên quan đến câu hỏi:

{department_info}

Dựa vào thông tin trên, hãy trả lời câu hỏi một cách chính xác và đầy đủ.
"""
    
    try:
        logger.info(f"Gọi LLM với traditional RAG")
        
        # Lưu prompt để debug
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs("data/logs", exist_ok=True)
        prompt_file_path = f"data/logs/trad_prompt_{timestamp}.txt"
        with open(prompt_file_path, 'w', encoding='utf-8') as f:
            f.write(f"System Prompt:\n{system_prompt}\n\nUser Prompt:\n{prompt}")
        
        # Gọi LLM
        final_response = query_llm(prompt, system_prompt)
        
        # Lưu response để debug
        response_file_path = f"data/logs/trad_response_{timestamp}.txt"
        with open(response_file_path, 'w', encoding='utf-8') as f:
            f.write(final_response)
        
        # Lưu thông tin truy vấn
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "sub_phase": sub_phase,
            "department": department,
            "session_id": session_id,
            "response": final_response
        }
        
        log_file = f"data/logs/trad_query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
            
        # Xử lý phản hồi để loại bỏ các header không cần thiết
        cleaned_response = final_response
        if "# Trả lời câu hỏi:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời câu hỏi:", "")
        if "# Trả lời:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời:", "")
            
        # Hiển thị phản hồi đã xử lý
        st.write(cleaned_response)
        
        # Nếu phòng ban được chỉ định, hiển thị thông tin liên quan
        if department:
            with st.expander("📋 Thông tin liên quan"):
                st.write(department_info)
        
        return None
            
    except Exception as e:
        error_msg = f"Lỗi khi gọi LLM: {str(e)}"
        logger.error(error_msg)
        return f"Đã xảy ra lỗi khi xử lý câu hỏi: {str(e)}"

def show_department_not_found_message(department_tool, query, use_llm_analysis):
    """Hiển thị thông báo khi không tìm thấy phòng ban trong câu hỏi"""
    logger.warning(f"Không tìm thấy phòng ban trong câu hỏi: {query}")
    
    # Đưa ra thông báo phù hợp
    if use_llm_analysis:
        st.warning("❓ Không phát hiện được phòng ban trong câu hỏi của bạn. Vui lòng nhắc đến tên phòng ban cụ thể.")
        st.info("Các phòng ban hiện có: " + ", ".join(department_tool.get_departments()))
        st.markdown("Ví dụ câu hỏi: **Phòng ban Marketing có nhiệm vụ gì?**")
    else:
        st.warning("❓ Không phát hiện được phòng ban trong câu hỏi của bạn.")
        st.info("Vui lòng chọn một phòng ban từ thanh bên trái hoặc nhắc đến tên phòng ban cụ thể trong câu hỏi của bạn.")
    
    # Nếu phòng ban đã được chọn từ nút, nhắc người dùng sử dụng
    if not use_llm_analysis and 'selected_department' in st.session_state:
        st.success(f"Phòng ban hiện tại đã chọn: {st.session_state.selected_department}")
        st.markdown("Nhập câu hỏi của bạn và hệ thống sẽ tự động truy vấn thông tin về phòng ban này.")


def format_response(dept_info: Dict[str, Any], query: str, target_sub_phase: Optional[str] = None) -> str:
    """
    Định dạng phản hồi từ thông tin phòng ban
    
    Args:
        dept_info: Thông tin phòng ban từ DepartmentInfoTool
        query: Câu hỏi ban đầu của người dùng
        target_sub_phase: Giai đoạn con cần lọc (nếu có)
        
    Returns:
        Phản hồi định dạng cho người dùng
    """
    if not dept_info.get('success', False):
        return f"❌ {dept_info.get('error', 'Đã xảy ra lỗi khi truy vấn thông tin phòng ban')}"
    
    # Chuẩn bị dữ liệu cho LLM
    department = dept_info['department']
    tasks = dept_info['task_list']
    phases = dept_info['phases']
    task_count = dept_info['task_count']
    
    # Lọc tasks theo sub-phase nếu có yêu cầu
    if target_sub_phase:
        tasks = [task for task in tasks if task['sub_phase'] == target_sub_phase]
        if not tasks:
            return f"### Thông tin về phòng ban {department}\n\nKhông tìm thấy công việc nào thuộc giai đoạn con '{target_sub_phase}' trong phòng ban này."
    
    # Phân tích truy vấn để xác định nội dung cần thiết
    query_lower = query.lower()
    is_asking_for_specific_phase = any(phase.lower() in query_lower for phase in phases)
    is_asking_for_specific_task = any(task['name'].lower() in query_lower for task in tasks)
    
    # Tạo phản hồi
    if target_sub_phase:
        response = f"### Các công việc thuộc giai đoạn con '{target_sub_phase}' của phòng ban {department}\n\n"
        
        # Hiển thị các task thuộc sub-phase đó
        for i, task in enumerate(tasks, 1):
            response += f"{i}. {task['id']} - {task['name']}\n"
            if task['description']:
                response += f"   Mô tả: {task['description']}\n"
        
        return response
    
    # Nếu không có yêu cầu về sub-phase cụ thể, hiển thị theo định dạng cũ
    response = f"### Thông tin về phòng ban {department}\n\n"
    
    if task_count == 0:
        return response + "Không có công việc nào được tìm thấy cho phòng ban này."
    
    # Thông tin cơ bản
    response += f"- Số lượng công việc: {task_count}\n"
    response += f"- Các giai đoạn tham gia: {', '.join(phases)}\n\n"
    
    # Nếu hỏi về giai đoạn cụ thể
    if is_asking_for_specific_phase:
        for phase in phases:
            if phase.lower() in query_lower:
                phase_tasks = [t for t in tasks if t['phase'] == phase]
                
                response += f"### Giai đoạn {phase} ({len(phase_tasks)} công việc)\n\n"
                
                # Sắp xếp theo sub-phase nếu là MKT-SALES
                if phase == "MKT-SALES" and 'task_overview' in dept_info and phase in dept_info['task_overview']:
                    response += "#### Công việc theo giai đoạn con:\n\n"
                    
                    for sub_phase in dept_info['task_overview'][phase].get('sub_phases', []):
                        sub_phase_tasks = [t for t in phase_tasks if t['sub_phase'] == sub_phase]
                        
                        if sub_phase_tasks:
                            response += f"**{sub_phase}** ({len(sub_phase_tasks)} công việc):\n\n"
                            for i, task in enumerate(sub_phase_tasks, 1):
                                response += f"{i}. {task['id']} - {task['name']}\n"
                            response += "\n"
                else:
                    # Hiển thị tất cả task trong phase đó
                    for i, task in enumerate(phase_tasks, 1):
                        response += f"{i}. {task['id']} - {task['name']}"
                        if task['sub_phase']:
                            response += f" ({task['sub_phase']})"
                        response += "\n"
                
                break
    # Nếu hỏi về task cụ thể
    elif is_asking_for_specific_task:
        for task in tasks:
            if task['name'].lower() in query_lower:
                response += f"### Chi tiết về công việc: {task['id']} - {task['name']}\n\n"
                response += f"- Giai đoạn: {task['phase']}\n"
                if task['sub_phase']:
                    response += f"- Giai đoạn con: {task['sub_phase']}\n"
                if task['description']:
                    response += f"- Mô tả: {task['description']}\n"
                if task['prerequisite']:
                    response += f"- Điều kiện tiên quyết: {task['prerequisite']}\n"
                if task['responsible']:
                    response += f"- Người phụ trách: {task['responsible']}\n"
                if task['executor']:
                    response += f"- Người thực hiện: {task['executor']}\n"
                
                # Thêm thông tin đầy đủ
                response += f"\n### Thông tin đầy đủ\n\n{task['full_details']}"
                break
    else:
        # Hiển thị tổng quan tất cả task theo giai đoạn
        response += "### Tổng quan công việc theo giai đoạn\n\n"
        
        for phase in phases:
            phase_tasks = [t for t in tasks if t['phase'] == phase]
            response += f"**{phase}** ({len(phase_tasks)} công việc):\n\n"
            
            # Giới hạn số lượng task hiển thị
            display_limit = min(5, len(phase_tasks))
            for i, task in enumerate(phase_tasks[:display_limit], 1):
                response += f"{i}. {task['id']} - {task['name']}"
                if task['sub_phase']:
                    response += f" ({task['sub_phase']})"
                response += "\n"
            
            if len(phase_tasks) > display_limit:
                response += f"... và {len(phase_tasks) - display_limit} công việc khác.\n"
            
            response += "\n"
    
    return response

# Thêm các hàm quản lý lịch sử hội thoại
def add_to_chat_history(query: str, response: str, department: Optional[str] = None):
    """
    Thêm câu hỏi và câu trả lời vào lịch sử hội thoại
    
    Args:
        query: Câu hỏi của người dùng
        response: Câu trả lời của chatbot
        department: Phòng ban liên quan (nếu có)
    """
    current_session = get_current_session()
    
    if not current_session:
        # Nếu chưa có phiên, tạo phiên mới
        create_new_session("Phiên mặc định")
        current_session = get_current_session()
    
    # Thêm vào lịch sử của phiên hiện tại
    st.session_state.all_sessions[current_session]["chat_history"].append({
        "query": query,
        "response": response,
        "department": department,
        "timestamp": datetime.now().isoformat()
    })
    
    logger.info(f"Đã thêm hội thoại mới vào lịch sử phiên {current_session}. Department: {department}, Query: {query[:50]}...")

def get_chat_history():
    """
    Lấy toàn bộ lịch sử hội thoại của phiên hiện tại
    
    Returns:
        List[Dict]: Danh sách các hội thoại
    """
    current_session = get_current_session()
    
    if not current_session or 'all_sessions' not in st.session_state:
        return []
    
    return st.session_state.all_sessions[current_session].get("chat_history", [])

def clear_chat_history():
    """
    Xóa toàn bộ lịch sử hội thoại của phiên hiện tại
    """
    current_session = get_current_session()
    
    if current_session and 'all_sessions' in st.session_state:
        st.session_state.all_sessions[current_session]["chat_history"] = []
        logger.info(f"Đã xóa toàn bộ lịch sử hội thoại của phiên {current_session}")

def export_chat_history():
    """
    Xuất lịch sử hội thoại sang định dạng JSON
    
    Returns:
        str: Lịch sử hội thoại dưới dạng chuỗi JSON
    """
    history = get_chat_history()
    if not history:
        return ""
    
    # Chuyển đổi datetime nếu cần
    for item in history:
        if isinstance(item["timestamp"], datetime):
            item["timestamp"] = item["timestamp"].isoformat()
    
    current_session = get_current_session()
    session_info = {}
    
    if current_session and 'all_sessions' in st.session_state:
        session_name = st.session_state.all_sessions[current_session]["name"]
        created_at = st.session_state.all_sessions[current_session]["created_at"]
        session_info = {
            "session_id": current_session,
            "session_name": session_name,
            "created_at": created_at
        }
    
    export_data = {
        "session_info": session_info,
        "chat_history": history
    }
    
    return json.dumps(export_data, ensure_ascii=False, indent=2)

# Các hàm quản lý lịch sử phòng ban
def add_to_department_history(query, detected_department=None):
    """
    Thêm câu hỏi và phòng ban được phát hiện vào lịch sử
    
    Args:
        query: Câu hỏi của người dùng
        detected_department: Phòng ban được phát hiện, None nếu không phát hiện được
    """
    if 'department_history' not in st.session_state:
        st.session_state.department_history = []
    
    # Chỉ lưu trữ khi có phòng ban được phát hiện
    if detected_department:
        # Thêm vào đầu danh sách
        st.session_state.department_history.insert(0, {
            "query": query,
            "department": detected_department,
            "timestamp": datetime.now().isoformat()
        })
        
        # Giữ tối đa 3 mục gần nhất
        if len(st.session_state.department_history) > 3:
            st.session_state.department_history = st.session_state.department_history[:3]
        
        logger.info(f"Cập nhật lịch sử phòng ban: {detected_department} cho câu hỏi: {query}")


def analyze_query_with_llm(query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Sử dụng LLM để phân tích câu hỏi của người dùng và trích xuất thông tin
    
    Args:
        query: Câu hỏi của người dùng
        session_id: ID phiên hiện tại (để lấy lịch sử hội thoại)
        
    Returns:
        Dict chứa:
        - department: Tên phòng ban (str hoặc None)
        - query_type: Loại câu hỏi ("department_specific" hoặc "general")
        - error: Boolean đánh dấu lỗi phát hiện nhiều phòng ban trong 1 câu hỏi
    """
    try:
        logger.info(f"Đang phân tích câu hỏi với LLM: {query}, session_id: {session_id}")
        import re  # Đảm bảo import re ở đầu hàm để có thể sử dụng trong toàn bộ hàm
        
        # Khởi tạo biến lưu ngữ cảnh từ lịch sử hội thoại
        context = ""
        last_department = None
        
        # Lấy lịch sử chat từ session_id (nếu có) hoặc từ get_chat_history()
        chat_history = []
        if session_id:
            try:
                # Thử lấy lịch sử từ session_id trong websocket_server
                try:
                    from server import get_session_history
                    chat_history = get_session_history(session_id)
                    logger.info(f"[analyze_query_with_llm] Đã lấy được {len(chat_history)} bản ghi lịch sử từ websocket_server cho session {session_id}")
                except ImportError:
                    logger.warning("[analyze_query_with_llm] Không thể import get_session_history từ websocket_server, sử dụng get_chat_history")
                    chat_history = get_chat_history()
                    logger.info(f"[analyze_query_with_llm] Lấy lịch sử từ get_chat_history: {len(chat_history)} bản ghi")
            except Exception as e:
                logger.error(f"[analyze_query_with_llm] Lỗi khi lấy lịch sử hội thoại: {str(e)}")
                chat_history = []
        else:
            # Lấy lịch sử chat ngắn gọn để cung cấp ngữ cảnh
            chat_history = get_chat_history()
            logger.info(f"[analyze_query_with_llm] Session_id không được cung cấp, lấy lịch sử mặc định: {len(chat_history)} bản ghi")
        
        # Tạo ngữ cảnh từ lịch sử hội thoại - lấy 5 tin nhắn gần nhất thay vì 2
        recent_chat_context = ""
        if chat_history and len(chat_history) > 0:
            # Lấy tối đa 5 cuộc hội thoại gần nhất
            recent_chats = chat_history[-min(5, len(chat_history)):]
            recent_chat_context = "Lịch sử tin nhắn:\n"
            
            # Duyệt qua các tin nhắn gần đây để tìm phòng ban gần nhất
            for idx, chat in enumerate(recent_chats):
                recent_chat_context += f"Người dùng: {chat['query']}\n"
                
                # Thêm phòng ban vào ngữ cảnh nếu có
                if chat.get('department'):
                    recent_chat_context += f"(Phòng ban: {chat['department']})\n"
                    
                    # Lưu phòng ban gần nhất cho phân tích
                    if last_department is None:
                        last_department = chat.get('department')
                        logger.info(f"[analyze_query_with_llm] Tìm thấy phòng ban gần nhất từ lịch sử: {last_department}")
                
                # KHÔNG thêm phản hồi của trợ lý, để đồng bộ với xử lý trong websocket_server.py
                
            recent_chat_context += "\n"
            logger.info(f"[analyze_query_with_llm] Đã tạo ngữ cảnh từ {len(recent_chats)} hội thoại gần nhất")
            
            # Thêm thông tin về phòng ban đã xác định được từ lịch sử
            if last_department:
                recent_chat_context += f"Phòng ban được nhắc đến gần đây nhất: {last_department}\n\n"
                
            # Log lịch sử tin nhắn được thêm vào prompt
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            history_log_path = f"data/logs/analyze_history_{timestamp}.txt"
            os.makedirs(os.path.dirname(history_log_path), exist_ok=True)
            
            with open(history_log_path, 'w', encoding='utf-8') as f:
                f.write(f"=== LỊCH SỬ TIN NHẮN CHO PHÂN TÍCH (SESSION {session_id}) ===\n\n")
                f.write(f"{recent_chat_context}\n\n")
                f.write(f"=== CÂU HỎI HIỆN TẠI ===\n\n")
                f.write(f"{query}\n\n")
            
            logger.info(f"[analyze_query_with_llm] Đã lưu lịch sử tin nhắn cho phân tích vào file: {history_log_path}")
        
        system_prompt = """
        Bạn là trợ lý AI phân tích câu hỏi để xác định:
        1. Phòng ban người dùng đang hỏi (department)
        2. Loại câu hỏi: phòng ban cụ thể hay chung (query_type)
        3. Nếu câu hỏi đề cập nhiều phòng ban (error)

        DANH SÁCH PHÒNG BAN:
        2D, Dự toán, Kinh doanh, Kế toán, Marketing, Mua hàng, Team dự án, Thi công, Thiết kế, Đặt hàng

        PHÂN LOẠI CÂU HỎI:
        - "department_specific": Câu hỏi về phòng ban cụ thể hoặc tiếp tục ngữ cảnh phòng ban trước
        - "general": Câu hỏi về quy trình chung, không liên quan phòng ban cụ thể

        QUY TẮC QUAN TRỌNG:
        1. Nếu phát hiện HAI/NHIỀU phòng ban cùng lúc: department=null, query_type=null, error=true
        2. "Marketing và Bán hàng" = giai đoạn "MKT-SALES", không phải hai phòng ban riêng biệt
        3. Thứ tự ưu tiên xác định phòng ban:
        - HÀNG ĐẦU: Phòng ban được đề cập trực tiếp trong câu hỏi hiện tại
        - THỨ HAI: Phòng ban từ ngữ cảnh trước nếu câu hỏi tiếp tục ngữ cảnh
        - THỨ BA: General chỉ khi hoàn toàn không liên quan đến phòng ban cụ thể
        4. Câu hỏi ngắn ("bước tiếp theo", "họ làm gì") PHẢI giữ department từ ngữ cảnh trước
        5. "Construction" = giai đoạn; "Thi công" = phòng ban
        6. Câu hỏi về DBhomes/DBplus (công ty) = general
        7. Từ "họ", "bộ phận này", "phòng ban đó" = tiếp tục dùng phòng ban đã nhắc trước đó

        VÍ DỤ PHÂN LOẠI:
        1. "Phòng abc có công việc gì?" → {"department": "abc", "query_type": "department_specific", "error": false}
        2. "Nhiệm vụ của phòng kế toán và marketing" → {"department": null, "query_type": null, "error": true}
        3. "Có bao nhiêu giai đoạn trong quy trình?" → {"department": null, "query_type": "general", "error": false}
        4. "Bước 2 là gì?" (sau khi hỏi về Kinh doanh) → {"department": "Kinh doanh", "query_type": "department_specific", "error": false}

        PHẢI TRẢ VỀ JSON: {"department": "tên/null", "query_type": "loại/null", "error": true/false}
        """
                
        # Tạo prompt cho LLM - nhấn mạnh việc chỉ trả về JSON
        prompt = f"""Lịch sử tin nhắn:
        {context}{recent_chat_context}
        Câu hỏi người dùng hiện tại: "{query}"

        Phân tích câu hỏi và trả về JSON có định dạng:
        {{"department": "tên phòng ban hoặc null", "query_type": "department_specific hoặc general hoặc null", "error": true hoặc false}}

        Nếu câu hỏi hiện tại là tiếp nối câu hỏi trước và không đề cập rõ phòng ban, hãy sử dụng phòng ban từ lịch sử hội thoại gần đây.

        QUAN TRỌNG NHẤT: NẾU Lịch sử tin nhắn không đề cập đến phòng ban nào, hoăc câu hỏi không liên quan đến quy trình, phòng ban thì bắt buộc phải là câu hỏi type general.
        """
        
        # Log lịch sử hội thoại và prompt được gửi
        logger.info(f"[analyze_query_with_llm] Sử dụng lịch sử hội thoại: {len(chat_history)} bản ghi")
        logger.info(f"[analyze_query_with_llm] Prompt cuối cùng: {prompt[:200]}...")
        
        # Gọi LLM API với stream=False vì đây là analyzer/router
        response_text = query_llm(prompt, system_prompt, max_tokens=200, stream=False)
        
        # Tạo ID duy nhất cho phiên phân tích này để theo dõi trong logs
        analysis_id = f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Ghi log đầy đủ của phản hồi gốc ra file
        raw_response_path = f"data/logs/{analysis_id}_raw.txt"
        os.makedirs(os.path.dirname(raw_response_path), exist_ok=True)
        with open(raw_response_path, 'w', encoding='utf-8') as f:
            f.write(response_text)
        logger.info(f"[{analysis_id}] Đã ghi phản hồi gốc vào: {raw_response_path}")
        
        # Log phản hồi gốc (chỉ log phần đầu để tránh quá dài)
        logger.info(f"[{analysis_id}] Phản hồi gốc: {response_text[:100]}...")
        
        # Xử lý thẻ <think> nếu có
        if "<think>" in response_text:
            logger.warning(f"[{analysis_id}] Phát hiện thẻ <think> trong phản hồi. Xử lý đặc biệt...")
            # Tìm nội dung JSON trong phản hồi sử dụng regex
            json_pattern = r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}'
            json_matches = re.findall(json_pattern, response_text)
            
            if json_matches:
                logger.info(f"[{analysis_id}] Đã tìm thấy {len(json_matches)} mẫu JSON tiềm năng trong phản hồi")
                for potential_json in json_matches:
                    try:
                        result = json.loads(potential_json)
                        # Kiểm tra xem chuỗi JSON có chứa các trường cần thiết không
                        if all(key in result for key in ["department", "query_type", "error"]):
                            logger.info(f"[{analysis_id}] Tìm thấy JSON hợp lệ trong thẻ <think>: {result}")
                            return result
                    except json.JSONDecodeError:
                        continue
        
        # BƯỚC 1: Thử kiểm tra xem cả chuỗi phản hồi có phải là JSON hợp lệ không
        try:
            # Thử parse trực tiếp toàn bộ chuỗi
            logger.info(f"[{analysis_id}] BƯỚC 1: Thử parse toàn bộ chuỗi phản hồi")
            direct_json = json.loads(response_text)
            logger.info(f"[{analysis_id}] BƯỚC 1: Parse thành công: {direct_json}")
            
            # Trả về kết quả nếu có các trường cần thiết
            if all(key in direct_json for key in ["department", "query_type", "error"]):
                logger.info(f"[{analysis_id}] BƯỚC 1: JSON hợp lệ có đủ các trường cần thiết")
                
                # Xử lý logic trước khi trả về
                if direct_json.get("error") == True:
                    direct_json["error_message"] = "Phát hiện 2 phòng ban trong cùng 1 câu hỏi"
                
                department = direct_json.get("department")
                if department and department != "null" and not direct_json.get("error"):
                    add_to_department_history(query, department)
                
                # Thêm log phân tích chi tiết
                logger.info(f"[{analysis_id}] Kết quả phân tích cho query '{query}': department={department}, query_type={direct_json.get('query_type')}, error={direct_json.get('error')}")
                if department:
                    if query.lower().find(department.lower()) == -1:
                        logger.info(f"[{analysis_id}] Lưu ý: Phòng ban '{department}' được suy luận từ ngữ cảnh hội thoại, không xuất hiện trực tiếp trong câu hỏi")
                    
                return direct_json
            else:
                logger.warning(f"[{analysis_id}] BƯỚC 1: JSON không có đủ các trường cần thiết, tiếp tục các phương pháp khác")
                
        except json.JSONDecodeError as e:
            logger.info(f"[{analysis_id}] BƯỚC 1: Không phải JSON hợp lệ: {str(e)}")
            # Tiếp tục các phương pháp khác
            
        # BƯỚC 2: Tìm JSON trong chuỗi phản hồi
        try:
            logger.info(f"[{analysis_id}] BƯỚC 2: Tìm JSON trong chuỗi phản hồi")
            
            # Sử dụng regex để tìm cấu trúc JSON
            json_pattern = r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}'
            json_matches = re.findall(json_pattern, response_text)
            
            if json_matches:
                logger.info(f"[{analysis_id}] BƯỚC 2: Tìm thấy {len(json_matches)} mẫu JSON tiềm năng")
                
                # Kiểm tra từng mẫu JSON tìm được
                for potential_json in json_matches:
                    try:
                        result = json.loads(potential_json)
                        
                        # Kiểm tra xem JSON có đủ các trường cần thiết không
                        if all(key in result for key in ["department", "query_type", "error"]):
                            logger.info(f"[{analysis_id}] BƯỚC 2: Tìm thấy JSON hợp lệ: {result}")
                            
                            # Xử lý logic trước khi trả về
                            if result.get("error") == True:
                                result["error_message"] = "Phát hiện 2 phòng ban trong cùng 1 câu hỏi"
                            
                            department = result.get("department")
                            if department and department != "null" and not result.get("error"):
                                add_to_department_history(query, department)
                            
                            # Thêm log phân tích chi tiết
                            logger.info(f"[{analysis_id}] Kết quả phân tích cho query '{query}': department={department}, query_type={result.get('query_type')}, error={result.get('error')}")
                            if department:
                                if query.lower().find(department.lower()) == -1:
                                    logger.info(f"[{analysis_id}] Lưu ý: Phòng ban '{department}' được suy luận từ ngữ cảnh hội thoại, không xuất hiện trực tiếp trong câu hỏi")
                            
                            return result
                    except json.JSONDecodeError:
                        continue
                
                logger.warning(f"[{analysis_id}] BƯỚC 2: Không tìm thấy JSON hợp lệ trong các mẫu")
            else:
                logger.warning(f"[{analysis_id}] BƯỚC 2: Không tìm thấy mẫu JSON nào trong phản hồi")
        
        except Exception as e:
            logger.error(f"[{analysis_id}] BƯỚC 2: Lỗi khi tìm JSON: {str(e)}")
        
        # BƯỚC 3: Xử lý các chuỗi cụ thể để tìm thông tin cần thiết
        try:
            logger.info(f"[{analysis_id}] BƯỚC 3: Xử lý chuỗi thủ công để trích xuất thông tin")
            
            # Tìm phòng ban được đề cập trong câu hỏi
            department_tool = DepartmentInfoTool()
            departments = department_tool.get_departments()
            
            department = None
            for dept in departments:
                if dept.lower() in query.lower():
                    department = dept
                    logger.info(f"[{analysis_id}] BƯỚC 3: Tìm thấy phòng ban trong câu hỏi: {department}")
                    break
            
            # Nếu không tìm thấy phòng ban trong câu hỏi, xem xét lấy từ lịch sử
            if not department and last_department:
                # Nếu câu hỏi ngắn hoặc có vẻ là tiếp tục cuộc hội thoại trước
                short_queries = ["họ", "bộ phận này", "phòng ban đó", "tiếp theo", "bước tiếp theo", "giai đoạn này"]
                if any(term in query.lower() for term in short_queries) or len(query.split()) < 10:
                    department = last_department
                    logger.info(f"[{analysis_id}] BƯỚC 3: Sử dụng phòng ban từ ngữ cảnh hội thoại: {department}")
            
            # Xác định loại câu hỏi
            general_terms = ["quy trình", "giai đoạn chung", "tất cả phòng ban", "công ty", "dự án", "phòng ban nào"]
            query_type = "general" if (not department and any(term in query.lower() for term in general_terms)) else "department_specific"
            
            # Nếu có department nhưng query_type là general, thì sửa lại
            if department and query_type == "general":
                query_type = "department_specific"
            
            # Nếu không có department nhưng query_type là department_specific, thì sửa lại
            if not department and query_type == "department_specific":
                query_type = "general"
            
            # Tạo kết quả phân tích cuối cùng
            result = {
                "department": department,
                "query_type": query_type,
                "error": False
            }
            
            logger.info(f"[{analysis_id}] BƯỚC 3: Kết quả phân tích thủ công: {result}")
            
            # Nếu có phòng ban, thêm vào lịch sử
            if department:
                add_to_department_history(query, department)
            
            return result
            
        except Exception as e:
            logger.error(f"[{analysis_id}] BƯỚC 3: Lỗi khi xử lý chuỗi thủ công: {str(e)}")
        
        # Nếu tất cả các phương pháp trên đều thất bại, trả về kết quả mặc định
        logger.warning(f"[{analysis_id}] Tất cả phương pháp phân tích đều thất bại, trả về kết quả mặc định")
        
        default_result = {
            "department": None,
            "query_type": "general",
            "error": False
        }
        
        return default_result
    
    except Exception as e:
        logger.error(f"Lỗi khi phân tích câu hỏi bằng LLM: {str(e)}")
        
        # Luôn trả về một đối tượng hợp lệ, không bao giờ trả về None
        return {
            "department": None,
            "query_type": "general",
            "error": False
        }

def traditional_rag_query(query: str, sub_phase: str = None, department: str = None, session_id: Optional[str] = None) -> str:
    """
    Truy vấn RAG truyền thống (search & retrieve)
    
    Args:
        query: Câu hỏi của người dùng
        sub_phase: Giai đoạn con liên quan
        department: Phòng ban liên quan
        session_id: ID phiên hiện tại (nếu có)
        
    Returns:
        Phản hồi của LLM
    """
    logger.info(f"Truy vấn Traditional RAG - Giai đoạn: {sub_phase}, Phòng ban: {department}, session_id: {session_id}")
    
    # Khởi tạo công cụ thông tin phòng ban
    department_tool = DepartmentInfoTool()
    
    # Tạo prompt hệ thống
    system_prompt = create_system_prompt(sub_phase, department)
    
    # Trích xuất thông tin từ công cụ - Lưu ý: chỉ truyền tham số department
    if department:
        department_info = department_tool.get_department_info(department)
    else:
        department_info = "Không có thông tin phòng ban cụ thể."
    
    # Tạo prompt cho LLM
    prompt = f"""
Câu hỏi: "{query}"

Đây là thông tin liên quan đến câu hỏi:

{department_info}

Dựa vào thông tin trên, hãy trả lời câu hỏi một cách chính xác và đầy đủ.
"""
    
    try:
        logger.info(f"Gọi LLM với traditional RAG")
        
        # Lưu prompt để debug
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs("data/logs", exist_ok=True)
        prompt_file_path = f"data/logs/trad_prompt_{timestamp}.txt"
        with open(prompt_file_path, 'w', encoding='utf-8') as f:
            f.write(f"System Prompt:\n{system_prompt}\n\nUser Prompt:\n{prompt}")
        
        # Gọi LLM
        final_response = query_llm(prompt, system_prompt)
        
        # Lưu response để debug
        response_file_path = f"data/logs/trad_response_{timestamp}.txt"
        with open(response_file_path, 'w', encoding='utf-8') as f:
            f.write(final_response)
        
        # Lưu thông tin truy vấn
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "sub_phase": sub_phase,
            "department": department,
            "session_id": session_id,
            "response": final_response
        }
        
        log_file = f"data/logs/trad_query_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
            
        # Xử lý phản hồi để loại bỏ các header không cần thiết
        cleaned_response = final_response
        if "# Trả lời câu hỏi:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời câu hỏi:", "")
        if "# Trả lời:" in cleaned_response:
            cleaned_response = cleaned_response.replace("# Trả lời:", "")
            
        # Hiển thị phản hồi đã xử lý
        st.write(cleaned_response)
        
        # Nếu phòng ban được chỉ định, hiển thị thông tin liên quan
        if department:
            with st.expander("📋 Thông tin liên quan"):
                st.write(department_info)
        
        return None
            
    except Exception as e:
        error_msg = f"Lỗi khi gọi LLM: {str(e)}"
        logger.error(error_msg)
        return f"Đã xảy ra lỗi khi xử lý câu hỏi: {str(e)}"

def show_department_not_found_message(department_tool, query, use_llm_analysis):
    """Hiển thị thông báo khi không tìm thấy phòng ban trong câu hỏi"""
    logger.warning(f"Không tìm thấy phòng ban trong câu hỏi: {query}")
    
    # Đưa ra thông báo phù hợp
    if use_llm_analysis:
        st.warning("❓ Không phát hiện được phòng ban trong câu hỏi của bạn. Vui lòng nhắc đến tên phòng ban cụ thể.")
        st.info("Các phòng ban hiện có: " + ", ".join(department_tool.get_departments()))
        st.markdown("Ví dụ câu hỏi: **Phòng ban Marketing có nhiệm vụ gì?**")
    else:
        st.warning("❓ Không phát hiện được phòng ban trong câu hỏi của bạn.")
        st.info("Vui lòng chọn một phòng ban từ thanh bên trái hoặc nhắc đến tên phòng ban cụ thể trong câu hỏi của bạn.")
    
    # Nếu phòng ban đã được chọn từ nút, nhắc người dùng sử dụng
    if not use_llm_analysis and 'selected_department' in st.session_state:
        st.success(f"Phòng ban hiện tại đã chọn: {st.session_state.selected_department}")
        st.markdown("Nhập câu hỏi của bạn và hệ thống sẽ tự động truy vấn thông tin về phòng ban này.")


# Thêm hàm quản lý phiên hội thoại
def create_new_session(session_name):
    """
    Tạo một phiên hội thoại mới
    
    Args:
        session_name: Tên phiên hội thoại
    """
    if 'all_sessions' not in st.session_state:
        st.session_state.all_sessions = {}
    
    # Tạo phiên mới với tên được đặt
    session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    st.session_state.all_sessions[session_id] = {
        "name": session_name,
        "created_at": datetime.now().isoformat(),
        "chat_history": []
    }
    
    # Đặt phiên mới làm phiên hiện tại
    st.session_state.current_session = session_id
    logger.info(f"Đã tạo phiên mới: {session_name} với ID: {session_id}")

def get_all_sessions():
    """
    Lấy danh sách tất cả các phiên
    
    Returns:
        Dict: Danh sách các phiên
    """
    if 'all_sessions' not in st.session_state:
        st.session_state.all_sessions = {}
    
    return st.session_state.all_sessions

def get_current_session():
    """
    Lấy phiên hiện tại
    
    Returns:
        str: ID phiên hiện tại, None nếu không có
    """
    if 'current_session' not in st.session_state:
        # Nếu có phiên, chọn phiên đầu tiên
        if 'all_sessions' in st.session_state and st.session_state.all_sessions:
            st.session_state.current_session = list(st.session_state.all_sessions.keys())[0]
        else:
            return None
    
    return st.session_state.current_session

def delete_session(session_id):
    """
    Xóa một phiên hội thoại
    
    Args:
        session_id: ID phiên cần xóa
    """
    if 'all_sessions' in st.session_state and session_id in st.session_state.all_sessions:
        session_name = st.session_state.all_sessions[session_id]["name"]
        del st.session_state.all_sessions[session_id]
        
        # Nếu đã xóa phiên hiện tại, chọn phiên khác
        if 'current_session' in st.session_state and st.session_state.current_session == session_id:
            if st.session_state.all_sessions:
                st.session_state.current_session = list(st.session_state.all_sessions.keys())[0]
            else:
                del st.session_state.current_session
        
        logger.info(f"Đã xóa phiên: {session_name} với ID: {session_id}")

def main():
    # Đảm bảo set_page_config() là lệnh Streamlit đầu tiên được gọi
    st.set_page_config(
        page_title="🏢 Chatbot về quy trình của phòng ban cụ thể",
        page_icon="🏢",
        layout="wide",
    )
    
    # Đảm bảo thư mục logs tồn tại
    os.makedirs('data/logs', exist_ok=True)
    
    st.title("🏢 Chatbot RAG Phòng Ban")
    st.markdown("Hỏi về bất kỳ phòng ban nào để lấy thông tin về các công việc và nhiệm vụ của họ.")
    
    # Hướng dẫn sử dụng (giữ nguyên phần này)
    with st.expander("📚 Hướng dẫn sử dụng"):
        st.markdown("""
        ### Cách sử dụng chatbot
        
        1. Nhập câu hỏi về một phòng ban trong ô nhập liệu bên dưới
        2. Ví dụ các câu hỏi:
           - "Cho tôi biết về phòng ban Marketing"
           - "Phòng Thi công có những công việc nào trong giai đoạn CONSTRUCTION?"
           - "Nhiệm vụ của phòng Kế toán là gì?"
           - "Những công việc nào của phòng Kinh doanh thuộc giai đoạn con Sales Sourcing?"
        3. Chatbot sẽ tự động phát hiện phòng ban và cung cấp thông tin liên quan
        
        ### Chế độ DeepThink
        
        - Bấm nút **🧠 DeepThink** để kích hoạt chế độ suy nghĩ sâu, giúp chatbot đưa ra câu trả lời chi tiết và phân tích sâu hơn
        - Bấm nút **❌ Tắt DeepThink** để tắt chế độ này và nhận câu trả lời ngắn gọn hơn
        
        ### Có thể tìm thông tin theo giai đoạn con:
        
        - **MKT-SALES:** Branding MKT, Sales Sourcing, Data Qualification, Approach
        - **PROPOSAL:** Proposal
        - **CONSTRUCTION:** Thi công
        - **DEFECT-HANDOVER:** Defect & Handover
        - **AFTERSALE-MAINTENANCE:** After Sales & Maintenance
        - **Chung:** Done
        
        ### Lưu ý
        
        "Marketing và Bán hàng" không phải là tên phòng ban mà là giai đoạn dự án (MKT-SALES).
        Khi hỏi về "Marketing và Bán hàng", chatbot sẽ hiểu là bạn đang hỏi về phòng ban Marketing hoặc Kinh doanh.

        ### Phiên hội thoại
        
        - Mỗi phiên (session) sẽ có lịch sử hội thoại riêng
        - Bạn có thể tạo nhiều phiên khác nhau và chuyển đổi giữa các phiên
        - Sử dụng chức năng quản lý phiên trong thanh sidebar
        """)
    
    # Khởi tạo department_tool
    department_tool = DepartmentInfoTool()
    
    # Tải danh sách phòng ban
    all_depts = department_tool.get_all_departments()
    departments = all_depts.get('departments', [])
    
    # Khởi tạo session state cho các biến checkbox nếu chưa tồn tại
    if 'use_llm_analysis' not in st.session_state:
        st.session_state.use_llm_analysis = True
    
    if 'use_llm' not in st.session_state:
        st.session_state.use_llm = True

    if 'use_deepthink' not in st.session_state:
        st.session_state.use_deepthink = False
        
    if 'send_message' not in st.session_state:
        st.session_state.send_message = False
    
    if 'last_query' not in st.session_state:
        st.session_state.last_query = ""
    
    # Đảm bảo có phiên mặc định
    if 'all_sessions' not in st.session_state or not st.session_state.all_sessions:
        create_new_session("Phiên mặc định")
    
    # Sidebar - Phần quản lý hội thoại và cài đặt
    with st.sidebar:
        # Phần 1: Cài đặt
        st.title("⚙️ Cài đặt")
        
        # Đưa các checkbox vào expander để tiết kiệm không gian
        with st.expander("Tùy chọn phân tích", expanded=False):
            # Đảm bảo sử dụng key để liên kết với session state
            use_llm_analysis = st.checkbox("Sử dụng phân tích LLM", 
                                          key="use_llm_analysis",
                                          help="Bật tính năng này để phân tích câu hỏi bằng LLM")
            
            use_llm = st.checkbox("Sử dụng LLM cho câu trả lời",
                               key="use_llm",
                               help="Bật tính năng này để sử dụng LLM cho câu trả lời")
        
        # Hiển thị trạng thái LLM API trong sidebar
        with st.expander("Trạng thái LLM API", expanded=False):
            try:
                status_url = f"{LLM_CFG['model_server']}/models"
                response = requests.get(status_url, timeout=2)
                if response.status_code == 200:
                    st.success("✅ LLM API đang hoạt động")
                    models = response.json().get('data', [])
                    if models:
                        st.text(f"Mô hình: {', '.join([m.get('id', 'unknown') for m in models])}")
                else:
                    st.error("❌ LLM API không phản hồi đúng")
            except Exception as e:
                st.error(f"❌ Không thể kết nối đến LLM API: {str(e)}")
        
        # Phần 2: Quản lý phiên hội thoại
        st.title("💬 Quản lý phiên")
        
        # Form tạo phiên mới
        with st.form(key="new_session_form"):
            session_name = st.text_input("Tên phiên mới:", placeholder="Nhập tên phiên...", key="new_session_name")
            submit_button = st.form_submit_button(label="🆕 Tạo phiên mới")
            
            if submit_button and session_name:
                create_new_session(session_name)
                st.success(f"Đã tạo phiên mới: {session_name}")
                st.rerun()
        
        # Chọn phiên hiện tại
        st.subheader("Chọn phiên")
        all_sessions = get_all_sessions()
        current_session = get_current_session()
        
        # Sắp xếp phiên theo thời gian mới nhất trước
        sorted_sessions = sorted(
            all_sessions.items(), 
            key=lambda x: x[1]["created_at"], 
            reverse=True
        )
        
        # Tạo danh sách session_ids và session_names
        session_ids = []
        session_names = []
        for session_id, session_data in sorted_sessions:
            session_ids.append(session_id)
            session_name = session_data["name"]
            created_at = datetime.fromisoformat(session_data["created_at"]).strftime('%d/%m/%Y %H:%M')
            chat_count = len(session_data['chat_history'])
            display_name = f"{session_name} ({chat_count} hội thoại)"
            session_names.append(display_name)
        
        # Tìm vị trí phiên hiện tại trong danh sách
        current_index = 0
        if current_session in session_ids:
            current_index = session_ids.index(current_session)
        
        # Sử dụng radio để chọn phiên
        selected_index = st.radio(
            "Phiên đang hoạt động:",
            range(len(session_names)),
            format_func=lambda i: session_names[i],
            index=current_index,
            key="session_selector"
        )
        
        # Cập nhật phiên hiện tại nếu có thay đổi
        selected_session_id = session_ids[selected_index]
        if selected_session_id != current_session:
            st.session_state.current_session = selected_session_id
            st.rerun()
        
        # Hiển thị thông tin phiên đã chọn
        selected_session = all_sessions[selected_session_id]
        created_at = datetime.fromisoformat(selected_session["created_at"]).strftime('%d/%m/%Y %H:%M')
        st.caption(f"Tạo lúc: {created_at}")
        
        # Nút xóa phiên
        if st.button("🗑️ Xóa phiên này", key="delete_current_session"):
            if len(all_sessions) > 1:  # Đảm bảo luôn có ít nhất 1 phiên
                delete_session(selected_session_id)
                st.success(f"Đã xóa phiên {selected_session['name']}")
                st.rerun()
            else:
                st.error("Không thể xóa phiên cuối cùng")
        
        # Đường kẻ phân cách
        st.divider()
        
        # Phần 3: Danh sách phòng ban
        st.title("🏢 Danh sách phòng ban")

        # Hiển thị danh sách phòng ban và tạo các nút chọn khi không sử dụng LLM analysis
        if not use_llm_analysis:
            # Reset selected department khi thay đổi chế độ
            if 'previous_llm_analysis_state' not in st.session_state or st.session_state.previous_llm_analysis_state != use_llm_analysis:
                if 'selected_department' in st.session_state:
                    del st.session_state.selected_department
                st.session_state.previous_llm_analysis_state = use_llm_analysis
                
            st.info("Khi tắt phân tích LLM, bạn cần chọn phòng ban từ danh sách bên dưới")
            
            # Lấy danh sách phòng ban từ tool
            departments = department_tool.get_departments()
            
            # Loại bỏ các phòng ban trùng lặp (nếu có)
            departments = list(dict.fromkeys(departments))
            
            # Tạo các nút cho từng phòng ban
            cols = st.columns(2)  # Chia thành 2 cột để hiển thị nút
            for i, dept in enumerate(departments):
                col_idx = i % 2  # Xác định cột để đặt nút
                
                # Kiểm tra xem phòng ban này có phải là phòng ban đã chọn không
                is_selected = 'selected_department' in st.session_state and st.session_state.selected_department == dept
                
                # Tạo nút với định dạng đặc biệt nếu đã chọn
                if is_selected:
                    # Sử dụng emoji ✅ cho phòng ban đã chọn
                    button_label = f"✅ {dept}"
                    # Sử dụng success để làm nổi bật nút với màu xanh lá
                    cols[col_idx].success(button_label)
                else:
                    # Nút bình thường cho các phòng ban khác
                    if cols[col_idx].button(dept, key=f"btn_{dept}_{i}"):
                        st.session_state.selected_department = dept
                        logger.info(f"Đã chọn phòng ban: {dept}")
                        # Refresh trang để cập nhật UI
                        st.rerun()
            
            # Hiển thị phòng ban đã chọn
            if 'selected_department' in st.session_state:
                st.success(f"Phòng ban đã chọn: {st.session_state.selected_department}")
        else:
            # Hiển thị danh sách phòng ban khi sử dụng LLM analysis
            departments = department_tool.get_departments()
            # Loại bỏ phòng ban trùng lặp bằng cách chuyển sang set rồi list
            departments = list(dict.fromkeys(departments))
            # Hiển thị danh sách phòng ban nhỏ gọn hơn
            dept_text = ", ".join(departments)
            st.write(f"Có thể hỏi về: {dept_text}")
        
        # Phần 4: Quản lý lịch sử hội thoại
        st.title("📝 Quản lý hội thoại")
        
        # Các nút quản lý lịch sử
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🚑 Xóa lịch sử", key="clear_history", help="Xóa toàn bộ lịch sử hội thoại của phiên hiện tại"):
                clear_chat_history()
                st.success("Đã xóa toàn bộ lịch sử")
                # Rerun để cập nhật giao diện
                st.rerun()
        
        with col2:
            if st.button("📥 Export lịch sử", key="export_history", help="Xuất lịch sử phiên hiện tại dạng JSON"):
                json_data = export_chat_history()
                if json_data:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    current_session = get_current_session()
                    session_name = "default"
                    if current_session and current_session in all_sessions:
                        session_name = all_sessions[current_session]["name"]
                    
                    st.download_button(
                        label="Tải xuống",
                        data=json_data,
                        file_name=f"chat_history_{session_name}_{timestamp}.json",
                        mime="application/json",
                        key="download_history"
                    )
                else:
                    st.info("Lịch sử trống")
        
        # Hiển thị lịch sử hội thoại
        st.subheader("Lịch sử gần đây")
        chat_history = get_chat_history()
        
        if not chat_history:
            st.info("Chưa có hội thoại nào")
        else:
            # Hiển thị 5 hội thoại gần nhất (thảo luận theo thứ tự mới nhất lên đầu)
            reversed_history = list(reversed(chat_history[-5:]))
            for i, chat in enumerate(reversed_history):
                # Rút ngắn quá dài 
                query_short = chat["query"][:50] + "..." if len(chat["query"]) > 50 else chat["query"]
                
                # Thứ tự theo hội thoại mới
                chat_id = len(chat_history) - i
                
                # Sử dụng expander cho mỗi hội thoại  
                with st.expander(f"#{chat_id}: {query_short}", expanded=False):
                    # Phòng ban và thời gian
                    dept_info = f"**Phòng ban:** {chat['department']}" if chat.get('department') else ""
                    time_str = datetime.fromisoformat(chat['timestamp']).strftime('%d/%m/%Y %H:%M:%S')
                    
                    st.markdown(f"**Hỏi:** {chat['query']}")
                    st.markdown(f"**Trả lời:** {chat['response']}")
                    st.markdown(f"{dept_info} | **Thời gian:** {time_str}")
    
    # Tiếp tục phần còn lại của hàm main() (giao diện người dùng)
    # Hàm callback khi nhấn nút DeepThink
    def on_deepthink_toggle():
        st.session_state.use_deepthink = not st.session_state.use_deepthink
    
    
    # Hàng 1: Ô nhập liệu chiếm toàn bộ chiều rộng
    query = st.text_input(
        "Nhập câu hỏi của bạn:", 
        placeholder="Ví dụ: Cho tôi biết về phòng ban Marketing", 
        key="user_query",
    )
    
    # Hàng 2: Nút DeepThink và nút Gửi
    cols = st.columns([0.6, 0.4])
    
    with cols[0]:
        # Tùy chỉnh nút DeepThink dựa trên trạng thái
        if st.session_state.use_deepthink:
            deepthink_label = "🧠 DeepThink: BẬT"
            deepthink_help = "Nhấn để tắt chế độ phân tích chi tiết"
            button_type = "primary"
        else:
            deepthink_label = "🧠 DeepThink: TẮT"
            deepthink_help = "Nhấn để bật chế độ phân tích chi tiết"
            button_type = "secondary"
            
        st.button(deepthink_label, key="deepthink_button", 
                 help=deepthink_help, 
                 type=button_type, 
                 on_click=on_deepthink_toggle,
                 use_container_width=True)  # Sử dụng toàn bộ chiều rộng cột
    
    with cols[1]:
        # Nút gửi luôn dùng màu chính - nổi bật hơn
        send_clicked = st.button("📤 Gửi câu hỏi", 
                 key="send_button", 
                 help="Gửi câu hỏi và nhận phản hồi", 
                 type="primary",
                 use_container_width=True)  # Sử dụng toàn bộ chiều rộng cột
    
    # Kiểm tra nếu nút gửi được nhấn và có câu hỏi
    if send_clicked and query.strip():
        # Lưu trữ câu hỏi vào session state
        st.session_state.last_query = query
        st.session_state.send_message = True
        # Thực hiện rerun để xử lý tin nhắn
        st.rerun()
    
    # Hiển thị thông tin trạng thái phụ thuộc vào DeepThink
    if st.session_state.use_deepthink:
        st.success("Chế độ DeepThink đã được kích hoạt. Câu trả lời sẽ chi tiết và phân tích sâu hơn.")
    
    # Xử lý khi cần gửi tin nhắn - đây là phần quan trọng để xử lý tin nhắn
    if st.session_state.send_message and st.session_state.last_query:
        query = st.session_state.last_query
        
        # Hiển thị thông báo đang xử lý
        with st.spinner(f"🔄 Đang xử lý câu hỏi: '{query}'"):
            try:
                # Khởi tạo department_tool nếu chưa có
                department_tool = DepartmentInfoTool()
                
                # Sử dụng LLM để phân tích câu hỏi và xác định phòng ban
                analysis_result = analyze_query_with_llm(query)
                
                if analysis_result.get("error", False):
                    # Xử lý lỗi phát hiện nhiều phòng ban
                    error_message = analysis_result.get("error_message", "Phát hiện 2 phòng ban trong cùng 1 câu hỏi")
                    st.error(f"❌ {error_message}")
                    st.info("Vui lòng chỉ hỏi về một phòng ban cụ thể trong mỗi câu hỏi.")
                    logger.warning(f"Lỗi khi phân tích câu hỏi: {error_message}")
                    st.session_state.send_message = False
                    return
                
                department = analysis_result.get("department")
                query_type = analysis_result.get("query_type")
                
                logger.info(f"Phân tích câu hỏi: Phòng ban={department}, Loại={query_type}")
                
                # Nếu câu hỏi thuộc loại chung, không liên quan đến phòng ban cụ thể
                if query_type == "general":
                    logger.info("Câu hỏi chung, sử dụng handle_general_query")
                    response = handle_general_query(query, use_llm=st.session_state.use_llm)
                    # Thêm vào lịch sử
                    add_to_chat_history(query, response)
                    # Reset trạng thái gửi tin nhắn
                    st.session_state.send_message = False
                    return
                    
                # Nếu không tìm thấy phòng ban, hiển thị thông báo
                if not department:
                    show_department_not_found_message(department_tool, query, st.session_state.use_llm_analysis)
                    # Reset trạng thái gửi tin nhắn
                    st.session_state.send_message = False
                    return
                
                # Luôn sử dụng smart_rag_query bất kể trạng thái DeepThink
                logger.info(f"Sử dụng smart_rag_query cho: {query}")
                # Không cần phát hiện sub_phase, LLM sẽ xử lý trong quá trình phân tích
                response = smart_rag_query(query, sub_phase=None, department=department)
                
                # Thêm vào lịch sử
                add_to_chat_history(query, response, department)
                
                # Reset trạng thái gửi tin nhắn
                st.session_state.send_message = False
                
            except Exception as e:
                # Hiển thị lỗi nếu có
                st.error(f"❌ Đã xảy ra lỗi khi xử lý câu hỏi: {str(e)}")
                logger.error(f"Lỗi khi xử lý câu hỏi: {str(e)}", exc_info=True)
                # Reset trạng thái gửi tin nhắn
                st.session_state.send_message = False

# Sửa phần gọi hàm main() ở cuối file
if __name__ == "__main__":
    main() 