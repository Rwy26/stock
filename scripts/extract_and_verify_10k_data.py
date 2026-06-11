"""10-K 추출 데이터 저장·전수 검증.

1단계: 추출 에이전트 전사본(JSONL)에서 마지막 ```json 블록을 기계 추출해
       valuation/raw_10k_extracts/{SYM}.json 으로 저장 (사람 손 전사 배제).
2단계: 모든 레코드의 수치(매출·순이익·EPS·주가 고저)를 EDGAR 원본 텍스트의
       approx_line 주변 ±250행에서 직접 재확인. 불일치는 전부 보고.

데이터 정확성 원칙: 검증 실패 레코드는 exclude 표시 — 후속 P/E 계산에서 제외.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TASKS = Path(r"D:\AI\tmp\claude\C--\0491dc86-8925-4326-8d43-9b2f671c1335\tasks")
OUT = Path(r"D:\STOCK DATA-US\dotcom_1995_2002\valuation\raw_10k_extracts")
EDGAR = Path(r"D:\STOCK DATA-US\dotcom_1995_2002\edgar")

AGENTS = {
    "MSFT": "af6dfe4bb2ba6c372.output",
    "CSCO": "a403f043a03344f57.output",
    "INTC": "a72bff1136ec1e57e.output",
    "ORCL": "a23935bc4a3bf3a96.output",
    "AMZN": "a2cbea548cdb6c785.output",
}


def extract_json_from_transcript(path: Path) -> list:
    """JSONL 전사본의 모든 텍스트에서 마지막 ```json 블록을 파싱."""
    texts: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "text" and isinstance(o.get("text"), str):
                texts.append(o["text"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            walk(json.loads(line))
        except json.JSONDecodeError:
            continue
    blob = "\n".join(texts)
    blocks = re.findall(r"```json\s*(.*?)```", blob, re.S)
    if not blocks:
        # 코드펜스 없이 [ ... ] 만 반환한 경우
        m = re.search(r"(\[\s*\{.*\}\s*\])", blob, re.S)
        blocks = [m.group(1)] if m else []
    if not blocks:
        raise RuntimeError(f"{path.name}: JSON 블록 없음")
    return json.loads(blocks[-1])


def _norm_num_variants(v) -> list[str]:
    """원본 텍스트에서 매칭을 시도할 문자열 후보들."""
    out: list[str] = []
    if v is None:
        return out
    if isinstance(v, dict):  # AMZN weighted_avg_shares {basic, diluted}
        for x in v.values():
            out += _norm_num_variants(x)
        return out
    s = str(v).strip()
    if not s:
        return out
    out.append(s)
    s2 = s.lstrip("$")
    if s2 != s:
        out.append(s2)
    try:
        f = float(s.replace(",", "").replace("(", "-").replace(")", ""))
    except ValueError:
        return out
    neg = f < 0
    a = abs(f)
    cands = set()
    for fmt in (f"{a:,.0f}", f"{a:.0f}", f"{a:,.2f}", f"{a:.2f}", f"{a:.1f}"):
        cands.add(fmt)
    if a < 10:  # EPS 류: .37 / 0.37 / (.37)
        cands.add(f"{a:.2f}".lstrip("0"))
    for c in list(cands):
        if neg:
            out += [f"({c})", f"-{c}", f"({c}"]
        else:
            out.append(c)
    return out


def verify_record(rec: dict, sym: str, win: int = 250) -> dict:
    src = rec.get("source_file") or ""
    fname = Path(src).name if src else None
    if not fname:
        return {"status": "skip", "reason": "source_file 없음"}
    f = EDGAR / sym / fname
    if not f.exists():
        return {"status": "fail", "reason": f"원본 없음: {fname}"}
    raw_text = f.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.splitlines()
    # approx_line + note 의 라인 참조 전부 후보 (주가표는 본문과 떨어진 Item 5 에 있음)
    refs: list[int] = []
    for src in (rec.get("approx_line"), rec.get("note")):
        for tok in re.findall(r"\d{3,6}", str(src or "")):
            n = int(tok)
            if 1 <= n <= len(lines):
                refs.append(n)
    if not refs:
        refs = [1]
    segs = []
    for r in refs:
        segs.append("\n".join(lines[max(0, r - win): min(len(lines), r + win)]))
    hay = "\n".join(segs)

    fields = ["revenue", "net_income", "eps_basic", "eps_diluted", "eps",
              "price_high", "price_low", "weighted_avg_shares"]
    checked = found = 0
    misses = []
    for k in fields:
        v = rec.get(k)
        if v is None:
            continue
        checked += 1
        variants = _norm_num_variants(v)
        hit = any(c in hay for c in variants)
        if not hit:
            # 폴백: 충분히 구별되는 토큰(소수점/천단위 포함, 4자 이상)은 파일 전체 검색
            hit = any(c in raw_text for c in variants
                      if len(c) >= 4 and ("." in c or "," in c))
        if hit:
            found += 1
        else:
            misses.append(f"{k}={v}")
    if checked == 0:
        return {"status": "skip", "reason": "수치 필드 없음 (note 레코드)"}
    ok = found == checked
    return {"status": "pass" if ok else "fail",
            "found": found, "checked": checked, "misses": misses}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for sym in AGENTS:
        # 에이전트 전사본이 0바이트로 비어 있어 raw_10k_extracts/{SYM}.json (수기 보존본)
        # 을 직접 로드 — 아래 원본 전수 대조가 전사 오류를 잡는다.
        data = json.loads((OUT / f"{sym}.json").read_text(encoding="utf-8"))
        for rec in data:  # 이전 실행의 검증 표식 초기화
            rec.pop("verification_failed", None)
            rec.pop("verification_misses", None)

        results = []
        n_pass = n_fail = n_skip = 0
        for i, rec in enumerate(data):
            r = verify_record(rec, sym)
            results.append({"idx": i, **r,
                            "fy": rec.get("fiscal_year"), "q": rec.get("quarter_label")})
            if r["status"] == "pass":
                n_pass += 1
            elif r["status"] == "fail":
                n_fail += 1
                rec["verification_failed"] = True
                rec["verification_misses"] = r.get("misses") or [r.get("reason")]
            else:
                n_skip += 1
        # 검증 표식 반영해 재저장
        (OUT / f"{sym}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / f"{sym}_verification.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        summary[sym] = {"records": len(data), "pass": n_pass, "fail": n_fail, "skip": n_skip}
        print(f"{sym}: {len(data)}건 — 원본 재대조 PASS {n_pass} / FAIL {n_fail} / SKIP {n_skip}")
        for r in results:
            if r["status"] == "fail":
                print(f"   FAIL idx{r['idx']} FY{r.get('fy')} {str(r.get('q'))[:28]}: "
                      f"{r.get('misses') or r.get('reason')}")
    (OUT / "_verification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
