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

# Cấu hình logging chỉ với console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("chatbot_rag")

# Cấu hình Qwen LLM
LLM_CFG = {
    'model': 'qwen3-30b-a3b',
    'model_server': 'http://192.168.0.43:1234/v1'
}


def create_system_prompt(sub_phase: Optional[str] = None, department: Optional[str] = None) -> str:
    """
    Tạo system prompt thống nhất cho tất cả các truy vấn
    
    Args:
        sub_phase: Giai đoạn con liên quan (nếu có)
        department: Phòng ban liên quan (nếu có)
    
    Returns:
        str: System prompt chuẩn cho LLM
    """
    base_prompt = """
Bạn là trợ lý AI hỗ trợ trả lời các câu hỏivề công việc của các phòng ban trong công ty. 
Nhiệm vụ: phân tích thông tin về các task trong phòng ban và cung cấp thông tin hữu ích.

Dự án được chia thành các giai đoạn chính (main phases) theo thứ tự cố định:
1. MKT-SALES: Giai đoạn Marketing và Bán hàng
2. PROPOSAL: Giai đoạn đề xuất
3. CONSTRUCTION: Giai đoạn thi công
4. DEFECT-HANDOVER: Giai đoạn xử lý lỗi và bàn giao
5. AFTERSALE-MAINTENANCE: Giai đoạn sau bán hàng và bảo trì

Giai đoạn MKT-SALES bao gồm các giai đoạn con (sub-phases) theo thứ tự:
1. Branding MKT: Marketing thương hiệu
2. Sales Sourcing: Tìm kiếm nguồn bán hàng
3. Data Qualification: Phân loại dữ liệu
4. Approach: Tiếp cận

Giai đoạn PROPOSAL bao gồm các giai đoạn con/bước/quy trình con (sub-phases) theo thứ tự:
1. PROPOSAL

Giai đoạn CONSTRUCTION bao gồm các giai đoạn con/bước/quy trình con (sub-phases) theo thứ tự:
1. CONSTRUCTION

Giai đoạn DEFECT-HANDOVER bao gồm các giai đoạn con/bước/quy trình con (sub-phases) theo thứ tự:
1. DEFECT-HANDOVER
2. AFTERSALE-MAINTENANCE (bước chuyển tiếp)

Giai đoạn AFTERSALE-MAINTENANCE bao gồm các giai đoạn con/bước/quy trình con (sub-phases) theo thứ tự:
1. AFTERSALE-MAINTENANCE
2. Done (Kết thúc toàn bộ giai đoạn)

QUY TẮC NGHIÊM NGẶT:
1. KHÔNG TỰ TẠO mối liên hệ giữa giai đoạn và phòng ban
2. KHÔNG LIỆT KÊ phòng ban nào tham gia vào giai đoạn nào
3. CHỈ TẬP TRUNG vào thông tin của một phòng ban cụ thể
4. KHÔNG ĐỀ CẬP đến mối quan hệ giữa các phòng ban
5. Khi hỏi về mối liên hệ giữa giai đoạn và phòng ban, CHỈ trả lời: "Vui lòng hỏi về một phòng ban cụ thể để biết thêm chi tiết"

KHI TRẢ LỜI:
1. Ngắn gọn, súc tích nhưng đầy đủ thông tin
2. Nếu không tìm thấy thông tin, thông báo rằng không có thông tin trong dữ liệu.
3. chỉ liệt kê giai đoạn nếu người dùng hỏi về các giai đoạn, nếu chỉ hỏi về giai đoạn cụ thể thì chỉ tập trung vào giai đoạn đó và trả lời.
4. Trả lời ngắn gọn, không cần thông tin chi tiết.
5. Với câu hỏi chào hỏi/không liên quan đến phòng ban, giai đoạn, công việc, hãy trả lời bình thường, không nhắc đến công việc. Có thể giới thiệu bản thân.

Trả lời bằng tiếng Việt, ngay cả khi người dùng hỏi bằng tiếng Anh.
"""

    # Thêm thông tin về giai đoạn và phòng ban nếu có
    if sub_phase:
        base_prompt += f"\nGiai đoạn con hiện tại: {sub_phase}"
    if department:
        base_prompt += f"\nPhòng ban hiện tại: {department}"

    return base_prompt


