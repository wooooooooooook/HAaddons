# Changelog

모든 주요 변경 사항이 이 파일에 기록됩니다.

## [1.3.4] - 2024-12-21

### 변경됨
- 기기 상태 관리 개선
  - devices_and_packets_structures.yaml에서 전원 상태 값을 "on"에서 "idle"로 변경

### 개선됨
- WallpadController 기능 강화
  - 상태 처리 로직 개선
  - 액션 상태 관리 기능 추가
  - 온도 업데이트에 대한 로깅 개선

## [1.3.3] - 2024-12-20

### 변경됨
- 애드온 구성 및 성능 개선
  - 애드온 이름을 "COMMAX Wallpad Addon by ew11-mqtt"로 변경
  - 성능 향상을 위해 max_send_count를 15로 증가하고 mqtt_log 비활성화
  - devices_and_packets_structures.yaml 파일을 /share 디렉토리에 복사하도록 Dockerfile 수정

### 개선됨
- WallpadController의 파일 처리 기능 강화
  - /share 디렉토리에서 우선적으로 devices_and_packets_structures.yaml 로드
  - 기본 경로로의 폴백 메커니즘 구현
  - 파일 작업에 대한 에러 처리 개선
  - 기기 구조 로딩 및 에러 시나리오에 대한 로깅 개선

## [1.3.2] - 2024-12-20

### 개선됨
- devices_and_packets_structures.yaml 파일 구조 개선 및 WallpadController 필드 위치 처리 강화
  - 잠재적 충돌 방지를 위해 다양한 기기의 fieldPositions 섹션 주석 처리
  - 기기 구조를 기반으로 한 fieldPositions 자동 생성 구현으로 일관성 향상
  - 필드 위치 생성 중 중복 필드명에 대한 에러 로깅 추가

## [1.3.0] - 2024-12-19

### 개선됨
- WallpadController의 MQTT 명령 처리 및 데이터 핸들링 강화
  - `publish_mqtt` 메소드가 Any 타입 값을 허용하도록 개선
  - 메모리 최적화를 위한 수집 데이터 크��� 제한 (최근 100개 항목으로 제한)
  - `process_queue` 메소드의 응답 처리 개선
    - 예상 상태 정보 검증 강화
    - 명령 재전송 시 에러 처리 개선
    - 성능 향상을 위한 최대 전송 횟수 설정 조정
  - 명령 전송 및 에러 상태에 대한 로깅 명확성 향상

## [1.3.1] - 2024-03-20

### 개선됨
- WallpadController의 예상 상태 처리 로직 개선
  - ExpectedStatePacket TypedDict 도입으로 예상 상태 표현 명확화
  - QueueItem의 expected_state를 새로운 ExpectedStatePacket 타입으로 업데이트
  - `generate_expected_state_packet` 메소드가 ExpectedStatePacket을 반환하도록 수정하여 타입 안정성 강화
  - `process_queue`의 예상 상태 응답에 대한 검증 및 에러 처리 개선
  - 명령 재전송 로직 및 로깅 최적화로 성능 및 가독성 향상

## [1.2.9] - 2024-12-19

### 개선됨
- WallpadController의 `generate_expected_state_packet` 메소드 개선
  - 반환 타입을 Optional[str]에서 Union[dict, None]으로 변경하여 명확성 향상
  - 예상 패킷과 필요한 바이트 위치를 포함하는 딕셔너리 반환 구조로 변경
  - 불필요한 디버그 로깅 제거로 코드 간소화
- `process_queue_and_monitor` 메소드의 sleep 시간 조정으로 성능 개선

## [1.2.8] - 2024-12-19

### 개선됨
- WallpadController의 MQTT 연결 처리 강화
  - 메인 이벤트 루프 미실행 시 에러 로깅 추가
  - MQTT 연결 성공 확인 후 이벤트 설정하도록 개선
  - 연결 상태 관리의 안정성 향상

## [1.2.7] - 2024-12-19

### 개선됨
- WallpadController의 명령 처리 및 로깅 개선
  - 명령 타입 검사 로직 단순화
  - 전원 및 온도 설정에 대한 상태 패킷 업데이트 개선
  - 에러 처리 강화
  - 디버깅을 위한 로깅 명확성 향상

## [1.2.6] - 2024-12-19

### 개선됨
- WallpadController의 명령 패킷 처리 로직 개선
  - 기기 구조체 필드 접근 방식 간소화
  - 온도조절기(Thermo) 기기의 하드코딩된 카운트 제거
  - 명령 및 상태 패킷 생성 로직 명확성 향상
  - 기기 호작용 리 방식 단순화

## [1.2.5] - 2024-12-19

### 변경됨
- YAML 설정의 기기 구조체 표준화
  - 명명 규칙 통일
  - 향후 사용을 위한 빈 필드 추가
