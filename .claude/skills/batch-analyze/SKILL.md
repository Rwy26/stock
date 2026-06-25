# 배치 분석 실행 (batch-analyze)

MOON STOCK 전 종목 배치 AI 분석을 자율 실행한다.

## 실행 규칙

1. 백엔드 헬스 확인: `GET http://127.0.0.1:5001/health` → 실패 시 중단 후 보고
2. `backend/.venv/Scripts/python.exe scripts/batch_analyze.py` 실행
3. **청크별 중간 보고 없이** 전 종목 완료까지 자율 진행
4. 실패 종목은 원인 진단 후 자동 재시도 (cp949 오류, 타임아웃, API 에러 구분)
5. 완료 후 단 1회 요약 보고: 성공/실패 건수 + 실패 원인 목록

## Python 규칙
- 모든 파일 I/O에 `encoding='utf-8'`
- LLM 타임아웃 최소 300초
- groq 폴백 프롬프트는 TPM 한도 이내로 슬림화

## 보고 형식
```
배치 분석 완료
  성공: N종목
  실패: M종목 (원인: ...)
  소요시간: X분
```