def create_llm_prompt(query: str, dept_info: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """
    Tạo LLM prompt thống nhất cho tất cả các truy vấn
    
    Args:
        query: Câu hỏi của người dùng
        dept_info: Thông tin về phòng ban
        session_id: ID của phiên hiện tại (nếu có)
        
    Returns:
        str: LLM prompt chuẩn
    """
    # Log các thông tin quan trọng để debug
    department = dept_info.get('department', 'Không xác định')
    logger.info(f"Tạo prompt LLM cho phòng ban: {department}, session_id: {session_id}")
    logger.info(f"Số task: {dept_info.get('task_count', 0)}")
    
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
                logger.warning("[create_llm_prompt] Không thể import get_session_history từ websocket_server.")
                history = []
            except Exception as e_hist:
                 logger.error(f"[create_llm_prompt] Lỗi khi lấy lịch sử hội thoại cho session {session_id} bằng get_session_history: {str(e_hist)}")

            # Lấy 5 cuộc hội thoại gần đây nhất (thay vì 2-3)
            recent_history = history[-5:] if len(history) > 5 else history
            
            if recent_history:
                conversation_history = "Lịch sử tin nhắn:\\n"
                # Duyệt ngược để hiển thị tin nhắn gần nhất cuối cùng
                for idx, item in enumerate(recent_history):
                    # Thêm câu hỏi của người dùng
                    conversation_history += f"Người dùng: {item.get('query', '')}\\n"
                    
                    # Xóa phần thêm thông tin phòng ban
                    # if item.get('department'):
                    #     conversation_history += f"(Phòng ban: {item['department']})\\n"
                    
                    # KHÔNG thêm phản hồi của trợ lý, để đồng bộ với xử lý trong websocket_server.py
                
                # Thêm thông tin tổng kết về phòng ban đã nhắc đến gần đây
                mentioned_departments = [item.get('department') for item in recent_history if item.get('department')]
                if mentioned_departments:
                    last_department = mentioned_departments[-1]
                    conversation_history += f"\\n**LƯU Ý**: Phòng ban được nhắc đến gần đây nhất là: **{last_department}**\\n\\n"
                
                logger.info(f"[create_llm_prompt] Đã thêm {len(recent_history)} hội thoại vào prompt cho session {session_id}")
        except Exception as e:
            logger.error(f"[create_llm_prompt] Lỗi tổng quát khi xử lý lịch sử hội thoại cho session {session_id}: {str(e)}")
    else:
        logger.info("[create_llm_prompt] Không có session_id, không lấy lịch sử hội thoại.")
    
    # Hàm lọc thông tin quan trọng từ full_details
    def extract_important_details(full_details: Optional[str]) -> str:
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
        'id': task.get('id', ''),
        'name': task.get('name', ''),
        'phase': task.get('phase', ''),
        'sub_phase': task.get('sub_phase', ''),
        'important_details': extract_important_details(task.get('full_details', ''))
    } for task in dept_info.get('task_list', [])], ensure_ascii=False)

    # Tạo prompt cuối cùng
    final_prompt = f"""
Câu hỏi: {query}

Thông tin về phòng ban {department}:
{tasks_json}

{conversation_history if conversation_history else ""}

Dựa vào thông tin trên, hãy trả lời câu hỏi một cách chính xác và đầy đủ.
"""

    return final_prompt


# Prompt hệ thống cho LLM
SYSTEM_PROMPT = create_system_prompt()


