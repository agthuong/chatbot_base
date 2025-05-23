#!/usr/bin/env python

import asyncio
import websockets
import json
import sys
import os
import re
import logging
import requests
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
import aiohttp
import traceback
from dotenv import load_dotenv

# Thêm thư mục hiện tại vào path để import module gemini_handler
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import từ gemini_handler mới
from gemini_handler import (
    configure_gemini_model, 
    format_history_for_gemini, 
    create_gemini_system_prompt,
    query_gemini_llm_streaming,
    gemini_rag_query,
    retrieve_relevant_content,
    ensure_data_directory,
    initialize_cache,
    create_sample_markdown_data
)

# Tải biến môi trường từ file .env nếu có
load_dotenv()

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("websocket_server.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("websocket_server")

# Import các hàm cần thiết từ chatbot.py nếu cần
try:
    from chatbot import (
        analyze_query_with_llm, 
        query_llm,
        create_system_prompt,
        create_llm_prompt,
        handle_general_query,
        smart_rag_query
    )
except ImportError:
    logger.warning("Không thể import từ chatbot.py. Sử dụng hàm mock.")
    
    def analyze_query_with_llm(query, session_id=None):
        return {"department": None, "query_type": "general", "error": False}
        
    def query_llm(prompt, system_prompt):
        return f"Mock response for: {prompt}"
        
    def create_system_prompt(sub_phase=None, department=None):
        return "System prompt"
        
    def create_llm_prompt(query, dept_info, session_id=None):
        return f"User prompt for query: {query}"
        
    def handle_general_query(query, session_id=None):
        return f"Mock response for general query: {query}"
        
    def smart_rag_query(query, sub_phase=None, department=None, session_id=None):
        return f"Mock response for department-specific query: {query}, department: {department}"

# Cấu hình LLM
LLM_CFG = {
    'model': 'qwen3-30b-a3b',
    'model_server': 'http://192.168.0.43:1234/v1'
}

# Khởi tạo Gemini model khi bắt đầu server
configure_gemini_model()

# Nhập DepartmentInfoTool
try:
    from department_info_tool import DepartmentInfoTool
except ImportError:
    # Tạo mock class nếu không import được
    logger.warning("Không thể import DepartmentInfoTool. Sử dụng mock class.")
    class DepartmentInfoTool:
        def get_department_info(self, department):
            return {
                "department": department,
                "task_count": 0,
                "phases": [],
                "task_list": []
            }
        
        def get_departments(self):
            return ["Marketing", "Kinh doanh", "Kế toán", "Thi công"]

# Lưu trữ phiên hội thoại
sessions = {}
current_session_id = None

def create_session(session_name=None):
    """Tạo phiên hội thoại mới"""
    global current_session_id
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "id": session_id,
        "name": session_name or f"Phiên hội thoại {len(sessions) + 1}",
        "created_at": datetime.now().isoformat(),
        "original_model_history": [],
        "gemini_model_history": [],
        "message_count": 0,
        "enable_thinking": True,
        "current_model_type": "original"
    }
    current_session_id = session_id
    logger.info(f"Đã tạo phiên mới: {session_id} với model mặc định là 'original'")
    return session_id

def get_sessions():
    """Lấy danh sách tất cả các phiên hội thoại"""
    return [
        {
            "id": session_id,
            "name": session["name"],
            "created_at": session["created_at"],
            "message_count": session["message_count"],
            "current_model_type": session.get("current_model_type", "original")
        }
        for session_id, session in sessions.items()
    ]

def get_session_history(session_id, model_type=None):
    """Lấy lịch sử hội thoại của một phiên dựa trên model_type"""
    if session_id in sessions:
        session = sessions[session_id]
        active_model_type = model_type or session.get("current_model_type", "original")
        
        if active_model_type == "gemini":
            return session.get("gemini_model_history", [])
        else:
            return session.get("original_model_history", [])
    return []

def add_to_history(session_id, query, response, model_type, department=None):
    """Thêm một hội thoại vào lịch sử của phiên dựa trên model_type"""
    if session_id not in sessions:
        logger.warning(f"Phiên {session_id} không tồn tại, không thể thêm lịch sử.")
        return
    
    session = sessions[session_id]
    clean_query = query.replace(" /think", "").replace(" /no_think", "").strip()
    
    history_entry = {
        "timestamp": datetime.now().isoformat(),
        "query": clean_query,
        "response": response,
    }
    if department:
        history_entry["department"] = department

    if model_type == "gemini":
        session.setdefault("gemini_model_history", []).append(history_entry)
        logger.info(f"Đã thêm vào gemini_model_history của phiên {session_id}")
    else:
        session.setdefault("original_model_history", []).append(history_entry)
        logger.info(f"Đã thêm vào original_model_history của phiên {session_id}")
        
    session["message_count"] = len(session.get("original_model_history", [])) + len(session.get("gemini_model_history", []))

def delete_session(session_id):
    """Xóa một phiên hội thoại"""
    global current_session_id
    
    if session_id not in sessions:
        return None
    
    # Xóa phiên
    del sessions[session_id]
    
    # Nếu đã xóa phiên hiện tại, chọn phiên khác
    if current_session_id == session_id:
        if sessions:
            current_session_id = list(sessions.keys())[0]
        else:
            current_session_id = create_session("Phiên mặc định")
    
    return current_session_id

def rename_session(session_id, new_name):
    """Đổi tên phiên hội thoại"""
    if session_id in sessions and new_name:
        sessions[session_id]["name"] = new_name
        return True
    return False

def clear_session_history(session_id):
    """Xóa lịch sử hội thoại của một phiên (cả hai model)"""
    if session_id in sessions:
        sessions[session_id]["original_model_history"] = []
        sessions[session_id]["gemini_model_history"] = []
        sessions[session_id]["message_count"] = 0
        logger.info(f"Đã xóa toàn bộ lịch sử của phiên {session_id}")
        return True
    return False

