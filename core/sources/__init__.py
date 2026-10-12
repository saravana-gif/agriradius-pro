"""Data-provider adapters for scheduled jobs.

Jobs talk to an adapter, not to a vendor API, so a provider can be
swapped without touching the job or the store. This matters because
the free tiers we lean on (Open-Meteo, Earth Engine) are licensed for
non-commercial use only.
"""
