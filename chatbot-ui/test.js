import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const markdown = `
### Hướng dẫn làm việc cho nhân viên 2D:

#### Giai đoạn **CONSTRUCTION** (Thi công):
- **Task 2D-001**: Chuẩn bị kick-off nội bộ/ Chuẩn bị họp cập nhật dự án  
  - Đầu ra: Biên bản khảo sát mặt bằng  
  - Mô tả: Khảo sát mặt bằng  
  - Mục tiêu: N  

- **Task 2D-002**: Chuẩn bị kick-off nội bộ/ Chuẩn bị họp cập nhật dự án  
  - Đầu ra: Bản vẽ xin phép  
  - Mô tả: Vẽ bản vẽ xin phép  
  - Mục tiêu: N  

#### Giai đoạn **DEFECT-HANDOVER** (Xử lý lỗi và bàn giao):
- **Task 2D-003**: Chuẩn bị hồ sơ Quyết toán  
  - Đầu ra: Bản vẽ hoàn công  
  - Mô tả: Điều chỉnh bản vẽ xin phép theo thực tế để làm bản vẽ hoàn công  
  - Mục tiêu: Hoàn công với tòa nhà  

Nếu bước không đạt được mục tiêu, quay về task tương ứng.
`;

export default function MarkdownTest() {
  return (
    <div className="prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}