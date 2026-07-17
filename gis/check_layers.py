from data.gis_data import GIS_DATA

def check_layers():

    print()

    print("Checking GIS datasets...")

    print("-"*50)

    for state in GIS_DATA:

        print()

        print(state.upper())

        for layer, path in GIS_DATA[state].items():

            if path.exists():

                print(f"✔ {layer:<15} {path}")

            else:

                print(f"✘ {layer:<15} MISSING")