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
        "name": "Qcartao", # linkdobem.com
        "enabled": True,
    },
    {
        "network_code": "21670997783",
        "name": "Bloogao", # bloogao.com 
        "enabled": True,
    },
    {
        "network_code": "23154702080",
        "name": "DOM-MI-LATAM",
        # MCM Manage Inventory do GAM LATAM: os dados vem da API de clientes do office.joinads.me,
        # filtrados pela network pai; a credencial GAM nao precisa de acesso ao pai.
        # Sem "domains": entram os dominios do usuario do token e dos usuarios filhos dele no office.
        # Habilitar so depois do deploy do office (escopo de dominios + filtro `network` no key-value)
        # e com JOINADS_API_TOKEN.
        "enabled": False,
        "source": "joinads_api",
        "joinads_network": "22088551542",
        "revenue_field": "revenue",
    },
    # Add more networks as needed
]


def get_enabled_networks():
    """Return only enabled networks."""
    return [n for n in NETWORKS if n.get("enabled", True)]


def get_network_by_code(code: str):
    """Find network by code."""
    return next((n for n in NETWORKS if n["network_code"] == code), None)
