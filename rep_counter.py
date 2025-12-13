"""
Rep counting logic with form validation & Hysteresis
"""

class RepCounter:
    """Handles rep counting logic with form validation"""
    
    def __init__(self, calibration_data, min_rep_duration: float = 0.5):
        self.calibration = calibration_data
        self.min_rep_duration = min_rep_duration
        # Hysteresis margin prevents flickering when hovering near threshold
        self.hysteresis_margin = 8 
    
    def process_rep(self, arm: str, angle: int, metrics, 
                   current_time: float, history) -> None:
        """Process rep counting and form feedback for one arm"""
        from constants import ArmStage
        
        # Update current rep time
        metrics.curr_rep_time = current_time - metrics.last_down_time
        metrics.angle = angle
        
        previous_feedback = metrics.feedback
        metrics.feedback = ""
        
        # --- 1. STATE MACHINE WITH HYSTERESIS ---
        # Must go significantly below threshold to trigger UP
        if angle < (self.calibration.contracted_threshold - self.hysteresis_margin):
            metrics.stage = ArmStage.UP.value
        
        # Must go significantly above threshold to trigger DOWN
        elif angle > (self.calibration.extended_threshold + self.hysteresis_margin):
            
            # Rep Counting Logic
            if metrics.stage == ArmStage.UP.value and metrics.curr_rep_time >= self.min_rep_duration:
                rep_time = current_time - metrics.last_down_time
                
                if metrics.min_rep_time == 0.0 or rep_time < metrics.min_rep_time:
                    metrics.min_rep_time = rep_time
                
                metrics.rep_count += 1
                metrics.rep_time = rep_time
                metrics.last_down_time = current_time
            
            metrics.stage = ArmStage.DOWN.value
        
        # --- 2. FORM FEEDBACK (Optimized for TTS) ---
        feedback_key = f'{arm.lower()}_feedback_count'
        
        # Safety Limits
        if angle < self.calibration.safe_angle_min:
            metrics.feedback = "Over Curling"
            if metrics.feedback != previous_feedback:
                setattr(history, feedback_key, getattr(history, feedback_key) + 1)
                
        elif angle > self.calibration.safe_angle_max:
            metrics.feedback = "Over Extending"
            if metrics.feedback != previous_feedback:
                setattr(history, feedback_key, getattr(history, feedback_key) + 1)
        
        # ROM Guidance (Only if stuck in middle)
        elif (self.calibration.contracted_threshold < angle < self.calibration.extended_threshold):
            
            # If in DOWN stage but arm bent
            if metrics.stage == ArmStage.DOWN.value and angle < (self.calibration.extended_threshold - 15):
                 metrics.feedback = "Extend Fully"
            
            # If in UP stage but arm not curled enough
            elif metrics.stage == ArmStage.UP.value and angle > (self.calibration.contracted_threshold + 15):
                metrics.feedback = "Curl Higher"