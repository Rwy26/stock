#!/usr/bin/env python3
"""
AI Conversation History → Obsidian Converter
=============================================
지원: ChatGPT, Claude, Gemini (Google Takeout), Perplexity, Grok

사용법:
  python ai_to_obsidian.py

내보낸 파일을 C:\\Users\\MOON\\Downloads\\ai-exports\\ 에 넣고 실행하면
D:\\.obsidian\\ai\\conversations\\ 에 자동으로 정리됩니다.

지원 입력 파일:
  - ChatGPT:   conversations.json (Settings > Data Controls > Export)
  - Claude:    conversations.json (Settings > Privacy > Export)
  - Gemini:    Google Takeout ZIP (takeout.google.com → "Gemini Apps Activity" 선택)
  - Perplexity: 수동 복사 후 perplexity_*.json
  - Grok:      수동 복사 후 grok_*.json
"""

import os
import re
import json
import zipfile
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from html.parser import HTMLParser

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
SOURCE_DIR = Path(r"C:\Users\MOON\Downloads\ai-exports")
VAULT_DIR  = Path(r"D:\.obsidian\ai\conversations")

# 자동 주제 분류 키워드 (우선순위 순)
TOPIC_MAP = [
    ("주식·투자",   ["주식", "stock", "투자", "매매", "포트폴리오", "bollinger", "rsi",
                    "kis", "한국투자", "etf", "종목", "코스피", "나스닥", "배당"]),
    ("코딩·개발",   ["python", "javascript", "typescript", "react", "fastapi", "코드",
                    "code", "함수", "api", "backend", "frontend", "git", "docker",
                    "uvicorn", "vite", "mysql", "sql", "debug"]),
    ("AI·머신러닝", ["ai", "머신러닝", "딥러닝", "llm", "gpt", "gemini", "claude",
                    "모델", "학습", "inference", "prompt", "프롬프트", "fine-tuning"]),
    ("비즈니스·사업",["사업", "비즈니스", "스타트업", "수익", "마케팅", "고객", "시장",
                    "경쟁", "브랜드", "수입"]),
    ("건강·음식",   ["음식", "건강", "다이어트", "스마트팜", "농업", "영양", "레시피"]),
    ("여행·일상",   ["여행", "베트남", "이태원", "카페", "맛집", "일상"]),
    ("기타",        []),
]


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────
def safe_filename(text: str, max_len: int = 60) -> str:
    """파일명으로 쓸 수 없는 문자 제거"""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = text.strip(". ")
    return text[:max_len] or "untitled"


def detect_topic(text: str) -> str:
    text_lower = text.lower()
    for topic, keywords in TOPIC_MAP[:-1]:  # 기타 제외
        if any(k in text_lower for k in keywords):
            return topic
    return "기타"


def ts_to_dt(ts) -> datetime:
    if ts is None:
        return datetime.now()
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone()
    except Exception:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
        except Exception:
            return datetime.now()


def write_note(service: str, date: datetime, title: str, topic: str, body: str):
    """Obsidian 마크다운 파일 작성"""
    month_dir = VAULT_DIR / service / date.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{date.strftime('%Y-%m-%d')} {safe_filename(title)}.md"
    fpath = month_dir / fname

    # 중복 방지
    if fpath.exists():
        i = 1
        while fpath.exists():
            fname = f"{date.strftime('%Y-%m-%d')} {safe_filename(title)} ({i}).md"
            fpath = month_dir / fname
            i += 1

    frontmatter = (
        f"---\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        f"date: {date.strftime('%Y-%m-%d')}\n"
        f"service: {service}\n"
        f"topic: {topic}\n"
        f"tags: [ai-chat, {service}, {topic.replace('·', '-')}]\n"
        f"---\n\n"
    )

    fpath.write_text(frontmatter + body, encoding="utf-8")
    return fpath


