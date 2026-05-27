ClaimLens 약제 심사 지원 Streamlit 프로그램
==========================================

포함 파일
- app.py: 프로그램 본체
- seed_data.json: 초기 약제 예시 데이터(씨엠쿨산 포함)
- requirements.txt: 설치 패키지 목록
- README.md: 기능 및 운영 안내
- .streamlit/config.toml: 화면 테마 설정
- .streamlit/secrets.toml.example: 관리자 및 AI 설정 예시

실행 방법
1. 압축을 풉니다.
2. PowerShell 또는 터미널에서 압축을 푼 폴더로 이동합니다.
3. 아래 명령을 실행합니다.

   python -m pip install -r requirements.txt
   streamlit run app.py

관리자 설정
- .streamlit/secrets.toml.example 파일을 참고하여 배포 환경에서
  ADMIN_PASSWORD를 설정해야 관리자 업로드 메뉴를 사용할 수 있습니다.
- OPENAI_API_KEY를 설정하면 AI 보조 검토 기능을 사용할 수 있습니다.

운영 전 주의
- 포함된 약제 자료는 화면 및 업무 흐름 구현 예시입니다.
- 실제 운영 전 최신 HIRA/MFDS/DUR 공식 자료와 심사 전문가 검수를
  반드시 반영해야 합니다.
