"""
MQTT 통신을 관리하고 메시지를 처리하는 모듈입니다.

이 모듈은 다음과 같은 기능들을 제공합니다:
- MQTT 브로커 연결 관리
- 메시지 발행 및 구독
- 패킷 처리 및 상태 관리
- 기기 제어 명령 처리
"""

import paho.mqtt.client as mqtt # type: ignore
import json
import asyncio
import re
import time
import telnetlib3 # type: ignore
from typing import Dict, Any, Optional, List, Set, TypedDict, Callable, TYPE_CHECKING
from packet_handler import PacketHandler
from device_controller import DeviceController
from utils import checksum, verify_checksum


if TYPE_CHECKING:
    from logger import LoggerInstance

class QueueItem(TypedDict):
    """큐에 저장되는 메시지 아이템의 구조를 정의합니다."""
    sendcmd: str  # 전송할 명령 패킷
    count: int    # 전송 시도 횟수
    expected_state: Dict[str, Any]  # 예상되는 응답 상태

class CollectData(TypedDict):
    """수집된 데이터의 구조를 정의합니다."""
    send_data: Set[str]  # 송신된 패킷 목록
    recv_data: Set[str]  # 수신된 패킷 목록
    last_recv_time: int  # 마지막 수신 시간

class MQTTHandler:
    """
    MQTT 통신을 관리하고 메시지를 처리하는 클래스입니다.
    
    이 클래스는 다음과 같은 기능들을 제공합니다:
    - MQTT 브로커 연결 설정 및 관리
    - 메시지 발행 및 구독 처리
    - 패킷 큐 관리 및 처리
    - 기기 상태 모니터링
    - Elfin 장치 관리
    
    Attributes:
        config (Dict[str, Any]): MQTT 설정 정보
        logger (Logger): 로깅을 담당하는 로거
        DEVICE_STRUCTURE (Dict[str, Any]): 기기 구조 정보
        ELFIN_TOPIC (str): Elfin 장치 토픽
        HA_TOPIC (str): Home Assistant 토픽
        STATE_TOPIC (str): 상태 토픽 형식
        QUEUE (List[QueueItem]): 메시지 큐
        COLLECTDATA (CollectData): 수집된 데이터
        mqtt_client (Optional[mqtt.Client]): MQTT 클라이언트
        packet_handler (PacketHandler): 패킷 처리기
        device_controller (DeviceController): 기기 제어기
        loop (Optional[asyncio.AbstractEventLoop]): 이벤트 루프
    """

    def __init__(self, config: Dict[str, Any], logger: LoggerInstance, device_structure: Dict[str, Any]):
        self.config = config
        self.logger = logger
        self.DEVICE_STRUCTURE = device_structure
        
        self.ELFIN_TOPIC: str = 'ew11'
        self.HA_TOPIC: str = config['mqtt_TOPIC']
        self.STATE_TOPIC: str = self.HA_TOPIC + '/{}/{}/state'
        
        self.QUEUE: List[QueueItem] = []
        self.COLLECTDATA: CollectData = {
            'send_data': set(),
            'recv_data': set(),
            'last_recv_time': 0
        }
        
        self.mqtt_client: Optional[mqtt.Client] = None
        self.packet_handler = PacketHandler(device_structure, self.logger)
        self.device_controller = DeviceController(self, self.logger, self.STATE_TOPIC)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def setup_mqtt(self, client_id: Optional[str] = None) -> mqtt.Client:
        """
        MQTT 클라이언트를 설정하고 반환합니다.
        
        Args:
            client_id (Optional[str]): MQTT 클라이언트 ID. 지정하지 않으면 HA_TOPIC 사용
            
        Returns:
            mqtt.Client: 설정된 MQTT 클라이언트
            
        Raises:
            Exception: MQTT 클라이언트 설정 중 오류 발생 시
        """
        try:
            client = mqtt.Client(client_id or self.HA_TOPIC)
            client.username_pw_set(
                self.config['mqtt_id'], 
                self.config['mqtt_password']
            )
            return client
        except Exception as e:
            self.logger.error(f"MQTT 클라이언트 설정 중 오류 발생: {str(e)}")
            raise

    def connect_mqtt(self) -> None:
        """
        MQTT 브로커에 최초 연결을 시도합니다.
        
        기존 연결이 있다면 종료하고 새로운 연결을 시도합니다.
        연결 실패 시 예외를 발생시킵니다.
        """
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.logger.info("기존 MQTT 연결을 종료합니다.")
            self.mqtt_client.disconnect()
        try:
            self.logger.info("MQTT 브로커 연결 시도 중...")
            if self.mqtt_client:
                self.mqtt_client.connect(self.config['mqtt_server'])
            else:
                self.logger.error("MQTT 클라이언트가 초기화되지 않았습니다.")
        except Exception as e:
            self.logger.error(f"MQTT 연결 실패: {str(e)}")

    def reconnect_mqtt(self) -> None:
        """
        MQTT 브로커 연결이 끊어진 경우 재연결을 시도합니다.
        
        최대 5번까지 재시도하며, 각 시도 사이에 5초간 대기합니다.
        모든 재시도가 실패하면 예외를 발생시킵니다.
        """
        max_retries = 5
        retry_interval = 5  # 초

        for attempt in range(max_retries):
            try:
                self.logger.info(f"MQTT 브로커 재연결 시도 중... (시도 {attempt + 1}/{max_retries})")
                if self.mqtt_client:
                    self.mqtt_client.connect(self.config['mqtt_server'])
                    return
                else:
                    raise Exception("MQTT 클라이언트가 초기화되지 않았습니다.")
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"MQTT 재연결 실패: {str(e)}. {retry_interval}초 후 재시도...")
                    if self.loop and self.loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(
                            asyncio.sleep(retry_interval),
                            self.loop
                        )
                        future.result()  # 결과를 기다림
                    else:
                        time.sleep(retry_interval)
                else:
                    self.logger.error(f"MQTT 재연결 실패: {str(e)}. 최대 재시도 횟수 초과.")
                    raise

    def publish_mqtt(self, topic: str, value: Any, retain: bool = False) -> None:
        """
        MQTT 메시지를 발행합니다.
        
        Args:
            topic (str): 메시지를 발행할 토픽
            value (Any): 발행할 메시지 내용
            retain (bool, optional): 메시지 유지 여부. 기본값은 False
            
        Note:
            토픽이 '/send'로 끝나는 경우 value를 그대로 발행하고,
            그 외의 경우 value를 UTF-8로 인코딩하여 발행합니다.
        """
        if self.mqtt_client:
            if topic.endswith('/send'):
                self.mqtt_client.publish(topic, value, retain=retain)
                self.logger.mqtt(f'{topic} >> {value}')
            else:
                self.mqtt_client.publish(topic, value.encode(), retain=retain)
                self.logger.mqtt(f'{topic} >> {value}')
        else:
            self.logger.error('MQTT 클라이언트가 초기화되지 않았습니다.')

    async def on_mqtt_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        """
        MQTT 연결 성공/실패 시 호출되는 콜백 함수입니다.
        
        Args:
            client (mqtt.Client): MQTT 클라이언트 인스턴스
            userdata (Any): 사용자 정의 데이터
            flags (Dict[str, Any]): 연결 플래그
            rc (int): 연결 결과 코드 (0: 성공)
            
        Note:
            연결 성공 시 필요한 토픽을 구독하고 Discovery 메시지를 발행합니다.
            실패 시 오류 메시지를 로깅합니다.
        """
        if rc == 0:
            self.logger.info("MQTT broker 접속 완료")
            self.logger.info("구독 시작")
            try:
                topics = [
                    (f'{self.HA_TOPIC}/+/+/command', 0),
                    (f'{self.ELFIN_TOPIC}/recv', 0),
                    (f'{self.ELFIN_TOPIC}/send', 0)
                ]
                client.subscribe(topics)
                # MQTT Discovery 메시지 발행
                await self.publish_discovery_message()
            except Exception as e:
                self.logger.error(f"MQTT 토픽 구독 중 오류 발생: {str(e)}")
        else:
            errcode = {
                1: 'Connection refused - incorrect protocol version',
                2: 'Connection refused - invalid client identifier',
                3: 'Connection refused - server unavailable',
                4: 'Connection refused - bad username or password',
                5: 'Connection refused - not authorised'
            }
            error_msg = errcode.get(rc, '알 수 없는 오류')
            self.logger.error(f"MQTT 연결 실패: {error_msg}")

    async def process_elfin_data(self, raw_data: str) -> None:
        """
        Elfin 장치에서 전송된 raw_data를 분석하고 처리합니다.
        
        Args:
            raw_data (str): 16진수 형태의 원시 데이터
            
        Note:
            데이터를 16바이트 단위로 나누어 처리하며,
            각 패킷의 체크섬을 검증하고 해당하는 기기의 상태를 업데이트합니다.
        """
        try:
            for k in range(0, len(raw_data), 16):
                data = raw_data[k:k + 16]
                if verify_checksum(data):
                    self.COLLECTDATA['recv_data'].add(data)
                    if len(self.COLLECTDATA['recv_data']) > 100:
                        self.COLLECTDATA['recv_data'] = set(list(self.COLLECTDATA['recv_data'])[-100:])
                    
                    byte_data = bytearray.fromhex(data)
                    
                    for device_name, structure in self.DEVICE_STRUCTURE.items():
                        state_structure = structure['state']
                        field_positions = state_structure['fieldPositions']
                        if byte_data[0] == int(state_structure['header'], 16):
                            device_id_pos = field_positions['deviceId']
                            device_id = byte_data[int(device_id_pos)]
                            
                            if device_name == 'Thermo':
                                power_pos = field_positions.get('power', 1)
                                power = byte_data[int(power_pos)]
                                current_temp = int(format(byte_data[int(field_positions.get('currentTemp', 3))], '02x'))
                                target_temp = int(format(byte_data[int(field_positions.get('targetTemp', 4))], '02x'))
                                power_hex = format(power, '02x').upper()
                                power_values = state_structure['structure'][power_pos]['values']
                                power_off_hex = power_values.get('off', '').upper()
                                power_heating_hex = power_values.get('heating', '').upper()
                                mode_text = 'off' if power_hex == power_off_hex else 'heat'
                                action_text = 'heating' if power_hex == power_heating_hex else 'idle'
                                self.logger.signal(f'{byte_data.hex()}: 온도조절기 ### {device_id}번, 모드: {mode_text}, 현재 온도: {current_temp}°C, 설정 온도: {target_temp}°C')
                                await self.device_controller.update_temperature(device_id, mode_text, action_text, current_temp, target_temp)
                            
                            elif device_name == 'Light':
                                power_pos = field_positions.get('power', 1)
                                power = byte_data[int(power_pos)]
                                power_values = state_structure['structure'][power_pos]['values']
                                power_hex = format(power, '02x').upper()
                                state = "ON" if power_hex == power_values.get('on', '').upper() else "OFF"
                                self.logger.signal(f'{byte_data.hex()}: 조명 ### {device_id}번, 상태: {state}')
                                await self.device_controller.update_light(device_id, state)

                            elif device_name == 'LightBreaker':
                                power_pos = field_positions.get('power', 1)
                                power = byte_data[int(power_pos)]
                                power_values = state_structure['structure'][power_pos]['values']
                                power_hex = format(power, '02x').upper()
                                state = "ON" if power_hex == power_values.get('on', '').upper() else "OFF"
                                self.logger.signal(f'{byte_data.hex()}: 조명차단기 ### {device_id}번, 상태: {state}')
                                await self.device_controller.update_light_breaker(device_id, state)
                                
                            elif device_name == 'Outlet':
                                power_pos = field_positions.get('power', 1)
                                power = byte_data[int(power_pos)]
                                power_values = state_structure['structure'][power_pos]['values']
                                power_hex = format(power, '02x').upper()
                                power_text = "ON" if power_hex == power_values.get('on', '').upper() else "OFF"
                                watt_pos = field_positions.get('watt', 5)
                                watt = byte_data[int(watt_pos)]
                                self.logger.signal(f'{byte_data.hex()}: 콘센트 ### {device_id}번, 상태: {power_text}')
                                await self.device_controller.update_outlet(device_id, power_text, watt)

                            elif device_name == 'Fan':
                                power_pos = field_positions.get('power', 1)
                                power = byte_data[int(power_pos)]
                                power_values = state_structure['structure'][power_pos]['values']
                                power_hex = format(power, '02x').upper()
                                power_text = "OFF" if power_hex == power_values.get('off', '').upper() else "ON"
                                speed_pos = field_positions.get('speed', 3)  
                                speed = byte_data[int(speed_pos)]
                                speed_values = state_structure['structure'][speed_pos]['values']
                                speed_hex = format(speed, '02x').upper()
                                speed_text = speed_values.get(speed_hex, 'low')
                                self.logger.signal(f'{byte_data.hex()}: 환기장치 ### {device_id}번, 상태: {power_text}, 속도: {speed_text}')
                                await self.device_controller.update_fan(device_id, power_text, speed_text)
                            
                            elif device_name == 'EV':
                                power_pos = field_positions.get('power', 1)
                                power = byte_data[int(power_pos)]
                                power_values = state_structure['structure'][power_pos]['values']
                                power_hex = format(power, '02x').upper()
                                power_text = "ON" if power_hex == power_values.get('on', '').upper() else "OFF"
                                floor_pos = field_positions.get('floor', 3)
                                floor = byte_data[int(floor_pos)]
                                floor_values = state_structure['structure'][floor_pos]['values']
                                floor_hex = format(floor, '02x').upper()
                                floor_text = floor_values.get(floor_hex, 'B')
                                self.logger.signal(f'{byte_data.hex()}: 엘리베이터 ### {device_id}번, 상태: {power_text}, 층: {floor_text}')
                                await self.device_controller.update_ev(device_id, power_text, floor_text)

                            break
                else:
                    self.logger.signal(f'체크섬 불일치: {data}')
        
        except Exception as e:
            self.logger.error(f"Elfin 데이터 처리 중 오류 발생: {str(e)}")

    async def process_ha_command(self, topics: List[str], value: str) -> None:
        """
        홈어시스턴트에서 전송된 명령을 처리합니다.
        
        Args:
            topics (List[str]): 토픽 경로 리스트 (예: ["homeassistant", "light1", "power", "command"])
            value (str): 명령 값
            
        Note:
            토픽 구조에서 기기 종류와 ID를 추출하여 해당하는 명령을 생성하고
            명령 큐에 추가합니다.
        """
        try:
            device = ''.join(re.findall('[a-zA-Z]', topics[1]))
            device_id = int(''.join(re.findall('[0-9]', topics[1])))
            state = topics[2]

            if device not in self.DEVICE_STRUCTURE:
                self.logger.error(f'장치 {device}가 DEVICE_STRUCTURE에 존재하지 않습니다.')
                return

            packet_hex = None
            packet = bytearray(7)
            device_structure = self.DEVICE_STRUCTURE[device]
            command = device_structure["command"]
            
            packet[0] = int(command["header"], 16)
            packet[int(command["fieldPositions"]["deviceId"])] = device_id

            if device == 'Light':
                power_value = command["structure"][str(command["fieldPositions"]["power"])]["values"]["on" if value == "ON" else "off"]
                packet[int(command["fieldPositions"]["power"])] = int(power_value, 16)
            elif device == 'Thermo':
                cur_temp_str = self.device_controller.HOMESTATE.get(topics[1] + 'curTemp')
                set_temp_str = self.device_controller.HOMESTATE.get(topics[1] + 'setTemp')
                if cur_temp_str is None or set_temp_str is None:
                    self.logger.error('현재 온도 또는 설정 온도가 존재하지 않습니다.')
                    return
                
                cur_temp = int(float(cur_temp_str))
                set_temp = int(float(value)) if state == 'setTemp' else int(float(set_temp_str))
                
                if state == 'power':
                    if value == 'heat':
                        packet_hex = self.packet_handler.make_climate_command(device_id, cur_temp, set_temp, 'commandON')
                    else:
                        packet_hex = self.packet_handler.make_climate_command(device_id, cur_temp, set_temp, 'commandOFF')
                elif state == 'setTemp':
                        packet_hex = self.packet_handler.make_climate_command(device_id, cur_temp, set_temp, 'commandCHANGE')
                        self.logger.debug(f'온도조절기 설정 온도 변경 명령: {packet_hex}')
            elif device == 'Fan':
                packet[int(command["fieldPositions"]["commandType"])] = int(command[str(command["fieldPositions"]["commandType"])]["values"]["power"], 16)
                
                if state == 'power':
                    packet[int(command["fieldPositions"]["commandType"])] = int(command[str(command["fieldPositions"]["commandType"])]["values"]["power"], 16)
                    packet[int(command["fieldPositions"]["value"])] = int(command[str(command["fieldPositions"]["value"])]["on" if value == "ON" else "off"], 16)
                    self.logger.debug(f'환기장치 {value} 명령 생성')
                elif state == 'speed':
                    if value not in ["low", "medium", "high"]:
                        self.logger.error(f"잘못된 팬 속도입니다: {value}")
                        return
                    packet[int(command["fieldPositions"]["commandType"])] = int(command[str(command["fieldPositions"]["commandType"])]["values"]["setSpeed"], 16)
                    packet[int(command["fieldPositions"]["value"])] = int(command[str(command["fieldPositions"]["value"])]["values"][value], 16)
                    self.logger.debug(f'환기장치 속도 {value} 명령 생성')
            
            if packet_hex is None:
                packet_hex = packet.hex().upper()
                packet_hex = checksum(packet_hex)

            if packet_hex:
                expected_state = self.packet_handler.generate_expected_state_packet(packet_hex)
                if expected_state:
                    self.logger.debug(f'예상 상태: {expected_state}')
                    self.QUEUE.append({
                        'sendcmd': packet_hex, 
                        'count': 0, 
                        'expected_state': expected_state
                    })
                else:
                    self.logger.error('예상 상태 패킷 생성 실패')
        except Exception as e:
            self.logger.error(f"HA 명령 처리 중 오류 발생: {str(e)}")

    async def process_queue(self) -> None:
        """
        큐에 있는 모든 명령을 처리하고 예상되는 응답을 확인합니다.
        
        Note:
            - 큐의 첫 번째 명령을 꺼내서 처리합니다.
            - 명령 전송 후 예상되는 응답을 기다립니다.
            - 응답이 없으면 최대 전송 횟수까지 재전송합니다.
        """
        max_send_count = self.config.get("max_send_count", 20)
        default_send_count = 5
        
        if not self.QUEUE:
            return
        
        send_data = self.QUEUE.pop(0)
        
        try:
            # 먼저 명령 전송
            cmd_bytes = bytes.fromhex(send_data['sendcmd'])
            self.publish_mqtt(f'{self.ELFIN_TOPIC}/send', cmd_bytes)
            send_data['count'] += 1
        except (ValueError, TypeError) as e:
            self.logger.error(f"명령 전송 중 오류 발생: {str(e)}")
            return
            
        expected_state = send_data.get('expected_state')
        
        if expected_state and isinstance(expected_state, dict):
            expected_packet = expected_state.get('expected_packet')
            required_bytes = expected_state.get('required_bytes')
            
            if isinstance(expected_packet, str) and isinstance(required_bytes, list):
                expected_bytes = bytes.fromhex(expected_packet)
                
                # 수집된 데이터에서 예상 패킷 확인
                for received_packet in self.COLLECTDATA['recv_data']:
                    if not isinstance(received_packet, str):
                        continue
                        
                    try:
                        received_bytes = bytes.fromhex(received_packet)
                    except ValueError:
                        continue
                        
                    # 필수 바이트 위치의 값들이 모두 일���하는지 확인
                    match = True
                    try:
                        for pos in required_bytes:
                            if not isinstance(pos, int):
                                match = False
                                break
                                
                            if (len(received_bytes) <= pos or 
                                len(expected_bytes) <= pos or
                                received_bytes[pos] != expected_bytes[pos]):
                                match = False
                                break
                                
                    except (IndexError, TypeError) as e:
                        self.logger.error(f"패킷 비교 중 오류 발생: {str(e)}")
                        match = False
                        
                    if match:
                        self.logger.debug(f"예상된 응답을 수신했습니다: {received_packet}")
                        return
                
                if send_data['count'] < max_send_count:
                    self.logger.debug(f"명령 재전송 예약 (시도 {send_data['count']}/{max_send_count}): {send_data['sendcmd']}")
                    self.QUEUE.append(send_data)
                else:
                    self.logger.warning(f"최대 전송 횟수 초과. 응답을 받지 못했습니다: {send_data['sendcmd']}")
                        
        # 상태 정보가 없거나 잘못된 경우
        else:
            if send_data['count'] < default_send_count:
                self.logger.debug(f"명령 전송 (횟수 {send_data['count']}/{default_send_count}): {send_data['sendcmd']}")
                self.QUEUE.append(send_data)
        
        await asyncio.sleep(0.05)

    async def process_queue_and_monitor(self, elfin_reboot_interval: float) -> bool:
        """
        메시지 큐를 주기적으로 처리하고 기기 상태를 모니터링하는 함수입니다.

        1ms 간격으로 다음 작업들을 수행합니다:
        1. 큐에 있는 메시지 처리 (100ms 이상 통신이 없을 때)
        2. ew11 기기 상태 모니터링 및 필요시 재시작

        Args:
            elfin_reboot_interval (float): ew11 기기 재시작 판단을 위한 통신 제한 시간 (초)

        Returns:
            bool: 처리 성공 여부

        Raises:
            Exception: 큐 처리 또는 기기 재시작 중 오류 발생시
        """
        while True:
            try:
                current_time = time.time_ns()
                last_recv = self.COLLECTDATA['last_recv_time']
                signal_interval = (current_time - last_recv)/1_000_000 #ns to ms
                
                if signal_interval > elfin_reboot_interval * 1_000:  # seconds
                    self.logger.warning(f'{elfin_reboot_interval}초간 신호를 받지 못했습니다.')
                    self.COLLECTDATA['last_recv_time'] = time.time_ns()
                    if (self.config.get("elfin_auto_reboot",True)):
                        self.logger.warning('EW11 재시작을 시도합니다.')
                        await self.reboot_elfin_device()
                if signal_interval > 150: #150ms이상 여유있을 때 큐 실행
                    await self.process_queue()
                
            except Exception as err:
                self.logger.error(f'process_queue_and_monitor() 오류: {str(err)}')
                return True
            
            await asyncio.sleep(self.config.get("queue_interval_in_second",0.01)) #10ms 

    async def reboot_elfin_device(self):
        """
        Elfin 장치를 재시작합니다.
        
        Note:
            - telnet을 통해 장치에 접속합니다.
            - 로그인 후 재시작 명령을 전송합니다.
            - 재시작 후 10초간 대기합니다.
            
        Raises:
            Exception: 재시작 과정에서 오류 발생시
        """
        try:
            reader, writer = await telnetlib3.open_connection(self.config['elfin_server'])
            await reader.readuntil(b"login: ")
            writer.write(self.config['elfin_id'] + '\n')
            await reader.readuntil(b"password: ")
            writer.write(self.config['elfin_password'] + '\n')
            writer.write('Restart\n')
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(10)
            
        except Exception as err:
            self.logger.error(f'기기 재시작 오류: {str(err)}')

    def __del__(self):
        """클래스 인스턴스가 삭제될 때 리소스 정리"""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except:
                pass
        if self.loop and not self.loop.is_closed():
            self.loop.close() 

    def on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            topics = msg.topic.split('/')
            
            if topics[0] == self.ELFIN_TOPIC:
                if topics[1] == 'recv':
                    raw_data = msg.payload.hex().upper()
                    self.logger.signal(f'->> 수신: {raw_data}')
                    if self.loop and self.loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(
                            self.process_elfin_data(raw_data),
                            self.loop
                        )
                        future.result()  # 결과를 기다림
                    current_time = time.time_ns()
                    self.COLLECTDATA['last_recv_time'] = current_time
                    
                elif topics[1] == 'send':
                    raw_data = msg.payload.hex().upper()
                    self.logger.signal(f'<<- 송신: {raw_data}')
                    self.COLLECTDATA['send_data'].add(raw_data)
                    if len(self.COLLECTDATA['send_data']) > 100:
                        self.COLLECTDATA['send_data'] = set(list(self.COLLECTDATA['send_data'])[-100:])
                    
            elif topics[0] == self.HA_TOPIC:
                value = msg.payload.decode()
                self.logger.mqtt(f'->> 수신: {"/".join(topics)} -> {value}')
                
                if self.loop and self.loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self.process_ha_command(topics, value),
                        self.loop
                    )
                    future.result()  # 결과를 기다림
                
        except Exception as err:
            self.logger.error(f'MQTT 메시지 처리 중 오류 발생: {str(err)}') 

    async def publish_discovery_message(self) -> None:
        """
        홈어시스턴트 MQTT Discovery 메시지를 발행합니다.
        
        Note:
            - 각 기기 타입별로 적절한 Discovery 설정을 생성합니다.
            - 생성된 설정은 MQTT 브로커에 retain 플래그와 함께 발행됩니다.
            - 지원하는 기기 타입:
                - switch: 일반 스위치, 콘센트
                - light: 조명
                - fan: 환기장치
                - climate: 온도조절기
                - button: 가스밸브, 엘리베이터 호출
                
        Raises:
            Exception: Discovery 메시지 발행 중 오류 발생시
        """
        try:
            # Discovery 접두사
            discovery_prefix = "homeassistant"
            
            # 공통 디바이스 정보
            device_base_info = {
                "identifiers": ["commax_wallpad"],
                "name": "commax_wallpad",
                "model": "commax_wallpad",
                "manufacturer": "commax_wallpad"
            }
            
            for device_name, device_info in self.config['device_list'].items():
                device_type = device_info['type']
                device_count = device_info['count']
                
                # device_count가 0인 경우 건너뛰기
                if device_count == 0:
                    continue
                
                # 1부터 시작
                for idx in range(1, device_count + 1):
                    device_id = f"{device_name}{idx}"
                    
                    if device_type == 'switch':  # 기타 스위치
                        if device_name == 'Outlet':  # 콘센트인 경우
                            # 스위치 설정
                            config_topic = f"{discovery_prefix}/switch/{device_id}/config"
                            payload = {
                                "name": f"{device_name} {idx}",
                                "unique_id": f"commax_{device_id}",
                                "state_topic": self.STATE_TOPIC.format(device_id, "power"),
                                "command_topic": f"{self.HA_TOPIC}/{device_id}/power/command",
                                "payload_on": "ON",
                                "payload_off": "OFF",
                                "device_class": "outlet",
                                "device": device_base_info
                            }
                            # 전력 센서 설정
                            config_topic = f"{discovery_prefix}/sensor/{device_id}_watt/config"
                            payload = {
                                "name": f"{device_name} {idx} Power",
                                "unique_id": f"commax_{device_id}_watt",
                                "state_topic": self.STATE_TOPIC.format(device_id, "watt"),
                                "unit_of_measurement": "W",
                                "device_class": "power",
                                "state_class": "measurement",
                                "device": device_base_info
                            }
                        else:  # 일반 스위치인 경우
                            config_topic = f"{discovery_prefix}/switch/{device_id}/config"
                            payload = {
                                "name": f"{device_name} {idx}",
                                "unique_id": f"commax_{device_id}",
                                "state_topic": self.STATE_TOPIC.format(device_id, "power"),
                                "command_topic": f"{self.HA_TOPIC}/{device_id}/power/command",
                                "payload_on": "ON",
                                "payload_off": "OFF",
                                "device": device_base_info
                            }
                    elif device_type == 'light':  # 조명
                        config_topic = f"{discovery_prefix}/light/{device_id}/config"
                        payload = {
                            "name": f"{device_name} {idx}",
                            "unique_id": f"commax_{device_id}",
                            "state_topic": self.STATE_TOPIC.format(device_id, "power"),
                            "command_topic": f"{self.HA_TOPIC}/{device_id}/power/command",
                            "payload_on": "ON",
                            "payload_off": "OFF",
                            "device": device_base_info
                        }
                    elif device_type == 'fan':  # 환기장치
                        config_topic = f"{discovery_prefix}/fan/{device_id}/config"
                        payload = {
                            "name": f"{device_name} {idx}",
                            "unique_id": f"commax_{device_id}",
                            "state_topic": self.STATE_TOPIC.format(device_id, "power"),
                            "command_topic": f"{self.HA_TOPIC}/{device_id}/power/command",
                            "speed_state_topic": self.STATE_TOPIC.format(device_id, "speed"),
                            "speed_command_topic": f"{self.HA_TOPIC}/{device_id}/speed/command",
                            "speeds": ["low", "medium", "high"],
                            "payload_on": "ON",
                            "payload_off": "OFF",
                            "device": device_base_info
                        }
                        
                    elif device_type == 'climate':  # 온도조절기
                        config_topic = f"{discovery_prefix}/climate/{device_id}/config"
                        payload = {
                            "name": f"{device_name} {idx}",
                            "unique_id": f"commax_{device_id}",
                            "device": device_base_info,
                            "current_temperature_topic": self.STATE_TOPIC.format(device_id, "curTemp"),
                            "temperature_command_topic": f"{self.HA_TOPIC}/{device_id}/setTemp/command",
                            "temperature_state_topic": self.STATE_TOPIC.format(device_id, "setTemp"),
                            "mode_command_topic": f"{self.HA_TOPIC}/{device_id}/power/command",
                            "mode_state_topic": self.STATE_TOPIC.format(device_id, "power"),
                            "action_state_topic": self.STATE_TOPIC.format(device_id, "action"),
                            "modes": ["off", "heat"],
                            "temperature_unit": "C",
                            "min_temp": 10,
                            "max_temp": 40,
                            "temp_step": 1,
                        }
                    elif device_type == 'button':  # 버튼형 기기 (가스밸브, 엘리베이터 호출)
                        config_topic = f"{discovery_prefix}/button/{device_id}/config"
                        payload = {
                            "name": f"{device_name} {idx}",
                            "unique_id": f"commax_{device_id}",
                            "state_topic": self.STATE_TOPIC.format(device_id, "power"),
                            "command_topic": f"{self.HA_TOPIC}/{device_id}/power/command",
                            "device": device_base_info
                        }
                    if 'payload' in locals():
                        self.publish_mqtt(config_topic, json.dumps(payload), retain=True)

            self.logger.info("MQTT Discovery 설정 완료")
            
        except Exception as e:
            self.logger.error(f"MQTT Discovery 설정 중 오류 발생: {str(e)}") 