# ─────────────────────────────────────────────
# ChatGPT 파서
# ─────────────────────────────────────────────
def parse_chatgpt(json_path: Path) -> list[dict]:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    results = []
    for conv in data:
        title    = conv.get("title") or "ChatGPT 대화"
        created  = ts_to_dt(conv.get("create_time"))
        mapping  = conv.get("mapping", {})

        # 메시지를 시간 순으로 정렬
        messages = []
        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            role     = msg.get("author", {}).get("role", "")
            content  = msg.get("content", {})
            parts    = content.get("parts", [])
            text     = "\n".join(str(p) for p in parts if isinstance(p, str) and p.strip())
            if not text or role == "system":
                continue
            msg_time = ts_to_dt(msg.get("create_time"))
            messages.append((msg_time, role, text))

        messages.sort(key=lambda x: x[0])

        body_lines = [f"# {title}\n"]
        full_text  = title
        for _, role, text in messages:
            icon = "**나**" if role == "user" else "**ChatGPT**"
            body_lines.append(f"### {icon}\n{text}\n")
            full_text += " " + text

        results.append({
            "title":   title,
            "date":    created,
            "topic":   detect_topic(full_text),
            "body":    "\n".join(body_lines),
        })
    return results


# ─────────────────────────────────────────────
# Claude 파서
# ─────────────────────────────────────────────
def parse_claude(json_path: Path) -> list[dict]:
    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)

    # 포맷: {"conversations": [...]} 또는 직접 리스트
    data = raw.get("conversations", raw) if isinstance(raw, dict) else raw

    results = []
    for conv in data:
        title   = conv.get("name") or "Claude 대화"
        created = ts_to_dt(conv.get("created_at"))
        msgs    = conv.get("chat_messages", conv.get("messages", []))

        body_lines = [f"# {title}\n"]
        full_text  = title
        for msg in msgs:
            sender = msg.get("sender", msg.get("role", ""))
            text   = msg.get("text", msg.get("content", ""))
            if isinstance(text, list):
                text = "\n".join(t.get("text", "") for t in text if isinstance(t, dict))
            if not str(text).strip():
                continue
            icon = "**나**" if sender in ("human", "user") else "**Claude**"
            body_lines.append(f"### {icon}\n{text}\n")
            full_text += " " + str(text)

        results.append({
            "title":  title,
            "date":   created,
            "topic":  detect_topic(full_text),
            "body":   "\n".join(body_lines),
        })
    return results


# ─────────────────────────────────────────────
# Gemini / Google Takeout HTML 파서
# ─────────────────────────────────────────────
class _GeminiHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.conversations = []
        self._cur = []
        self._capture = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")
        if "conversation-container" in classes or "mdl-card" in classes:
            self._cur = []
            self._capture = True
            self._depth = 0
        if self._capture:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._capture:
            self._depth -= 1
            if self._depth <= 0:
                self.conversations.append("\n".join(self._cur))
                self._cur = []
                self._capture = False

    def handle_data(self, data):
        if self._capture and data.strip():
            self._cur.append(data.strip())


def parse_gemini_html(html_path: Path) -> list[dict]:
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    # 파일명에서 날짜 추출 (Takeout 파일명: YYYY-MM-DD...)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", html_path.name)
    created = ts_to_dt(date_match.group(1) + "T00:00:00") if date_match else datetime.now()

    # 간단한 텍스트 추출 (태그 제거)
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) < 20:
        return []

    # 첫 줄을 제목으로
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = lines[0][:60] if lines else "Gemini 대화"

    body = f"# {title}\n\n" + "\n".join(lines[1:])
    return [{"title": title, "date": created, "topic": detect_topic(text), "body": body}]


