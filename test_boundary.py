from gis.village_search import get_villages

villages = get_villages(
    11.923,
    76.939,
    20
)

print(villages.head())

print()

print("Villages Found:", len(villages))