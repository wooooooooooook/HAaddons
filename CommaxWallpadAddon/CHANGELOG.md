# Changelog

모든 주요 변경 사항이 이 파일에 기록됩니다.

## [1.1.9] - 2024-03-XX

### 변경됨
- WallpadController의 로깅 기능 개선
  - RS485 수신 간격 로깅 주석 처리
  - 바이트 데이터에 대한 디버그 로깅 추가
  - 기기 상태 처리 디버깅 용이성 향상

## [1.1.8] - 2024-03-XX

### 개선됨
- WallpadController의 명령 패킷 생성 로직 리팩토링
  - 명령 구조체의 정수 위치값을 활용한 데이터 할당 방식 개선
    - 기기 ID
    - 명령 타입
    - 설정값
  - 전원 및 온도 설정 명령 처리의 정확성 향상
  - 잘못된 명령 타입에 대한 에러 처리 강화
  - 명령 패킷 생성 프로세스 간소화

## [1.1.7] - 2024-03-XX

### 개선됨
- WallpadController의 기기 상태 처리 로직 개선
  - 온도조절기(Thermo)와 조명(Light) 기기의 상태 처리 간소화
  - 상태 구조체 참조를 통한 바이트 데이터 접근 방식 개선
  - 온도 및 전원 상태에 대한 로깅 기능 강화
  - 명령 패킷 생성의 정확성 향상
  - 기기 상호작용의 유지보수성 및 가독성 개선

## [1.1.6] - 2024-03-XX

### 추가됨
- WallpadController에 초기 MQTT 연결 메소드 구현
  - `connect_mqtt` 메소드 추가로 MQTT 브로커 연결 관리 개선
  - `reconnect_mqtt` 메소드의 로깅 기능 개선
    - 재연결 시도 상태를 더 정확하게 표시
  - MQTT 연결 처리의 안정성 향상

## [1.1.5] - 2024-03-XX

### 개선됨
- WallpadController의 기기 처리 로직 개선
  - device_count가 0일 때 처리를 건너뛰도록 검사 로직 추가
  - 기기 관리의 안정성 향상
  - 컨트롤러 기능의 전반적인 신뢰성 개선

## [1.1.4] - 2024-03-XX

### 변경됨
- WallpadController의 패킷 생성 및 처리 로직 개선
  - `make_command_packet` 메소드 임시 주석 처리 (향후 검토 예정)
  - `generate_expected_state_packet` 메소드 개선
    - 에러 처리 강화
    - 로깅 기능 개선
  - 기기별 상태 패킷 생성 로직 개선
    - 온도조절기(Thermo)
    - 조명(Light)
    - 환기장치(Fan)
  - 디버그 로깅 추가로 패킷 생성 문제 해결 용이성 향상

## [1.1.3] - 2024-03-XX

### 개선됨
- WallpadController의 `process_elfin_data` 메소드 리팩토링
  - 온도조절기(Thermo)와 조명(Light) 기기의 데이터 처리 로직 개선
  - 바이트 데이터 접근 방식 개선 (문자열 인덱스를 정수로 변환)
  - 기기 상태 로깅 기능 강화
  - 타입 힌트 개선으로 코드 가독성 및 유지보수성 향상

## [1.1.2] - 2024-03-XX

### 변경됨
- MQTT 클라이언트 설정 로직 개선
  - `setup_mqtt()` 메소드를 재사용 가능하도록 리팩토링
  - 임시 MQTT 연결과 메인 MQTT 연결 로직 통합
  - Optional 타입 힌트 추가로 타입 안정성 향상

### 개선됨
- 기기 검색 로직 개선
  - 임시 MQTT 클라이언트 연결 후 명시�� 연결 해제 추가
  - 검색 결과 처리 및 저장 로직 구조화

### 제거됨
- 사용하지 않는 기기 관련 메소드 주석 처리
  - `insert_device_index_to_hex()`
  - `update_fan()`
  - `update_outlet_value()`
  - `update_ev_value()`
  - `generate_device_packets()`
  - `make_device_lists()`

### 버그 수정
- 한글 인코딩 관련 문제 수정
- MQTT 재연결 로직 안정성 개선

## [1.1.1] - 2024-03-XX

### 변경됨
- MQTT 클라이언트 설정 로직 개선
  - `setup_mqtt()` 메소드를 재사용 가능하도록 리팩토링
  - 임시 MQTT 연결과 메인 MQTT 연결 로직 통합
  - Optional 타입 힌트 추가로 타입 안정성 향상

### 개선됨
- 기기 검색 로직 개선
  - 임시 MQTT 클라이언트 연결 후 명시적 연결 해제 추가
  - 검색 결과 처리 및 저장 로직 구조화

### 제거됨
- 사용하지 않는 기기 관련 메소드 주석 처리
  - `insert_device_index_to_hex()`
  - `update_fan()`
  - `update_outlet_value()`
  - `update_ev_value()`
  - `generate_device_packets()`
  - `make_device_lists()`

### 버그 수정
- 한글 인코딩 관련 문제 수정
- MQTT 재연결 로직 안정성 개선

## [1.0.0] - 2024-03-XX

### 추가됨
- 최초 릴리스
- 코맥스 월패드 기기 제어 기능
- MQTT 통신 지원
- Home Assistant 통합