def parse_gemini_takeout_zip(zip_path: Path) -> list[dict]:
    results = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        gemini_files = [n for n in names
                        if ("Gemini" in n or "Bard" in n) and
                        (n.endswith(".html") or n.endswith(".json"))]

        for name in gemini_files:
            with zf.open(name) as f:
                content = f.read().decode("utf-8", errors="ignore")

            if name.endswith(".json"):
                try:
                    data = json.loads(content)
                    convs = data if isinstance(data, list) else data.get("conversations", [])
                    for c in convs:
                        title = c.get("title") or "Gemini 대화"
                        created = ts_to_dt(c.get("created_at") or c.get("create_time"))
                        msgs = c.get("messages", c.get("turns", []))
                        body_lines = [f"# {title}\n"]
                        full = title
                        for m in msgs:
                            role = m.get("role", m.get("author", ""))
                            text = m.get("text", m.get("content", ""))
                            if not str(text).strip():
                                continue
                            icon = "**나**" if role in ("user", "human") else "**Gemini**"
                            body_lines.append(f"### {icon}\n{text}\n")
                            full += " " + str(text)
                        results.append({"title": title, "date": created,
                                        "topic": detect_topic(full), "body": "\n".join(body_lines)})
                except Exception:
                    pass
            else:
                # HTML 임시 저장 후 파싱
                tmp = SOURCE_DIR / "_tmp_gemini.html"
                tmp.write_text(content, encoding="utf-8")
                tmp.rename(SOURCE_DIR / f"_tmp_{Path(name).name}")
    return results


# ─────────────────────────────────────────────
# 자동 감지 & 일괄 처리
# ─────────────────────────────────────────────
STATS = defaultdict(int)


def process_file(path: Path):
    name = path.name.lower()
    service = None
    items   = []

    # ── ChatGPT ──
    if name == "conversations.json":
        with open(path, encoding="utf-8") as f:
            try:
                first = json.load(f)
            except Exception:
                return
        # ChatGPT 형식: 리스트, 각 항목에 "mapping" 키
        if isinstance(first, list) and first and "mapping" in first[0]:
            service = "chatgpt"
            items   = parse_chatgpt(path)
        # Claude 형식: dict with "conversations" 또는 리스트 with "chat_messages"
        elif isinstance(first, dict) and "conversations" in first:
            service = "claude"
            items   = parse_claude(path)
        elif isinstance(first, list) and first and "chat_messages" in first[0]:
            service = "claude"
            items   = parse_claude(path)

    # ── 명시적 접두사 ──
    elif name.startswith("claude") and name.endswith(".json"):
        service = "claude"
        items   = parse_claude(path)
    elif name.startswith("perplexity") and name.endswith(".json"):
        service = "perplexity"
        items   = parse_claude(path)  # 유사 구조
    elif name.startswith("grok") and name.endswith(".json"):
        service = "grok"
        items   = parse_claude(path)  # 유사 구조

    # ── Google Takeout ZIP ──
    elif name.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                inner = zf.namelist()
            if any("Gemini" in n or "Bard" in n for n in inner):
                service = "gemini"
                items   = parse_gemini_takeout_zip(path)
            elif any("conversations.json" in n for n in inner):
                # ChatGPT ZIP
                service = "chatgpt"
                with zipfile.ZipFile(path) as zf:
                    with zf.open("conversations.json") as f:
                        tmp = SOURCE_DIR / "_chatgpt_tmp.json"
                        tmp.write_bytes(f.read())
                items = parse_chatgpt(tmp)
                tmp.unlink(missing_ok=True)
        except Exception as e:
            print(f"  ⚠ ZIP 처리 실패: {path.name} — {e}")
            return

    # ── Gemini HTML (단독 파일) ──
    elif name.endswith(".html") and ("gemini" in name or "bard" in name):
        service = "gemini"
        items   = parse_gemini_html(path)

    else:
        return  # 알 수 없는 형식

    if not items:
        print(f"  ⚠ 변환 결과 없음: {path.name}")
        return

    for item in items:
        fp = write_note(service, item["date"], item["title"], item["topic"], item["body"])
        STATS[service] += 1
        print(f"  ✓ [{service}] {fp.name}")


