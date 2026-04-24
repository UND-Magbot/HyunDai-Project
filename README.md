# 현대 글로비스 RCS (Robot Control System)

AutoXing AMR 로봇 기반 물류 자동화 시스템. 로봇 관제(Convoy 대열 작업), 태블릿 UI, 맵 편집, 이중화 서버 환경을 제공합니다.

---

## 🏗️ 아키텍처

```
┌────────────────────────────────────────────────┐
│  작업자 / 관리자                               │
│  ├─ 태블릿 (Android, AMR 탑재)                 │
│  └─ 웹 관리자 UI (PC)                          │
└──────────────────┬─────────────────────────────┘
                   │ HTTP / WebSocket
                   ▼
            ┌─────────────┐
            │  VIP        │  192.168.10.8
            │  (MCCS)     │  → 활성 노드로 자동 라우팅
            └──────┬──────┘
          ┌────────┴────────┐
          ▼                 ▼
┌─────────────┐      ┌─────────────┐
│  5번 서버   │◄────►│  6번 서버   │
│  (Active)   │ 이중화│  (Standby)  │
│             │      │             │
│ Backend     │      │ Backend     │
│ (FastAPI)   │      │ (FastAPI)   │
│             │      │             │
│ Frontend    │      │ Frontend    │
│ (Next.js)   │      │ (Next.js)   │
│             │      │             │
│ MariaDB     │◄────►│ MariaDB     │
│ (Master)    │Master│ (Master)    │
│             │-Master│             │
│ BSR 복제    │◄────►│ BSR 복제    │
│ (Block)     │디스크│ (Block)     │
└──────┬──────┘      └──────┬──────┘
       │                    │
       └────────┬───────────┘
                │
                ▼
       ┌────────────────┐
       │  AMR 로봇 풀   │
       │  AMR01 ~ AMR06 │  (AutoXing API :8090)
       └────────────────┘
```

---

## 🛠️ 기술 스택

| 계층 | 기술 |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy, uvicorn, websocket-client |
| Frontend | Next.js 14, React, TypeScript, Tailwind CSS |
| Database | MariaDB 10.6 (Master-Master 복제) |
| 컨테이너 | Docker, Docker Compose |
| 이중화 | MCCS (맨텍 클러스터) + BSR (블록 복제) |
| 로봇 API | AutoXing REST API + WebSocket |
| 태블릿 앱 | Android (Kotlin) + WebView |

---

## 📂 디렉토리 구조

```
HyunDai-Project/
├─ BackEnd/                  # FastAPI 백엔드
│  ├─ app/
│  │  ├─ routers/            # API 엔드포인트
│  │  │  ├─ convoy.py        # Convoy 대열 작업
│  │  │  ├─ task.py          # 로봇 작업/태블릿 페이지
│  │  │  ├─ robot.py         # 로봇 관리
│  │  │  ├─ map.py           # 맵 관리
│  │  │  └─ ...
│  │  ├─ robot_api/          # AutoXing 연동
│  │  │  ├─ robot_convoy_service.py    # Convoy 루프/hot-swap
│  │  │  ├─ robot_task_service.py      # 개별 작업 이동
│  │  │  └─ robot_live_service.py      # 실시간 상태
│  │  ├─ crud/               # DB 조회/수정
│  │  ├─ models/             # ORM 모델
│  │  └─ schemas/            # Pydantic 스키마
│  ├─ Dockerfile
│  └─ requirements.txt
│
├─ frontend/                 # Next.js 프론트엔드
│  ├─ app/
│  │  ├─ monitoring/         # 모니터링 페이지
│  │  ├─ map/                # 맵 편집기
│  │  ├─ robots/             # 로봇 관리
│  │  └─ components/
│  └─ Dockerfile
│
├─ scripts/                  # 유틸 스크립트
│  ├─ sync-maps.sh           # 맵 동기화
│  └─ migrate_standby_to_charging.sql (현재 미사용)
│
├─ docker-compose.yml        # 로컬/서버 공통
└─ README.md
```

**별도 저장소**:
- `TabletApp/` — Android 태블릿 앱 (별도 경로 관리)

---

## 🚀 설치 / 실행

### 로컬 개발 환경

**사전 요구사항**
- Docker + Docker Compose
- MariaDB 호스트 설치 (Docker 밖에서 동작 — 컨테이너는 `host.docker.internal` 경유 접속)

**환경 변수** (`.env`)
```
DB_HOST=host.docker.internal
DB_PORT=3306
DB_USER=root
DB_PASSWORD=<비밀번호>
DB_NAME=rcs_db
NEXT_PUBLIC_API_URL=http://192.168.10.8:8000
```

**실행**
```bash
docker compose up -d
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- API 문서: http://localhost:8000/docs

### 서버 배포 (이중화 환경)

```bash
# 로컬에서 빌드
docker compose build backend
docker save hyundai-project-backend:latest -o backend.tar

# 양 서버에 전송
scp backend.tar administrator@192.168.10.5:~/hyundai-project/
scp backend.tar administrator@192.168.10.6:~/hyundai-project/

