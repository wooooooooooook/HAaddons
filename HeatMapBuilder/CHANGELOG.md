# Changelog

[0.4.2]
- arm64(aarch64) 아키텍처 환경 빌드 속도 대폭 향상 (numpy, scipy, matplotlib, shapely, pillow 등의 무거운 패키지들을 Alpine pre-compiled 패키지로 설치하도록 변경)

[0.4.1]
- 이미지 캐싱 등으로 인해 발생하는 로드 레이스 컨디션 및 TypeError 에러 수정 (Cannot read properties of null (reading 'style') 해결)
- 레이블 아이콘 설정이 없는 경우(null) 발생하는 센서 불러오기 실패 오류 수정
- Home Assistant Entity Registry 조회 실패 시 센서 목록 전체가 누락되던 필터링 조건 버그 수정

[0.4.0]
- 사용할 수 없는 센서 위치에 삼각형 경고 아이콘(!) 및 상태 표시 기능 추가
- 상태 조회가 불가능하거나 누락된 센서에 대한 예외 처리 개선

[0.2.0]
- GIF 애니메이션 생성 기능 설정 UI 추가
- 이미지 로테이션 처리 중 에러 발생 최소화

[0.1.3]
- aarch64(라즈베리파이) 아키텍쳐 지원

[0.1.2]
- 설정탭 오류들 수정
- 일부 단위가 바뀐 설정들이 있습니다. 생성되는 맵 확인하시고 다시 설정이 필요할 수 있습니다.