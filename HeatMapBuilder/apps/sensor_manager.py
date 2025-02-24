import os
import requests
from typing import Optional, Dict, Any, List

class SensorManager:
    """센서 상태 관리를 담당하는 클래스"""
    
    def __init__(self, is_local: bool, config_manager, logger, supervisor_token):
        self.is_local = is_local
        self.config_manager = config_manager
        self.logger = logger
        self.supervisor_token = supervisor_token

    
    def get_ha_api(self) -> Optional[Dict[str, Any]]:
        """Home Assistant API 설정"""
        if self.is_local:
            return {
                'base_url': 'mock_url',
                'headers': {'Content-Type': 'application/json'}
            }
        if not self.supervisor_token:
            self.logger.error("Supervisor Token is not configured")
            return None
        return {
            'base_url': 'http://supervisor/core/api',
            'headers': {
                'Authorization': f'Bearer {self.supervisor_token}',
                'Content-Type': 'application/json'
            }
        }
    
    def get_sensor_state(self, entity_id: str) -> Dict[str, Any]:
        """센서 상태 조회"""
        try:
            if self.is_local:
                mock_data = self.config_manager.get_mock_data()
                for sensor in mock_data.get('temperature_sensors', []):
                    if sensor['entity_id'] == entity_id:
                        return {
                            'entity_id': entity_id,
                            'state': sensor.get('state', '0'),
                            'attributes': sensor.get('attributes', {})
                        }
                self.logger.warning(f"Mock 센서 데이터를 찾을 수 없음: {entity_id}")
                return {'state': '20', 'entity_id': entity_id}
            
            api = self.get_ha_api()
            if not api:
                self.logger.error("Home Assistant API 설정을 가져올 수 없습니다")
                return {'state': '0', 'entity_id': entity_id}
            
            self.logger.info(f"센서 상태 조회 중: {entity_id}")
            response = requests.get(
                f"{api['base_url']}/states/{entity_id}",
                headers=api['headers']
            )
            return response.json()
        except Exception as e:
            self.logger.error(f"센서 상태 조회 실패: {str(e)}")
            return {'state': '0', 'entity_id': entity_id}
    
    def get_all_states(self) -> List[Dict]:
        """모든 센서 상태 조회"""
        if self.is_local:
            mock_data = self.config_manager.get_mock_data()
            self.logger.debug(f"가상 센서 상태 조회: {mock_data}")
            return mock_data.get('temperature_sensors', [])
        
        api = self.get_ha_api()
        if not api:
            self.logger.error("Home Assistant API 설정을 가져올 수 없습니다")
            return []
        

        try:
            response = requests.get(f"{api['base_url']}/states", headers=api['headers'])
            response.raise_for_status()
            states = response.json()
        except Exception as e:
            self.logger.error(f"센서 상태 조회 실패: {str(e)}")
            self.logger.error(f"응답 내용: {response.text}")
            return []
        
        # self.logger.debug(f"API로 센서 상태 조회 성공: {states}")
        return [
            state for state in states
            if state.get('attributes', {}).get('device_class') == 'temperature' and
               state.get('attributes', {}).get('state_class') == 'measurement'
        ]


