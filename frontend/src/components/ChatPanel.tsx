import { SendOutlined } from "@ant-design/icons";
import { Button, List, Space, Typography, Input, Tag } from "antd";
import { useState } from "react";
import { api } from "../api/client";

interface Message { role: "user" | "assistant"; content: string; sources?: string[]; }

const QUICK_QUESTIONS = [
  "帮我生成一份库存统计报表",
  "20002183 的到货率如何？",
  "最近消耗情况怎么样？",
  "M12螺栓哪个仓库有现货？",
  "哪些物资呆滞超过一年了？",
];

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [value, setValue] = useState("");
  const [sessionId, setSessionId] = useState<string>();
  const send = async (text?: string) => {
    const message = (text ?? value).trim();
    if (!message) return;
    setValue("");
    setMessages((items) => [...items, { role: "user", content: message }]);
    try {
      const result = await api.chat(message, sessionId);
      setSessionId(result.session_id);
      setMessages((items) => [...items, { role: "assistant", content: result.answer, sources: result.sources }]);
    } catch (error) {
      setMessages((items) => [...items, { role: "assistant", content: error instanceof Error ? error.message : "请求失败" }]);
    }
  };
  return <Space direction="vertical" size="middle" style={{ width: "100%" }}>
    <Space size={8} wrap>
      {QUICK_QUESTIONS.map((question) => <Button key={question} size="small" onClick={() => void send(question)}>{question}</Button>)}
    </Space>
    <List size="small" dataSource={messages} locale={{ emptyText: "可以问：到货率、库存统计报表、消耗情况、现货位置、呆滞预警……" }} renderItem={(item) => <List.Item><Space direction="vertical" size={4}><Typography.Text strong>{item.role === "user" ? "我" : "智能助手"}</Typography.Text><Typography.Text>{item.content}</Typography.Text>{item.sources?.length ? <Space size={4} wrap>{item.sources.map((source) => <Tag key={source}>{source}</Tag>)}</Space> : null}</Space></List.Item>} />
    <Input.Search value={value} onChange={(event) => setValue(event.target.value)} onSearch={() => void send()} enterButton={<Button icon={<SendOutlined />}>发送</Button>} placeholder="例如：20002183 的到货率如何？" />
  </Space>;
}
