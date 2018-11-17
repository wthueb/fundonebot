def to_nearest(num: float, tick_size: float) -> float:
    mult = 1 / tick_size
    
    rounded = round(num * mult)
    
    return float(rounded / mult)
