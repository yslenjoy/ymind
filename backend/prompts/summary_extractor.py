"""
Summary Extractor Prompt - Session Theme & Emotion Extraction
Extracts psychological essence from conversation sessions for cross-session analysis.
"""

PROMPT_VERSION = "v1.5"

SUMMARY_EXTRACTOR_PROMPT = """# Task

Analyze this conversation session and extract its psychological essence.

---

# Input

## Conversation History

{history}

## Extracted Nodes (Thought Graph)

{nodes}

---

# Output Requirements

Return a JSON object with exactly these fields:

```json
{{
  "title": "<session title, in conversation language>",
  "themes": ["theme1", "theme2", "theme3"],
  "emotions": ["emotion1", "emotion2", "emotion3", "emotion4", "emotion5"],
  "summary": "<brief summary, in conversation language>"
}}
```

## Field Specifications

### title (required)
**What to extract**: A concrete, recognizable session title — the user should glance at it and immediately recall what they talked about.

Format:
- 5-15 characters (CN) / 3-8 words (EN), like a chat thread subject
- **MUST match conversation language** — English conversation → English title, Chinese → Chinese
- Describe the SPECIFIC TOPIC discussed, not a psychological diagnosis
- **English titles: Title Case** (capitalize each major word)

✅ Good (CN): "要不要辞职去创业", "AI 会取代设计师吗"
✅ Good (EN): "Titanic and What Love Means", "Should I Quit My PhD", "Fighting With Mom About Moving Out"
❌ Bad (too abstract): "职业转型的深层恐惧", "AI焦虑与创造力的拉扯", "The Neurochemistry of Romance"
❌ Bad (too vague): "我最近在想...", "关于工作的一些思考"
❌ Bad (wrong language): English conversation → "泰坦尼克与爱情观" (WRONG, must be English)

### themes (3 items, required)
**What to extract**: Core **subconscious patterns**, not surface topics.

Format: ALWAYS in English, **Title Case** (capitalize each major word)

✅ Good examples:
- "Fear of Uncertainty"
- "Seeking External Validation"
- "Perfectionism-Induced Procrastination"
- "Self-Worth Tied to Performance"

❌ Avoid surface topics:
- "Work" → instead: "Need for Control at Work"
- "Family" → instead: "Rebelling Against Family Expectations"

### emotions (5 items, required)
**What to extract**: The emotional undertones throughout the conversation.

Format: Single emotion words **in English, Capitalized** (first letter uppercase), e.g.:
- Anxious, Hopeful, Confused, Conflicted, Relieved, Helpless, Curious, Ambivalent, Determined, Doubtful

### summary (1-2 sentences, required)
**What to extract**: A concise snapshot of the session.

Format:
- **MUST match conversation language** — English conversation → English summary
- Start with the core exploration topic
- End with where the user arrived emotionally/mentally
- Keep it under 50 characters (CN) / 25 words (EN)

Example (CN): "探索职业转型的深层恐惧，发现'害怕失败'背后是对自我价值的怀疑。"
Example (EN): "Debated whether Titanic's love story is real love or just a dopamine spike from extreme circumstances."

---

# Language Rule (CRITICAL)

Detect the conversation language from the user messages. Then apply strictly:

- **title**: MUST match conversation language (English conversation → English title). Title Case for English.
- **themes**: ALWAYS in English, Title Case (for cross-session matching)
- **emotions**: ALWAYS in English, Capitalized (for cross-session matching)
- **summary**: MUST match conversation language (English conversation → English summary)

⚠️ NEVER output Chinese title/summary for an English conversation, or vice versa.

---

# Output

Return ONLY the JSON object, no additional text.
""".strip()


def format_history_for_summary(history: list) -> str:
    """Format conversation history for summary prompt."""
    if not history:
        return "(No conversation history)"

    formatted = []
    turn = 0
    for i, msg in enumerate(history):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user":
            turn += 1
            formatted.append(f"[Turn {turn}] User: {content[:500]}...")
        else:
            formatted.append(f"[Turn {turn}] AI: {content[:300]}...")

    return "\n\n".join(formatted)


def format_nodes_for_summary(nodes: list) -> str:
    """Format nodes for summary prompt."""
    if not nodes:
        return "(No nodes extracted)"

    formatted = []
    for node in nodes:
        node_type = node.get("type", "fact")
        label = node.get("label", "")
        summary = node.get("rich_summary", "")

        if node_type == "root":
            continue

        formatted.append(f"- [{node_type}] {label}: {summary[:100]}")

    return "\n".join(formatted) if formatted else "(No nodes extracted)"
