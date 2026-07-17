import ee
from gee.auth import initialize

initialize()

print(ee.Number(5).multiply(5).getInfo())