# 각 서버에서 load + up
cd ~/hyundai-project
docker load -i backend.tar
docker compose up -d backend
```

> 프론트엔드는 서버별 `NEXT_PUBLIC_API_URL` 차이로 **서버별 별도 빌드** 필요.

---

## 🎯 주요 기능

### 1. Convoy 대열 작업
- 여러 AMR이 줄지어 작업(WORK1~6)을 돌며 자재 운반
- 태블릿에서 작업 완료 확인 → 다음 포인트 이동
- 작업 중 배터리 부족 시 자동 복귀 + 대기 풀에서 교체 투입
- 화재 경보 시 SAFE-L/R POI로 자동 대피

### 2. 배터리 로테이션 (자동)
- **1시간 주기 체크** (작업 중): 최저 배터리 로봇 ↔ 대기 풀 최고 배터리 로봇 교체 (5% 마진 이상일 때만)
- **작업 시작 시 1회** (Convoy 시작 60초 후): 대기 장소 로봇을 빈 충전소로 자동 이동
- **정지 시 재배치**: 배터리 낮은 순으로 C1→C2→C3→W1→W2 배정

### 3. Convoy 대상 로봇 자동 추출
- UI에서 각 로봇의 **충전소 드롭다운**만 설정하면 자동으로 Convoy 대상에 포함
- 별도 설정 페이지 불필요
- 스페어 교체 시 드롭다운 2번 조작으로 완료

### 4. 맵 편집기
- POI 배치 (충전소, 대기장소, 작업점, 접근점)
- 라인 연결 (직선/커브)
- 가상벽 (4점 클릭으로 사각형 생성)
- 로봇 맵 ↔ DB 맵 동기화

### 5. 이중화 (HA)
- **VIP** (192.168.10.8) → 활성 노드 자동 라우팅
- **MariaDB Master-Master 복제** (양방향)
- **BSR 블록 복제** (디스크 단위)
- **MCCS** 클러스터 매니저로 장애 자동 감지 및 failover

### 6. 태블릿 앱
- Android WebView + 네이티브 오버레이 버튼
- 서버 연결 실패 시 재연결/설정 UI (네이티브)
- 서버 주소 / 로봇 ID 현장 설정 가능

---

## 🔧 운영 가이드

### 스페어 로봇 교체

```
1. 로봇 관리 페이지 → 기존 로봇 상세 모달 열기
2. 충전소 드롭다운 → "해제 (선택 안 함)" 선택 → 적용
3. 새 로봇 상세 모달 → 충전소 드롭다운 → C3 등 빈 자리 선택 → 적용
4. Convoy 시작 버튼 클릭
```

### 서버 장애 시 수동 전환 (MCCS 자동 실패 시)

```
1. MCCS 콘솔에서 Docker_RG 그룹 상태 확인
2. 활성 노드에서 Clear Fault + Flush + Online 수행
3. 또는 직접 명령:
   - BSR Primary 승격 (한쪽만)
   - Docker 컨테이너 기동
```

### 일상 점검

```bash
# 복제 상태 (양쪽 서버)
mysql -u root -p<비번> -h 172.17.0.1 -e "SHOW SLAVE STATUS\G" | \
  grep -E "Slave_IO_Running|Slave_SQL_Running|Seconds_Behind_Master|Last_Error"

# WS 무응답 빈도 (최근 1시간)
docker compose logs backend --since 1h 2>&1 | grep "무응답" | wc -l

# MariaDB 에러 로그
sudo tail -30 /DB/docker1.err  # 5번
sudo tail -30 /DB/docker2.err  # 6번
```

### 정상 기준

| 항목 | 정상 값 |
|---|---|
| Slave_IO_Running | Yes |
| Slave_SQL_Running | Yes |
| Seconds_Behind_Master | 0 ~ 낮은 숫자 |
| Last_Error | (비어있음) |
| WS 무응답 (1h) | 0 ~ 2건 |
| DNS 역조회 경고 | 0건 |

---

## 📝 최근 주요 업데이트

### 2026.04.23 — DB 장애 복구 (DNS 역조회 원인)
- MariaDB `skip-name-resolve` 설정 추가 (양쪽 서버)
- `binlog_format = ROW` 로 복제 안정성 향상
- 불필요 anonymous user 정리

### 2026.04.16~22 — Convoy 운영 개선
- Convoy 대상 로봇 DB 자동 추출 (`robots_config` JSON 의존 제거)
- 로봇 드롭다운 "해제" 옵션 추가
- 배터리 교체 5% 마진 판정
- Hot-swap 시 최고 배터리 로봇 자동 선택
- 작업 시작 시 W→빈 C 자동 이동 (60초 뒤, 실패 시 5분 재시도)
- 정지 시 배터리 기반 자동 재배치

### 2026.04.19 — 태블릿 앱 네이티브화
- WebView 위 네이티브 오버레이 버튼 (홈 / 설정)
- 서버 연결 실패 시 에러 오버레이 + 재연결/설정 UI

### 2026.04.15 이전 — 초기 기능
- MariaDB Master-Master 이중화 구성
- Convoy 도착 검증 개선
- 비상정지 → 일시정지 방식 전환
- 태블릿 확인 버튼 쿨다운
- Docker 로그 로테이션

---

## 📚 참고

- **노션**: [현대 글로비스 RCS 개발](https://www.notion.so/RCS-30267b13b837801b8954cd166b1e7c8d) — 상세 보고서 및 작업 이력
- **API 문서**: 로컬 개발 시 `/docs` 경로 (FastAPI 자동 생성)

---

## 👥 참여자

Noah, Jinny, Chris, Mathew
