"""
Angle calculation and smoothing algorithms - OPTIMIZED ACCURACY
"""
import numpy as np
from collections import deque
from typing import Dict, List

class AngleCalculator:
    """Handles all angle-related calculations with Hybrid Smoothing"""
    
    def __init__(self, smoothing_window: int = 5):
        # Reduced window size slightly for faster response, relying on EMA for smoothness
        self.angle_buffers: Dict[str, deque] = {
            'RIGHT': deque(maxlen=smoothing_window),
            'LEFT': deque(maxlen=smoothing_window)
        }
        # Store previous smoothed values for Exponential Moving Average (EMA)
        self.prev_ema: Dict[str, float] = {
            'RIGHT': None,
            'LEFT': None
        }
        self.alpha = 0.6  # Smoothing factor (0.0 - 1.0). Higher = less smoothing, faster response.
    
    @staticmethod
    def calculate_angle(a: List[float], b: List[float], c: List[float]) -> float:
        """Calculate angle between three points using vectors"""
        a = np.array(a)
        b = np.array(b)
        c = np.array(c)
        
        radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - \
                  np.arctan2(a[1] - b[1], a[0] - b[0])
        angle = np.abs(np.degrees(radians))
        
        return 360 - angle if angle > 180.0 else angle
    
    def get_smoothed_angle(self, arm: str, new_angle: float) -> int:
        """
        Apply Hybrid Smoothing: Median Filter (removes outliers) + EMA (smooths jitter)
        """
        buffer = self.angle_buffers[arm]
        
        # 1. Add raw value to buffer
        if len(buffer) == 0:
            for _ in range(buffer.maxlen):
                buffer.append(new_angle)
        buffer.append(new_angle)
        
        # 2. Median Step: Good for removing random single-frame glitches
        median_val = np.median(buffer)
        
        # 3. EMA Step: Good for smooth transitions
        if self.prev_ema[arm] is None:
            self.prev_ema[arm] = median_val
        else:
            # New_EMA = (Current * alpha) + (Previous_EMA * (1 - alpha))
            self.prev_ema[arm] = (median_val * self.alpha) + (self.prev_ema[arm] * (1 - self.alpha))
            
        return int(self.prev_ema[arm])
    
    def reset_buffers(self):
        """Clear all angle buffers"""
        for buffer in self.angle_buffers.values():
            buffer.clear()
        self.prev_ema = {'RIGHT': None, 'LEFT': None}