def extract_thinking(text):
    """
    Trích xuất nội dung thinking từ text
    Trả về tuple (phần thinking, phần còn lại)
    """
    thinking_pattern = r'<think>(.*?)</think>'
    thinking_match = re.search(thinking_pattern, text, re.DOTALL)
    
    if thinking_match:
        thinking_content = thinking_match.group(1).strip()
        # Loại bỏ phần thinking khỏi text gốc
        remaining_text = re.sub(thinking_pattern, '', text, flags=re.DOTALL).strip()
        
        # Xử lý các danh sách và khoảng cách dòng trong phần còn lại
        # 1. Đảm bảo dấu gạch ngang (-) ở đầu dòng được bảo toàn
        remaining_text = re.sub(r'(?m)^(\s*)- ', r'\1- ', remaining_text)
        
        # 2. Đảm bảo chỉ có 1 dòng trống liên tiếp
        remaining_text = re.sub(r'\n{3,}', '\n\n', remaining_text)
        
        # 3. Đảm bảo mỗi mục danh sách có khoảng cách phù hợp
        remaining_text = re.sub(r'(?m)^- (.+)\n\n- ', r'- \1\n- ', remaining_text)
        
        logger.info(f"Đã trích xuất thinking ({len(thinking_content)} ký tự) và còn lại {len(remaining_text)} ký tự phản hồi")
        # Ghi lại nội dung phản hồi chuẩn hóa để kiểm tra
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = f"data/logs/llm_response_{timestamp}.txt"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("<think>\n\n</think>\n\n")
            f.write(remaining_text)
        logger.info(f"Đã lưu phản hồi đã xử lý vào: {log_path}")
        
        return thinking_content, remaining_text
    else:
        # Xử lý các danh sách và khoảng cách dòng trong trường hợp không có thẻ thinking
        processed_text = text.strip()
        
        # 1. Đảm bảo dấu gạch ngang (-) ở đầu dòng được bảo toàn
        processed_text = re.sub(r'(?m)^(\s*)- ', r'\1- ', processed_text)
        
        # 2. Đảm bảo chỉ có 1 dòng trống liên tiếp
        processed_text = re.sub(r'\n{3,}', '\n\n', processed_text)
        
        # 3. Đảm bảo mỗi mục danh sách có khoảng cách phù hợp
        processed_text = re.sub(r'(?m)^- (.+)\n\n- ', r'- \1\n- ', processed_text)
        
        # Ghi lại nội dung phản hồi chuẩn hóa để kiểm tra
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = f"data/logs/llm_response_{timestamp}.txt"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("<think>\n\n</think>\n\n")
            f.write(processed_text)
        logger.info(f"Đã lưu phản hồi đã xử lý vào: {log_path}")
        
        return None, processed_text

def filter_thinking_tags(response_text):
    """
    Lọc thẻ <think> và trích xuất JSON từ phản hồi LLM
    
    Args:
        response_text: Phản hồi từ LLM, có thể chứa thẻ <think>
        
    Returns:
        dict: JSON đã được parse hoặc None nếu không tìm thấy JSON hợp lệ
    """
    try:
        logger.info(f"Xử lý phản hồi có thể chứa thẻ <think>: {response_text[:100]}...")
        
        # Kiểm tra xem có thẻ <think> không
        if "<think>" in response_text:
            logger.info("Phát hiện thẻ <think> trong phản hồi, tiến hành trích xuất...")
            thinking_content, remaining_text = extract_thinking(response_text)
            
            # Log thinking content để debug
            if thinking_content:
                logger.info(f"Nội dung thinking: {thinking_content[:100]}...")
                logger.info(f"Nội dung remaining: {remaining_text[:100]}...")
            
            # Tìm JSON trong cả thinking_content và remaining_text
            json_pattern = r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}'
            
            # Thứ tự ưu tiên: thinking_content trước, remaining_text sau
            # Vì thinking content thường sẽ chứa thông tin đánh giá rõ hơn
            for text_to_check in [thinking_content, remaining_text]:
                if not text_to_check:
                    continue
                    
                json_matches = re.findall(json_pattern, text_to_check)
                
                if json_matches:
                    logger.info(f"Tìm thấy {len(json_matches)} mẫu JSON tiềm năng")
                    for potential_json in json_matches:
                        try:
                            result = json.loads(potential_json)
                            # Chỉ trả về JSON có cấu trúc phù hợp
                            if isinstance(result, dict):
                                logger.info(f"Đã trích xuất JSON hợp lệ: {result}")
                                return result
                        except json.JSONDecodeError:
                            continue
        
        # Nếu không có thẻ <think> hoặc không tìm thấy JSON trong thinking content,
        # thử parse toàn bộ chuỗi như JSON
        try:
            result = json.loads(response_text)
            if isinstance(result, dict):
                logger.info(f"Phản hồi là JSON hợp lệ, không cần lọc: {result}")
                return result
        except json.JSONDecodeError:
            pass
            
        # Thử tìm JSON trong toàn bộ chuỗi
        json_pattern = r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}'
        json_matches = re.findall(json_pattern, response_text)
        
        if json_matches:
            for potential_json in json_matches:
                try:
                    result = json.loads(potential_json)
                    if isinstance(result, dict):
                        logger.info(f"Tìm thấy JSON từ regular expression: {result}")
                        return result
                except json.JSONDecodeError:
                    continue
        
        # Không tìm thấy JSON hợp lệ
        logger.warning("Không tìm thấy JSON hợp lệ trong phản hồi")
        return None
        
    except Exception as e:
        logger.error(f"Lỗi khi lọc thẻ <think>: {str(e)}")
        return None

