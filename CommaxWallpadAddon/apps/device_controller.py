"""
월패드 기기들의 상태를 관리하고 업데이트하는 모듈입니다.

이 모듈은 다음과 같은 기능을 제공합니다:
- 각 기기의 현재 상태 저장 및 관리
- 상태 변경 시 MQTT 메시지 발행
- 기기별 상태 업데이트 메서드 제공
"""

import json
from typing import Dict, Any, Optional
from logger import LoggerClass

class DeviceController:
    """
    월패드의 각 기기들의 상태를 관리하는 클래스입니다.
    
    Attributes:
        HOMESTATE (Dict[str, Any]): 각 기기의 현재 상태를 저장하는 딕셔너리
        logger (LoggerClass): 로깅을 위한 Logger 인스턴스
        mqtt_handler: MQTT 핸들러 인스턴스
        state_topic (str): MQTT 상태 토픽 형식
    """
    
    def __init__(self, mqtt_handler, logger: LoggerClass, state_topic: str) -> None:
        """
        DeviceController 클래스를 초기화합니다.
        
        Args:
            mqtt_handler: MQTT 핸들러 인스턴스
            logger (LoggerClass): 로깅을 위한 Logger 인스턴스
            state_topic (str): MQTT 상태 토픽 형식
        """
        self.HOMESTATE: Dict[str, Any] = {}
        self.logger = logger
        self.mqtt_handler = mqtt_handler
        self.STATE_TOPIC = state_topic

    def publish_state(self, device_id: str, state_type: str, value: str) -> None:
        """
        기기의 상태를 MQTT 브로커에 발행합니다.
        
        Args:
            device_id (str): 기기 ID
            state_type (str): 상태 유형 (예: power, temperature 등)
            value (str): 상태 값
            
        Note:
            상태가 변경된 경우에만 메시지를 발행합니다.
        """
        state_id = device_id + state_type
        current_state = self.HOMESTATE.get(state_id)
        
        if current_state != value:
            self.HOMESTATE[state_id] = value
            topic = self.STATE_TOPIC.format(device_id, state_type)
            self.mqtt_handler.publish(topic, value, retain=True)

    async def update_light(self, device_id: int, state: str) -> None:
        """
        조명의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 조명 ID
            state (str): 조명 상태 ("ON" 또는 "OFF")
        """
        self.publish_state(f"Light{device_id}", "power", state)

    async def update_light_breaker(self, device_id: int, state: str) -> None:
        """
        조명 차단기의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 차단기 ID
            state (str): 차단기 상태 ("ON" 또는 "OFF")
        """
        self.publish_state(f"LightBreaker{device_id}", "power", state)

    async def update_outlet(self, device_id: int, state: str, watt: Optional[int] = None) -> None:
        """
        콘센트의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 콘센트 ID
            state (str): 콘센트 상태 ("ON" 또는 "OFF")
            watt (Optional[int]): 현재 소비 전력 (와트)
        """
        self.publish_state(f"Outlet{device_id}", "power", state)
        if watt is not None:
            self.publish_state(f"Outlet{device_id}", "watt", str(watt))

    async def update_gas(self, device_id: int, state: str) -> None:
        """
        가스밸브의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 가스밸브 ID
            state (str): 밸브 상태 ("ON" 또는 "OFF")
        """
        self.publish_state(f"Gas{device_id}", "power", state)

    async def update_fan(self, device_id: int, state: str, speed: Optional[str] = None) -> None:
        """
        환기장치의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 환기장치 ID
            state (str): 전원 상태 ("ON" 또는 "OFF")
            speed (Optional[str]): 팬 속도 ("low", "medium", "high")
        """
        self.publish_state(f"Fan{device_id}", "power", state)
        if speed:
            self.publish_state(f"Fan{device_id}", "speed", speed)

    async def update_temperature(self, device_id: int, mode: str, action: str, 
                               current_temp: float, target_temp: float) -> None:
        """
        온도조절기의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 온도조절기 ID
            mode (str): 운전 모드 ("off" 또는 "heat")
            action (str): 현재 동작 ("idle" 또는 "heating")
            current_temp (float): 현재 온도
            target_temp (float): 설정 온도
        """
        device_name = f"Thermo{device_id}"
        self.publish_state(device_name, "power", mode)
        self.publish_state(device_name, "action", action)
        self.publish_state(device_name, "curTemp", str(current_temp))
        self.publish_state(device_name, "setTemp", str(target_temp))

    async def update_ev(self, device_id: int, state: str, floor: str) -> None:
        """
        엘리베이터의 상태를 업데이트합니다.
        
        Args:
            device_id (int): 엘리베이터 ID
            state (str): 호출 상태 ("ON" 또는 "OFF")
            floor (str): 현재 층수
        """
        device_name = f"EV{device_id}"
        self.publish_state(device_name, "power", state)
        self.publish_state(device_name, "floor", floor) 