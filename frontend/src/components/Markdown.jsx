import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// AI output is rendered as Markdown with raw HTML disabled (react-markdown's default).
export default function Markdown({ children }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
