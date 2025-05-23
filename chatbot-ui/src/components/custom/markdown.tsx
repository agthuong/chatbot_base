import { memo, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const NonMemoizedMarkdown = ({ children }: { children: string }) => {
  // Xử lý trước nội dung để đảm bảo các từ khóa được đánh dấu bằng ** hiển thị đúng
  const [processedContent, setProcessedContent] = useState(children);
  
  // Xử lý và chuẩn hóa nội dung khi children thay đổi
  useEffect(() => {
    // Đảm bảo children là một chuỗi
    if (typeof children !== 'string') {
      setProcessedContent(String(children));
      return;
    }
    
    // Kiểm tra xem nội dung có chứa HTML không
    const hasHtml = /<[a-z][\s\S]*>/i.test(children);
    
    // Nếu có HTML, giữ nguyên nội dung
    if (hasHtml) {
      // Xử lý các thẻ HTML đặc biệt
      let content = children;
      
      // Chuyển đổi thẻ <strong class="highlight-keyword"> thành định dạng Markdown
      content = content.replace(/<strong class="highlight-keyword">([^<]+)<\/strong>/g, '**$1**');
      
      setProcessedContent(content);
      return;
    }
    
    // Cải thiện xử lý text bằng cách đảm bảo các dấu ** được tách rõ ràng
    let content = children;
    
    // Xử lý đặc biệt cho các từ khóa được bọc trong dấu **
    // 1. Đảm bảo các dấu ** được tách biệt để ReactMarkdown có thể xử lý
    content = content.replace(/([^\s])\*\*/g, "$1 **");
    content = content.replace(/\*\*([^\s])/g, "** $1");
    
    // 2. Xử lý các trường hợp ** liền nhau
    content = content.replace(/\*\*([^*]+)\*\*\*\*([^*]+)\*\*/g, "**$1** **$2**");
    
    // 3. Thêm khoảng trắng giữa các từ khóa nếu cần
    content = content.replace(/\*\*\s*\*\*/g, " ");
    
    // 4. Đảm bảo có đủ dấu ** (số chẵn) bằng cách thêm dấu nếu thiếu
    const countAsterisks = (content.match(/\*\*/g) || []).length;
    if (countAsterisks % 2 !== 0) {
      content += "**"; // Thêm dấu đóng nếu thiếu
    }
    
    // 5. Xử lý từng từ khóa đặc biệt
    const specialKeywords = [
      "MKT-SALES", 
      "PROPOSAL", 
      "CONSTRUCTION", 
      "DEFECT-HANDOVER", 
      "AFTERSALE-MAINTENANCE",
      "content"
    ];
    
    // Đảm bảo các từ khóa đặc biệt được hiển thị đúng
    specialKeywords.forEach(keyword => {
      // Thay thế cả hai trường hợp: có dấu ** và không có dấu **
      const patternWithAsterisks = new RegExp(`\\*\\*${keyword}\\*\\*`, 'gi');
      
      // Ưu tiên thay thế các từ khóa có dấu ** trước
      content = content.replace(patternWithAsterisks, `**${keyword}**`);
    });
    
    setProcessedContent(content);
  }, [children]);
  
  const components = {
    // Cấu hình để render HTML nội tuyến một cách an toàn
    p: ({ node, children, ...props }: any) => {
      // Kiểm tra xem nội dung có chứa HTML không
      const htmlContent = typeof children === 'string' && /<[a-z][\s\S]*>/i.test(children);
      
      if (htmlContent) {
        return <div className="mb-1" dangerouslySetInnerHTML={{ __html: children }} />;
      }
      
      return (
        <p className="mb-1 leading-snug" {...props}>
          {children}
        </p>
      );
    },
    
    strong: ({ node, children, ...props }: any) => {
      // Kiểm tra xem nội dung có phải là từ khóa đặc biệt không
      const content = children && children[0] ? children[0].toString() : '';
      const specialKeywords = [
        "MKT-SALES", 
        "PROPOSAL", 
        "CONSTRUCTION", 
        "DEFECT-HANDOVER", 
        "AFTERSALE-MAINTENANCE",
        "content"
      ];
      
      const isSpecialKeyword = specialKeywords.some(
        keyword => content.toLowerCase() === keyword.toLowerCase()
      );
      
      return (
        <span 
          className={isSpecialKeyword 
            ? "font-bold text-primary bg-primary/10 px-1 rounded" 
            : "font-bold text-primary"} 
          {...props}
        >
          {children}
        </span>
      );
    },
    
    // Các component khác
    code: ({ node, inline, className, children, ...props }: any) => {
      const match = /language-(\w+)/.exec(className || "");
      return !inline && match ? (
        <pre
          {...props}
          className={`${className} text-sm w-[80dvw] md:max-w-[500px] overflow-x-scroll bg-zinc-100 p-3 rounded-lg mt-2 dark:bg-zinc-800`}
        >
          <code className={match[1]}>{children}</code>
        </pre>
      ) : (
        <code
          className={`${className} text-sm bg-zinc-100 dark:bg-zinc-800 py-0.5 px-1 rounded-md`}
          {...props}
        >
          {children}
        </code>
      );
    },
    ol: ({ node, children, ...props }: any) => {
      return (
        <ol className="list-decimal pl-4" {...props}>
          {children}
        </ol>
      );
    },
    li: ({ node, children, ...props }: any) => {
      return (
        <li className="pl-0 ml-0" {...props}>
          {children}
        </li>
      );
    },
    ul: ({ node, children, ...props }: any) => {
      return (
        <ul className="pl-4" {...props}>
          {children}
        </ul>
      );
    },
    a: ({ node, children, ...props }: any) => {
      return (
        <a
          className="text-blue-500 hover:underline"
          target="_blank"
          rel="noreferrer"
          {...props}
        >
          {children}
        </a>
      );
    },
    h1: ({ node, children, ...props }: any) => {
      return (
        <h1 className="text-3xl font-semibold mt-6 mb-2" {...props}>
          {children}
        </h1>
      );
    },
    h2: ({ node, children, ...props }: any) => {
      return (
        <h2 className="text-2xl font-semibold mt-6 mb-2" {...props}>
          {children}
        </h2>
      );
    },
    h3: ({ node, children, ...props }: any) => {
      return (
        <h3 className="text-xl font-semibold mt-6 mb-2" {...props}>
          {children}
        </h3>
      );
    },
    h4: ({ node, children, ...props }: any) => {
      return (
        <h4 className="text-lg font-semibold mt-6 mb-2" {...props}>
          {children}
        </h4>
      );
    },
    h5: ({ node, children, ...props }: any) => {
      return (
        <h5 className="text-base font-semibold mt-6 mb-2" {...props}>
          {children}
        </h5>
      );
    },
    h6: ({ node, children, ...props }: any) => {
      return (
        <h6 className="text-sm font-semibold mt-6 mb-2" {...props}>
          {children}
        </h6>
      );
    },
    table: ({ node, children, ...props }: any) => {
      return (
        <div className="w-full overflow-x-auto my-4 rounded-lg border border-gray-200 dark:border-zinc-700">
          <table className="w-full border-collapse" {...props}>
            {children}
          </table>
        </div>
      );
    },
    thead: ({ node, children, ...props }: any) => {
      return (
        <thead className="bg-gray-100 dark:bg-zinc-800" {...props}>
          {children}
        </thead>
      );
    },
    tbody: ({ node, children, ...props }: any) => {
      return (
        <tbody {...props}>
          {children}
        </tbody>
      );
    },
    tr: ({ node, children, ...props }: any) => {
      return (
        <tr className="border-b border-gray-200 dark:border-zinc-700 hover:bg-gray-50 dark:hover:bg-zinc-800/70" {...props}>
          {children}
        </tr>
      );
    },
    th: ({ node, children, ...props }: any) => {
      return (
        <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-200" {...props}>
          {children}
        </th>
      );
    },
    td: ({ node, children, ...props }: any) => {
      return (
        <td className="px-4 py-3 text-gray-800 dark:text-gray-300 break-words" {...props}>
          {children}
        </td>
      );
    }
  };

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {processedContent}
    </ReactMarkdown>
  );
};

export const Markdown = memo(
  NonMemoizedMarkdown,
  (prevProps, nextProps) => prevProps.children === nextProps.children,
);
