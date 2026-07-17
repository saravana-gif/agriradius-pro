import pandas as pd

def export_excel(results, filename):

    df = pd.DataFrame(results)

    df.to_excel(filename, index=False)

    print("Excel exported successfully.")