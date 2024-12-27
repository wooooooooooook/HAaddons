"""
월패드 통신에 필요한 유틸리티 함수들을 제공하는 모듈입니다.

이 모듈은 다음과 같은 기능들을 제공합니다:
- 체크섬 계산 및 검증
- 숫자 패딩
"""

from typing import Optional

def checksum(input_hex: str) -> Optional[str]:
    """
    input_hex에 체크섬을 붙여주는 함수입니다.
    
    체크섬 계산 방식:
    1. 입력된 16진수 문자열의 처음 14자리를 2자리씩 나누어 각각 정수로 변환
    2. 짝수 위치의 값들의 합과 홀수 위치의 값들의 합을 계산
    3. 계산된 값들을 16진수로 변환하여 원래 문자열 뒤에 추가
    
    Args:
        input_hex (str): 기본 16진수 명령어 문자열 (14자리)
    
    Returns:
        Optional[str]: 체크섬이 포함된 16자리 16진수 명령어. 실패시 None 반환
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

def pad(value: int) -> str:
    """
    한 자리 숫자를 두 자리 문자열로 변환합니다.
    
    Args:
        value (int): 변환할 숫자 (0-99)
        
    Returns:
        str: 두 자리 문자열 (예: "01", "10")
        
    Example:
        >>> pad(5)
        "05"
        >>> pad(12)
        "12"
    """
    return '0' + str(value) if value < 10 else str(value)

def verify_checksum(data: str) -> bool:
    """
    체크섬이 포함된 데이터의 유효성을 검증합니다.
    
    Args:
        data (str): 체크섬이 포함된 16자리 16진수 문자열
        
    Returns:
        bool: 체크섬이 유효하면 True, 아니면 False
    """
    try:
        if len(data) != 16:
            return False
        return checksum(data[:14]) == data
    except:
        return False 