async def query_llm_streaming(prompt, system_prompt):
    """Gửi truy vấn đến LLM và trả về kết quả dạng streaming"""
    url = f"{LLM_CFG['model_server']}/chat/completions"
    
    # Kiểm tra kích thước prompt để giảm độ dài khi quá lớn
    prompt_size = len(prompt)
    system_size = len(system_prompt)
    total_size = prompt_size + system_size
    
    logger.info(f"Kích thước prompt: {prompt_size} ký tự")
    logger.info(f"Kích thước system prompt: {system_size} ký tự") 
    logger.info(f"Tổng kích thước: {total_size} ký tự")
    
    # Kiểm tra ngay từ đầu, nếu prompt quá lớn, thực hiện cắt giảm trước khi gửi
    initial_token_estimate = total_size / 4  # Ước tính thô: 1 token ~ 4 ký tự
    if initial_token_estimate > 3500:  # Giữ dưới ngưỡng an toàn để có không gian cho tokens đầu ra
        logger.warning(f"Prompt ước tính có khoảng {initial_token_estimate:.0f} tokens, vượt quá ngưỡng an toàn")
        reduction_ratio = 3500 / initial_token_estimate
        prompt = prompt[:int(len(prompt) * reduction_ratio)]
        logger.warning(f"Cắt giảm prompt xuống {len(prompt)} ký tự để giữ dưới ngưỡng token")
        # Gửi cảnh báo ngay từ đầu
        warning_message = json.dumps({
            "type": "warning",
            "content": "⚠️ Dữ liệu quá lớn vượt quá giới hạn token. Hệ thống đang cắt giảm dữ liệu, phản hồi có thể thiếu sót."
        })
        yield warning_message
    
    # Biến đánh dấu đã gửi cảnh báo
    warning_sent = initial_token_estimate > 3500  # Đã gửi cảnh báo nếu đã cắt giảm ban đầu
    
    # Áp dụng chiến lược giảm kích thước nếu prompt quá lớn
    original_prompt = prompt
    max_attempts = 3
    attempt = 0
    
    while attempt < max_attempts:
        try:
            logger.info(f"Bắt đầu gọi LLM API (lần thử {attempt + 1}/{max_attempts})")
            
            payload = {
                "model": LLM_CFG['model'],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "stream": False
            }
            
            # Gửi request và nhận response dạng streaming
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"API trả về status 200 OK")
                        async for line in response.content:
                            if line:
                                line_text = line.decode('utf-8').strip()
                                if line_text.startswith('data: ') and line_text != 'data: [DONE]':
                                    json_str = line_text[6:]  # Bỏ 'data: ' prefix
                                    if json_str:
                                        try:
                                            data = json.loads(json_str)
                                            content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                            if content:
                                                yield content
                                        except json.JSONDecodeError:
                                            logger.error(f"Lỗi JSON không hợp lệ: {json_str[:100]}")
                                            continue
                                        except Exception as e:
                                            logger.error(f"Lỗi khi xử lý dữ liệu JSON: {str(e)}, JSON: {json_str[:100]}")
                                            continue
                        logger.info("Streaming hoàn tất thành công")
                        yield "[END]"
                    else:
                        error_text = await response.text()
                        logger.error(f"Lỗi API (status {response.status}): {error_text}")
                        
                        # Kiểm tra xem lỗi có liên quan đến context length không
                        if "context length" in error_text or "token" in error_text or "capacity" in error_text:
                            if attempt < max_attempts - 1:
                                # Gửi thông báo cảnh báo nếu chưa gửi
                                if not warning_sent:
                                    warning_message = json.dumps({
                                        "type": "warning",
                                        "content": "⚠️ Dữ liệu quá lớn vượt quá giới hạn token. Hệ thống đang cắt giảm dữ liệu, phản hồi có thể thiếu sót."
                                    })
                                    yield warning_message
                                    warning_sent = True
                                
                                # Giảm kích thước prompt cho lần thử tiếp theo
                                reduction_ratio = 0.6 - (attempt * 0.1)  # Giảm nhiều hơn mỗi lần thử
                                prompt = original_prompt[:int(len(original_prompt) * reduction_ratio)]
                                logger.warning(f"Giảm kích thước prompt xuống {len(prompt)} ký tự (lần thử {attempt + 1})")
                                
                                # Thử lại với prompt ngắn hơn
                                attempt += 1
                                continue
                            else:
                                logger.error(f"Đã thử cắt giảm {max_attempts} lần nhưng vẫn không thành công")
                                yield f"Xin lỗi, câu hỏi của bạn quá dài và phức tạp. Hệ thống không thể xử lý với giới hạn hiện tại. Vui lòng chia nhỏ câu hỏi hoặc hỏi về một phòng ban/giai đoạn cụ thể hơn."
                                yield "[END]"
                                return
                        else:
                            # Lỗi khác không liên quan đến context length
                            logger.error(f"Lỗi không liên quan đến context length: {error_text}")
                            yield f"Xin lỗi, đã xảy ra lỗi khi xử lý yêu cầu. Vui lòng thử lại sau."
                            yield "[END]"
                            return
            
            # Nếu hoàn thành thành công, thoát khỏi vòng lặp
            break
        except Exception as e:
            logger.error(f"Lỗi khi gọi LLM API: {str(e)}", exc_info=True)
            
            # Kiểm tra xem lỗi có liên quan đến context length không
            if "context length" in str(e) or "token" in str(e) or "capacity" in str(e):
                if attempt < max_attempts - 1:
                    # Gửi thông báo cảnh báo nếu chưa gửi
                    if not warning_sent:
                        warning_message = json.dumps({
                            "type": "warning",
                            "content": "⚠️ Dữ liệu quá lớn vượt quá giới hạn token. Hệ thống đang cắt giảm dữ liệu, phản hồi có thể thiếu sót."
                        })
                        yield warning_message
                        warning_sent = True
                    
                    # Giảm kích thước prompt
                    reduction_ratio = 0.6 - (attempt * 0.1)  # Giảm từ 60% xuống 50%, 40% qua các lần
                    prompt = original_prompt[:int(len(original_prompt) * reduction_ratio)]
                    logger.warning(f"Giảm kích thước prompt xuống {len(prompt)} ký tự (lần thử {attempt + 1}/{max_attempts})")
                    attempt += 1
                else:
                    logger.error(f"Đã thử cắt giảm {max_attempts} lần nhưng vẫn không thành công")
                    yield f"Xin lỗi, câu hỏi của bạn quá dài và phức tạp. Hệ thống không thể xử lý với giới hạn hiện tại. Vui lòng chia nhỏ câu hỏi hoặc hỏi về một phòng ban/giai đoạn cụ thể hơn."
                    yield "[END]"
                    return
            else:
                # Lỗi khác không liên quan đến context length
                logger.error(f"Lỗi không liên quan đến context length: {str(e)}")
                yield f"Xin lỗi, đã xảy ra lỗi khi xử lý yêu cầu: {str(e)}. Vui lòng thử lại sau."
                yield "[END]"
                return

def add_history_to_prompt(prompt, session_id):
    """
    Thêm lịch sử tin nhắn gần nhất vào prompt
    
    Args:
        prompt: Prompt gốc
        session_id: ID phiên hiện tại
    
    Returns:
        str: Prompt đã thêm lịch sử
    """
    if not session_id or session_id not in sessions:
        logger.warning(f"Không thể thêm lịch sử: session_id={session_id} không hợp lệ")
        return prompt
    
    # Lấy 5 tin nhắn gần nhất
    history = sessions[session_id]["original_model_history"]
    if not history or len(history) == 0:
        logger.info("Không có lịch sử tin nhắn cho phiên này")
        return prompt
        
    recent_messages = history[-5:] if len(history) >= 5 else history
    
    # Tạo phần lịch sử tin nhắn
    history_text = "Lịch sử tin nhắn:\n"
    for msg in recent_messages:
        query = msg.get("query", "")
        
        # Loại bỏ hậu tố /think và /no_think từ câu query
        query = query.replace(" /think", "").replace(" /no_think", "").strip()
        
        # Chỉ hiển thị tin nhắn người dùng, không hiển thị phòng ban
        history_text += f"Người dùng: {query}\n"
    
    # Kiểm tra nếu prompt đã có phần "Lịch sử tin nhắn"
    if "Lịch sử tin nhắn:" in prompt:
        # Không thay đổi prompt nếu đã có phần lịch sử
        logger.info("Prompt đã có phần lịch sử tin nhắn, giữ nguyên")
        return prompt
    
    # Thêm lịch sử vào đầu prompt
    logger.info(f"Đã thêm {len(recent_messages)} tin nhắn gần nhất vào prompt")
    
    # Lưu lịch sử tin nhắn vào file log
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    history_log_path = f"data/logs/history_prompt_{timestamp}.txt"
    os.makedirs(os.path.dirname(history_log_path), exist_ok=True)
    
    with open(history_log_path, 'w', encoding='utf-8') as f:
        f.write(f"=== LỊCH SỬ TIN NHẮN CHO SESSION {session_id} ===\n\n")
        f.write(f"{history_text}\n\n")
        f.write(f"=== PROMPT GỐC ===\n\n")
        f.write(f"{prompt}\n\n")
        f.write(f"=== PROMPT ĐẦY ĐỦ ===\n\n")
        f.write(f"{history_text}\n{prompt}")
    
    logger.info(f"Đã lưu lịch sử tin nhắn và prompt vào file: {history_log_path}")
    
    return f"{history_text}\n{prompt}"

