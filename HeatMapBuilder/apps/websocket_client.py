import websockets # type: ignore
import json
from typing import Optional, Dict, Any, List
import asyncio
import time
from custom_logger import CustomLogger

class WebSocketClient:
    def __init__(self, supervisor_token: str, logger: CustomLogger):
        self.supervisor_token = supervisor_token
        self.logger = logger
        self.message_id = 1
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.reconnect_attempt = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5
        self._connection_lock = None  # 초기에는 Lock을 생성하지 않고 None으로 설정
        self._event_loop = None       # 이벤트 루프 참조 저장
        self._keepalive_tasks = set()  # keepalive 태스크 추적용

    async def _get_connection_lock(self):
        """현재 이벤트 루프에 맞는 connection lock을 반환합니다."""
        current_loop = asyncio.get_running_loop()
        
        # 이벤트 루프가 변경되었거나 lock이 없는 경우 새로 생성
        if self._connection_lock is None or self._event_loop != current_loop:
            self.logger.trace("현재 이벤트 루프에 맞는 새 connection lock 생성")
            self._connection_lock = asyncio.Lock()
            self._event_loop = current_loop
            
        return self._connection_lock

    def _truncate_log_message(self, message: str, max_length: int = 100) -> str:
        """로그 메시지를 지정된 길이로 잘라서 반환합니다."""
        if len(message) <= max_length:
            return message
        return message[:max_length] + "..."

    async def _cleanup_keepalive_tasks(self):
        """keepalive 태스크들을 정리합니다."""
        for task in list(self._keepalive_tasks):
            if not task.done():
                self.logger.trace(f"keepalive 태스크 취소 시도: {task}")
                task.cancel()
                try:
                    # 태스크 취소 대기에 3초 타임아웃 추가
                    await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    self.logger.trace(f"keepalive 태스크 취소됨 또는 타임아웃: {task}")
                    pass
                except Exception as e:
                    self.logger.error(f"keepalive 태스크 취소 중 오류: {str(e)}")
            self._keepalive_tasks.discard(task)

    async def _force_cleanup(self):
        """락 획득 타임아웃 발생 시 강제로 자원을 정리합니다."""
        self.logger.warning("웹소켓 연결 강제 정리 시작")
        try:
            # keepalive 태스크 강제 정리
            for task in list(self._keepalive_tasks):
                if not task.done():
                    task.cancel()
                self._keepalive_tasks.discard(task)
                
            # 웹소켓 객체 강제 정리
            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception as e:
                    self.logger.error(f"웹소켓 강제 종료 중 오류: {str(e)}")
                finally:
                    self.websocket = None
            
            self.logger.warning("웹소켓 연결 강제 정리 완료")
        except Exception as e:
            self.logger.error(f"웹소켓 연결 강제 정리 중 오류 발생: {str(e)}")

    async def close(self):
        """웹소켓 연결을 안전하게 종료합니다."""
        self.logger.trace("웹소켓 연결 종료 시작")
        
        # keepalive 태스크들 정리 (락 없이 수행)
        self.logger.trace("웹소켓 연결 종료 중 keepalive 태스크들 정리 시작")
        await self._cleanup_keepalive_tasks()
        self.logger.trace("웹소켓 연결 종료 중 keepalive 태스크들 정리 완료")
        
        # 웹소켓 객체 정리 (락 보호 하에 수행)
        if self.websocket:
            try:
                # 웹소켓 객체 닫기 전에 락 획득
                lock = await self._get_connection_lock()
                try:
                    self.logger.trace("웹소켓 연결 종료 중. async with lock 블록 진입 시도")
                    async with asyncio.timeout(2):  # 2초 타임아웃
                        async with lock:
                            self.logger.trace("웹소켓 연결 종료 중 웹소켓 객체 닫기 시도")
                            if self.websocket:  # 다시 한번 확인
                                await self.websocket.close()
                                self.websocket = None
                                self.logger.trace("웹소켓 객체 닫기 성공")
                except asyncio.TimeoutError:
                    self.logger.error("락 획득 타임아웃 발생, 강제로 진행합니다")
                    await self._force_cleanup()
                except Exception as e:
                    self.logger.error(f"웹소켓 객체 닫기 중 오류 발생: {str(e)}")
                    await self._force_cleanup()
            except Exception as e:
                self.logger.error(f"웹소켓 연결 종료 중 예상치 못한 오류 발생: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())
                await self._force_cleanup()

    async def ensure_connected(self) -> bool:
        """연결 상태를 확인하고 필요한 경우 재연결합니다."""
        websocket_to_check = None
        
        # 현재 웹소켓 객체 가져오기 (락 보호)
        lock = await self._get_connection_lock()
        try:
            async with asyncio.timeout(2):  # 2초 타임아웃
                async with lock:
                    websocket_to_check = self.websocket
        except (asyncio.TimeoutError, Exception) as e:
            self.logger.error(f"웹소켓 상태 확인을 위한 락 획득 실패: {str(e)}")
            websocket_to_check = None
        
        # 연결 상태 확인 (락 없이 수행)
        if websocket_to_check:
            try:
                self.logger.trace("웹소켓 연결 상태 확인 중: ping 시도")
                pong_waiter = await websocket_to_check.ping()
                await asyncio.wait_for(pong_waiter, timeout=2.0)
                self.logger.trace("웹소켓 ping 성공")
                return True
            except asyncio.TimeoutError:
                self.logger.trace("웹소켓 ping 타임아웃, 연결 재시도 필요")
            except Exception as e:
                self.logger.trace(f"웹소켓 ping 실패, 연결 재시도 필요: {str(e)}")

        # 연결이 끊어진 것으로 간주하고 재연결 시도
        self.logger.trace("웹소켓 연결 없음 또는 끊어짐, 재연결 시도 시작")
        await self.close()  # 기존 연결 정리

        self.reconnect_attempt = 0  # 재연결 시도 카운터 초기화
        max_reconnect_time = 30  # 최대 재연결 시도 시간 (초)
        start_time = time.time()
        
        while self.reconnect_attempt < self.max_reconnect_attempts:
            # 최대 재연결 시간 체크
            if time.time() - start_time > max_reconnect_time:
                self.logger.error(f"최대 재연결 시간 초과: {max_reconnect_time}초")
                return False
                
            self.reconnect_attempt += 1
            self.logger.trace(f"웹소켓 재연결 시도 {self.reconnect_attempt}/{self.max_reconnect_attempts}")
            
            try:
                # 연결 시도 시간 측정
                connect_start = time.time()
                self.logger.trace("_connect 메서드 호출 시작")
                
                # 웹소켓 연결 시도
                new_websocket = await asyncio.wait_for(self._connect(), timeout=10.0)
                
                if new_websocket:
                    # 새 웹소켓 객체 설정 (락 보호)
                    try:
                        async with asyncio.timeout(2):  # 2초 타임아웃
                            async with lock:
                                self.websocket = new_websocket
                                connect_time = time.time() - connect_start
                                self.logger.trace(f"웹소켓 재연결 성공 (소요시간: {connect_time:.3f}초)")
                                self.reconnect_attempt = 0
                                return True
                    except (asyncio.TimeoutError, Exception) as e:
                        self.logger.error(f"새 웹소켓 설정을 위한 락 획득 실패: {str(e)}")
                        await new_websocket.close()
                        continue
                
                self.logger.warning(f"웹소켓 재연결 실패: _connect()에서 None 반환 (시도 {self.reconnect_attempt})")
                delay = self.reconnect_delay * (1.5 ** (self.reconnect_attempt - 1))  # 지수 백오프
                self.logger.trace(f"{delay:.1f}초 후 재시도...")
                await asyncio.sleep(delay)
                
            except asyncio.TimeoutError:
                connect_time = time.time() - connect_start
                self.logger.error(f"웹소켓 연결 타임아웃 (소요시간: {connect_time:.3f}초, 시도 {self.reconnect_attempt})")
                delay = self.reconnect_delay * (1.5 ** (self.reconnect_attempt - 1))
                self.logger.trace(f"{delay:.1f}초 후 재시도...")
                await asyncio.sleep(delay)
                
            except Exception as e:
                self.logger.error(f"웹소켓 재연결 시도 중 오류 발생 (시도 {self.reconnect_attempt}): {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())
                delay = self.reconnect_delay * (1.5 ** (self.reconnect_attempt - 1))
                self.logger.trace(f"{delay:.1f}초 후 재시도...")
                await asyncio.sleep(delay)

        self.logger.error("최대 재연결 시도 횟수 초과")
        return False

    async def _connect(self) -> Optional[websockets.WebSocketClientProtocol]:
        websocket = None
        try:
            uri = "ws://supervisor/core/api/websocket"
            self.logger.trace(f"웹소켓 연결 시도: {uri}")
            connect_start = time.time()
            
            try:
                websocket = await websockets.connect(uri, 
                                                   max_size=2**24,
                                                   max_queue=2**10,
                                                   compression=None)
                connect_time = time.time() - connect_start
                self.logger.trace(f"웹소켓 연결 수립 성공 (소요시간: {connect_time:.3f}초)")
            except Exception as conn_err:
                self.logger.error(f"웹소켓 연결 실패: {str(conn_err)}")
                import traceback
                self.logger.error(traceback.format_exc())
                return None
            
            # keepalive 태스크 추적 시작
            if hasattr(websocket, '_keepalive_ping') and websocket._keepalive_ping is not None:
                self._keepalive_tasks.add(websocket._keepalive_ping)
                self.logger.trace("keepalive_ping 태스크 추적 시작")
            if hasattr(websocket, '_keepalive_pong') and websocket._keepalive_pong is not None:
                self._keepalive_tasks.add(websocket._keepalive_pong)
                self.logger.trace("keepalive_pong 태스크 추적 시작")
            
            # 서버로부터 초기 메시지 수신 대기
            self.logger.trace("인증 요청 메시지 수신 대기 중...")
            try:
                auth_required = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                auth_required_data = json.loads(auth_required)
                self.logger.trace(f"수신 메시지: {self._truncate_log_message(auth_required)}")
                
                if auth_required_data.get('type') != 'auth_required':
                    self.logger.error(f"예상치 못한 초기 메시지 타입: {auth_required_data.get('type', '알 수 없음')}")
                    await websocket.close()
                    return None
            except asyncio.TimeoutError:
                self.logger.error("인증 요청 메시지 수신 타임아웃")
                await websocket.close()
                return None
            except Exception as auth_req_err:
                self.logger.error(f"인증 요청 메시지 수신 중 오류: {str(auth_req_err)}")
                import traceback
                self.logger.error(traceback.format_exc())
                await websocket.close()
                return None
            
            # 인증 메시지 보내기
            try:
                auth_message = {
                    "type": "auth",
                    "access_token": self.supervisor_token
                }
                auth_message_str = json.dumps(auth_message)
                self.logger.trace(f"인증 메시지 전송: {self._truncate_log_message(auth_message_str)}")
                await websocket.send(auth_message_str)
            except Exception as auth_send_err:
                self.logger.error(f"인증 메시지 전송 중 오류: {str(auth_send_err)}")
                import traceback
                self.logger.error(traceback.format_exc())
                await websocket.close()
                return None
            
            # 인증 응답 대기
            try:
                self.logger.trace("인증 응답 대기 중...")
                auth_response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                self.logger.trace(f"인증 응답 수신: {self._truncate_log_message(auth_response)}")
                auth_response_data = json.loads(auth_response)
                
                if auth_response_data.get('type') == 'auth_ok':
                    self.logger.trace("웹소켓 인증 성공")
                    return websocket
                else:
                    self.logger.error(f"웹소켓 인증 실패: {auth_response_data.get('type', '알 수 없음')}")
                    await websocket.close()
                    return None
            except asyncio.TimeoutError:
                self.logger.error("인증 응답 대기 타임아웃")
                await websocket.close()
                return None
            except Exception as auth_resp_err:
                self.logger.error(f"인증 응답 처리 중 오류: {str(auth_resp_err)}")
                import traceback
                self.logger.error(traceback.format_exc())
                await websocket.close()
                return None
                
        except asyncio.TimeoutError as e:
            self.logger.error(f"웹소켓 연결 또는 인증 타임아웃: {str(e)}")
            if websocket:
                await websocket.close()
            return None
        except Exception as e:
            self.logger.error(f"웹소켓 연결 실패: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            if websocket:
                await websocket.close()
            return None

    async def send_message(self, message_type: str, **kwargs) -> Optional[Any]:
        # message_id 확인 및 0 또는 음수일 경우 리셋
        if self.message_id <= 0:
            self.logger.warning(f"message_id가 유효하지 않음: {self.message_id}, 1로 리셋합니다")
            self.message_id = 1
        
        # 연결 확인
        connection_success = await self.ensure_connected()
        if not connection_success or not self.websocket:
            self.logger.error(f"웹소켓 연결 실패로 메시지를 보낼 수 없습니다: {message_type}")
            return None
            
        # 메시지 ID 할당
        current_id = self.message_id
        self.logger.trace(f"메시지 ID 할당: current_id={current_id}, 타입={message_type}")
            
        message = {
            "id": current_id,
            "type": message_type,
            **kwargs
        }
        
        # 다음 메시지를 위해 ID 증가
        self.message_id += 1
        
        try:
            # 메시지 전송
            message_str = json.dumps(message)
            self.logger.trace(f"송신 메시지 (ID: {message['id']}, 타입: {message_type}): {self._truncate_log_message(message_str)}")
            
            send_start_time = time.time()
            await self.websocket.send(message_str)
            send_time = time.time() - send_start_time
            
            self.logger.trace(f"메시지 전송 완료 (ID: {message['id']}, 타입: {message_type}, 소요시간: {send_time:.3f}초)")
            
            # 응답 대기 시간 설정 
            timeout = 10.0 
            start_time = time.time()
            
            # 응답 대기 시작 로깅
            self.logger.trace(f"응답 대기 시작 (ID: {message['id']}, 타입: {message_type}, 제한시간: {timeout}초)")
            
            # 응답 수신 대기 루프
            while True:
                # 타임아웃 체크
                elapsed_time = time.time() - start_time
                if elapsed_time > timeout:
                    self.logger.error(f"응답 타임아웃 (ID: {message['id']}, 타입: {message_type}, 제한시간: {timeout}초)")
                    return None
                
                try:
                    # 응답 대기 (짧은 타임아웃으로 여러 번 시도)
                    wait_start_time = time.time()
                    response = await asyncio.wait_for(self.websocket.recv(), 3.0)
                    wait_time = time.time() - wait_start_time
                    
                    self.logger.trace(f"메시지 수신 (소요시간: {wait_time:.3f}초): {self._truncate_log_message(response)}")
                    
                    try:
                        response_data = json.loads(response)
                    except json.JSONDecodeError as json_err:
                        self.logger.error(f"JSON 파싱 오류: {str(json_err)}, 원본: {self._truncate_log_message(response)}")
                        continue
                    
                    # 현재 처리 중인 요청에 대한 응답인지 확인
                    if 'id' in response_data:
                        # 응답 ID 확인
                        if response_data.get('id') == message['id']:
                            total_time = time.time() - start_time
                            
                            if response_data.get('success', True):  # success 필드가 없으면 기본적으로 성공으로 간주
                                result = response_data.get('result')
                                result_size = len(result) if isinstance(result, list) else "N/A"
                                
                                self.logger.trace(f"요청 성공 (ID: {message['id']}, 타입: {message_type}, 총 소요시간: {total_time:.3f}초, 결과 크기: {result_size})")
                                return result
                            else:
                                error_msg = response_data.get('error', {}).get('message', '알 수 없는 오류')
                                self.logger.error(f"웹소켓 요청 실패 (ID: {message['id']}, 타입: {message_type}, 총 소요시간: {total_time:.3f}초): {error_msg}")
                                return None
                        else:
                            # 다른 메시지에 대한 응답인 경우 로깅하고 계속 기다림
                            other_id = response_data.get('id')
                            self.logger.trace(f"다른 메시지 응답 수신 (요청 ID: {message['id']}, 응답 ID: {other_id})")
                    else:
                        # ID가 없는 응답 (이벤트 등)은 로깅만 하고 계속 대기
                        msg_type = response_data.get('type', 'unknown')
                        if msg_type == 'event':
                            event_type = response_data.get('event', {}).get('event_type', '알 수 없음')
                            self.logger.trace(f"이벤트 메시지 수신: {event_type}")
                        else:
                            self.logger.trace(f"ID 없는 메시지 수신 (타입: {msg_type})")
                            
                except asyncio.TimeoutError:
                    # 응답 대기 타임아웃은 오류가 아님 (계속 대기)
                    continue
                    
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.error(f"웹소켓 연결이 닫힘: {str(e)}")
            await self.close()
            return None
        except Exception as e:
            import traceback
            self.logger.error(f"웹소켓 통신 중 오류 발생: {str(e)}")
            self.logger.error(traceback.format_exc())
            await self.close()
            return None

class MockWebSocketClient:
    def __init__(self, config_manager, logger: CustomLogger):
        self.config_manager = config_manager
        self.websocket = True  # 연결된 것으로 간주
        self._event_loop = None
        self._connection_lock = None
        self._mock_data = None
        self.message_id = 1
        self.reconnect_attempt = 0
        self.logger = logger
        self.logger.trace(f"MockWebSocketClient 초기화: message_id={self.message_id}")

    def _truncate_log_message(self, message: str, max_length: int = 100) -> str:
        """로그 메시지를 지정된 길이로 잘라서 반환합니다."""
        if len(message) <= max_length:
            return message
        return message[:max_length] + "..."

    async def _get_connection_lock(self):
        """현재 이벤트 루프에 맞는 connection lock을 반환합니다."""
        current_loop = asyncio.get_running_loop()
        
        # 이벤트 루프가 변경되었거나 lock이 없는 경우 새로 생성
        if self._connection_lock is None or self._event_loop != current_loop:
            self.logger.trace("모의 웹소켓: 현재 이벤트 루프에 맞는 새 connection lock 생성")
            self._connection_lock = asyncio.Lock()
            self._event_loop = current_loop
            
        return self._connection_lock

    async def ensure_connected(self) -> bool:
        """웹소켓 연결 상태를 확인합니다. 모의 클라이언트는 항상 연결된 것으로 간주합니다."""
        self.logger.trace("모의 웹소켓 연결 상태 확인 (항상 True 반환)")
        # 가끔 재연결 과정을 시뮬레이션
        if self.reconnect_attempt > 0:
            self.logger.trace(f"모의 웹소켓 재연결 시도 중 (시도: {self.reconnect_attempt})")
            await asyncio.sleep(0.2)
            self.reconnect_attempt = 0
            self.logger.trace("모의 웹소켓 재연결 성공")
        
        # 간단한 지연 추가
        await asyncio.sleep(0.05)
        return True

    def _get_mock_data(self):
        """mock 데이터를 가져오고 필요한 경우 초기화합니다."""
        if self._mock_data is None:
            self.logger.trace("모의 데이터 초기화 중...")
            self._mock_data = self.config_manager.get_mock_data()
            
            # 온도 센서 데이터가 없거나 모든 값이 0인 경우 기본값 설정
            temp_sensors = self._mock_data.get('temperature_sensors', [])
            
            # float 변환 시 오류 처리
            def is_zero_state(sensor):
                try:
                    return float(sensor.get('state', '0')) == 0
                except (ValueError, TypeError):
                    self.logger.warning(f"숫자로 변환할 수 없는 센서 상태값: {sensor.get('state')}")
                    return True
            
            if not temp_sensors or all(is_zero_state(sensor) for sensor in temp_sensors):
                # 기본 온도값 범위 설정 (20°C ~ 25°C)
                import random
                for sensor in temp_sensors:
                    sensor['state'] = str(round(random.uniform(20, 25), 1))
                    if 'attributes' not in sensor:
                        sensor['attributes'] = {}
                    sensor['attributes']['unit_of_measurement'] = '°C'
                self._mock_data['temperature_sensors'] = temp_sensors
                self.logger.trace(f"기본 온도 센서 데이터 생성: {len(temp_sensors)}개")
        
        return self._mock_data

    async def send_message(self, message_type: str, **kwargs) -> Optional[Any]:
        try:
            # message_id 확인 및 0 또는 음수일 경우 리셋
            if self.message_id <= 0:
                self.logger.warning(f"모의 message_id가 유효하지 않음: {self.message_id}, 1로 리셋합니다")
                self.message_id = 1
            
            # 연결 상태 확인
            await self.ensure_connected()
            
            # 메시지 ID 할당
            current_id = self.message_id
            
            # 메시지 생성
            message_data = {"id": current_id, "type": message_type, **kwargs}
            message_str = json.dumps(message_data)
            
            # 다음 메시지를 위해 ID 증가
            self.message_id += 1
            
            # 메시지 로깅
            self.logger.trace(f"모의 메시지 (ID: {current_id}, 타입: {message_type}): {self._truncate_log_message(message_str)}")
            
            # 간단한 지연 추가 (네트워크 지연 시뮬레이션)
            await asyncio.sleep(0.2)
            
            # 모의 데이터 가져오기
            mock_data = self._get_mock_data()
            
            # 메시지 타입에 따른 응답 생성
            result = None
            
            if message_type == 'auth':
                result = {"type": "auth_ok", "id": current_id}
            elif message_type == 'get_states':
                result = mock_data.get('temperature_sensors', [])
            elif message_type == 'config/entity_registry/list':
                result = mock_data.get('entity_registry', [])
            elif message_type == 'config/label_registry/list':
                result = mock_data.get('label_registry', [])
            
            # 결과 로깅
            result_size = len(result) if result and isinstance(result, list) else 0
            self.logger.trace(f"모의 응답 (ID: {current_id}, 타입: {message_type}, 결과 크기: {result_size})")
            
            return result
            
        except Exception as e:
            import traceback
            self.logger.error(f"모의 웹소켓 통신 중 오류 발생 (타입: {message_type}): {str(e)}")
            self.logger.error(traceback.format_exc())
            return None
            
    async def _connect(self):
        """웹소켓 연결을 시도합니다. MockWebSocketClient의 경우 항상 성공으로 처리합니다."""
        self.logger.trace("모의 웹소켓 _connect 호출됨")
        
        # 모의 연결 지연 시뮬레이션
        await asyncio.sleep(0.1)
        
        # 연결 확인
        await self.ensure_connected()
        
        # 모의 웹소켓은 항상 True를 웹소켓 객체로 사용
        self.websocket = True
        self.logger.trace("모의 웹소켓 연결 수립 성공")
        
        return self.websocket

    async def close(self):
        self.logger.trace("모의 웹소켓 연결 종료")
        self.websocket = None
        
        # 현재 이벤트 루프에 맞는 lock 가져오기
        try:
            lock = await self._get_connection_lock()
            async with lock:
                self._event_loop = None
                self._connection_lock = None
                self.logger.trace("모의 웹소켓 자원 정리 완료")
        except Exception as e:
            self.logger.error(f"모의 웹소켓 연결 종료 중 오류 발생: {str(e)}")
            pass 