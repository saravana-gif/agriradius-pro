import ee
from config import PROJECT_ID


def initialize():

    try:
        ee.Initialize(project=PROJECT_ID)

    except Exception:

        ee.Authenticate()

        ee.Initialize(project=PROJECT_ID)