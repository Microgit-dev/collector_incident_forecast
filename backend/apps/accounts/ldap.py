"""
Интеграция с корпоративным каталогом (LDAP/AD) через django-auth-ldap.

У заказчика тестового контура нет, поэтому в docker compose поднимается OpenLDAP с
демо-учётками. Группы каталога cn=<role> в ou=roles маппятся на одноимённые Django Groups,
то есть на роли из roles.py; атрибут departmentNumber — код команды (Team.code), из него
берутся команда и зона ответственности. Для реального AD достаточно поменять переменные окружения:
ветки и фильтр поиска (в AD — sAMAccountName), тип групп и StartTLS.
"""


def configure_ldap(env, settings: dict) -> None:
    import ldap
    from django_auth_ldap.config import ActiveDirectoryGroupType, GroupOfNamesType, LDAPSearch

    base_dn = env("LDAP_BASE_DN", default="dc=collector,dc=local")
    settings["AUTH_LDAP_SERVER_URI"] = env("LDAP_SERVER_URI", default="ldap://openldap:389")
    settings["AUTH_LDAP_BIND_DN"] = env("LDAP_BIND_DN", default=f"cn=admin,{base_dn}")
    settings["AUTH_LDAP_BIND_PASSWORD"] = env("LDAP_BIND_PASSWORD", default="admin")
    settings["AUTH_LDAP_START_TLS"] = env.bool("LDAP_START_TLS", default=False)
    # Корневой сертификат ЦС заказчика для ldaps:// и StartTLS (файл монтируется в контейнер)
    if ca := env("LDAP_CA_CERT", default=""):
        settings["AUTH_LDAP_GLOBAL_OPTIONS"] = {ldap.OPT_X_TLS_CACERTFILE: ca, ldap.OPT_X_TLS_NEWCTX: 0}
    settings["AUTH_LDAP_USER_SEARCH"] = LDAPSearch(
        env("LDAP_USER_BASE", default=f"ou=people,{base_dn}"),
        ldap.SCOPE_SUBTREE,
        env("LDAP_USER_FILTER", default="(uid=%(user)s)"),
    )
    settings["AUTH_LDAP_GROUP_SEARCH"] = LDAPSearch(
        env("LDAP_GROUP_BASE", default=f"ou=roles,{base_dn}"),
        ldap.SCOPE_SUBTREE,
        env("LDAP_GROUP_FILTER", default="(objectClass=groupOfNames)"),
    )
    # AD: группы — objectClass=group, членство через member; имя роли — cn группы
    ad = env("LDAP_GROUP_TYPE", default="groupOfNames").lower() == "ad"
    settings["AUTH_LDAP_GROUP_TYPE"] = (
        ActiveDirectoryGroupType(name_attr="cn") if ad else GroupOfNamesType(name_attr="cn")
    )
    settings["AUTH_LDAP_MIRROR_GROUPS"] = True
    settings["AUTH_LDAP_USER_ATTR_MAP"] = {"first_name": "givenName", "last_name": "sn", "email": "mail"}
    settings["AUTH_LDAP_ALWAYS_UPDATE_USER"] = True


def connect_signals() -> None:
    """При каждом входе через каталог обновляем команду и зону по departmentNumber."""
    from django_auth_ldap.backend import populate_user

    from .services import apply_directory_attrs

    def on_populate(sender, user, ldap_user, **kwargs):
        apply_directory_attrs(user, ldap_user.attrs)

    populate_user.connect(on_populate, weak=False, dispatch_uid="accounts.ldap.populate")