async def handle_gemini_request(websocket, content, session_id):
    """
    Xử lý yêu cầu dùng model Gemini
    
    Args:
        websocket: WebSocket connection
        content: Nội dung câu hỏi
        session_id: ID phiên
    """
    try:
        logger.info(f"=== BẮT ĐẦU XỬ LÝ YÊU CẦU GEMINI ===")
        logger.info(f"Xử lý yêu cầu Gemini: '{content[:100]}...' (session_id={session_id})")
        
        # Đảm bảo thư mục data tồn tại
        ensure_data_directory()
        
        # Đảm bảo file dữ liệu tồn tại, nhưng không lưu cache
        initialize_cache()
        logger.info("Đã đảm bảo thư mục và file dữ liệu tồn tại")
        
        # Chuẩn bị câu hỏi - chỉ loại bỏ hậu tố /think và /no_think ở cuối nếu có
        clean_query = content
        if clean_query.endswith(" /think"):
            clean_query = clean_query[:-7].strip()
        elif clean_query.endswith(" /no_think"):
            clean_query = clean_query[:-10].strip()
            
        logger.info(f"Câu hỏi gốc: '{content}', câu hỏi sau khi làm sạch: '{clean_query}'")
        
        # Lấy lịch sử hội thoại của Gemini
        gemini_history = get_session_history(session_id, "gemini")
        
        # Format lịch sử theo định dạng Gemini yêu cầu
        formatted_gemini_history = format_history_for_gemini(gemini_history)
        
        # Truy xuất nội dung RAG trực tiếp từ nội dung câu hỏi
        # Không cần phân tích phòng ban vì RAG mới hoạt động dựa trên file markdown
        # Luôn đọc lại dữ liệu từ file mỗi lần gọi
        logger.info("Truy xuất nội dung RAG từ file...")
        rag_content = retrieve_relevant_content(clean_query)
        
        # Kiểm tra RAG content kỹ lưỡng
        if rag_content:
            logger.info(f"ĐÃ NHẬN RAG CONTENT, độ dài: {len(rag_content)} ký tự")
            logger.info(f"Đoạn đầu RAG content: {rag_content[:100]}...")
        else:
            logger.warning("KHÔNG NHẬN ĐƯỢC RAG CONTENT từ retrieve_relevant_content!")
            
        logger.info(f"Đã truy xuất dữ liệu RAG: {len(rag_content) if rag_content else 0} ký tự")
        
        # Thông báo đang xử lý cho client
        processing_msg = json.dumps({
            "role": "assistant",
            "content": "",  # Bắt đầu với nội dung trống
            "model_type": "gemini",
            "session_id": session_id
        })
        await websocket.send(processing_msg)
        
        # Biến để tích lũy phản hồi đầy đủ
        full_response = ""
        
        # Biến lưu trữ cảnh báo nếu có
        warning_message = None
        
        # Lưu log chi tiết về yêu cầu
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_log_file = os.path.join(log_dir, f"gemini_request_{timestamp}.txt")
        
        try:
            with open(request_log_file, "w", encoding="utf-8") as f:
                f.write("=== GEMINI REQUEST DETAILS ===\n\n")
                f.write(f"Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"Query: '{clean_query}'\n\n")
                f.write(f"RAG content tồn tại: {'Có' if rag_content else 'Không'}\n")
                if rag_content:
                    f.write(f"Độ dài RAG content: {len(rag_content)} ký tự\n")
                    f.write("Đoạn đầu RAG content:\n")
                    f.write(f"{rag_content[:500] if rag_content else 'Không có nội dung'}...\n\n")
                f.write(f"History: {'Có' if formatted_gemini_history else 'Không'}\n")
                if formatted_gemini_history:
                    f.write(f"History items: {len(formatted_gemini_history)}\n\n")
            logger.info(f"Đã lưu chi tiết yêu cầu vào: {request_log_file}")
        except Exception as e:
            logger.error(f"Lỗi khi lưu chi tiết yêu cầu: {str(e)}")
        
        logger.info("Gọi gemini_rag_query với RAG content...")
        # Gọi Gemini API với cơ chế streaming và RAG
        async for chunk in gemini_rag_query(
            clean_query,
            rag_content=rag_content,
            formatted_history=formatted_gemini_history
        ):
            if chunk == "[END]":
                # Kết thúc streaming
                break
                
            try:
                # Parse chunk JSON
                chunk_data = json.loads(chunk)
                
                # Kiểm tra lỗi
                if "error" in chunk_data:
                    error_msg = chunk_data["error"]
                    logger.error(f"Gemini API error: {error_msg}")
                    
                    # Gửi thông báo lỗi cho client
                    error_response = json.dumps({
                        "role": "assistant",
                        "content": f"❌ Lỗi từ Gemini API: {error_msg}",
                        "model_type": "gemini",
                        "session_id": session_id
                    })
                    await websocket.send(error_response)
                    return
                
                # Kiểm tra cảnh báo
                if "warning" in chunk_data:
                    warning_message = chunk_data["warning"]
                    logger.warning(f"Cảnh báo từ Gemini RAG: {warning_message}")
                    
                    # Gửi thông báo cảnh báo cho client
                    warning_response = json.dumps({
                        "role": "assistant",
                        "content": f"⚠️ {warning_message}",
                        "model_type": "gemini",
                        "session_id": session_id,
                        "is_warning": True
                    })
                    await websocket.send(warning_response)
                    continue  # Bỏ qua chunk này, không thêm vào phản hồi đầy đủ
                
                # Xử lý nội dung chunk
                if "content" in chunk_data:
                    chunk_content = chunk_data["content"]
                    full_response += chunk_content
                    
                    # Gửi nội dung hiện tại cho client
                    update_msg = json.dumps({
                        "role": "assistant",
                        "content": full_response,  # Gửi toàn bộ nội dung tích lũy
                        "model_type": "gemini",
                        "session_id": session_id
                    })
                    await websocket.send(update_msg)
            except json.JSONDecodeError:
                logger.warning(f"Không thể parse chunk JSON: {chunk}")
        
        # Lưu vào lịch sử sau khi hoàn thành
        if full_response:
            add_to_history(session_id, clean_query, full_response, "gemini")
            logger.info(f"Đã thêm hội thoại Gemini vào lịch sử: {session_id}")
            
            # Gửi thông báo hoàn thành
            complete_msg = json.dumps({
                "role": "assistant",
                "content": full_response,
                "model_type": "gemini",
                "session_id": session_id,
                "status": "complete"
            })
            await websocket.send(complete_msg)
            
    except Exception as e:
        error_msg = f"Lỗi khi xử lý yêu cầu Gemini: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        error_response = json.dumps({
            "role": "assistant",
            "content": f"❌ Đã xảy ra lỗi: {error_msg}",
            "model_type": "gemini",
            "session_id": session_id
        })
        await websocket.send(error_response)

