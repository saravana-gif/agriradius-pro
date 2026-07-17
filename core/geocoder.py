from geopy.geocoders import Nominatim

geolocator = Nominatim(user_agent="AgriRadiusPro")

def search_place(place_name):
    try:
        location = geolocator.geocode(place_name)

        if location:
            return location.latitude, location.longitude

    except Exception:
        pass

    return None