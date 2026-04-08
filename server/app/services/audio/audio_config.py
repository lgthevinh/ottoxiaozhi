class AudioConstants:
    PACKET_START = 0x01
    PACKET_END = 0x03
    
    SAMPLE_RATE = 16000
    CHANNELS = 1
    BITS_PER_SAMPLE = 16
    FRAME_DURATION = 20  # milliseconds
    SAMPLES_PER_FRAME = (SAMPLE_RATE * FRAME_DURATION) // 1000 # 320 samples per frame
    BYTES_PER_SAMPLE = (BITS_PER_SAMPLE // 8) * CHANNELS * SAMPLES_PER_FRAME # 640 bytes per frame