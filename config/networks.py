"""
Network configuration for DOM sync.
Add/remove networks here to control which GAM networks are synced.
"""

NETWORKS = [
    {
        "network_code": "23154379558",
        "name": "Maturidade",
        "enabled": True,
    },
    {
        "network_code": "23025038160",
        "name": "RedePublica",
        "enabled": True,
    },
    {
        "network_code": "23062194970",
        "name": "Qcartao",
        "enabled": True,
    },
    # Add more networks as needed
]


def get_enabled_networks():
    """Return only enabled networks."""
    return [n for n in NETWORKS if n.get("enabled", True)]


def get_network_by_code(code: str):
    """Find network by code."""
    return next((n for n in NETWORKS if n["network_code"] == code), None)
