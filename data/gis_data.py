from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

GIS_DATA = {
    "karnataka": {
        "villages": DATA_DIR / "boundaries" / "Karnataka" / "karnataka_villages.shp",
        "taluks": DATA_DIR / "boundaries" / "Karnataka" / "karnataka_taluks.shp",
        "districts": DATA_DIR / "boundaries" / "Karnataka" / "karnataka_districts.shp",
    }
}