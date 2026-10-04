"""reelkit — turn a landscape football broadcast clip into a vertical Reel/Short.

Pipeline:  ffmpeg normalize -> YOLO ball detect -> Kalman track (+coast) ->
           virtual camera (speed/accel limited, deadzone) -> per-shot layout
           (tracked 9:16 crop | full frame + blurred pad) -> watermark inpaint ->
           graphics -> H.264 + audio.
"""
__version__ = "1.43"
