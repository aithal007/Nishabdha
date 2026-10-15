import { useMemo, useState } from "react";
import {
  CopilotKitCoreReact,
  useAgent,
} from "@copilotkit/react-core/v2/headless";
import { CopilotKitContext } from "@copilotkit/react-core/v2/context";
import { HttpAgent } from "@ag-ui/client";
import { ArrowUp, BookOpen, LoaderCircle, ShieldCheck } from "lucide-react";
import { Button } from "./components/ui/button";

function PolicyChat() {
  const { agent, isReady } = useAgent({ agentId: "policy" });
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const submit = async (question: string) => {
    if (!question.trim() || agent.isRunning || !isReady) return;
    setInput("");
    setError("");
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: question.trim(),
    });
    try {
      await agent.runAgent();
    } catch {
      setError(
        "The policy assistant is unavailable. Your agent session has not been changed. Try again.",
      );
    }
  };
  const messages = agent.messages.filter(
    (m) =>
      (m.role === "user" || m.role === "assistant") &&
      "content" in m &&
      typeof m.content === "string",
  );
  return (
    <div className="policy-chat">
      <div className="assistant-scope">
        <ShieldCheck size={16} />
        <span>Reviewed policies only · No account access or action tools</span>
      </div>
      <div className="policy-messages" role="log" aria-live="polite">
        {!messages.length && (
          <div className="policy-welcome">
            <div className="assistant-symbol">
              <BookOpen size={28} />
            </div>
            <h3>
              A clear answer.
              <br />A source you can inspect.
            </h3>
            <p>
              Ask how Nishabdha handles caller evidence, passkeys, and assistant
              permissions.
            </p>
            <div className="policy-prompts">
              {[
                "How do I approve a transfer with a passkey?",
                "How do I verify the agent session?",
                "What can the support assistant delegate do?",
              ].map((q) => (
                <button key={q} disabled={!isReady} onClick={() => submit(q)}>
                  {q}
                  <span>↗</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={"policy-message " + m.role}>
            <div className="lbl">
              {m.role === "user" ? "YOU" : "NISHABDHA POLICY ASSISTANT"}
            </div>
            <div>{"content" in m ? String(m.content) : ""}</div>
          </div>
        ))}
        {agent.isRunning && (
          <div className="policy-thinking" role="status">
            <LoaderCircle size={16} className="spin" /> Finding a reviewed
            source…
          </div>
        )}
        {error && (
          <div role="alert" className="inline-error">
            {error}
          </div>
        )}
      </div>
      <form
        className="policy-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void submit(input);
        }}
      >
        <label className="sr-only" htmlFor="policy-question">
          Ask a policy question
        </label>
        <input
          id="policy-question"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={1000}
          placeholder="Ask about a policy or safety control…"
        />
        <Button
          size="icon"
          aria-label="Send policy question"
          disabled={!input.trim() || agent.isRunning || !isReady}
        >
          <ArrowUp size={18} />
        </Button>
      </form>
      <p className="assistant-disclaimer">
        Answers quote reviewed demo policies. Missing evidence produces an
        abstention.
      </p>
    </div>
  );
}
export default function PolicyAssistant() {
  const context = useMemo(
    () => ({
      copilotkit: new CopilotKitCoreReact({
        agents__unsafe_dev_only: {
          policy: new HttpAgent({
            url: "/api/copilot/policy",
            agentId: "policy",
            description: "Read-only reviewed agent trust policies",
          }),
        },
      }),
      executingToolCallIds: new Set<string>(),
      showIntelligenceIndicator: false,
    }),
    [],
  );
  return (
    <CopilotKitContext.Provider value={context}>
      <PolicyChat />
    </CopilotKitContext.Provider>
  );
}
