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
    'model': 'qwen3-8b',
    'model_server': 'http://localhost:1234/v1'
}

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
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "id": session_id,
        "name": session_name or f"Phiên hội thoại {len(sessions) + 1}",
        "created_at": datetime.now().isoformat(),
        "history": [],
        "message_count": 0,
        "enable_thinking": False  # Mặc định bật chế độ thinking
    }
    return session_id

def get_sessions():
    """Lấy danh sách tất cả các phiên hội thoại"""
    return [
        {
            "id": session_id,
            "name": session["name"],
            "created_at": session["created_at"],
            "message_count": session["message_count"]
        }
        for session_id, session in sessions.items()
    ]

def get_session_history(session_id):
    """Lấy lịch sử hội thoại của một phiên"""
    if session_id in sessions:
        return sessions[session_id]["history"]
    return []

def add_to_history(session_id, query, response, department=None):
    """Thêm một hội thoại vào lịch sử của phiên"""
    if session_id not in sessions:
        logger.warning(f"Phiên {session_id} không tồn tại")
        return
    
    # Loại bỏ hậu tố /think và /no_think từ câu query trước khi lưu
    clean_query = query.replace(" /think", "").replace(" /no_think", "").strip()
    
    sessions[session_id]["history"].append({
        "timestamp": datetime.now().isoformat(),
        "query": clean_query,
        "response": response,
        "department": department
    })
    sessions[session_id]["message_count"] += 1

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
    """Xóa lịch sử hội thoại của một phiên"""
    if session_id in sessions:
        sessions[session_id]["history"] = []
        sessions[session_id]["message_count"] = 0
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
        logger.info(f"Đã trích xuất thinking ({len(thinking_content)} ký tự) và còn lại {len(remaining_text)} ký tự phản hồi")
        return thinking_content, remaining_text
    else:
        return None, text.strip()

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
    history = sessions[session_id]["history"]
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

