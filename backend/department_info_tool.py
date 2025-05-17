import os
import re
import json
import logging
from typing import Dict, List, Any, Optional

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("department_tool.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("department_info_tool")

# Thư mục dữ liệu
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
DEPARTMENT_DATA_DIR = os.path.join(BASE_DIR, "data", "departments")

# Thứ tự các giai đoạn chính
PHASES_ORDER = [
    "MKT-SALES",
    "PROPOSAL",
    "CONSTRUCTION",
    "DEFECT-HANDOVER",
    "AFTERSALE-MAINTENANCE"
]

# Thứ tự các giai đoạn con (sub-phases) trong từng giai đoạn chính
SUB_PHASES_ORDER = {
    "MKT-SALES": [
        "Branding MKT",
        "Sales Sourcing",
        "Data Qualification",
        "Approach"
    ],
    # Có thể thêm thứ tự cho các giai đoạn khác nếu cần
}

def remove_accents(input_str: str) -> str:
    """
    Loại bỏ dấu tiếng Việt, giữ lại ký tự ASCII.
    Ví dụ: "Thông báo" -> "Thong bao"
    """
    s = input_str
    # Các ánh xạ dấu tiếng Việt sang không dấu
    mapping = {
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'đ': 'd',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y'
    }
    
    for vietnamese, latin in mapping.items():
        s = s.replace(vietnamese, latin)
        s = s.replace(vietnamese.upper(), latin.upper())
    
    return s

def load_departments() -> List[str]:
    """Tải danh sách phòng ban từ thư mục dữ liệu"""
    departments = []
    
    if not os.path.exists(DEPARTMENT_DATA_DIR):
        logger.error(f"Thư mục {DEPARTMENT_DATA_DIR} không tồn tại!")
        return ["Không có dữ liệu phòng ban"]
    
    # Đọc thông tin từ các file phòng ban
    for filename in os.listdir(DEPARTMENT_DATA_DIR):
        if filename.endswith('.txt') and not filename.startswith('all_') and not filename.startswith('ALL-'):
            file_path = os.path.join(DEPARTMENT_DATA_DIR, filename)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # Trích xuất tên phòng ban
                    dept_match = re.search(r"# PHÒNG BAN: ([^\n]+)", content)
                    if dept_match:
                        department = dept_match.group(1).strip()
                        departments.append(department)
            except Exception as e:
                logger.error(f"Lỗi khi đọc file {filename}: {str(e)}")
    
    return sorted(departments)

class DepartmentInfoTool:
    """
    Tool duy nhất để trích xuất thông tin về phòng ban và tất cả các task
    """
    
    def __init__(self):
        """Khởi tạo công cụ thông tin phòng ban."""
        # Tải danh sách phòng ban khi khởi tạo
        try:
            self.departments = load_departments()
            # Loại bỏ phòng ban trùng lặp ngay từ đầu
            self.departments = list(dict.fromkeys(self.departments))
            logger.info(f"Đã tải {len(self.departments)} phòng ban")
        except Exception as e:
            self.departments = []
            logger.error(f"Lỗi khi tải danh sách phòng ban: {str(e)}")
    
    def get_department_info(self, department_name: str) -> Dict[str, Any]:
        """
        Lấy thông tin chi tiết về một phòng ban và tất cả task trong phòng ban đó.
        
        Args:
            department_name: Tên phòng ban cần lấy thông tin
            
        Returns:
            Dict chứa thông tin chi tiết về phòng ban và các task
        """
        logger.info(f"Đang trích xuất thông tin cho phòng ban: {department_name}")
        
        if not department_name:
            return {
                'success': False,
                'error': 'Tên phòng ban không được để trống',
                'available_departments': self.departments
            }
        
        # Chuẩn hóa tên file: phòng ban -> phòng_ban.txt
        clean_filename = re.sub(r'[^\w\s-]', '', department_name).replace(' ', '_').lower()
        file_path = os.path.join(DEPARTMENT_DATA_DIR, f"{clean_filename}.txt")
        
        # Kiểm tra file có tồn tại không
        if not os.path.exists(file_path):
            logger.warning(f"Không tìm thấy file cho '{department_name}' tại đường dẫn {file_path}")
            
            # Thử tìm file tương tự nếu không tìm thấy chính xác
            if not os.path.exists(file_path):
                # Tìm các file trong thư mục
                all_files = os.listdir(DEPARTMENT_DATA_DIR)
                
                # Lọc các file .txt (loại bỏ file tổng hợp)
                txt_files = [f for f in all_files if f.endswith('.txt') and not f.startswith('all_') and not f.startswith('ALL-')]
                
                # Thử tìm file phù hợp bằng cách so sánh tên
                found = False
                
                # Phương pháp 1: Tìm kiếm trực tiếp
                for filename in txt_files:
                    # Kiểm tra nếu tên phòng ban xuất hiện trong tên file
                    if department_name.lower() in filename.lower():
                        file_path = os.path.join(DEPARTMENT_DATA_DIR, filename)
                        logger.info(f"Tìm thấy file thay thế: {filename}")
                        found = True
                        break
                
                # Phương pháp 2: Tìm kiếm không dấu
                if not found:
                    department_no_accent = remove_accents(department_name).lower()
                    for filename in txt_files:
                        filename_no_accent = remove_accents(filename).lower()
                        if department_no_accent in filename_no_accent:
                            file_path = os.path.join(DEPARTMENT_DATA_DIR, filename)
                            logger.info(f"Tìm thấy file thay thế không dấu: {filename}")
                            found = True
                            break
                
                # Phương pháp 3: Chuyển đổi chuẩn hóa tên file
                if not found:
                    for filename in txt_files:
                        # Bỏ đuôi .txt
                        name_only = filename[:-4]  
                        # Thay dấu gạch dưới bằng khoảng trắng
                        formatted_name = name_only.replace('_', ' ')
                        
                        # So sánh với tên phòng ban
                        if department_name.lower() == formatted_name.lower():
                            file_path = os.path.join(DEPARTMENT_DATA_DIR, filename)
                            logger.info(f"Tìm thấy file chuẩn hóa: {filename}")
                            found = True
                            break
                            
                        # So sánh không dấu
                        if remove_accents(department_name).lower() == remove_accents(formatted_name).lower():
                            file_path = os.path.join(DEPARTMENT_DATA_DIR, filename)
                            logger.info(f"Tìm thấy file chuẩn hóa không dấu: {filename}")
                            found = True
                            break
                
                # Không tìm thấy file
                if not found:
                    logger.error(f"Không tìm thấy file nào phù hợp cho phòng ban '{department_name}'")
                    return {
                        'success': False,
                        'error': f"Không tìm thấy thông tin cho phòng ban: {department_name}",
                        'available_departments': self.departments
                    }
        
        # Đọc nội dung file
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                logger.info(f"Đã đọc thành công file {file_path}, kích thước: {len(content)} bytes")
                
                # Trích xuất metadata cơ bản
                department_match = re.search(r"# PHÒNG BAN: ([^\n]+)", content)
                department_name = department_match.group(1) if department_match else department_name
                department_code = re.sub(r'[^\w]', '', department_name)[:3].upper()
                
                phases_matches = re.findall(r"## Giai đoạn: ([^\n]+)", content)
                phases = list(set(phases_matches))  # Loại bỏ trùng lặp
                
                # Sắp xếp phases theo thứ tự đã định nghĩa
                ordered_phases = []
                for phase in PHASES_ORDER:
                    if phase in phases:
                        ordered_phases.append(phase)
                for phase in phases:
                    if phase not in ordered_phases:
                        ordered_phases.append(phase)
                
                # Chuẩn bị cấu trúc dữ liệu mới
                task_overview = {}       # Cấu trúc phân cấp theo phase và sub-phase
                task_list = []           # Danh sách phẳng tất cả các task
                task_ids = []            # Danh sách ID của các task
                task_names = []          # Danh sách tên task
                task_map = {}            # Map giữa tên task và ID
                
                # Duyệt qua các giai đoạn theo thứ tự
                for phase in ordered_phases:
                    # Tìm nội dung của giai đoạn
                    phase_pattern = f"## Giai đoạn: {re.escape(phase)}(.*?)(?=## Giai đoạn:|$)"
                    phase_match = re.search(phase_pattern, content, re.DOTALL)
                    
                    if not phase_match:
                        continue
                        
                    phase_content = phase_match.group(1)
                    
                    # Tìm các giai đoạn con
                    sub_phases_raw = re.findall(r"### Giai đoạn con: ([^\n]+)", phase_content)
                    
                    # Khởi tạo cấu trúc cho giai đoạn này
                    task_overview[phase] = {
                        "sub_phases": [],
                        "tasks": []
                    }
                    
                    # Sắp xếp sub-phases theo thứ tự đã định nghĩa (nếu có)
                    sub_phases = []
                    if phase in SUB_PHASES_ORDER:
                        # Thêm các sub-phase theo thứ tự đã định nghĩa
                        for sub_phase in SUB_PHASES_ORDER[phase]:
                            if sub_phase in sub_phases_raw:
                                sub_phases.append(sub_phase)
                                task_overview[phase]["sub_phases"].append(sub_phase)
                        
                        # Thêm các sub-phase còn lại không nằm trong danh sách đã định nghĩa
                        for sub_phase in sub_phases_raw:
                            if sub_phase not in sub_phases:
                                sub_phases.append(sub_phase)
                                task_overview[phase]["sub_phases"].append(sub_phase)
                    else:
                        # Nếu không có thứ tự định nghĩa, giữ nguyên danh sách
                        sub_phases = sub_phases_raw
                        task_overview[phase]["sub_phases"] = sub_phases_raw
                    
                    # Tìm tất cả các task trong giai đoạn
                    task_matches = re.findall(r"#### Task: ([^\n]+)", phase_content)
                    tasks_positions = {}  # Theo dõi vị trí xuất hiện của các task trong file
                    
                    for i, task in enumerate(task_matches):
                        tasks_positions[task] = i
                    
                    # Sắp xếp các task theo thứ tự xuất hiện trong file
                    sorted_tasks = sorted(task_matches, key=lambda t: tasks_positions[t])
                    
                    # Xử lý từng task theo thứ tự
                    for task_heading in sorted_tasks:
                        # Trích xuất ID và tên
                        task_id_match = re.match(r"([A-Z0-9\-]+) - (.*)", task_heading)
                        
                        if task_id_match:
                            task_id = task_id_match.group(1).strip()
                            task_name = task_id_match.group(2).strip()
                        else:
                            # Fallback nếu không khớp với mẫu ID - Tên
                            task_id = f"{department_code}-{len(task_ids) + 1:03d}"
                            task_name = task_heading.strip()
                        
                        # Lưu ID và tạo mapping
                        task_ids.append(task_id)
                        task_names.append(task_name)
                        task_map[task_name] = task_id
                        
                        # Trích xuất thông tin chi tiết của task
                        task_pattern = fr"#### Task: {re.escape(task_heading)}(.*?)(?=#### Task:|$)"
                        task_details = re.search(task_pattern, phase_content, re.DOTALL)
                        task_details_text = task_details.group(1) if task_details else ""
                        
                        # Tìm sub_phase của task
                        sub_phase_match = re.search(r"##### Giai đoạn con: ([^\n]+)", task_details_text)
                        if not sub_phase_match:
                            sub_phase_match = re.search(r"- Giai đoạn con: ([^\n]+)", task_details_text)
                        
                        sub_phase = sub_phase_match.group(1).strip() if sub_phase_match else ""
                        
                        # Tìm mô tả công việc
                        description_match = re.search(r"##### Mô tả: ([^\n]+)", task_details_text)
                        if not description_match:
                            description_match = re.search(r"- Mô tả công việc: ([^\n]+)", task_details_text)
                        
                        description = description_match.group(1).strip() if description_match else ""
                        
                        # Tìm điều kiện tiên quyết
                        prerequisite_match = re.search(r"##### Điều kiện tiên quyết: ([^\n]+)", task_details_text)
                        if not prerequisite_match:
                            prerequisite_match = re.search(r"- Điều kiện tiên quyết: ([^\n]+)", task_details_text)
                        
                        prerequisite = prerequisite_match.group(1).strip() if prerequisite_match else ""
                        
                        # Tìm người phụ trách (A)
                        responsible_match = re.search(r"##### Người phụ trách: ([^\n]+)", task_details_text)
                        if not responsible_match:
                            responsible_match = re.search(r"- Người chịu trách nhiệm \(A\): ([^\n]+)", task_details_text)
                        
                        responsible = responsible_match.group(1).strip() if responsible_match else ""
                        
                        # Tìm người thực hiện (R)
                        executor_match = re.search(r"##### Người thực hiện: ([^\n]+)", task_details_text)
                        if not executor_match:
                            executor_match = re.search(r"- Người thực hiện \(R\): ([^\n]+)", task_details_text)
                        
                        executor = executor_match.group(1).strip() if executor_match else ""
                        
                        # Tạo đối tượng task đơn giản với các thông tin cơ bản
                        task_obj = {
                            "id": task_id,
                            "name": task_name,
                            "phase": phase,
                            "sub_phase": sub_phase,
                            "description": description,
                            "prerequisite": prerequisite,
                            "responsible": responsible,
                            "executor": executor,
                            "position": tasks_positions[task_heading],
                            "department": department_name,
                            "full_details": task_details_text.strip() if task_details_text else "Không có thông tin chi tiết"
                        }
                        
                        # Thêm vào danh sách phẳng
                        task_list.append(task_obj)
                        
                        # Thêm vào cấu trúc phase/sub-phase
                        if sub_phase and sub_phase in task_overview[phase]["sub_phases"]:
                            # Khởi tạo list tasks cho sub-phase nếu chưa có
                            if "tasks_by_sub_phase" not in task_overview[phase]:
                                task_overview[phase]["tasks_by_sub_phase"] = {}
                            
                            if sub_phase not in task_overview[phase]["tasks_by_sub_phase"]:
                                task_overview[phase]["tasks_by_sub_phase"][sub_phase] = []
                            
                            # Thêm task vào sub-phase
                            task_overview[phase]["tasks_by_sub_phase"][sub_phase].append(task_obj)
                        
                        # Thêm task vào danh sách chung của phase
                        task_overview[phase]["tasks"].append(task_obj)
                
                # Sắp xếp lại task_list theo thứ tự phase
                task_list.sort(key=lambda t: (PHASES_ORDER.index(t["phase"]) if t["phase"] in PHASES_ORDER else 999, 
                                               t["position"]))
                
                # Tạo các chuỗi định dạng cho hiển thị
                formatted_tasks = []
                for task in task_list:
                    formatted_tasks.append(f"{task['id']} - {task['name']} ({task['phase']}, {task['sub_phase'] if task['sub_phase'] else 'không có sub-phase'})")
                
                # Chuẩn bị kết quả trả về
                result = {
                    'success': True,
                    'department': department_name,
                    'department_code': department_code,
                    'phases': ordered_phases,
                    'task_overview': task_overview,
                    'task_list': task_list,
                    'task_count': len(task_list),
                    'task_names': sorted([task["name"] for task in task_list]),
                    'task_ids': [task["id"] for task in task_list],
                    'task_map': task_map,
                    'formatted_tasks': formatted_tasks,
                    'interaction_guide': f"Có thể hỏi về bất kỳ phase, sub-phase, công việc, mô tả hoặc thông tin liên quan đến phòng ban {department_name}.",
                }
                
                # Log kết quả cho debugging
                logger.info(f"Đã tìm thấy {len(ordered_phases)} giai đoạn và {len(task_list)} công việc cho phòng ban {department_name}")
                
                return result
                
        except Exception as e:
            logger.error(f"Lỗi khi xử lý file {file_path}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            
            return {
                'success': False,
                'error': f"Lỗi khi xử lý dữ liệu: {str(e)}"
            }
    
    def get_all_departments(self) -> Dict[str, Any]:
        """
        Lấy thông tin tổng quan về tất cả các phòng ban
        
        Returns:
            Dict[str, Any]: Thông tin về tất cả phòng ban
        """
        try:
            # Đã có danh sách phòng ban từ khi khởi tạo
            result = {
                'success': True,
                'departments': self.departments  # self.departments đã được khởi tạo trong __init__
            }
            
            # Loại bỏ các phòng ban trùng lặp
            result['departments'] = list(dict.fromkeys(result['departments']))
            
            logger.info(f"Đã lấy danh sách {len(result['departments'])} phòng ban")
            return result
        except Exception as e:
            logger.error(f"Lỗi khi lấy danh sách phòng ban: {str(e)}")
            return {
                'success': False,
                'error': f"Không thể lấy danh sách phòng ban: {str(e)}",
                'departments': []
            }
    
    def get_departments(self) -> List[str]:
        """
        Lấy danh sách tên của tất cả các phòng ban
        
        Returns:
            List[str]: Danh sách tên các phòng ban (đã loại bỏ trùng lặp)
        """
        result = self.get_all_departments()
        if result.get('success', False):
            # Lấy danh sách và loại bỏ các phần tử trùng lặp
            departments = result.get('departments', [])
            return list(dict.fromkeys(departments))
        return []

# Ví dụ sử dụng
if __name__ == "__main__":
    # Khởi tạo tool
    department_tool = DepartmentInfoTool()
    
    # Lấy danh sách phòng ban
    all_depts = department_tool.get_all_departments()
    print(f"Có {len(all_depts['departments'])} phòng ban trong hệ thống.")
    
    # Test trích xuất thông tin phòng ban
    # Thay đổi tên phòng ban ở đây để test
    result = department_tool.get_department_info("Marketing")
    
    if result['success']:
        print(f"Thông tin phòng ban {result['department']}:")
        print(f"- Số lượng task: {result['task_count']}")
        print(f"- Các giai đoạn: {', '.join(result['phases'])}")
        
        # In ra 5 task đầu tiên
        print("\nMột số task trong phòng ban:")
        for i, task in enumerate(result['formatted_tasks'][:5], 1):
            print(f"{i}. {task}")
    else:
        print(f"Lỗi: {result['error']}") 