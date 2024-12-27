from typing import Dict, Any, Optional, List
from utils import checksum
from logger import LoggerInstance

class PacketHandler:
    def __init__(self, device_structure: Dict[str, Any], logger: LoggerInstance):
        self.DEVICE_STRUCTURE = device_structure
        self.logger = logger

    def make_climate_command(self, device_id: int, current_temp: int, target_temp: int, command_type: str) -> Optional[str]:
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
            Optional[str]: 체크섬이 포함된 16진수 명령어 문자열 또는 None
        """
        try:
            thermo_structure = self.DEVICE_STRUCTURE["Thermo"]
            command = thermo_structure["command"]
            
            # 패킷 초기화
            packet = bytearray([0] * 7)

            # 헤더 설정
            packet[0] = int(command["header"], 16)
            
            # 기기 번호 설정
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
            return checksum(packet_hex)
        
        except Exception as e:
            self.logger.error(f'예외 발생: {e}')
            return None

    def generate_expected_state_packet(self, command_str: str) -> Optional[Dict[str, Any]]:
        """명령 패킷으로부터 예상되는 상태 패킷을 생성합니다.
        
        Args:
            command_str (str): 16진수 형태의 명령 패킷 문자열
            
        Returns:
            Optional[Dict[str, Any]]: 예상되는 상태 패킷 정보를 담은 딕셔너리 또는 None
        """
        try:
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
            command_field_positions = command_structure['fieldPositions']
            state_field_positions = state_structure['fieldPositions']
            
            # 상태 패킷 초기화 (7바이트 - 체크섬은 나중에 추가)
            status_packet = bytearray(7)
            # 필요한 바이트 리스트
            required_bytes = [0] # 헤더는 항상 포함
            
            # 상태 패킷 헤더 설정
            status_packet[0] = int(state_structure['header'], 16)
            
            # 기기 ID 복사
            device_id_pos = state_field_positions.get('deviceId', 2)
            status_packet[int(device_id_pos)] = command_packet[int(command_field_positions.get('deviceId', 1))]
            required_bytes.append(int(device_id_pos))

            if device_type == 'Thermo':
                # 온도조절기 상태 패킷 생성
                command_type_pos = command_field_positions.get('commandType', 2)
                command_type = command_packet[int(command_type_pos)]
                
                power_pos = state_field_positions.get('power',1)
                if command_type == int(command_structure["structure"][command_type_pos]['values']['power'], 16):
                    command_value = command_packet[int(command_field_positions.get('value', 3))]
                    status_packet[int(power_pos)] = command_value
                    required_bytes.append(int(power_pos))
                elif command_type == int(command_structure["structure"][command_type_pos]['values']['change'], 16):
                    status_packet[int(power_pos)] = int(state_structure['structure'][str(power_pos)]['values']['idle'], 16)
                    target_temp = command_packet[int(command_field_positions.get('value', 3))]
                    target_temp_pos = state_field_positions.get('targetTemp', 4)
                    status_packet[int(target_temp_pos)] = target_temp
                    current_temp_pos = state_field_positions.get('currentTemp', 5)
                    status_packet[int(current_temp_pos)] = target_temp
                    required_bytes.append(int(target_temp_pos))

            elif device_type in ['Light', 'LightBreaker']:
                # 조명 상태 패킷 생성
                power_pos = state_field_positions.get('power',1)
                command_value = command_packet[int(command_field_positions.get('power',2))]
                status_packet[int(power_pos)] = command_value
                required_bytes.append(int(power_pos))

            elif device_type == 'Fan':
                # 환기장치 상태 패킷 생성
                power_pos = state_field_positions.get('power',1)
                command_type_pos = command_field_positions.get('commandType', 2)
                command_type = command_packet[int(command_type_pos)]
                command_value = command_packet[int(command_field_positions.get('value', 3))]
                status_packet[int(power_pos)] = command_value
                required_bytes.append(int(power_pos))
            
            # 상태 패킷을 16진수 문자열로 변환
            status_hex = status_packet.hex().upper()
            status_hex = checksum(status_hex)
            if status_hex is None:
                self.logger.error("상태 패킷 체크섬 생성 실패") 
                return None

            return {
                'expected_packet': status_hex,
                'required_bytes': sorted(required_bytes)
            }
            
        except Exception as e:
            self.logger.error(f"상태 패킷 생성 중 오류 발생: {str(e)}")
            return None 