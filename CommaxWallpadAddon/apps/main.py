import json
import os
import yaml # type: ignore #PyYAML
import time
import asyncio
from typing import Dict, Any, Optional
from logger import LoggerInstance
from mqtt_handler import MQTTHandler
from web_server import WebServer
from utils import checksum

class WallpadController:
    def __init__(self, config: dict, logger: LoggerInstance) -> None:
        self.config = config
        self.logger = logger
        self.share_dir = '/share'
        self.device_list: Optional[Dict[str, Any]] = None
        self.DEVICE_STRUCTURE: Optional[Dict[str, Any]] = None
        self.load_devices_and_packets_structures()
        if self.DEVICE_STRUCTURE is None:
            raise ValueError("DEVICE_STRUCTURE가 초기화되지 않았습니다.")
        self.mqtt_handler = MQTTHandler(config, logger, self.DEVICE_STRUCTURE)
        self.web_server = WebServer(self)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def load_devices_and_packets_structures(self) -> None:
        """
        기기 및 패킷 구조를 로드하는 함수
        
        config의 vendor 설정에 따라 기본 구조 파일 또는 커스텀 구조 파일을 로드합니다.
        vendor가 설정되지 않은 경우 기본값으로 'commax'를 사용합니다.
        """
        try:
            vendor = self.config.get('vendor', 'commax').lower()
            default_file_path = f'/apps/packet_structures_{vendor}.yaml'
            custom_file_path = f'/share/packet_structures_custom.yaml'

            if vendor == 'custom':
                try:
                    with open(custom_file_path) as file:
                        self.DEVICE_STRUCTURE = yaml.safe_load(file)
                    self.logger.info(f'{vendor} 패킷 구조를 로드했습니다.')
                except FileNotFoundError:
                    self.logger.error(f'{custom_file_path} 파일을 찾을 수 없습니다.')
            else:
                try:
                    with open(default_file_path) as file:
                        self.DEVICE_STRUCTURE = yaml.safe_load(file)
                    self.logger.info(f'{vendor} 패킷 구조를 로드했습니다.')
                except FileNotFoundError:
                    self.logger.error(f'{vendor} 패킷 구조 파일을 찾을 수 없습니다.')
                    return

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

    def find_device(self) -> dict:
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
                    client.subscribe(f'{self.mqtt_handler.ELFIN_TOPIC}/#', 0)
                else:
                    self.logger.error(f"Connection failed with code {rc}")
            
            def on_message(client, userdata, msg):
                assert isinstance(self.DEVICE_STRUCTURE, dict), "DEVICE_STRUCTURE must be a dictionary"
                raw_data = msg.payload.hex().upper()
                for k in range(0, len(raw_data), 16):
                    data = raw_data[k:k + 16]
                    if data == checksum(data) and data[:2] in state_prefixes:
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
            temp_client = self.mqtt_handler.setup_mqtt('commax_finder')
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
            
        except Exception as e:
            self.logger.error(f'기기 검색 중 오류 발생: {str(e)}')
            return {}

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
            # 웹서버 시작
            self.web_server.run()
            
            # 메인 MQTT 클라이언트 설정
            self.mqtt_client = self.mqtt_handler.setup_mqtt()
            
            # MQTT 연결 완료 이벤트를 위한 Event 객체 생성
            mqtt_connected = asyncio.Event()
            
            # MQTT 콜백 설정
            def on_connect_callback(client, userdata, flags, rc):
                if rc == 0:  # 연결 성공
                    
                    if self.loop and self.loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self.mqtt_handler.on_mqtt_connect(client, userdata, flags, rc), 
                            self.loop
                        )
                        mqtt_connected.set()
                    else:
                        self.logger.error("인 루프가 실행되지 않았습니다.")
                        self.mqtt_handler.reconnect_mqtt()

                else:
                    # 재연결 시도
                    self.logger.error(f"MQTT 연결 실패 (코드: {rc})")

            def on_disconnect_callback(client, userdata, rc):
                mqtt_connected.clear()  # 연결 해제 시 이벤트 초기화
                if rc != 0:
                    self.logger.error(f"예기치 않은 MQTT 연결 끊김 (코드: {rc})")
                    # 재연결 시도
                    self.mqtt_handler.reconnect_mqtt()
            
            self.mqtt_client.on_connect = on_connect_callback
            self.mqtt_client.on_disconnect = on_disconnect_callback
            self.mqtt_client.on_message = self.mqtt_handler.on_message
            
            # MQTT 최초 연결
            self.mqtt_handler.connect_mqtt()
            
            self.mqtt_client.loop_start()
            
            # 메인 루프 실행
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # MQTT 연결 완료를 기다림
            async def wait_for_mqtt():
                while True:  # 무한 루프로 변경
                    try:
                        await mqtt_connected.wait()
                        self.logger.info("MQTT 연결이 완료되었습니다. 메인 루프를 시작합니다.")
                        
                        while mqtt_connected.is_set():
                            await self.mqtt_handler.process_queue_and_monitor(self.config.get('elfin_reboot_interval', 10))
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
        if hasattr(self, 'mqtt_handler'):
            del self.mqtt_handler

if __name__ == '__main__':
    with open('/data/options.json') as file:
        CONFIG = json.load(file)
    logger = LoggerInstance(debug=CONFIG['DEBUG'], elfin_log=CONFIG['elfin_log'], mqtt_log=CONFIG['mqtt_log'])
    logger.info("########################################################")
    logger.info("'Commax Wallpad Addon by ew11-mqtt'을 시작합니다.")
    controller = WallpadController(CONFIG, logger)
    controller.run()