def query_llm(prompt: str, system_prompt: str, max_tokens: int = 16000, stream: bool = True) -> str:
    """
    Gửi truy vấn đến LLM và nhận phản hồi
    
    Args:
        prompt: Nội dung truy vấn
        system_prompt: System prompt
        max_tokens: Số token tối đa cho phản hồi
        stream: Có sử dụng streaming hay không
        
    Returns:
        str: Phản hồi từ LLM
    """
    try:
        # Chuẩn bị dữ liệu cho request
        data = {
            "model": LLM_CFG['model'],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        # Gửi request đến LLM server
        response = requests.post(
            f"{LLM_CFG['model_server']}/chat/completions",
            json=data,
            stream=stream
        )
        
        # Xử lý phản hồi
        if stream:
            full_response = ""
            for line in response.iter_lines():
                if line:
                    try:
                        json_response = json.loads(line.decode('utf-8').split('data: ')[1])
                        if json_response.get('choices') and json_response['choices'][0].get('delta', {}).get('content'):
                            content = json_response['choices'][0]['delta']['content']
                            full_response += content
                    except Exception as e:
                        logger.error(f"Lỗi khi xử lý phản hồi streaming: {e}")
                        continue
            return full_response
        else:
            json_response = response.json()
            if json_response.get('choices') and json_response['choices'][0].get('message', {}).get('content'):
                return json_response['choices'][0]['message']['content']
            return ""
            
    except Exception as e:
        logger.error(f"Lỗi khi gọi LLM API: {e}")
        return f"Lỗi khi gọi API: {str(e)}"


def handle_general_query(query: str, use_llm: bool = True, session_id: Optional[str] = None) -> str:
    """
    Xử lý truy vấn chung không liên quan đến phòng ban cụ thể
    
    Args:
        query: Câu hỏi của người dùng
        use_llm: Có sử dụng LLM để phân tích hay không
        session_id: ID của phiên hiện tại (nếu có)
        
    Returns:
        str: Phản hồi cho câu hỏi
    """
    logger.info(f"Xử lý truy vấn chung: {query}")
    
    # Phân tích truy vấn bằng LLM nếu được yêu cầu
    if use_llm:
        analysis = analyze_query_with_llm(query, session_id)
        if analysis.get("error"):
            logger.error(f"Lỗi khi phân tích truy vấn: {analysis['error']}")
            return "Xin lỗi, đã xảy ra lỗi khi xử lý câu hỏi của bạn."
    
    # Tạo system prompt và prompt cho LLM
    system_prompt = create_system_prompt()
    dept_info = {"department": None, "task_count": 0, "task_list": [], "phases": []}
    llm_prompt = create_llm_prompt(query, dept_info, session_id)
    
    # Gọi LLM để xử lý truy vấn
    try:
        response = query_llm(llm_prompt, system_prompt)
        return response
    except Exception as e:
        logger.error(f"Lỗi khi gọi LLM: {str(e)}")
        return "Xin lỗi, đã xảy ra lỗi khi xử lý câu hỏi của bạn."


def smart_rag_query(query: str, sub_phase: Optional[str] = None, department: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """
    Thực hiện truy vấn RAG thông minh với phân tích LLM
    
    Args:
        query: Câu hỏi của người dùng
        sub_phase: Giai đoạn con (nếu có)
        department: Phòng ban (nếu có)
        session_id: ID của phiên hiện tại (nếu có)
        
    Returns:
        str: Phản hồi cho câu hỏi
    """
    logger.info(f"Bắt đầu smart_rag_query với query: {query}")
    
    # Khởi tạo DepartmentInfoTool
    department_tool = DepartmentInfoTool()
    
    # Phân tích truy vấn bằng LLM
    analysis = analyze_query_with_llm(query, session_id)
    if analysis.get("error"):
        logger.error(f"Lỗi khi phân tích truy vấn: {analysis['error']}")
        return "Xin lỗi, đã xảy ra lỗi khi xử lý câu hỏi của bạn."
    
    # Lấy phòng ban từ phân tích hoặc tham số
    detected_department = department or analysis.get("department")
    
    if not detected_department:
        logger.warning("Không phát hiện được phòng ban từ câu hỏi")
        return handle_general_query(query, use_llm=False, session_id=session_id)
    
    # Lấy thông tin phòng ban
    dept_info = department_tool.get_department_info(detected_department)
    if not dept_info or dept_info.get("error"):
        logger.error(f"Không tìm thấy thông tin cho phòng ban: {detected_department}")
        return f"Xin lỗi, không tìm thấy thông tin cho phòng ban: {detected_department}"
    
    # Tạo system prompt và prompt cho LLM
    system_prompt = create_system_prompt(sub_phase, detected_department)
    llm_prompt = create_llm_prompt(query, dept_info, session_id)
    
    # Gọi LLM để xử lý truy vấn
    try:
        response = query_llm(llm_prompt, system_prompt)
        return response
    except Exception as e:
        logger.error(f"Lỗi khi gọi LLM: {str(e)}")
        return "Xin lỗi, đã xảy ra lỗi khi xử lý câu hỏi của bạn."


def traditional_rag_query(query: str, sub_phase: Optional[str] = None, department: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """
    Thực hiện truy vấn RAG truyền thống không sử dụng phân tích LLM
    
    Args:
        query: Câu hỏi của người dùng
        sub_phase: Giai đoạn con (nếu có)
        department: Phòng ban (nếu có)
        session_id: ID của phiên hiện tại (nếu có)
        
    Returns:
        str: Phản hồi cho câu hỏi
    """
    logger.info(f"Bắt đầu traditional_rag_query với query: {query}")
    
    # Khởi tạo DepartmentInfoTool
    department_tool = DepartmentInfoTool()
    
    # Nếu không có phòng ban, trả về thông báo
    if not department:
        return show_department_not_found_message(department_tool, query, False)
    
    # Lấy thông tin phòng ban
    dept_info = department_tool.get_department_info(department)
    if not dept_info or dept_info.get("error"):
        logger.error(f"Không tìm thấy thông tin cho phòng ban: {department}")
        return f"Xin lỗi, không tìm thấy thông tin cho phòng ban: {department}"
    
    # Tạo system prompt và prompt cho LLM
    system_prompt = create_system_prompt(sub_phase, department)
    llm_prompt = create_llm_prompt(query, dept_info, session_id)
    
    # Gọi LLM để xử lý truy vấn
    try:
        response = query_llm(llm_prompt, system_prompt)
        return response
    except Exception as e:
        logger.error(f"Lỗi khi gọi LLM: {str(e)}")
        return "Xin lỗi, đã xảy ra lỗi khi xử lý câu hỏi của bạn."


def show_department_not_found_message(department_tool: DepartmentInfoTool, query: str, use_llm_analysis: bool) -> str:
    """
    Hiển thị thông báo khi không tìm thấy phòng ban
    
    Args:
        department_tool: Instance của DepartmentInfoTool
        query: Câu hỏi của người dùng
        use_llm_analysis: Có sử dụng phân tích LLM hay không
        
    Returns:
        str: Thông báo cho người dùng
    """
    available_departments = department_tool.get_departments()
    logger.warning(f"Không tìm thấy phòng ban. Các phòng ban hiện có: {available_departments}")
    return f"Không tìm thấy phòng ban phù hợp. Vui lòng thử lại với một trong các phòng ban sau: {', '.join(available_departments)}"

def format_response(dept_info: Dict[str, Any], query: str, target_sub_phase: Optional[str] = None) -> str:
    """
    Format phản hồi dựa trên thông tin phòng ban
    
    Args:
        dept_info: Thông tin về phòng ban
        query: Câu hỏi của người dùng
        target_sub_phase: Giai đoạn con cần tập trung (nếu có)
        
    Returns:
        str: Phản hồi đã được format
    """
    try:
        department = dept_info.get('department', 'Không xác định')
        tasks = dept_info.get('task_list', [])
        phases = dept_info.get('phases', [])
        
        if not tasks:
            return f"Không có thông tin về task cho phòng ban {department}"
            
        # Format phản hồi
        response = []
        
        # Thêm thông tin về phòng ban
        response.append(f"Thông tin về phòng ban {department}:")
        
        # Nếu có giai đoạn cụ thể, chỉ hiển thị task trong giai đoạn đó
        if target_sub_phase:
            filtered_tasks = [task for task in tasks if task.get('sub_phase') == target_sub_phase]
            if filtered_tasks:
                response.append(f"\nCác task trong giai đoạn {target_sub_phase}:")
                for task in filtered_tasks:
                    response.append(f"- {task.get('name', 'Không có tên')}")
            else:
                response.append(f"\nKhông có task nào trong giai đoạn {target_sub_phase}")
        else:
            # Hiển thị tất cả các giai đoạn và task
            for phase in phases:
                phase_tasks = [task for task in tasks if task.get('phase') == phase]
                if phase_tasks:
                    response.append(f"\nGiai đoạn {phase}:")
                    for task in phase_tasks:
                        response.append(f"- {task.get('name', 'Không có tên')}")
        
        return "\n".join(response)
        
    except Exception as e:
        logger.error(f"Lỗi khi format phản hồi: {str(e)}")
        return "Đã xảy ra lỗi khi xử lý thông tin phòng ban"

def add_to_chat_history(query: str, response: str, department: Optional[str] = None):
    """
    Thêm một cặp hội thoại vào lịch sử
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_entry = {
        "timestamp": timestamp,
        "query": query,
        "response": response
    }
    if department:
        history_entry["department"] = department
    
    logger.info(f"Đã thêm vào lịch sử hội thoại: Q: {query[:50]}... A: {response[:50]}...")
    return history_entry

def get_chat_history():
    """
    Lấy lịch sử hội thoại
    """
    return []

def clear_chat_history():
    """
    Xóa lịch sử hội thoại
    """
    logger.info("Đã xóa lịch sử hội thoại")

def export_chat_history():
    """
    Xuất lịch sử hội thoại
    """
    logger.info("Đã xuất lịch sử hội thoại")
    return []

def add_to_department_history(query, detected_department=None):
    """
    Thêm vào lịch sử phòng ban
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_entry = {
        "timestamp": timestamp,
        "query": query
    }
    if detected_department:
        history_entry["department"] = detected_department
    
    logger.info(f"Đã thêm vào lịch sử phòng ban: {detected_department} - Q: {query[:50]}...")
    return history_entry

def analyze_query_with_llm(query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Phân tích truy vấn bằng LLM để xác định phòng ban và loại truy vấn
    
    Args:
        query: Câu hỏi của người dùng
        session_id: ID của phiên hiện tại (nếu có)
        
    Returns:
        Dict chứa kết quả phân tích
    """
    try:
        # Tạo system prompt cho phân tích
        system_prompt = """
Bạn là trợ lý AI phân tích nội dung câu hỏi. Nhiệm vụ của bạn là:
1. Xác định phòng ban được đề cập trong câu hỏi
2. Xác định loại truy vấn (chung/cụ thể)

Các phòng ban có thể có:
- Marketing
- Kinh doanh
- Thiết kế
- Thi công
- Kế toán
- Mua hàng
- Dự toán
- Khách hàng
- Team dự án
- 2D

Trả về kết quả dưới dạng JSON với các trường:
{
    "department": "tên phòng ban hoặc null nếu không xác định",
    "query_type": "general hoặc specific",
    "error": false
}
"""
        
        # Tạo prompt cho LLM
        llm_prompt = f"Phân tích câu hỏi sau và trả về kết quả theo format JSON:\n\n{query}"
        
        # Gọi LLM để phân tích
        response = query_llm(llm_prompt, system_prompt, stream=False)
        
        try:
            # Parse kết quả JSON
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            logger.error(f"Không thể parse kết quả JSON từ LLM: {response}")
            return {
                "department": None,
                "query_type": "general",
                "error": True
            }
            
    except Exception as e:
        logger.error(f"Lỗi khi phân tích truy vấn: {str(e)}")
        return {
            "department": None,
            "query_type": "general",
            "error": True
        }
