from gis.spatial import villages_in_buffer


def get_villages(lat, lon, radius):

    gdf = villages_in_buffer(
        lat,
        lon,
        radius
    )

    cols = [
        "vilname11",
        "sdtname",
        "dtname",
        "stname"
    ]

    cols = [c for c in cols if c in gdf.columns]

    return gdf[cols]