# Cập nhật process_streaming_response để phân luồng theo model_type
async def process_streaming_response(websocket, content, detected_department=None, session_id=None, model_type=None):
    """
    Xử lý phản hồi theo phương thức streaming, phân luồng theo model_type
    
    Args:
        websocket: WebSocket connection
        content: Nội dung tin nhắn từ người dùng
        detected_department: Phòng ban đã được phát hiện (tùy chọn)
        session_id: ID phiên hiện tại (tùy chọn)
        model_type: Loại model sử dụng ("original" hoặc "gemini") (tùy chọn)
    """
    try:
        global current_session_id
        
        # Đảm bảo session_id luôn có giá trị
        if not session_id:
            session_id = current_session_id
            logger.info(f"Session ID không được cung cấp, sử dụng current_session_id: {session_id}")
        
        # Đảm bảo phiên tồn tại
        if session_id not in sessions:
            session_id = create_session("Phiên tự động")
            current_session_id = session_id
            logger.info(f"Tạo phiên mới vì session_id không tồn tại: {session_id}")
        
        # Xác định model_type nếu không được cung cấp
        if not model_type:
            model_type = sessions[session_id].get("current_model_type", "original")
            logger.info(f"Model type không được cung cấp, sử dụng model mặc định của phiên: {model_type}")
        else:
            # Cập nhật model_type trong session
            sessions[session_id]["current_model_type"] = model_type
            logger.info(f"Cập nhật current_model_type của phiên {session_id}: {model_type}")
            
        logger.info(f"Xử lý streaming response cho: '{content}', phòng ban: {detected_department}, session_id: {session_id}, model_type: {model_type}")
        
        # Xử lý theo model_type
        if model_type == "gemini":
            # Sử dụng luồng xử lý dành riêng cho Gemini - không có thinking, không cần phân tích phòng ban
            await handle_gemini_request(websocket, content, session_id)
        else:
            # Model cũ - giữ lại logic hiện tại
            # Lấy trạng thái thinking từ session
            enable_thinking = sessions[session_id].get("enable_thinking", True)
            
            # Tạo bản sao của nội dung gốc để xử lý
            query = content
            query_for_model = content  # Nội dung sẽ gửi đến mô hình, giữ nguyên hậu tố
            
            # Xác định chế độ thinking dựa trên hậu tố của tin nhắn hiện tại
            if content.endswith('/think'):
                # Cập nhật trạng thái thinking trong session
                sessions[session_id]["enable_thinking"] = True
                enable_thinking = True
                # Loại bỏ hậu tố chỉ khỏi query hiển thị, không phải query gửi đến mô hình
                query = content[:-7].strip()  # Loại bỏ hậu tố cho hiển thị trong lịch sử
                logger.info(f"Phát hiện lệnh /think, bật chế độ thinking cho: {query}")
            elif content.endswith('/no_think'):
                # Cập nhật trạng thái thinking trong session
                sessions[session_id]["enable_thinking"] = False
                enable_thinking = False
                # Loại bỏ hậu tố chỉ khỏi query hiển thị, không phải query gửi đến mô hình
                query = content[:-10].strip()  # Loại bỏ hậu tố cho hiển thị trong lịch sử
                logger.info(f"Phát hiện lệnh /no_think, tắt chế độ thinking cho: {query}")
            else:
                # Không có hậu tố, sử dụng trạng thái trong session
                query = content
            
            logger.info(f"Xử lý streaming response với model cũ. Query: '{query}', Mode thinking: {enable_thinking}")
            
            # Thêm lịch sử tin nhắn vào prompt - chỉ lấy lịch sử của model cũ
            content_with_history = add_history_to_prompt(query, session_id)
            
            # Phân tích câu hỏi để xác định phòng ban nếu chưa có
            if not detected_department:
                # Phân tích câu hỏi
                analysis_result = analyze_query_with_llm(content_with_history, session_id)
                
                # Xử lý trường hợp LLM trả về thẻ <think> thay vì JSON
                if isinstance(analysis_result, str) and "<think>" in analysis_result:
                    logger.warning("Phát hiện thẻ <think> trong phản hồi của analyze_query_with_llm")
                    # Sử dụng filter_thinking_tags để lọc thẻ <think> và trích xuất JSON
                    filtered_result = filter_thinking_tags(analysis_result)
                    if filtered_result:
                        analysis_result = filtered_result
                    else:
                        # Nếu không tìm thấy JSON, sử dụng kết quả mặc định
                        logger.warning("Không thể trích xuất JSON từ phản hồi có thẻ <think>, sử dụng kết quả mặc định")
                        analysis_result = {
                            "department": None,
                            "query_type": "general",
                            "error": False
                        }
                
                # Kiểm tra xem analysis_result có phải là None không
                if analysis_result is None:
                    logger.warning("analyze_query_with_llm trả về None. Sử dụng giá trị mặc định.")
                    analysis_result = {"department": None, "query_type": "general", "error": False}
            else:
                # Sử dụng kết quả phân tích trước đó
                analysis_result = {"department": detected_department, "query_type": "department_specific", "error": False}
            
            # Kiểm tra lỗi nhiều phòng ban
            if analysis_result.get("error", False):
                error_message = analysis_result.get("error_message", "Phát hiện nhiều phòng ban trong một câu hỏi")
                error_response = json.dumps({
                    "role": "assistant",
                    "content": f"❌ {error_message}. Vui lòng chỉ hỏi về một phòng ban mỗi lần.",
                    "thinking": None,
                    "warning": error_message,
                    "session_id": session_id,
                    "model_type": "original"
                })
                await websocket.send(error_response)
                return
                
            # Xác định phòng ban từ kết quả phân tích
            department = analysis_result.get("department")
            query_type = analysis_result.get("query_type")
            
            # Đảm bảo luôn gửi hậu tố thinking đúng đến mô hình
            if enable_thinking and not query_for_model.endswith('/think'):
                query_for_model = query_for_model + ' /think'
            elif not enable_thinking and not query_for_model.endswith('/no_think'):
                query_for_model = query_for_model + ' /no_think'
            
            logger.info(f"Phân tích câu hỏi: Phòng ban={department}, Loại={query_type}, Thinking={enable_thinking}")
            logger.info(f"Query thực tế gửi đến mô hình: {query_for_model}")
            
            # Xử lý phản hồi dạng streaming
            if query_type == "department_specific" and department:
                # Câu hỏi về phòng ban cụ thể
                logger.info(f"Câu hỏi về phòng ban cụ thể: {department}, chế độ thinking: {enable_thinking}")
                
                # Sử dụng query_for_model để đảm bảo hậu tố được gửi đến mô hình
                response_content = smart_rag_query(query_for_model, None, department, session_id)
                
                # Kiểm tra và xử lý thẻ <think> nếu có
                thinking_part = None
                if "<think>" in response_content:
                    # Trích xuất phần thinking và phần còn lại
                    thinking_part, response_content = extract_thinking(response_content)
                    logger.info(f"Đã trích xuất phần thinking ({len(thinking_part) if thinking_part else 0} ký tự) từ phản hồi")
                
                # Lưu vào lịch sử hội thoại - chỉ lưu phần query đã loại bỏ hậu tố
                if session_id and session_id in sessions:
                    add_to_history(session_id, query, response_content, "original", department)
                    logger.info(f"Đã lưu hội thoại phòng ban {department} vào lịch sử của session {session_id}")
                else:
                    logger.warning(f"Không thể lưu hội thoại phòng ban vào lịch sử: session_id={session_id}")
                
                # Gửi phản hồi cuối cùng với thinking nếu có
                final_message = json.dumps({
                    "role": "assistant",
                    "content": response_content,
                    "thinking": thinking_part if enable_thinking else None,
                    "session_id": session_id,
                    "model_type": "original"  # Thêm model_type
                })
                await websocket.send(final_message)
                
            elif query_type == "general":
                # Câu hỏi chung về quy trình
                logger.info(f"Câu hỏi chung, chế độ thinking: {enable_thinking}")
                
                # Sử dụng query_for_model để đảm bảo hậu tố được gửi đến mô hình
                response_content = handle_general_query(query_for_model, session_id=session_id)
                
                # Kiểm tra và xử lý thẻ <think> nếu có
                thinking_part = None
                if "<think>" in response_content:
                    # Trích xuất phần thinking và phần còn lại
                    thinking_part, response_content = extract_thinking(response_content)
                    logger.info(f"Đã trích xuất phần thinking ({len(thinking_part) if thinking_part else 0} ký tự) từ phản hồi")
                
                # Lưu vào lịch sử hội thoại - chỉ lưu phần query đã loại bỏ hậu tố
                if session_id and session_id in sessions:
                    add_to_history(session_id, query, response_content, "original", None)
                    logger.info(f"Đã lưu hội thoại chung vào lịch sử của session {session_id}")
                else:
                    logger.warning(f"Không thể lưu hội thoại chung vào lịch sử: session_id={session_id}")
                
                # Gửi phản hồi cuối cùng với thinking nếu có
                final_message = json.dumps({
                    "role": "assistant",
                    "content": response_content,
                    "thinking": thinking_part if enable_thinking else None,
                    "session_id": session_id,  # Thêm session_id vào message
                    "model_type": "original"   # Thêm model_type
                })
                await websocket.send(final_message)
        
    except Exception as e:
        logger.error(f"Lỗi khi xử lý streaming response: {str(e)}")
        traceback.print_exc()
        
        # Gửi phản hồi lỗi
        error_response = json.dumps({
            "role": "assistant",
            "content": f"❌ Đã xảy ra lỗi khi xử lý câu hỏi: {str(e)}",
            "thinking": None,
            "warning": f"Lỗi: {str(e)}",
            "session_id": session_id,  # Thêm session_id vào message
            "model_type": model_type or "original"  # Thêm model_type
        })
        await websocket.send(json.dumps(error_response))

