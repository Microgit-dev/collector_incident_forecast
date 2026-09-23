"""
Интеграция с корпоративным каталогом (LDAP/AD) через django-auth-ldap.

У заказчика тестового контура нет, поэтому в docker compose поднимается OpenLDAP с
демо-учётками. Группы каталога cn=<role> в ou=roles маппятся на одноимённые Django Groups,
то есть на роли из roles.py. Для реального AD достаточно поменять переменные окружения.
"""


def configure_ldap(env, settings: dict) -> None:
    import ldap
    from django_auth_ldap.config import GroupOfNamesType, LDAPSearch

    base_dn = env("LDAP_BASE_DN", default="dc=collector,dc=local")
    settings["AUTH_LDAP_SERVER_URI"] = env("LDAP_SERVER_URI", default="ldap://openldap:389")
    settings["AUTH_LDAP_BIND_DN"] = env("LDAP_BIND_DN", default=f"cn=admin,{base_dn}")
    settings["AUTH_LDAP_BIND_PASSWORD"] = env("LDAP_BIND_PASSWORD", default="admin")
    settings["AUTH_LDAP_USER_SEARCH"] = LDAPSearch(
        f"ou=people,{base_dn}", ldap.SCOPE_SUBTREE, "(uid=%(user)s)"
    )
    settings["AUTH_LDAP_GROUP_SEARCH"] = LDAPSearch(
        f"ou=roles,{base_dn}", ldap.SCOPE_SUBTREE, "(objectClass=groupOfNames)"
    )
    settings["AUTH_LDAP_GROUP_TYPE"] = GroupOfNamesType(name_attr="cn")
    settings["AUTH_LDAP_MIRROR_GROUPS"] = True
    settings["AUTH_LDAP_USER_ATTR_MAP"] = {"first_name": "givenName", "last_name": "sn", "email": "mail"}
    settings["AUTH_LDAP_ALWAYS_UPDATE_USER"] = True