- MQTT 연결 타임아웃 최적화
  - 연결 타임아웃을 30초에서 5초로 단축
  - 패킷 생성 관련 에러 로깅 강화
  - 기기 설정의 일관성 개선
  - 연결 처리 안정성 향상

## [1.2.4] - 2024-12-19

### 개선됨
- WallpadController의 MQTT 연결 관리 강화
  - keepalive 간격 및 타임아웃 관리 추가
  - 연결 상태 확인을 위한 30초 타임아웃 구현
  - MQTT 브로커 연결 시 안정성 향상
  - 연결 상태 로깅 명확성 개선

## [1.2.3] - 2024-12-19

### 개선됨
- WallpadController의 명령 패킷 생성 로직 간소화
  - 기기 ID, 명령 타입, 값 위치에 대한 불필요한 정수 변환 제거
  - 명령 구조체 처리 방식 개선
  - 코드 가독성 및 유지보수성 향상
  - 기기 상호작용의 정확성 개선

## [1.2.2] - 2024-12-19

### 변경됨
- YAML 구조체 개선
  - 여러 기기의 전원 값에 대한 일관된 따옴표 처리
  - devices_and_packets_structures.yaml 파일 구조 정리
- MQTT 연결 에러 처리 강화
  - 연결 시도 시 에러 처리 개선
  - 로깅 및 흐름 제어 기능 향상

## [1.2.1] - 2024-12-19

### 개선됨
- WallpadController의 MQTT 연결 처리 강화
  - MQTT 연결 성공/실패에 대한 이벤트 관리 추가
  - 연결 상태에 대한 로깅 개선
  - 메인 루프 실행 전 MQTT 연결 대기 로직 추가
  - MQTT 작업의 안정성 및 명확성 향상

## [1.1.9] - 2024-12-19

### 변경됨
- WallpadController의 로깅 기능 개선
  - RS485 수신 간격 로깅 주석 처리
  - 바이트 데이터에 대한 디버그 로깅 가
  - 기기 상태 처리 디버깅 용���성 향상

## [1.1.8] - 2024-12-19

### 개선됨
- WallpadController의 명령 패킷 생성 로직 리팩토링
  - 명령 구조체 정수 위치값을 활용한 데이터 할당 방식 개선
    - 기기 ID
    - 명령 타입
    - 설정값
  - 전원 및 온도 설정 명령 처리의 정확성 향상
  - 잘못된 명령 타입에 대한 에러 처리 강화
  - 명령 패킷 생성 프로세스 간소화

## [1.1.7] - 2024-12-19

### 개선됨
- WallpadController의 기기 상태 처리 로직 개선
  - 온도조절기(Thermo)와 조명(Light) 기기의 상태 처리 간소화
  - 상태 구조체 참조를 통해 바이트 데이터 접근 방식 개선
  - 온도 및 전원 상태에 대한 로깅 기능 강화
  - 명령 패킷 생성의 정확성 향상
  - 기기 상호작용의 유지보수성 및 가독성 개선

## [1.1.6] - 2024-12-19

### 추가됨
- WallpadController에 초기 MQTT 연결 메소드 구현
  - `connect_mqtt` 메소드 추가로 MQTT 브로커 연결 관리 개선
  - `reconnect_mqtt` 메소드의 로깅 기능 개선
    - 재연결 시도 상태를 더 정확하게 표시
  - MQTT 연결 처리의 안정성 향상

## [1.1.5] - 2024-12-19

### 개선됨
- WallpadController의 기기 처리 로직 개선
  - device_count가 0일 때 리를 건너뛰도록 검사 로직 추가
  - 기기 관리의 안정성 향상
  - 컨트롤러 기능의 전반적인 신뢰성 개선

## [1.1.4] - 2024-12-19

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

## [1.1.3] - 2024-12-19

### 개선됨
- WallpadController의 `process_elfin_data` 메소드 리팩토링
  - 온도조절기(Thermo)와 조명(Light) 기기의 데이터 처리 로직 개선
  - 바이트 데이터 접근 방식 개선 (자열 인덱스를 정수로 변환)
  - 기기 상태 로깅 기능 강화
  - 타입 힌트 개선으로 코드 가독성 및 유지보수성 향상

## [1.1.2] - 2024-12-19

### 변경됨
- MQTT 클라이언트 설정 로직 개선
  - `setup_mqtt()` 메소드를 재사용 가능하도록 리팩토링
  - 임시 MQTT 연결과 메인 MQTT 연결 로직 통합
  - Optional 타입 힌트 추가로 타입 안정성 향상

### 개선됨
- 기기 검색 로직 개
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

## [1.1.1] - 2024-12-19

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

## [1.0.0] - 2024-12-19

### 추가됨
- 최초 릴리스
- 코맥스 월패드 기기 제어 기능
- MQTT 통신 지원
- Home Assistant 통합