async def handle_action(websocket, action, data):
    """Xử lý các hành động WebSocket"""
    global current_session_id
    
    try:
        if action == "get_sessions":
            # Đảm bảo luôn có ít nhất một phiên
            if not sessions:
                current_session_id = create_session("Phiên mặc định")
                logger.info(f"Không có phiên nào, tạo phiên mặc định: {current_session_id}")
            else:
                logger.info(f"Có {len(sessions)} phiên, phiên hiện tại: {current_session_id}")
            
            # Tạo phản hồi với đầy đủ thông tin
            response = {
                "action": "get_sessions_response",
                "status": "success",
                "sessions": get_sessions(),  # Đã bao gồm current_model_type cho mỗi session
                "current_session_id": current_session_id
            }
            logger.info(f"Gửi danh sách {len(get_sessions())} phiên cho client")
            await websocket.send(json.dumps(response))
            
        elif action == "create_session":
            session_name = data.get("session_name", "Phiên mới")
            # Có thể nhận model_type khi tạo phiên mới
            model_type = data.get("model_type", "original")
            
            session_id = create_session(session_name)
            current_session_id = session_id
            
            # Cập nhật model_type nếu khác mặc định
            if model_type != "original":
                sessions[session_id]["current_model_type"] = model_type
                logger.info(f"Đặt model_type={model_type} cho phiên mới {session_id}")
            
            response = {
                "action": "create_session_response",
                "status": "success",
                "session_id": session_id,
                "model_type": model_type
            }
            await websocket.send(json.dumps(response))
            
        elif action == "set_session_model_type":
            # Action mới: thiết lập model_type cho session
            session_id = data.get("session_id", current_session_id)
            model_type = data.get("model_type")
            
            if not model_type or model_type not in ["original", "gemini"]:
                response = {
                    "action": "set_session_model_type_response",
                    "status": "error",
                    "error": "model_type không hợp lệ. Phải là 'original' hoặc 'gemini'."
                }
                await websocket.send(json.dumps(response))
                return
                
            if session_id and session_id in sessions:
                # Nếu chuyển sang model Gemini, đảm bảo dữ liệu RAG được chuẩn bị
                if model_type == "gemini":
                    # Đảm bảo thư mục data tồn tại
                    ensure_data_directory()
                    
                    # Đảm bảo file dữ liệu tồn tại, nhưng không lưu cache
                    if initialize_cache():
                        logger.info("Đã đảm bảo thư mục và file dữ liệu tồn tại")
                    else:
                        logger.warning("Không thể đảm bảo file dữ liệu tồn tại")
                        # Thử tạo file mẫu
                        logger.info("Thử tạo file mẫu...")
                        create_sample_markdown_data()
                        initialize_cache()  # Thử lại một lần nữa
                
                # Lấy model_type hiện tại của phiên
                current_model_type = sessions[session_id].get("current_model_type", "original")
                
                # Kiểm tra xem phiên hiện tại có lịch sử tin nhắn của model cũ không
                current_history = []
                if current_model_type == "original":
                    current_history = sessions[session_id].get("original_model_history", [])
                else:
                    current_history = sessions[session_id].get("gemini_model_history", [])
                
                # Nếu phiên không có tin nhắn hoặc model_type vẫn giữ nguyên, cập nhật model_type bình thường
                if len(current_history) == 0 or current_model_type == model_type:
                    # Cập nhật model_type cho session hiện tại
                    sessions[session_id]["current_model_type"] = model_type
                    logger.info(f"Đã cập nhật model_type={model_type} cho phiên {session_id} (không có lịch sử)")
                    
                    # Lấy lịch sử tương ứng với model_type mới
                    history = get_session_history(session_id, model_type)
                    
                    response = {
                        "action": "set_session_model_type_response",
                        "status": "success",
                        "session_id": session_id,
                        "model_type": model_type,
                        "history": history  # Gửi lịch sử tin nhắn tương ứng với model mới
                    }
                    await websocket.send(json.dumps(response))
                else:
                    # Trường hợp phiên có lịch sử và đổi model, tạo session mới và chuyển qua đó
                    session_name = f"{sessions[session_id]['name']} - {model_type}"
                    new_session_id = create_session(session_name)
                    
                    # Thiết lập model_type cho session mới
                    sessions[new_session_id]["current_model_type"] = model_type
                    
                    # Cập nhật session hiện tại
                    current_session_id = new_session_id
                    
                    logger.info(f"Đã tạo phiên mới {new_session_id} với model_type={model_type} từ phiên {session_id}")
                    
                    # Lấy lịch sử trống của model mới
                    history = []
                    
                    response = {
                        "action": "set_session_model_type_response",
                        "status": "success",
                        "session_id": new_session_id,  # Trả về session_id mới
                        "model_type": model_type,
                        "history": history,
                        "new_session": True           # Đánh dấu rằng đã tạo session mới
                    }
                    await websocket.send(json.dumps(response))
                    
                    # Thông báo cho client biết phiên hiện tại đã thay đổi
                    session_updated = {
                        "action": "session_updated",
                        "status": "success",
                        "current_session_id": new_session_id,
                        "model_type": model_type,
                        "history": history
                    }
                    await websocket.send(json.dumps(session_updated))
            else:
                response = {
                    "action": "set_session_model_type_response",
                    "status": "error",
                    "error": "Phiên không tồn tại"
                }
                await websocket.send(json.dumps(response))
            
        elif action == "get_thinking":
            # Xử lý yêu cầu lấy thinking content
            query = data.get('query', '')
            session_id = data.get('session_id', current_session_id)
            request_id = data.get('request_id')  # Lấy request_id nếu có
            
            # Kiểm tra model_type của session
            model_type = sessions[session_id].get("current_model_type", "original") if session_id in sessions else "original"
            
            # Nếu là Gemini, không hỗ trợ thinking
            if model_type == "gemini":
                response = {
                    "action": "get_thinking_response",
                    "status": "error",
                    "error": "Model Gemini không hỗ trợ chức năng thinking",
                    "request_id": request_id,
                    "session_id": session_id,
                    "model_type": "gemini"
                }
                await websocket.send(json.dumps(response))
                return
            
            # Kiểm tra session_id có tồn tại không
            if not session_id or session_id not in sessions:
                logger.warning(f"Session {session_id} không tồn tại, sử dụng session hiện tại")
                session_id = current_session_id
                
                # Nếu vẫn không có session nào
                if not session_id or session_id not in sessions:
                    # Tạo session mới
                    session_id = create_session("Phiên tự động")
                    current_session_id = session_id
                    logger.info(f"Đã tạo session mới {session_id} vì không tìm thấy session hợp lệ")
            
            await handle_thinking_request(websocket, query, session_id, request_id)
            
        elif action == "switch_session":
            session_id = data.get("session_id")
            if session_id and session_id in sessions:
                current_session_id = session_id
                
                # Lấy model_type của phiên mới
                model_type = sessions[session_id].get("current_model_type", "original")
                
                # Lấy lịch sử tương ứng với model_type của phiên đó
                history = get_session_history(session_id, model_type)
                
                response = {
                    "action": "switch_session_response",
                    "status": "success",
                    "session_id": session_id,
                    "model_type": model_type,
                    "history": history  # Gửi lịch sử tin nhắn của phiên mới và model đang dùng
                }
                await websocket.send(json.dumps(response))
                
                # Thông báo cho tất cả clients về việc phiên được cập nhật
                session_updated = {
                    "action": "session_updated",
                    "status": "success",
                    "current_session_id": current_session_id,
                    "model_type": model_type,
                    "history": history
                }
                await websocket.send(json.dumps(session_updated))
            else:
                response = {
                    "action": "switch_session_response",
                    "status": "error",
                    "error": "Phiên không tồn tại"
                }
                await websocket.send(json.dumps(response))
                
        elif action == "delete_session":
            session_id = data.get("session_id")
            if session_id and session_id in sessions:
                new_session_id = delete_session(session_id)
                
                if new_session_id:
                    # Lấy model_type của phiên mới
                    new_model_type = sessions[new_session_id].get("current_model_type", "original")
                    # Lấy lịch sử của phiên mới
                    history = get_session_history(new_session_id, new_model_type)
                else:
                    new_model_type = "original"
                    history = []
                
                response = {
                    "action": "delete_session_response",
                    "status": "success",
                    "new_session_id": new_session_id,
                    "model_type": new_model_type,
                    "history": history  # Gửi lịch sử tin nhắn của phiên mới
                }
                await websocket.send(json.dumps(response))
                
                # Thông báo cho tất cả clients về việc phiên được cập nhật
                if new_session_id:
                    session_updated = {
                        "action": "session_updated",
                        "status": "success",
                        "current_session_id": new_session_id,
                        "model_type": new_model_type,
                        "history": history
                    }
                    await websocket.send(json.dumps(session_updated))
            else:
                response = {
                    "action": "delete_session_response",
                    "status": "error",
                    "error": "Phiên không tồn tại"
                }
                await websocket.send(json.dumps(response))
                
        elif action == "rename_session":
            session_id = data.get("session_id")
            new_name = data.get("new_name")
            
            if session_id and session_id in sessions and new_name:
                success = rename_session(session_id, new_name)
                
                response = {
                    "action": "rename_session_response",
                    "status": "success" if success else "error",
                    "session_id": session_id
                }
                await websocket.send(json.dumps(response))
            else:
                response = {
                    "action": "rename_session_response",
                    "status": "error",
                    "error": "Phiên không tồn tại hoặc tên không hợp lệ"
                }
                await websocket.send(json.dumps(response))
                
        elif action == "get_history":
            session_id = data.get("session_id", current_session_id)
            # Thêm tham số model_type để có thể lấy lịch sử cụ thể cho model
            model_type = data.get("model_type")
            
            if session_id and session_id in sessions:
                # Nếu không có model_type cụ thể, lấy theo model hiện tại của phiên
                if not model_type:
                    model_type = sessions[session_id].get("current_model_type", "original")
                    
                history = get_session_history(session_id, model_type)
                
                response = {
                    "action": "get_history_response",
                    "status": "success",
                    "history": history,
                    "model_type": model_type
                }
                await websocket.send(json.dumps(response))
            else:
                response = {
                    "action": "get_history_response",
                    "status": "error",
                    "error": "Phiên không tồn tại"
                }
                await websocket.send(json.dumps(response))
                
        elif action == "clear_history":
            session_id = data.get("session_id", current_session_id)
            
            if session_id and session_id in sessions:
                success = clear_session_history(session_id)
                
                # Lấy model hiện tại của phiên
                model_type = sessions[session_id].get("current_model_type", "original")
                
                response = {
                    "action": "clear_history_response",
                    "status": "success" if success else "error",
                    "session_id": session_id,
                    "model_type": model_type
                }
                await websocket.send(json.dumps(response))
                
                # Thông báo cho tất cả clients về việc phiên được cập nhật
                session_updated = {
                    "action": "session_updated",
                    "status": "success",
                    "current_session_id": session_id,
                    "model_type": model_type,
                    "history": []  # Lịch sử đã bị xóa
                }
                await websocket.send(json.dumps(session_updated))
            else:
                response = {
                    "action": "clear_history_response",
                    "status": "error",
                    "error": "Phiên không tồn tại"
                }
                await websocket.send(json.dumps(response))
                
        else:
            response = {
                "action": "unknown_action",
                "status": "error",
                "error": f"Hành động không được hỗ trợ: {action}"
            }
            await websocket.send(json.dumps(response))
            
    except Exception as e:
        logger.error(f"Lỗi khi xử lý hành động {action}: {str(e)}", exc_info=True)
        response = {
            "action": f"{action}_response",
            "status": "error",
            "error": str(e)
        }
        await websocket.send(json.dumps(response))

