# AI 개발 적합성 진단 리포트 (Windows)

작성일: 2026-03-18

## 결론 (요약)
이 PC는 **로컬 AI 개발(LLM/CV/추천/강화학습 등)용으로 “충분히 적합”** 합니다.
- 강점: **RTX 3070 Ti Laptop (VRAM 8GB)** + **RAM 32GB** + **NVMe SSD 2개(약 512GB/1TB)**
- 현재 상태: **PyTorch CUDA 정상 동작(행렬곱 테스트 통과)**
- 주의: VRAM 8GB라서 대형 모델(예: 13B 이상 FP16) “풀 파인튜닝”은 제한적이며, **4/8-bit 양자화, LoRA/QLoRA, offload, 작은 배치**가 현실적인 선택입니다.

## 시스템 스냅샷 (진단 근거)
- 모델: HP OMEN by HP Gaming Laptop 16-n0xxx
- OS: Windows 11 Pro (Build 26200)
- CPU: AMD Ryzen 7 6800H (8C/16T)
- RAM: 32GB
- GPU:
  - NVIDIA GeForce RTX 3070 Ti Laptop GPU (VRAM 8192MiB)
  - AMD Radeon(TM) Graphics (iGPU)
- 디스크:
  - NVMe 512GB (OS)
  - NVMe 1TB (데이터)
- 드라이버/런타임:
  - NVIDIA Driver 581.83
  - PyTorch 2.6.0+cu124 / CUDA 사용 가능(True)

### 생성된 로컬 로그(참고)
아래 로그 파일은 `logs/`에 생성되며 `.gitignore`로 커밋되지 않습니다(로컬 참고용).
- `logs/ai-dev-audit-20260318-124836.txt`
- `logs/storage-report-20260318-125019.txt`
- `logs/check-env-20260318-125127.txt`
- `logs/ai-gpu-test-20260318-125142.txt`

필요하면 아래 스크립트로 언제든 재생성할 수 있습니다.
- `scripts/ai-dev-audit.ps1`
- `scripts/storage-report.ps1`
- `scripts/check-env.ps1`
- `scripts/ai-gpu-test.ps1`

## AI 개발 관점 평가

### 잘 되는 작업
- PyTorch/Transformers 기반 **추론(inference)**, 실험, 데이터 전처리
- 7B급 모델까지는 **양자화(4/8bit)**, **LoRA/QLoRA** 방식으로 파인튜닝/실험 가능
- CV(객체탐지/분류), 시계열/추천 모델링 등은 로컬에서 충분히 개발 가능

### 병목/제약
- VRAM 8GB: 큰 모델을 FP16으로 올리면 즉시 VRAM 한계 도달
- 노트북 전원/열: 장시간 학습 시 쓰로틀링(클럭 하락) 가능
- WSL/가상화: 현재 WSL이 설치되어 있지 않으며, 필요 시 관리자 권한 설치가 필요

## 시스템 관리 제안 (우선순위)

### 1) 안정성 우선 (실패/잠김/용량 문제 예방)
- **임시폴더(TEMP/TMP)는 항상 접근 가능한 드라이브(C:)**를 기본으로 권장
  - D:를 쓰더라도 “잠김/마운트 문제”가 있으면 개발 도구가 연쇄적으로 실패할 수 있음
- 디스크 여유 공간 유지
  - C:는 현재 여유가 충분하지만(약 396GB free), **학습/데이터셋/모델 캐시로 급격히 줄 수 있음**
  - rule-of-thumb: OS SSD는 최소 20% 이상 여유 권장

### 2) 성능 우선 (학습/추론 성능 개선)
- 전원 계획: 현재 `OMEN Performance`가 활성화되어 있어 적절
  - 장시간 학습 시에는 **전원 어댑터 연결 + 고성능 계획 유지** 권장
- GPU 드라이버는 안정 버전 기준으로 유지(불안정하면 1버전 롤백도 고려)

### 3) 운영 자동화/관측(문제 발견을 빨리)
- Git 자동 저장: 1시간마다 commit+push 작업이 이미 구성됨
- 자동 저장 로그: `logs/git-auto-save.log`
- BitLocker/암호화 상태 감시(재발 방지)
  - `stock-bitlocker-watch` 작업이 일 1회 상태를 `logs/bitlocker-watch.log`에 기록

## 다음 액션(권장 체크리스트)
- [ ] 전원 어댑터 연결 상태에서 GPU 테스트(`scripts/ai-gpu-test.ps1`) 재확인
- [ ] 대형 모델 사용 계획이 있으면: 4-bit/8-bit + LoRA/QLoRA 워크플로우 채택
- [ ] 장시간 학습 시 온도/클럭 모니터링(OMEN Hub 또는 벤더 툴)
- [ ] 캐시/데이터셋 저장 위치 정책 확정(C: 우선, D:는 데이터 전용 권장)
