import paho.mqtt.client as mqtt
import time
import asyncio
import os
from logger import Logger
from typing import Any, Dict, Union, List, Optional, Set, TypedDict, Callable, TypeVar, Callable
from functools import wraps
import yaml #PyYAML
import json
import re
import telnetlib
import shutil

T = TypeVar('T')

def require_device_structure(default_return: Any = None) -> Callable:
    """DEVICE_STRUCTURE가 초기화되었는지 확인하는 데코레이터
    
    Args:
        default_return: DEVICE_STRUCTURE가 None일 때 반환할 기본값
        
    Returns:
        Callable: 데코레이터 함수
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.DEVICE_STRUCTURE is None:
                self.logger.error("DEVICE_STRUCTURE가 초기화되지 않았습니다.")
                return default_return
            return func(self, *args, **kwargs)
        return wrapper
    return decorator

class CollectData(TypedDict):
    data: Set[str]
    last_recv_time: int

class ExpectedStatePacket(TypedDict):
    expected_packet: str
    required_bytes: List[int]

class QueueItem(TypedDict):
    sendcmd: str
    count: int
    expected_state: Optional[ExpectedStatePacket]

    
class WallpadController:
    def __init__(self, config: Dict[str, Any], logger: Logger) -> None:
        self.config: Dict[str, Any] = config
        self.logger: Logger = logger
        self.share_dir: str = '/share'
        self.ELFIN_TOPIC: str = 'ew11'
        self.HA_TOPIC: str = config['mqtt_TOPIC']
        self.STATE_TOPIC: str = self.HA_TOPIC + '/{}/{}/state'
        self.HOMESTATE: Dict[str, str] = {}
        self.QUEUE: List[QueueItem] = []
        self.COLLECTDATA: CollectData = {
            'data': set(),
            'last_recv_time': time.time_ns()
        }
        self.mqtt_client: Optional[mqtt.Client] = None
        self.device_list: Optional[Dict[str, Any]] = None
        self.DEVICE_STRUCTURE: Optional[Dict[str, Any]] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.load_devices_and_packets_structures() # 기기 정보와 패킷 정보를 로드 to self.DEVICE_STRUCTURE

    # 유틸리티 함수들
    @staticmethod
    def checksum(input_hex: str) -> Optional[str]:
        """
        input_hex에 checksum을 붙여주는 함수
        
        Args:
            input_hex (str): 기본 16진수 명령어 문자열
        
        Returns:
            str: 체크섬이 포함된 수정된 16진수 명령어. 실패시 None 반환
        """
        try:
            input_hex = input_hex[:14]
            s1 = sum([int(input_hex[val], 16) for val in range(0, 14, 2)])
            s2 = sum([int(input_hex[val + 1], 16) for val in range(0, 14, 2)])
            s1 = s1 + int(s2 // 16)
            s1 = s1 % 16
            s2 = s2 % 16
            return input_hex + format(s1, 'X') + format(s2, 'X')
        except:
            return None

    @staticmethod
    def pad(value: Union[int, str]) -> str:
        value = int(value)
        return '0' + str(value) if value < 10 else str(value)

    def load_devices_and_packets_structures(self) -> None:
        try:
            # /share 디렉토리의 파일을 먼저 확인
            share_file_path = '/share/commax_devices_and_packets_structures.yaml'
            default_file_path = '/apps/devices_and_packets_structures.yaml'
            
            if os.path.exists(share_file_path):
                with open(share_file_path) as file:
                    self.DEVICE_STRUCTURE = yaml.safe_load(file)
                    self.logger.info(f'기기 및 패킷 구조를 {share_file_path}에서 로드했습니다.')
                    self.logger.info(f'파일이 망가진 경우 초기화하려면 파일을 삭제하고 애드온을 재시작하세요.')
            else:
                with open(default_file_path) as file:
                    self.DEVICE_STRUCTURE = yaml.safe_load(file)
                    self.logger.info(f'기기 및 패킷 구조를 {default_file_path}에서 로드했습니다.')
                # 기본 파일을 share 디렉토리로 복사
                self.logger.info(f'기기 및 패킷 구조 복사본을 {share_file_path}로 복사합니다.')
                try:
                    shutil.copy2(default_file_path, share_file_path)
                except Exception as e:
                    self.logger.error(f'파일 복사 중 오류 발생: {str(e)}')
                    
            if self.DEVICE_STRUCTURE is not None:
                # fieldPositions 자동 생성
                for device_name, device in self.DEVICE_STRUCTURE.items():
                    for packet_type in ['command', 'state']:
                        if packet_type in device:
                            structure = device[packet_type]['structure']
                            field_positions = {}
                            
                            for pos, field in structure.items():
                                field_name = field['name']
                                if field_name != 'empty':
                                    if field_name in field_positions:
                                        self.logger.error(
                                            f"중복된 필드 이름 발견: {device_name}.{packet_type} - "
                                            f"'{field_name}' (위치: {field_positions[field_name]}, {pos})"
                                        )
                                    else:
                                        field_positions[field_name] = pos
                                    
                            device[packet_type]['fieldPositions'] = field_positions
                        
        except FileNotFoundError:
            self.logger.error('기기 및 패킷 구조 파일을 찾을 수 없습니다.')
        except yaml.YAMLError:
            self.logger.error('기기 및 패킷 구조 파일의 YAML 형식이 잘못되었습니다.')

    # MQTT 관련 함수들
    def setup_mqtt(self, client_id: Optional[str] = None) -> mqtt.Client:
        """MQTT 클라이언트를 설정하고 반환합니다.
        
        Args:
            client_id (Optional[str]): MQTT 클라이언트 ID. 기본값은 self.HA_TOPIC
            
        Returns:
            mqtt.Client: 설정된 MQTT 클라이언트
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
        """MQTT 브로커에 최초 연결을 시도합니다."""
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.logger.info("기존 MQTT 연결을 종료합니다.")
            self.mqtt_client.disconnect()
        try:
            self.logger.info("MQTT 브로커 연결 시도 중...")
            if self.mqtt_client:
                self.mqtt_client.connect(self.config['mqtt_server'])
            else:
                self.logger.error("MQTT 클라이언트가 초기화되지 않았습니다.")
            return
        except Exception as e:
            self.logger.error(f"MQTT 연결 실패: {str(e)}")
            return

    def reconnect_mqtt(self) -> None:
        """MQTT 브로커 연결이 끊어진 경우 재연결을 시도합니다."""
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
                    time.sleep(retry_interval)
                else:
                    self.logger.error(f"MQTT 재연결 실패: {str(e)}. 최대 재시도 횟수 초과.")
                    raise

    async def on_mqtt_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        """MQTT 연결 성공/실패 시 호출되는 콜백"""
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

    def on_mqtt_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            topics = msg.topic.split('/')
            
            if topics[0] == self.ELFIN_TOPIC:
                if topics[1] == 'recv':
                    raw_data = msg.payload.hex().upper()
                    self.logger.signal(f'->> 수신: {raw_data}')                    
                    # 수신 간격 계산
                    current_time = time.time_ns()
                    if 'last_recv_time' in self.COLLECTDATA:
                        interval = current_time - self.COLLECTDATA['last_recv_time']
                        # self.logger.signal(f'RS485 수신 간격: {interval/1_000_000} ms')
                    self.COLLECTDATA['last_recv_time'] = current_time
                    
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self.process_elfin_data(raw_data),
                            self.loop
                        )
                elif topics[1] == 'send':
                    raw_data = msg.payload.hex().upper()
                    self.logger.signal(f'<<- 송신: {raw_data}')
                    
            elif topics[0] == self.HA_TOPIC:
                value = msg.payload.decode()
                self.logger.mqtt(f'->> 수신: {"/".join(topics)} -> {value}')
                
                if self.loop and self.loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.process_ha_command(topics, value),
                        self.loop
                    )
                
        except Exception as err:
            self.logger.error(f'MQTT 메시지 처리 중 오류 발생: {str(err)}')

    def publish_mqtt(self, topic: str, value: Any, retain: bool = False) -> None:
        if self.mqtt_client:
            if topic.endswith('/send'):
                self.mqtt_client.publish(topic, value, retain=retain)
                self.logger.mqtt(f'{topic} >> {value}')
                return
            self.mqtt_client.publish(topic, value.encode(), retain=retain)
            self.logger.mqtt(f'{topic} >> {value}')
        else:
            self.logger.error('MQTT 클라이언트가 초기화되지 않았습니다.')

    # 기기 검색 및 상태 관리 함수들
    @require_device_structure({})
    def find_device(self) -> Dict[str, Any]:
        """MQTT에 발행되는 RS485신호에서 기기를 찾는 함수입니다."""
        try:
            if not os.path.exists(self.share_dir):
                os.makedirs(self.share_dir)
                self.logger.info(f'{self.share_dir} 디렉토리를 생성했습니다.')
            
            save_path = os.path.join(self.share_dir, 'commax_found_device.json')
            
            # 헤입 체크를 위한 assertion 추가
            assert isinstance(self.DEVICE_STRUCTURE, dict), "DEVICE_STRUCTURE must be a dictionary"
            
            # 헤더로 기기 타입 매핑
            state_prefixes = {
                self.DEVICE_STRUCTURE[name]["state"]["header"]: name 
                for name in self.DEVICE_STRUCTURE 
                if "state" in self.DEVICE_STRUCTURE[name]
            }
            
            # 기기별 최대 인덱스 저장
            device_count = {name: 0 for name in state_prefixes.values()}
            
            target_time = time.time() + 20
            
            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    self.logger.info("MQTT broker 접속 완료")
                    self.logger.info("20초동안 기기를 검색합니다.")
                    client.subscribe(f'{self.ELFIN_TOPIC}/#', 0)
                else:
                    self.logger.error(f"Connection failed with code {rc}")
            
            def on_message(client, userdata, msg):
                assert isinstance(self.DEVICE_STRUCTURE, dict), "DEVICE_STRUCTURE must be a dictionary"
                raw_data = msg.payload.hex().upper()
                for k in range(0, len(raw_data), 16):
                    data = raw_data[k:k + 16]
                    if data == self.checksum(data) and data[:2] in state_prefixes:
                        name = state_prefixes[data[:2]]
                        device_structure = self.DEVICE_STRUCTURE[name]
                        device_id_position = int(device_structure["state"]["structure"]["2"]["name"] == "deviceId" 
                                              and "2" or next(
                                                  pos for pos, field in device_structure["state"]["structure"].items()
                                                  if field["name"] == "deviceId"
                                              ))
                        device_count[name] = max(
                            device_count[name], 
                            int(data[device_id_position*2:device_id_position*2+2], 16)
                        )
            
            # 임시 MQTT 클라이언트 설정
            temp_client = self.setup_mqtt('commax_finder')
            temp_client.on_connect = on_connect
            temp_client.on_message = on_message
            
            # MQTT 연결 및 검색 시작
            temp_client.connect(self.config['mqtt_server'])
            temp_client.loop_start()
            
            while time.time() < target_time:
                pass
            
            temp_client.loop_stop()
            temp_client.disconnect()
            
            # 검색 결과 처리
            self.logger.info('다음의 기기들을 찾았습니다...')
            self.logger.info('======================================')
            
            device_list = {}
            
            for name, count in device_count.items():
                if count > 0:
                    assert isinstance(self.DEVICE_STRUCTURE, dict)  # 타입 체크 재확인
                    device_list[name] = {
                        "type": self.DEVICE_STRUCTURE[name]["type"],
                        "count": count
                    }
                    self.logger.info(f'DEVICE: {name}')
                    self.logger.info(f'Count: {count}')
                    self.logger.info('-------------------')
            
            self.logger.info('======================================')
            
            # 검색 결과 저장
            try:
                with open(save_path, 'w', encoding='utf-8') as make_file:
                    json.dump(device_list, make_file, indent="\t")
                    self.logger.info(f'기기리스트 저장 완료: {save_path}')
            except IOError as e:
                self.logger.error(f'기기리스트 저장 실패: {str(e)}')
            
            return device_list
            # device_list 내용 예시:
            # {"light":
            #   "type":"light",
            #   "count":0
            # }
            
        except Exception as e:
            self.logger.error(f'기기 검색 중 오류 발생: {str(e)}')
            return {}
        
    async def publish_discovery_message(self):
        """홈어시스턴트 MQTT Discovery 메시지 발행"""
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
            
            if self.device_list is None:
                self.logger.error("device_list가 초기화되지 않았습니다.")
                return
            
            for device_name, device_info in self.device_list.items():
                device_type = device_info['type']
                device_count = device_info['count']
                
                # device_count가 0인 경우 건너뛰기
                if device_count == 0:
                    continue
                
                # 1부터 시작
                for idx in range(1, device_count + 1):
                    device_id = f"{device_name}{idx}"
                    
                    if device_type == 'switch':  # 조명
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
                            "max_temp": 30,
                            "temp_step": 1,
                        }
                    
                    if 'payload' in locals():
                        self.publish_mqtt(config_topic, json.dumps(payload), retain=True)

            self.logger.info("MQTT Discovery 설정 완료")
            
        except Exception as e:
            self.logger.error(f"MQTT Discovery 설정 중 오류 발생: {str(e)}")

    # 명령 생성 함수들
    @require_device_structure(None)
    def make_climate_command(self, device_id: int, current_temp: int, target_temp: int, command_type: str) -> Union[str, None]:
        """
        온도 조절기의 16진수 명령어를 생성하는 함수
        
        Args:
            device_id (int): 온도 조절기 장치 id
            current_temp (int): 현재 온도 값
            target_temp (int): 설정하고자 하는 목표 온도 값
            command_type (str): 명령어 타입
                - 'commandOFF': 전원 끄기 명령
                - 'commandON': 전원 켜기 명령
                - 'commandCHANGE': 온도 변경 명령
        
        Returns:
            Union[str, None]: 
                - 성공 시: 체크섬이 포함된 16진수 명령어 문자열
                - 실패 시: None
        
        Examples:
            >>> make_climate_command(0, 22, 24, 'commandON')  # 온도절기 1번 켜기
            >>> make_climate_command(1, 25, 26, 'commandCHANGE')  # 온도조절기 2번 온도 변경
        """
        try:
            assert isinstance(self.DEVICE_STRUCTURE, dict), "DEVICE_STRUCTURE must be a dictionary"
            
            thermo_structure = self.DEVICE_STRUCTURE["Thermo"]
            command = thermo_structure["command"]
            
            # 패킷 초기화
            packet = bytearray([0] * 7)

            # 헤더 설정
            packet[0] = int(command["header"], 16)
            
            # 기기 번호 설정 - 10진수로 직접 설정
            device_id_pos = command["fieldPositions"]["deviceId"]
            packet[int(device_id_pos)] = device_id
            
            # 명령 타입 및 값 설정
            command_type_pos = command["fieldPositions"]["commandType"]
            value_pos = command["fieldPositions"]["value"]
            
            if command_type == 'commandOFF':
                packet[int(command_type_pos)] = int(command["structure"][command_type_pos]["values"]["power"], 16)
                packet[int(value_pos)] = int(command["structure"][value_pos]["values"]["off"], 16)
            elif command_type == 'commandON':
                packet[int(command_type_pos)] = int(command["structure"][command_type_pos]["values"]["power"], 16)
                packet[int(value_pos)] = int(command["structure"][value_pos]["values"]["on"], 16)
            elif command_type == 'commandCHANGE':
                packet[int(command_type_pos)] = int(command["structure"][command_type_pos]["values"]["change"], 16)
                packet[int(value_pos)] = int(str(target_temp),16)
            else:
                self.logger.error(f'잘못된 명령 타입: {command_type}')
                return None
            
            # 패킷을 16진수 문자열로 변환
            packet_hex = packet.hex().upper()
            
            # 체크섬 추가하여 return
            return self.checksum(packet_hex)
        
        except KeyError as e:
            # DEVICE_STRUCTURE에 필요한 키가 없는 경우
            self.logger.error(f'DEVICE_STRUCTURE에 필요한 키가 없습니다: {e}')
            return None
        except Exception as e:
            # 기타 예외 처리
            self.logger.error(f'예외 발생: {e}')
            return None
        
    

    @require_device_structure(None)
    def generate_expected_state_packet(self, command_str: str) -> Union[ExpectedStatePacket, None]:
        """명령 패킷으로부터 예상되는 상태 패킷을 생성합니다.
        
        Args:
            command_str (str): 16진수 형태의 명령 패킷 문자열
            
        Returns:
            Union[ExpectedStatePacket, None]: 예상되는 상태 패킷 정보를 담은 딕셔너리 또는 None
        """
        try:
            assert isinstance(self.DEVICE_STRUCTURE, dict)
            
            # 명령 패킷 검증
            if len(command_str) != 16:
                self.logger.error("명령 패킷 길이가 16자가 아닙니다.")
                return None
                
            # 명령 패킷을 바이트로 변환
            command_packet = bytes.fromhex(command_str)
            
            # 헤더로 기기 타입 찾기
            device_type = None
            for name, structure in self.DEVICE_STRUCTURE.items():
                if command_packet[0] == int(structure['command']['header'], 16):
                    device_type = name
                    break
                    
            if not device_type:
                self.logger.error("알 수 없는 명령 패킷입니다.")
                return None
                        
            # 기기별 상태 패킷 생성
            device_structure = self.DEVICE_STRUCTURE[device_type]
            command_structure = device_structure['command']
            state_structure = device_structure['state']
            
            # 상태 패킷 초기화 (7바이트 - 체크섬은 나중에 추가)
            status_packet = bytearray(7)
            # 필요한 바이트 리스트
            required_bytes = [0] # 헤더는 항상 포함
            
            # 상태 패킷 헤더 설정
            status_packet[0] = int(state_structure['header'], 16)
            
            # 기기 ID 복사
            device_id_pos = state_structure['fieldPositions']['deviceId']
            status_packet[int(device_id_pos)] = command_packet[int(command_structure['fieldPositions']['deviceId'])]
            # 필요한 바이트 리스트에 기기 ID 추가
            required_bytes.append(int(device_id_pos))

            if device_type == 'Thermo':
                # 온도조절기 상태 패킷 생성
                command_type_pos = command_structure['fieldPositions']['commandType']
                command_type = command_packet[int(command_type_pos)]
                
                power_pos = state_structure['fieldPositions']['power']
                if command_type == int(command_structure["structure"][command_type_pos]['values']['power'], 16): #04
                    command_value = command_packet[int(command_structure['fieldPositions']['value'])]
                    status_packet[int(power_pos)] = command_value
                    # 필요한 바이트 리스트에 전원 위치 추가
                    required_bytes.append(int(power_pos))
                elif command_type == int(command_structure["structure"][command_type_pos]['values']['change'], 16): #03
                    #Power는 켜진 상태로 설정
                    status_packet[int(power_pos)] = int(state_structure['structure'][str(power_pos)]['values']['on'], 16) #81
                    
                    target_temp = command_packet[int(command_structure['fieldPositions']['value'])]
                    target_temp_pos = state_structure['fieldPositions']['targetTemp']
                    status_packet[int(target_temp_pos)] = target_temp
                    current_temp_pos = state_structure['fieldPositions']['currentTemp']
                    status_packet[int(current_temp_pos)] = target_temp
                    # 필요한 바이트 리스트에 현재 온도 위치 추가
                    required_bytes.append(int(target_temp_pos))
            

            elif device_type == 'Light':
                # 조명 상태 패킷 생성
                power_pos = state_structure['fieldPositions']['power']
                command_value = command_packet[int(command_structure['fieldPositions']['power'])]
                status_packet[int(power_pos)] = command_value
                # 필요한 바이트 리스트에 전원 위치 추가
                required_bytes.append(int(power_pos))

            # elif device_type == 'Fan':
            #     # 환기장치 상태 패킷 생성
            #     command_type = command_packet[int(device_structure['command']['fieldPositions']['commandType'])]
            #     command_value = command_packet[int(device_structure['command']['fieldPositions']['value'])]
                
            #     if command_type == int(device_structure['command']['types']['power']['code'], 16):
            #         # 전원 명령
            #         status_packet[int(device_structure['state']['fieldPositions']['power'])] = command_value
            #     elif command_type == int(device_structure['command']['types']['setSpeed']['code'], 16):
            #         # 속도 설정 명령
            #         status_packet[int(device_structure['state']['fieldPositions']['speed'])] = command_value
            #         # 전원은 켜진 상태로 설정
            #         status_packet[int(device_structure['state']['fieldPositions']['power'])] = \
            #             int(device_structure['state']['structure']['1']['values']['on'], 16)
            
            # 상태 패킷을 16진수 문자열로 변환
            status_hex = status_packet.hex().upper()
            status_hex = self.checksum(status_hex)
            if status_hex is None:
                self.logger.error("상태 패킷 체크섬 생성 실패") 
                return None
            return ExpectedStatePacket(
                expected_packet=status_hex,
                required_bytes=required_bytes
            )
            
        except Exception as e:
            self.logger.error(f"상태 패킷 생성 중 오류 발생: {str(e)}\n"
                            f"장치 타입: {device_type}\n"
                            f"명령 패킷: {command_packet.hex().upper()}\n"
                            f"상태 패킷: {status_packet.hex().upper() if status_packet else 'None'}\n"
                            f"State_structure: {state_structure}\n"
                            f"command_structure: {command_structure}")
            return None
    
    # 상태 업데이트 함수들
    async def update_light(self, idx: int, onoff: str) -> None:
        state = 'power'
        deviceID = 'Light' + str(idx)

        topic = self.STATE_TOPIC.format(deviceID, state)
        self.publish_mqtt(topic, onoff)
        self.HOMESTATE[deviceID + state] = onoff

    async def update_temperature(self, idx: int, mode_text: str, action_text: str, curTemp: int, setTemp: int) -> None:
        """
        온도 조절기 상태를 업데이트하는 함수입니다.

        Args:
            idx (int): 온도 조절기 장치의 인덱스 번호.
            mode_text (str): 온도 조절기의 모드 텍스트 (예: 'heat', 'off').
            action_text (str): 온도 조절기의 동작 텍스트 (예: 'heating', 'idle').
            curTemp (int): 현재 온도 값.
            setTemp (int): 설정하고자 하는 목표 온도 값.

        Raises:
            Exception: 온도 업데이트 중 오류가 발생하면 예외를 발생시킵니다.
        """
        try:
            deviceID = 'Thermo' + str(idx)
            
            # 온도 상태 업데이트
            temperature = {
                'curTemp': self.pad(curTemp),
                'setTemp': self.pad(setTemp)
            }
            for state in temperature:
                # key = deviceID + state
                val = temperature[state]
                topic = self.STATE_TOPIC.format(deviceID, state)
                self.publish_mqtt(topic, val)
                self.HOMESTATE[deviceID + state] = val
            
            power_topic = self.STATE_TOPIC.format(deviceID, 'power')
            action_topic = self.STATE_TOPIC.format(deviceID, 'action')
            self.publish_mqtt(power_topic, mode_text)
            self.publish_mqtt(action_topic, action_text)
            
            self.logger.mqtt(f'->> HA : {deviceID} 온도={curTemp}°C, 설정={setTemp}°C, 상태={mode_text} {action_text}')
        except Exception as e:
            self.logger.error(f"온도 업데이트 중 오류 발생: {str(e)}")
 
    # async def update_fan(self, idx, value):
    #     try:
    #         deviceID = 'Fan' + str(idx + 1)
    #         if value == 'OFF':
    #             topic = self.STATE_TOPIC.format(deviceID, 'power')
    #             self.publish_mqtt(topic,'OFF')
    #         else:
    #             speed_map = {1: 'low', 2: 'medium', 3: 'high'}
    #             topic = self.STATE_TOPIC.format(deviceID, 'speed')
    #             speed = speed_map.get(int(value), 'low')
    #             self.publish_mqtt(topic, speed)
                
    #             topic = self.STATE_TOPIC.format(deviceID, 'power')
    #             self.publish_mqtt(topic, 'ON')
                
    #     except Exception as e:
    #         self.logger.error(f"팬 상태 업데이트 중 오류 발생: {str(e)}")

    # async def update_outlet_value(self, idx, val):
    #     deviceID = 'Outlet' + str(idx + 1)
    #     try:
    #         val = '%.1f' % float(int(val) / 10)
    #         topic = self.STATE_TOPIC.format(deviceID, 'watt')
    #         self.publish_mqtt(topic, val)
    #     except:
    #         pass

    # async def update_ev_value(self, idx, val):
    #     deviceID = 'EV' + str(idx + 1)
    #     if self.device_list is not None:
    #         try:
    #             BF = self.device_list['EV']['BasementFloor']
    #             val = str(int(val) - BF + 1) if val >= BF else 'B' + str(BF - int(val))
    #             topic = self.STATE_TOPIC.format(deviceID, 'floor')
    #             self.publish_mqtt(topic, val)
    #         except:
    #             pass
    #     else:
    #         self.logger.error("device_list가 초기화되지 않았습니다.")

    async def reboot_elfin_device(self):
        try:
            ew11 = telnetlib.Telnet(self.config['elfin_server'])
            ew11.read_until(b"login:")
            ew11.write(self.config['elfin_id'].encode('utf-8') + b'\n')
            ew11.read_until(b"password:")
            ew11.write(self.config['elfin_password'].encode('utf-8') + b'\n')
            ew11.write('Restart'.encode('utf-8') + b'\n')
            await asyncio.sleep(10)
        except Exception as err:
            self.logger.error(f'기기 재시작 오류: {str(err)}')

    # 메시지 처리 함수들
    @require_device_structure(None)
    async def process_elfin_data(self, raw_data: str) -> None:
        """Elfin 장치에서 전송된 raw_data를 분석합니다."""
        try:
            assert isinstance(self.DEVICE_STRUCTURE, dict), "DEVICE_STRUCTURE must be a dictionary"
            
            for k in range(0, len(raw_data), 16):
                data = raw_data[k:k + 16]
                if data == self.checksum(data):
                    self.COLLECTDATA['data'].add(data)
                    if len(self.COLLECTDATA['data']) > 100:
                        self.COLLECTDATA['data'] = set(list(self.COLLECTDATA['data'])[-100:])
                    
                    byte_data = bytearray.fromhex(data)
                    
                    for device_name, structure in self.DEVICE_STRUCTURE.items():
                        state_structure = structure['state']
                        if byte_data[0] == int(state_structure['header'], 16):
                            device_id_pos = state_structure['fieldPositions']['deviceId']
                            device_id = byte_data[int(device_id_pos)]
                            if device_name == 'Thermo':
                                power_pos = state_structure['fieldPositions']['power']
                                power = byte_data[int(power_pos)]
                                # 온도값을 10진수로 직접 해석
                                current_temp = int(format(byte_data[int(state_structure['fieldPositions']['currentTemp'])], '02x'))
                                target_temp = int(format(byte_data[int(state_structure['fieldPositions']['targetTemp'])], '02x'))
                                # power 값 비교를 16진수 문자열로 변환하여 수행
                                power_hex = format(power, '02x').upper()
                                power_values = state_structure['structure'][power_pos]['values']
                                # power 값과 정의된 값들을 직접 비교
                                power_off_hex = power_values.get('off', '').upper()
                                power_heating_hex = power_values.get('heating', '').upper()
                                mode_text = 'off' if power_hex == power_off_hex else 'heat'
                                action_text = 'heating' if power_hex == power_heating_hex else 'idle'
                                self.logger.signal(f'{byte_data.hex()}: 온도조절기 ### {device_id}번, 모드: {mode_text}, 현재 온도: {current_temp}°C, 설정 온도: {target_temp}°C')
                                await self.update_temperature(device_id, mode_text, action_text, current_temp, target_temp)
                            
                            elif device_name == 'Light':
                                power_pos = state_structure['fieldPositions']['power']
                                power = byte_data[int(power_pos)]
                                power_values = state_structure['structure'][power_pos]['values']
                                power_hex = format(power, '02x').upper()
                                state = "ON" if power_hex == power_values.get('on', '').upper() else "OFF"
                                
                                self.logger.signal(f'{byte_data.hex()}: 조명 ### {device_id}번, 상태: {state}')
                                await self.update_light(device_id, state)

                            #TODO: 다른 기기타입들 추가
                            
                            break
                else:
                    self.logger.signal(f'체크섬 불일치: {data}')
        
        except Exception as e:
            self.logger.error(f"Elfin 데이터 처리 중 오류 발생: {str(e)}")
            self.logger.debug(f"오류 상세 - raw_data: {raw_data}, device_name: {device_name if 'device_name' in locals() else 'N/A'}")

    @require_device_structure(None)
    async def process_ha_command(self, topics: List[str], value: str) -> None:
        try:
            device = ''.join(re.findall('[a-zA-Z]', topics[1]))
            device_id = int(''.join(re.findall('[0-9]', topics[1])))
            state = topics[2]

            assert isinstance(self.DEVICE_STRUCTURE, dict), "DEVICE_STRUCTURE must be a dictionary"

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
                cur_temp_str = self.HOMESTATE.get(topics[1] + 'curTemp')
                set_temp_str = self.HOMESTATE.get(topics[1] + 'setTemp')
                if cur_temp_str is None or set_temp_str is None:
                    self.logger.error('현재 온도 또는 설정 온도가 존재하지 않습니다.')
                    return
                
                cur_temp = int(float(cur_temp_str))
                set_temp = int(float(value)) if state == 'setTemp' else int(float(set_temp_str))
                
                if state == 'power':
                    if value == 'heat':
                        packet_hex = self.make_climate_command(device_id, cur_temp, set_temp, 'commandON')
                    else:
                        packet_hex = self.make_climate_command(device_id, cur_temp, set_temp, 'commandOFF')
                elif state == 'setTemp':
                        packet_hex = self.make_climate_command(device_id, cur_temp, set_temp, 'commandCHANGE')
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
                packet_hex = self.checksum(packet_hex)

            if packet_hex:
                expected_state = self.generate_expected_state_packet(packet_hex)
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
        """큐에 있는 모든 명령을 처리하고 예상되는 응답을 확인합니다."""
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
        
        if (isinstance(expected_state, dict) and 
            isinstance(expected_state.get('expected_packet'), str) and 
            isinstance(expected_state.get('required_bytes'), list)):
            
            expected_packet = expected_state['expected_packet']
            expected_bytes = bytes.fromhex(expected_packet)
            required_bytes = expected_state['required_bytes']
            assert isinstance(required_bytes, (list)), "required_bytes must be a list"
            
            # 수집된 데이터에서 예상 패킷 확인
            for received_packet in self.COLLECTDATA['data']:
                if not isinstance(received_packet, str):
                    continue
                    
                try:
                    received_bytes = bytes.fromhex(received_packet)
                except ValueError:
                    continue
                    
                # 필수 바이트 위치의 값들이 모두 일치하는지 확인
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
                    
        # 예상 상태 정보가 없거나 잘못된 경우
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

        Raises:
            Exception: 큐 처리 또는 기기 재시작 중 오류 발생시 예외를 발생시킵니다.
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

    # 메인 실행 함수
    def run(self) -> None:
        self.logger.info("저장된 기기정보가 있는지 확인합니다. (/share/commax_found_device.json)")
        try:
            with open(self.share_dir + '/commax_found_device.json') as file:
                self.device_list = json.load(file)
            if not self.device_list:
                self.logger.info('기기 목록이 비어있습니다. 기기 찾기를 시도합니다.')
                self.device_list = self.find_device()
            else:
                self.logger.info(f'기기정보를 찾았습니다. \n{json.dumps(self.device_list, ensure_ascii=False, indent=4)}')
        except IOError:
            self.logger.info('저장된 기기 정보가 없습니다. mqtt에 접속하여 기기 찾기를 시도합니다.')
            self.device_list = self.find_device()

        try:
            # 메인 MQTT 클라이언트 설정
            self.mqtt_client = self.setup_mqtt()
            
            # MQTT 연결 완료 이벤트를 위한 Event 객체 생성
            mqtt_connected = asyncio.Event()
            
            # MQTT 콜백 설정
            def on_connect_callback(client: mqtt.Client, userdata: Any, flags: Dict[str, int], rc: int) -> None:
                if rc == 0:  # 연결 성공
                    
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self.on_mqtt_connect(client, userdata, flags, rc), 
                            self.loop
                        )
                        mqtt_connected.set()
                    else:
                        self.logger.error("메인 루프가 실행되지 않았습니다.")
                        self.reconnect_mqtt()

                else:
                    # 재연결 시도
                    self.logger.error(f"MQTT 연결 실패 (코드: {rc})")

            def on_disconnect_callback(client: mqtt.Client, userdata: Any, rc: int) -> None:
                mqtt_connected.clear()  # 연결 해제 시 이벤트 초기화
                if rc != 0:
                    self.logger.error(f"예기치 않은 MQTT 연결 끊김 (코드: {rc})")
                    # 재연결 시도
                    self.reconnect_mqtt()
            
            self.mqtt_client.on_connect = on_connect_callback
            self.mqtt_client.on_disconnect = on_disconnect_callback
            self.mqtt_client.on_message = self.on_mqtt_message
            
            # MQTT 최초 연결
            self.connect_mqtt()
            
            self.mqtt_client.loop_start()
            
            # 메인 루프 실행
            self.loop = asyncio.get_event_loop()

            # MQTT 연결 완료를 기다림
            async def wait_for_mqtt():
                while True:  # 무한 루프로 변경
                    try:
                        await mqtt_connected.wait()
                        self.logger.info("MQTT 연결이 완료되었습니다. 메인 루프를 시작합니다.")
                        
                        while mqtt_connected.is_set():
                            await self.process_queue_and_monitor(self.config.get('elfin_reboot_interval', 10))
                            await asyncio.sleep(0.1)
                            
                    except Exception as e:
                        self.logger.error(f"메인 루프 실행 중 오류 발생: {str(e)}")
                        await asyncio.sleep(1)  # 오류 발생 시 1초 대기
                    
                    if not mqtt_connected.is_set():
                        self.logger.info("MQTT 재연결을 기다립니다...")
                        await asyncio.sleep(5)  # 재연결 시도 전 5초 대기
            
            # 메인 루프 실행
            self.loop.run_until_complete(wait_for_mqtt())
            
        except Exception as e:
            self.logger.error(f"실행 중 오류 발생: {str(e)}")
            raise
        finally:
            if self.loop:
                self.loop.close()
            if self.mqtt_client:
                self.mqtt_client.loop_stop()

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
            

if __name__ == '__main__':
    with open('/data/options.json') as file:
        CONFIG = json.load(file)
    logger = Logger(debug=CONFIG['DEBUG'], elfin_log=CONFIG['elfin_log'], mqtt_log=CONFIG['mqtt_log'])
    logger.info("########################################################")
    logger.info("'Commax Wallpad Addon by ew11-mqtt'을 시작합니다.")
    controller = WallpadController(CONFIG, logger)
    controller.run()