async def process_streaming_response(websocket, content, detected_department=None, session_id=None):
    """
    Xử lý phản hồi theo phương thức streaming
    
    Args:
        websocket: WebSocket connection
        content: Nội dung tin nhắn từ người dùng
        detected_department: Phòng ban đã được phát hiện trước đó (nếu có)
        session_id: ID phiên hiện tại 
    """
    try:
        global current_session_id
        
        # Đảm bảo session_id luôn có giá trị
        if not session_id:
            # Nếu session_id trống, sử dụng current_session_id
            session_id = current_session_id
            logger.info(f"Session ID không được cung cấp, sử dụng current_session_id: {session_id}")
        
        # Đảm bảo phiên tồn tại
        if session_id not in sessions:
            session_id = create_session("Phiên tự động")
            current_session_id = session_id
            logger.info(f"Tạo phiên mới vì session_id không tồn tại: {session_id}")
        
        logger.info(f"Xử lý streaming response cho: '{content}', phòng ban: {detected_department}, session_id: {session_id}")
        
        # Ghi log session_id để debug
        if session_id:
            logger.info(f"Session ID nhận được: {session_id}")
        else:
            logger.warning("Session ID không được cung cấp!")
        
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
        
        logger.info(f"Xử lý streaming response. Query: '{query}', Mode thinking: {enable_thinking}")
        
        # Thêm lịch sử tin nhắn vào prompt
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
                "session_id": session_id
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
                add_to_history(session_id, query, response_content, department)
                logger.info(f"Đã lưu hội thoại phòng ban {department} vào lịch sử của session {session_id}")
            else:
                logger.warning(f"Không thể lưu hội thoại phòng ban vào lịch sử: session_id={session_id}")
            
            # Gửi phản hồi cuối cùng với thinking nếu có
            final_message = json.dumps({
                "role": "assistant",
                "content": response_content,
                "thinking": thinking_part if enable_thinking else None,
                "session_id": session_id  # Thêm session_id vào message
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
                add_to_history(session_id, query, response_content, None)
                logger.info(f"Đã lưu hội thoại chung vào lịch sử của session {session_id}")
            else:
                logger.warning(f"Không thể lưu hội thoại chung vào lịch sử: session_id={session_id}")
            
            # Gửi phản hồi cuối cùng với thinking nếu có
            final_message = json.dumps({
                "role": "assistant",
                "content": response_content,
                "thinking": thinking_part if enable_thinking else None,
                "session_id": session_id  # Thêm session_id vào message
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
            "session_id": session_id  # Thêm session_id vào message
        })
        await websocket.send(error_response)

async def handle_thinking_request(websocket, query, session_id=None, request_id=None):
    """
    Xử lý yêu cầu phân tích (thinking) từ client và trả về nội dung thinking
    
    Args:
        websocket: WebSocket connection
        query: Nội dung câu hỏi cần phân tích
        session_id: ID phiên hiện tại
        request_id: ID yêu cầu để ghép cặp yêu cầu-phản hồi
    """
    logger.info(f"Nhận yêu cầu phân tích (thinking) cho câu hỏi: {query[:100]}")
    
    try:
        if not session_id:
            session_id = current_session_id
            logger.info(f"Sử dụng session_id mặc định: {session_id}")
            
        # Loại bỏ hậu tố /think và /no_think nếu có
        clean_query = query.replace(" /think", "").replace(" /no_think", "").strip()
            
        # Thêm lịch sử tin nhắn vào prompt nếu có
        content_with_history = add_history_to_prompt(clean_query, session_id)
        
        # Đầu tiên xác định xem đây là câu hỏi thuộc phòng ban nào
        logger.info("Phân tích câu hỏi để xác định phòng ban hoặc loại câu hỏi")
        analysis_result = analyze_query_with_llm(content_with_history, session_id)
        
        # Xử lý trường hợp LLM trả về thẻ <think> thay vì JSON
        if isinstance(analysis_result, str) and "<think>" in analysis_result:
            filtered_result = filter_thinking_tags(analysis_result)
            if filtered_result:
                analysis_result = filtered_result
            else:
                analysis_result = {"department": None, "query_type": "general", "error": False}
        
        # Nếu kết quả phân tích là None, sử dụng kết quả mặc định
        if analysis_result is None:
            analysis_result = {"department": None, "query_type": "general", "error": False}
        
        # Lấy thông tin phòng ban và loại câu hỏi
        department = None
        query_type = "general"
        
        if isinstance(analysis_result, dict):
            department = analysis_result.get("department")
            query_type = analysis_result.get("query_type")
        
        # Lấy nội dung thinking dựa trên loại câu hỏi
        thinking_content = ""
        
        if query_type == "department_specific" and department:
            # Nếu là câu hỏi phòng ban cụ thể, sử dụng smart_rag_query để lấy kết quả
            logger.info(f"Lấy phân tích cho câu hỏi phòng ban: {department}")
            
            # Thêm hậu tố /think để đảm bảo nhận được phần thinking
            query_with_think = clean_query + " /think"
            
            # Sử dụng smart_rag_query trực tiếp và trích xuất phần thinking
            response = smart_rag_query(query_with_think, None, department, session_id)
            
            # Trích xuất phần thinking từ phản hồi nếu có
            if "<think>" in response:
                thinking_extracted, _ = extract_thinking(response)
                if thinking_extracted:
                    thinking_content = thinking_extracted
                    logger.info(f"Đã trích xuất phần thinking ({len(thinking_content)} ký tự) từ phản hồi smart_rag_query")
                else:
                    # Nếu không tìm thấy thẻ <think>, tạo phân tích mới
                    analysis_prompt = f"""
Hãy phân tích chi tiết câu hỏi sau về phòng ban {department}:

{clean_query}

Phân tích:
1. Nhu cầu thông tin cụ thể
2. Các khía cạnh cần đề cập
3. Cách tiếp cận để trả lời toàn diện
"""
                    # Sử dụng department_info_tool để lấy thông tin phòng ban
                    dept_tool = DepartmentInfoTool()
                    dept_info = dept_tool.get_department_info(department)
                    
                    # Tạo một prompt cụ thể cho phòng ban
                    llm_prompt = create_llm_prompt(analysis_prompt, dept_info, session_id)
                    system_prompt = create_system_prompt(None, department)
                    
                    # Lấy phân tích
                    thinking_content = query_llm(llm_prompt, system_prompt, max_tokens=800, stream=False)
            else:
                # Nếu không có thẻ <think>, tạo phân tích tự động
                thinking_content = f"""
## Phân tích câu hỏi về phòng ban {department}

Câu hỏi: {clean_query}

### Nhu cầu thông tin
- Thông tin về quy trình, nhiệm vụ hoặc trách nhiệm của phòng ban {department}
- Hiểu rõ về các thông tin liên quan đến phòng ban này

### Cách tiếp cận
- Phân tích và tổng hợp thông tin từ cơ sở dữ liệu về phòng ban {department}
- Cung cấp thông tin chính xác và cụ thể về các quy trình liên quan
"""
        else:
            # Nếu là câu hỏi chung, sử dụng một prompt chung để phân tích
            logger.info("Lấy phân tích cho câu hỏi chung")
            
            # Thêm hậu tố /think để đảm bảo nhận được phần thinking
            query_with_think = clean_query + " /think"
            
            # Sử dụng handle_general_query trực tiếp và trích xuất phần thinking
            response = handle_general_query(query_with_think, session_id=session_id)
            
            # Trích xuất phần thinking từ phản hồi nếu có
            if "<think>" in response:
                thinking_extracted, _ = extract_thinking(response)
                if thinking_extracted:
                    thinking_content = thinking_extracted
                    logger.info(f"Đã trích xuất phần thinking ({len(thinking_content)} ký tự) từ phản hồi handle_general_query")
                else:
                    # Nếu không tìm thấy thẻ <think>, tạo phân tích mới
                    analysis_prompt = f"""
Hãy phân tích chi tiết câu hỏi sau:

{clean_query}

Phân tích:
1. Nhu cầu thông tin cụ thể
2. Các khía cạnh cần đề cập
3. Cách tiếp cận để trả lời toàn diện
"""
                    # Sử dụng hệ thống prompt chung
                    system_prompt = create_system_prompt()
                    
                    # Lấy phân tích
                    thinking_content = query_llm(analysis_prompt, system_prompt, max_tokens=800, stream=False)
            else:
                # Nếu không có thẻ <think>, tạo phân tích tự động
                thinking_content = f"""
## Phân tích câu hỏi chung

Câu hỏi: {clean_query}

### Nhu cầu thông tin
- Thông tin chung về quy trình làm việc
- Hiểu rõ về các nhiệm vụ và trách nhiệm 

### Cách tiếp cận
- Phân tích và tổng hợp thông tin từ cơ sở dữ liệu chung
- Cung cấp thông tin tổng quát về các quy trình
"""
        
        # Đảm bảo có kết quả trả về
        if not thinking_content or thinking_content.strip() == "":
            thinking_content = "Không thể tạo nội dung phân tích cho câu hỏi này."
            
        thinking_content = thinking_content.replace("Expecting value: line 1 column 1 (char 0)", 
                                                 "Lỗi khi phân tích JSON từ phản hồi.")
        
        # Chuẩn bị phản hồi JSON
        response = {
            "role": "assistant",
            "content": "",  # Không có nội dung chính, chỉ có thinking
            "thinking": thinking_content,
            "session_id": session_id
        }
        
        # Thêm request_id nếu được cung cấp
        if request_id:
            response["request_id"] = request_id
            logger.info(f"Gửi phản hồi thinking với request_id: {request_id}")
        
        # Gửi phản hồi dạng JSON
        await websocket.send(json.dumps(response))
        logger.info(f"Đã gửi nội dung thinking ({len(thinking_content)} ký tự)")
        
    except Exception as e:
        logger.error(f"Lỗi khi xử lý yêu cầu thinking: {str(e)}", exc_info=True)
        
        # Tạo phản hồi lỗi nhưng vẫn là JSON hợp lệ
        error_response = {
            "role": "assistant",
            "content": "",
            "thinking": f"Đã xảy ra lỗi khi phân tích câu hỏi: {str(e)}",
            "error": str(e),
            "session_id": session_id
        }
        
        # Thêm request_id nếu được cung cấp
        if request_id:
            error_response["request_id"] = request_id
        
        # Gửi phản hồi lỗi
        await websocket.send(json.dumps(error_response))

async def handle_action(websocket, action, data):
    """Xử lý các hành động WebSocket"""
    global current_session_id
    
    try:
        if action == "get_sessions":
            # Đảm bảo luôn có ít nhất một phiên
            if not sessions:
                current_session_id = create_session("Phiên mặc định")
            
            response = {
                "action": "get_sessions_response",
                "status": "success",
                "sessions": get_sessions(),
                "current_session_id": current_session_id
            }
            await websocket.send(json.dumps(response))
            
        elif action == "create_session":
            session_name = data.get("session_name", "Phiên mới")
            session_id = create_session(session_name)
            current_session_id = session_id
            
            response = {
                "action": "create_session_response",
                "status": "success",
                "session_id": session_id
            }
            await websocket.send(json.dumps(response))
            
        elif action == "get_thinking":
            # Xử lý yêu cầu lấy thinking content
            query = data.get('query', '')
            session_id = data.get('session_id', current_session_id)
            request_id = data.get('request_id')  # Lấy request_id nếu có
            
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
                
                response = {
                    "action": "switch_session_response",
                    "status": "success",
                    "session_id": session_id
                }
                await websocket.send(json.dumps(response))
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
                
                response = {
                    "action": "delete_session_response",
                    "status": "success",
                    "new_session_id": new_session_id
                }
                await websocket.send(json.dumps(response))
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
            
            if session_id and session_id in sessions:
                history = get_session_history(session_id)
                
                response = {
                    "action": "get_history_response",
                    "status": "success",
                    "history": history
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
                
                response = {
                    "action": "clear_history_response",
                    "status": "success" if success else "error",
                    "session_id": session_id
                }
                await websocket.send(json.dumps(response))
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
    
    try:
        async for message in websocket:
            # Kiểm tra xem message có phải là JSON action không
            try:
                data = json.loads(message)
                
                # Kiểm tra xem có phải là action không
                if 'action' in data:
                    await handle_action(websocket, data['action'], data)
                else:
                    # Nếu không phải là action, xử lý như tin nhắn JSON
                    logger.info(f"Nhận tin nhắn dạng JSON: {message[:100]}")
                    content = data.get('content', '')
                    session_id = data.get('session_id', '')
                    
                    # Đảm bảo session_id luôn có giá trị
                    if not session_id:
                        session_id = current_session_id
                        logger.info(f"Session ID không được cung cấp trong tin nhắn JSON, sử dụng current_session_id: {session_id}")
                    
                    # Đảm bảo phiên tồn tại
                    if session_id not in sessions:
                        session_id = create_session("Phiên tự động")
                        current_session_id = session_id
                        logger.info(f"Tạo phiên mới vì session_id không tồn tại: {session_id}")
                    
                    # Log session_id để debug
                    logger.info(f"Session ID từ client (sau khi kiểm tra): {session_id}")
                    
                    # Xử lý hậu tố think/no_think như với tin nhắn thông thường
                    enable_thinking = False
                    # Giữ nguyên query, KHÔNG loại bỏ hậu tố
                    query = content
                    
                    if " /think" in content:
                        enable_thinking = True
                        # KHÔNG loại bỏ hậu tố, giữ nguyên query
                        logger.info(f"Bật chế độ thinking cho câu hỏi: {query[:50]}...")
                    elif " /no_think" in content:
                        enable_thinking = False
                        # KHÔNG loại bỏ hậu tố, giữ nguyên query
                        logger.info(f"Tắt chế độ thinking cho câu hỏi: {query[:50]}...")
                    
                    logger.info(f"Nhận tin nhắn thông thường: {query[:100]}, enable_thinking={enable_thinking}")
                    
                    try:
                        # Thêm lịch sử tin nhắn vào prompt
                        query_with_history = add_history_to_prompt(query, session_id)
                        
                        # Phân tích câu hỏi để tìm phòng ban hoặc thông tin khác - truyền thêm session_id
                        analysis_result = analyze_query_with_llm(query_with_history, session_id)
                        
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
                    except Exception as e:
                        logger.error(f"Lỗi khi phân tích câu hỏi: {str(e)}", exc_info=True)
                        analysis_result = {
                            "department": None,
                            "query_type": "general", 
                            "error": False
                        }
                    
                    # Nếu kết quả phân tích là None, sử dụng kết quả mặc định
                    if analysis_result is None:
                        logger.warning("analyze_query_with_llm trả về None. Sử dụng giá trị mặc định.")
                        analysis_result = {
                            "department": None,
                            "query_type": "general",
                            "error": False
                        }
                    
                    # Kiểm tra lỗi nhiều phòng ban
                    if analysis_result.get("error", False):
                        error_message = analysis_result.get("error_message", "Phát hiện nhiều phòng ban trong một câu hỏi")
                        error_response = json.dumps({
                            "role": "assistant",
                            "content": f"❌ {error_message}. Vui lòng chỉ hỏi về một phòng ban mỗi lần.",
                            "thinking": None,
                            "warning": error_message,
                            "session_id": session_id
                        })
                        await websocket.send(error_response)
                        continue
                    
                    # Xác định phòng ban từ kết quả phân tích
                    department = analysis_result.get("department")
                    query_type = analysis_result.get("query_type")
                    
                    logger.info(f"Phân tích câu hỏi: Phòng ban={department}, Loại={query_type}, Thinking={enable_thinking}")
                    
                    # Xử lý phản hồi dạng streaming
                    await process_streaming_response(websocket, query, department, session_id)
                    
            except json.JSONDecodeError:
                # Không phải JSON, xử lý như tin nhắn văn bản thông thường
                logger.info(f"Nhận tin nhắn thường: {message[:100]}")
                
                # Kiểm tra hậu tố think/no_think để quyết định trạng thái thinking
                enable_thinking = False
                # Giữ nguyên query, KHÔNG loại bỏ hậu tố
                query = message
                
                # Kiểm tra hậu tố /think và /no_think
                if " /think" in message:
                    enable_thinking = True
                    # KHÔNG loại bỏ hậu tố, giữ nguyên query
                    logger.info(f"Bật chế độ thinking cho câu hỏi: {query[:50]}...")
                elif " /no_think" in message:
                    enable_thinking = False
                    # KHÔNG loại bỏ hậu tố, giữ nguyên query
                    logger.info(f"Tắt chế độ thinking cho câu hỏi: {query[:50]}...")
                
                logger.info(f"Nhận tin nhắn thường: {query[:100]}, enable_thinking={enable_thinking}")
                
                try:
                    # Thêm lịch sử tin nhắn vào prompt
                    query_with_history = add_history_to_prompt(query, current_session_id)
                    
                    # Phân tích câu hỏi để tìm phòng ban hoặc thông tin khác - truyền thêm session_id
                    analysis_result = analyze_query_with_llm(query_with_history, current_session_id)
                    
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
                except Exception as e:
                    logger.error(f"Lỗi khi phân tích câu hỏi: {str(e)}", exc_info=True)
                    analysis_result = {
                        "department": None,
                        "query_type": "general", 
                        "error": False
                    }
                
                # Nếu kết quả phân tích là None, sử dụng kết quả mặc định
                if analysis_result is None:
                    logger.warning("analyze_query_with_llm trả về None. Sử dụng giá trị mặc định.")
                    analysis_result = {
                        "department": None,
                        "query_type": "general",
                        "error": False
                    }
                
                # Kiểm tra lỗi nhiều phòng ban
                if analysis_result.get("error", False):
                    error_message = analysis_result.get("error_message", "Phát hiện nhiều phòng ban trong một câu hỏi")
                    await websocket.send(f"❌ {error_message}. Vui lòng chỉ hỏi về một phòng ban mỗi lần.")
                    continue
                
                # Xác định phòng ban từ kết quả phân tích
                department = analysis_result.get("department")
                query_type = analysis_result.get("query_type")
                
                logger.info(f"Phân tích câu hỏi: Phòng ban={department}, Loại={query_type}, Thinking={enable_thinking}")
                
                # Xử lý phản hồi dạng streaming
                await process_streaming_response(websocket, query, department, current_session_id)
    
    except websockets.exceptions.ConnectionClosed:
        logger.info("WebSocket connection closed")
    except Exception as e:
        logger.error(f"Lỗi trong handle_message: {str(e)}", exc_info=True)

async def main():
    """Khởi động server WebSocket"""
    # Đảm bảo thư mục log tồn tại
    os.makedirs('data/logs', exist_ok=True)
    
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