async def handle_message(websocket):
    """Xử lý các tin nhắn WebSocket"""
    global current_session_id
    
    # Đảm bảo luôn có ít nhất một phiên
    if not sessions:
        current_session_id = create_session("Phiên mặc định")
    
    # Gửi dữ liệu khởi tạo cho client khi kết nối mới được thiết lập
    try:
        # Lấy model_type hiện tại của phiên
        model_type = "original"
        if current_session_id and current_session_id in sessions:
            model_type = sessions[current_session_id].get("current_model_type", "original")
            
        # Lấy lịch sử tương ứng với model_type
        history = get_session_history(current_session_id, model_type) if current_session_id else []
        
        init_data = {
            "action": "init_session_data",
            "status": "success",
            "sessions": get_sessions(),
            "current_session_id": current_session_id,
            "model_type": model_type,
            "history": history
        }
        await websocket.send(json.dumps(init_data))
        logger.info(f"Đã gửi dữ liệu khởi tạo với current_session_id={current_session_id}, model_type={model_type}")
    except Exception as e:
        logger.error(f"Lỗi khi gửi dữ liệu khởi tạo: {str(e)}", exc_info=True)
    
    try:
        async for message in websocket:
            # Kiểm tra xem message có phải là JSON hay không
            try:
                data = json.loads(message)
                
                # Kiểm tra xem có phải là action không
                if 'action' in data:
                    # Chuyển xử lý cho hàm handle_action
                    await handle_action(websocket, data['action'], data)
                else:
                    # Nếu không phải là action, xử lý như tin nhắn thường
                    logger.info(f"Nhận tin nhắn dạng JSON: {message[:100]}...")
                    
                    # Lấy các thông tin từ JSON
                    content = data.get('content', '')
                    session_id = data.get('session_id', current_session_id)
                    model_type = data.get('model_type')
                    
                    # Đảm bảo session_id tồn tại
                    if not session_id or session_id not in sessions:
                        session_id = current_session_id
                        if not session_id or session_id not in sessions:
                            session_id = create_session("Phiên tự động")
                            current_session_id = session_id
                    
                    # Nếu model_type không được cung cấp, sử dụng từ phiên hiện tại
                    if not model_type:
                        model_type = sessions[session_id].get("current_model_type", "original")
                        logger.info(f"model_type không được cung cấp, sử dụng từ phiên: {model_type}")
                    else:
                        # Cập nhật model_type cho phiên
                        sessions[session_id]["current_model_type"] = model_type
                        logger.info(f"Cập nhật model_type={model_type} cho phiên {session_id}")
                    
                    # Gọi hàm xử lý streaming với model_type
                    await process_streaming_response(websocket, content, None, session_id, model_type)
                    
            except json.JSONDecodeError:
                # Không phải JSON, xử lý như tin nhắn văn bản thông thường
                logger.info(f"Nhận tin nhắn thường (không phải JSON): {message[:100]}...")
                
                # Sử dụng phiên hiện tại và model_type tương ứng
                session_id = current_session_id
                
                if session_id and session_id in sessions:
                    model_type = sessions[session_id].get("current_model_type", "original")
                else:
                    # Nếu không có phiên hiện tại, tạo mới
                    session_id = create_session("Phiên tự động")
                    current_session_id = session_id
                    model_type = "original"
                
                logger.info(f"Xử lý tin nhắn thường với model_type={model_type}, session_id={session_id}")
                await process_streaming_response(websocket, message, None, session_id, model_type)
    
    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket connection closed")
    except Exception as e:
        logger.error(f"Lỗi trong handle_message: {str(e)}", exc_info=True)

