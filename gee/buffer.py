import ee

def create_buffer(latitude, longitude, radius_km):
    point = ee.Geometry.Point([longitude, latitude])
    return point.buffer(radius_km * 1000)