def build_index():
    """서비스별 + 주제별 인덱스 페이지 생성"""
    # 서비스별 인덱스
    for service_dir in VAULT_DIR.iterdir():
        if not service_dir.is_dir():
            continue
        service = service_dir.name
        notes   = sorted(service_dir.rglob("*.md"))
        if not notes:
            continue

        lines = [f"# {service.upper()} 대화 목록\n",
                 f"> 총 {len(notes)}개 대화\n"]

        by_month = defaultdict(list)
        for n in notes:
            month = n.parent.name  # YYYY-MM
            by_month[month].append(n)

        for month in sorted(by_month.keys(), reverse=True):
            lines.append(f"\n## {month}\n")
            for n in sorted(by_month[month]):
                rel = n.relative_to(VAULT_DIR)
                lines.append(f"- [[{rel.as_posix().replace('/', ' / ')} | {n.stem}]]")

        (service_dir / "_index.md").write_text("\n".join(lines), encoding="utf-8")

    # 마스터 인덱스 (주제별)
    all_notes = sorted(VAULT_DIR.rglob("*.md"))
    all_notes = [n for n in all_notes if n.name != "_index.md"]

    by_topic = defaultdict(list)
    for n in all_notes:
        # frontmatter에서 topic 읽기
        try:
            txt = n.read_text(encoding="utf-8")
            m = re.search(r"^topic:\s*(.+)$", txt, re.MULTILINE)
            topic = m.group(1).strip() if m else "기타"
        except Exception:
            topic = "기타"
        by_topic[topic].append(n)

    lines = ["# AI 대화 기록 — 전체 인덱스\n",
             f"> 총 {len(all_notes)}개 대화 | 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
             "\n## 서비스별\n"]
    for svc, cnt in sorted(STATS.items()):
        lines.append(f"- [[{svc}/_index | {svc.upper()}]] — {cnt}개")

    lines.append("\n## 주제별\n")
    for topic in [t for t, _ in TOPIC_MAP]:
        notes = by_topic.get(topic, [])
        if notes:
            lines.append(f"\n### {topic} ({len(notes)}개)\n")
            for n in sorted(notes, reverse=True)[:30]:  # 최신 30개
                rel = n.relative_to(VAULT_DIR)
                svc = rel.parts[0]
                lines.append(f"- [[{rel.as_posix()} | {n.stem}]] `{svc}`")

    (VAULT_DIR / "_index.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📋 마스터 인덱스 생성: {VAULT_DIR / '_index.md'}")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  AI Conversations → Obsidian")
    print("=" * 60)
    print(f"  소스: {SOURCE_DIR}")
    print(f"  대상: {VAULT_DIR}\n")

    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    files = list(SOURCE_DIR.iterdir())
    target_ext = {".json", ".zip", ".html"}
    files = [f for f in files if f.is_file() and f.suffix.lower() in target_ext
             and not f.name.startswith("_")]

    if not files:
        print("⚠  소스 폴더에 변환할 파일이 없습니다.")
        print(f"\n   파일을 여기에 넣고 다시 실행하세요:")
        print(f"   {SOURCE_DIR}\n")
        print("   ChatGPT  → Settings > Data Controls > Export data")
        print("   Claude   → Settings > Privacy > Export data")
        print("   Gemini   → takeout.google.com (Gemini Apps Activity 선택)")
        print("   Grok     → grok.x.com (대화 복사 후 grok_YYYY-MM-DD.json)")
        return

    for f in files:
        print(f"→ 처리 중: {f.name}")
        process_file(f)

    print(f"\n{'─'*60}")
    print("  변환 완료")
    for svc, cnt in sorted(STATS.items()):
        print(f"  {svc:<15} {cnt:>5}개")
    print(f"  {'합계':<15} {sum(STATS.values()):>5}개")
    print(f"{'─'*60}")

    build_index()
    print("\n✅ Obsidian에서 ai/conversations/_index 를 열어보세요.")


if __name__ == "__main__":
    main()