async def main():
    """Khởi động server WebSocket"""
    # Đảm bảo thư mục log tồn tại
    os.makedirs('data/logs', exist_ok=True)
    
    # Đảm bảo thư mục data tồn tại
    ensure_data_directory()
    
    # Đảm bảo file dữ liệu tồn tại, nhưng không lưu cache
    if initialize_cache():
        logger.info("Đã đảm bảo file dữ liệu tồn tại khi khởi động server")
    else:
        logger.warning("Không thể đảm bảo file dữ liệu tồn tại khi khởi động server")
        
        # Nếu không thể khởi tạo, thử tạo file mẫu
        logger.info("Thử tạo file mẫu...")
        create_sample_markdown_data()
        if initialize_cache():
            logger.info("Đã đảm bảo file dữ liệu tồn tại sau khi tạo file mẫu")
    
    # Khởi tạo Gemini Model
    if not configure_gemini_model():
        logger.warning("Không thể khởi tạo Gemini Model. Chức năng Gemini sẽ không khả dụng.")
    else:
        logger.info("Đã khởi tạo Gemini Model thành công.")

    # Địa chỉ và port của server
    host = "0.0.0.0"  # Lắng nghe trên tất cả các interface
    port = 8090       # Cổng mà UI hiện tại đang kết nối đến
    
    logger.info(f"Khởi động server WebSocket tại {host}:{port}")
    
    async with websockets.serve(
        handle_message, 
        host, 
        port,
        ping_timeout=6000,  # Tăng thời gian timeout lên 6000 giây
        ping_interval=60,   # Gửi ping mỗi 60 giây
        close_timeout=10    # Timeout khi đóng kết nối
    ):
        logger.info(f"Server WebSocket đang chạy tại ws://{host}:{port}")
        logger.info(f"Đã cấu hình ping_timeout=6000 giây, ping_interval=60 giây")
        await asyncio.Future()  # Chạy vô thời hạn

if __name__ == "__main__":
    # Đảm bảo đường dẫn chatbot.py được thêm vào sys.path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server bị dừng bởi người dùng")
    except Exception as e:
        logger.error(f"Lỗi không xử lý được: {str(e)}", exc_info=True) 