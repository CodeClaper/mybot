import { MessageBubble } from "@/components/MessageBubble";
import { ThinkingBlock } from "@/components/thread/ThinkingBlock";
import type { UIMessage } from "@/lib/types";

interface ThreadMessagesProps {
  messages: UIMessage[];
  isStreaming?: boolean;
}

export function ThreadMessages({ messages, isStreaming = false }: ThreadMessagesProps) {
  const lastMessage = messages[messages.length - 1];
  const assistantReplied = lastMessage?.role === "assistant";
  const showThinking = isStreaming && !assistantReplied;

  return (
    <div className="flex w-full flex-col gap-5">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {showThinking && <ThinkingBlock variant="card" />}
    </div>
  );
}
