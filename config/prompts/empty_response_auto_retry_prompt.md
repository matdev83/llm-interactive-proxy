### Empty Response Recovery Prompt

**Context:**  
An **empty response** was just detected -- meaning the assistant produced neither text nor tool calls.  
This is unexpected and can break the agent loop.

**Instruction to model:**  
- Never produce an empty response again.  
- Always return at least one of:
  1. A **text reply** addressing the last user prompt,  
  2. A **tool call**,  
  3. Or both.  
- If a tool call is invalid, unavailable, or fails -> fall back to a text reply.  
- Keep answers concise, factual, and on-topic.

**Recovery steps:**  
1. Reflect briefly on why the last message was empty.  
2. Restate the user’s last request in one sentence to confirm understanding.  
3. Provide a valid response: tool call(s), text, or both.  
4. Double-check before sending that the reply is **not empty**.

**Fallback rule (never violate):**  
If no valid tool call can be made, output a short text reply instead.  
At minimum, the message must contain a one-sentence textual reply.

**Reminder:**  
Empty output is never acceptable -- always generate either a reply body, tool call, or both.
