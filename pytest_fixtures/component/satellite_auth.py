import copy
import socket

from box import Box
import pytest

from robottelo.config import settings
from robottelo.constants import (
    AUDIENCE_MAPPER,
    CERT_PATH,
    GROUP_MEMBERSHIP_MAPPER,
    HAMMER_CONFIG,
    HAMMER_SESSIONS,
    LDAP_ATTR,
    LDAP_SERVER_TYPE,
)
from robottelo.hosts import IPAHost, RHBKHost, RHSSOHost
from robottelo.logging import logger
from robottelo.utils.datafactory import gen_string
from robottelo.utils.installer import InstallerCommand

LOGGEDOUT = 'Logged out.'


@pytest.fixture(scope='module')
def default_sso_host(request, module_target_sat):
    """Returns default sso host"""
    if hasattr(request, 'param') and request.param:
        logger.info("Using RHBK host for SSO")
        return RHBKHost(module_target_sat)
    logger.info("Using RHSSO host for SSO")
    return RHSSOHost(module_target_sat)


@pytest.fixture(scope='module')
def default_ipa_host(module_target_sat):
    """Returns default IPA host"""
    return IPAHost(module_target_sat)


@pytest.fixture
def ldap_cleanup(target_sat):
    """this is an extra step taken to clean any existing ldap source"""
    ldap_auth_sources = target_sat.api.AuthSourceLDAP().search()
    for ldap_auth in ldap_auth_sources:
        users = target_sat.api.User(auth_source=ldap_auth).search()
        for user in users:
            user.delete()
        ldap_auth.delete()
    return


@pytest.fixture(scope='session')
def ad_data():
    supported_server_versions = ['2016', '2019']

    def _ad_data(version='2019'):
        if version in supported_server_versions:
            ad_server_details = {
                'ldap_user_name': settings.ldap.username,
                'ldap_user_shown_name': settings.ldap.user_shown_name,
                'ldap_user_cn': settings.ldap.username,
                'ldap_user_passwd': settings.ldap.password,
                'base_dn': settings.ldap.basedn,
                'group_base_dn': settings.ldap.grpbasedn,
                'realm': settings.ldap.realm,
                'ldap_hostname': getattr(settings.ldap.hostname, version),
                'workgroup': getattr(settings.ldap.workgroup, version),
                'nameserver': getattr(settings.ldap.nameserver, version),
                'nameserver6': getattr(settings.ldap.nameserver6, version),
            }
        else:
            raise Exception(
                f'The currently supported AD servers are {supported_server_versions}. '
                f'Does not match with provided {version}'
            )

        return Box(ad_server_details)

    return _ad_data


@pytest.fixture(scope='session')
def ipa_data():
    return {
        'ldap_user_name': settings.ipa.user,
        'ldap_user_shown_name': settings.ipa.user_shown_name,
        'ldap_user_cn': settings.ipa.username,
        'ipa_otp_username': settings.ipa.otp_user,
        'ldap_user_passwd': settings.ipa.password,
        'base_dn': settings.ipa.basedn,
        'group_base_dn': settings.ipa.grpbasedn,
        'ldap_hostname': settings.ipa.hostname,
        'time_based_secret': settings.ipa.time_based_secret,
        'disabled_user_ipa': settings.ipa.disabled_ipa_user,
        'users': settings.ipa.users,
        'groups': settings.ipa.groups,
    }


@pytest.fixture(scope='session')
def open_ldap_data():
    return {
        'ldap_user_name': settings.open_ldap.open_ldap_user,
        'ldap_user_shown_name': settings.open_ldap.user_shown_name,
        'ldap_user_cn': settings.open_ldap.username,
        'ldap_hostname': settings.open_ldap.hostname,
        'ldap_user_passwd': settings.open_ldap.password,
        'base_dn': settings.open_ldap.base_dn,
        'group_base_dn': settings.open_ldap.group_base_dn,
    }


@pytest.fixture
def auth_source(ldap_cleanup, module_target_sat, module_org, module_location, ad_data):
    ad_data = ad_data()
    return module_target_sat.api.AuthSourceLDAP(
        onthefly_register=True,
        account=ad_data['ldap_user_name'],
        account_password=ad_data['ldap_user_passwd'],
        base_dn=ad_data['base_dn'],
        groups_base=ad_data['group_base_dn'],
        attr_firstname=LDAP_ATTR['firstname'],
        attr_lastname=LDAP_ATTR['surname'],
        attr_login=LDAP_ATTR['login_ad'],
        server_type=LDAP_SERVER_TYPE['API']['ad'],
        attr_mail=LDAP_ATTR['mail'],
        name=gen_string('alpha'),
        host=ad_data['ldap_hostname'],
        tls=False,
        port='389',
        organization=[module_org],
        location=[module_location],
    ).create()


@pytest.fixture
def auth_source_ipa(ldap_cleanup, default_ipa_host, module_target_sat, module_org, module_location):
    return module_target_sat.api.AuthSourceLDAP(
        onthefly_register=True,
        account=default_ipa_host.ldap_user_cn,
        account_password=default_ipa_host.ldap_user_passwd,
        base_dn=default_ipa_host.base_dn,
        groups_base=default_ipa_host.group_base_dn,
        attr_firstname=LDAP_ATTR['firstname'],
        attr_lastname=LDAP_ATTR['surname'],
        attr_login=LDAP_ATTR['login'],
        server_type=LDAP_SERVER_TYPE['API']['ipa'],
        attr_mail=LDAP_ATTR['mail'],
        name=gen_string('alpha'),
        host=default_ipa_host.hostname,
        tls=False,
        port='389',
        organization=[module_org],
        location=[module_location],
    ).create()


@pytest.fixture
def auth_source_open_ldap(
    ldap_cleanup,
    module_target_sat,
    module_org,
    module_location,
    open_ldap_data,
):
    return module_target_sat.api.AuthSourceLDAP(
        onthefly_register=True,
        account=open_ldap_data['ldap_user_cn'],
        account_password=open_ldap_data['ldap_user_passwd'],
        base_dn=open_ldap_data['base_dn'],
        groups_base=open_ldap_data['group_base_dn'],
        attr_firstname=LDAP_ATTR['firstname'],
        attr_lastname=LDAP_ATTR['surname'],
        attr_login=LDAP_ATTR['login'],
        server_type=LDAP_SERVER_TYPE['API']['posix'],
        attr_mail=LDAP_ATTR['mail'],
        name=gen_string('alpha'),
        host=open_ldap_data['ldap_hostname'],
        tls=False,
        port='389',
        organization=[module_org],
        location=[module_location],
    ).create()


@pytest.fixture
def ldap_auth_source(
    request,
    module_org,
    module_location,
    ldap_cleanup,
    ad_data,
    ipa_data,
    open_ldap_data,
    module_target_sat,
):
    auth_type = request.param.lower()
    if 'ad' in auth_type:
        ad_data = ad_data()
        # entity create with AD settings
        auth_source = module_target_sat.api.AuthSourceLDAP(
            onthefly_register=True,
            account=f"cn={ad_data['ldap_user_name']},{ad_data['base_dn']}",
            account_password=ad_data['ldap_user_passwd'],
            base_dn=ad_data['base_dn'],
            groups_base=ad_data['group_base_dn'],
            attr_firstname=LDAP_ATTR['firstname'],
            attr_lastname=LDAP_ATTR['surname'],
            attr_login=LDAP_ATTR['login_ad'],
            server_type=LDAP_SERVER_TYPE['API']['ad'],
            attr_mail=LDAP_ATTR['mail'],
            name=gen_string('alpha'),
            host=ad_data['ldap_hostname'],
            tls=False,
            port='389',
            organization=[module_org],
            location=[module_location],
        ).create()
        ldap_data = ad_data
    elif auth_type == 'ipa':
        # entity create with IPA settings
        auth_source = module_target_sat.api.AuthSourceLDAP(
            onthefly_register=True,
            account=ipa_data['ldap_user_cn'],
            account_password=ipa_data['ldap_user_passwd'],
            base_dn=ipa_data['base_dn'],
            groups_base=ipa_data['group_base_dn'],
            attr_firstname=LDAP_ATTR['firstname'],
            attr_lastname=LDAP_ATTR['surname'],
            attr_login=LDAP_ATTR['login'],
            server_type=LDAP_SERVER_TYPE['API']['ipa'],
            attr_mail=LDAP_ATTR['mail'],
            name=gen_string('alpha'),
            host=ipa_data['ldap_hostname'],
            tls=False,
            port='389',
            organization=[module_org],
            location=[module_location],
        ).create()
        ldap_data = ipa_data
    elif auth_type == 'openldap':
        # entity create with OpenLdap settings
        auth_source = module_target_sat.api.AuthSourceLDAP(
            onthefly_register=True,
            account=open_ldap_data['ldap_user_cn'],
            account_password=open_ldap_data['ldap_user_passwd'],
            base_dn=open_ldap_data['base_dn'],
            groups_base=open_ldap_data['group_base_dn'],
            attr_firstname=LDAP_ATTR['firstname'],
            attr_lastname=LDAP_ATTR['surname'],
            attr_login=LDAP_ATTR['login'],
            server_type=LDAP_SERVER_TYPE['API']['posix'],
            attr_mail=LDAP_ATTR['mail'],
            name=gen_string('alpha'),
            host=open_ldap_data['ldap_hostname'],
            tls=False,
            port='389',
            organization=[module_org],
            location=[module_location],
        ).create()
        ldap_data = open_ldap_data
    else:
        raise Exception('Incorrect auth source parameter used')
    ldap_data['auth_type'] = auth_type
    if ldap_data['auth_type'] == 'ipa':
        ldap_data['server_type'] = LDAP_SERVER_TYPE['UI']['ipa']
        ldap_data['attr_login'] = LDAP_ATTR['login']
    elif ldap_data['auth_type'] == 'ad':
        ldap_data['server_type'] = LDAP_SERVER_TYPE['UI']['ad']
        ldap_data['attr_login'] = LDAP_ATTR['login_ad']
    else:
        ldap_data['server_type'] = LDAP_SERVER_TYPE['UI']['posix']
        ldap_data['attr_login'] = LDAP_ATTR['login']
    return ldap_data, auth_source


@pytest.fixture
def auth_data(request, ad_data, ipa_data):
    auth_type = request.param.lower()
    if 'ad' in auth_type:
        ad_data = ad_data()
        ad_data['server_type'] = LDAP_SERVER_TYPE['UI']['ad']
        ad_data['attr_login'] = LDAP_ATTR['login_ad']
        ad_data['auth_type'] = auth_type
        return ad_data
    if auth_type == 'ipa':
        ipa_data['server_type'] = LDAP_SERVER_TYPE['UI']['ipa']
        ipa_data['attr_login'] = LDAP_ATTR['login']
        ipa_data['auth_type'] = auth_type
        return ipa_data
    return None


@pytest.fixture(scope='module')
def enroll_configure_rhsso_external_auth(request, module_target_sat):
    """Enroll the Satellite6 Server to an RHSSO Server."""
    if hasattr(request, 'param') and request.param:
        uri = f'https://{settings.rhbk.host_name}:{settings.rhbk.host_port}'
        password = settings.rhbk.rhbk_password
        realm = settings.rhbk.realm
    else:
        uri = f'https://{settings.rhsso.host_name}:443'
        password = settings.rhsso.rhsso_password
        realm = settings.rhsso.realm
    if settings.robottelo.rhel_source == "ga":
        module_target_sat.register_to_cdn()
    # keycloak-httpd-client-install needs lxml but it's not an rpm dependency + is not documented
    assert (
        module_target_sat.execute(
            'yum -y --disableplugin=foreman-protector install '
            'mod_auth_openidc keycloak-httpd-client-install python3-lxml '
        ).status
        == 0
    )
    # if target directory not given it is installing in /usr/local/lib64
    assert (
        module_target_sat.execute(
            f'openssl s_client -connect {uri} -showcerts </dev/null 2>/dev/null| '
            f'sed "/BEGIN CERTIFICATE/,/END CERTIFICATE/!d" > {CERT_PATH}/rh-sso.crt'
        ).status
        == 0
    )
    assert (
        module_target_sat.execute(
            f'echo {password} | keycloak-httpd-client-install \
                --app-name foreman-openidc \
                --keycloak-server-url {uri} \
                --keycloak-admin-username "admin" \
                --keycloak-realm "{realm}" \
                --keycloak-admin-realm master \
                --keycloak-auth-role root-admin -t openidc -l /users/extlogin --force'
        ).status
        == 0
    )
    assert (
        module_target_sat.execute(
            f'satellite-installer --foreman-keycloak true '
            f"--foreman-keycloak-app-name 'foreman-openidc' "
            f"--foreman-keycloak-realm '{realm}' ",
            timeout=1000000,
        ).status
        == 0
    )
    assert module_target_sat.execute('systemctl restart httpd').status == 0


@pytest.fixture(scope='module')
def enable_external_auth_rhsso(
    enroll_configure_rhsso_external_auth, default_sso_host, module_target_sat
):
    """register the satellite with RH-SSO Server for single sign-on"""
    client_id = default_sso_host.get_sso_client_id()
    default_sso_host.create_mapper(GROUP_MEMBERSHIP_MAPPER, client_id)
    audience_mapper = copy.deepcopy(AUDIENCE_MAPPER)
    audience_mapper['config']['included.client.audience'] = audience_mapper['config'][
        'included.client.audience'
    ].format(rhsso_host=module_target_sat.hostname)
    default_sso_host.create_mapper(audience_mapper, client_id)
    default_sso_host.set_the_redirect_uri()


@pytest.fixture(scope='module')
def module_enroll_idm_and_configure_external_auth(module_target_sat):
    ipa_host = IPAHost(module_target_sat)
    ipa_host.enroll_idm_and_configure_external_auth()
    yield
    ipa_host.disenroll_idm()


@pytest.fixture
def func_enroll_idm_and_configure_external_auth(target_sat):
    ipa_host = IPAHost(target_sat)
    ipa_host.enroll_idm_and_configure_external_auth()
    yield
    ipa_host.disenroll_idm()


@pytest.fixture(scope='module')
def configure_realm(module_target_sat, default_ipa_host):
    """Configure realm"""
    realm = settings.upgrade.vm_domain.upper()
    module_target_sat.execute(f'curl -o /root/freeipa.keytab {settings.ipa.keytab_url}')
    module_target_sat.execute('mv /root/freeipa.keytab /etc/foreman-proxy')
    module_target_sat.execute('chown foreman-proxy:foreman-proxy /etc/foreman-proxy/freeipa.keytab')
    module_target_sat.execute(
        'satellite-installer --foreman-proxy-realm true '
        f'--foreman-proxy-realm-principal realm-proxy@{realm} '
        f'--foreman-proxy-dhcp-nameservers {socket.gethostbyname(default_ipa_host.hostname)}'
    )
    module_target_sat.execute('cp /etc/ipa/ca.crt /etc/pki/ca-trust/source/anchors/ipa.crt')
    module_target_sat.execute('update-ca-trust enable ; update-ca-trust')
    module_target_sat.execute('service foreman-proxy restart')


@pytest.fixture(scope="module")
def rhsso_setting_setup(request, module_target_sat):
    """Update the RHSSO setting and revert it in cleanup"""
    if hasattr(request, 'param') and request.param:
        uri = f'{settings.rhbk.host_url}'
        realm = settings.rhbk.realm
    else:
        uri = settings.rhsso.host_url
        realm = settings.rhsso.realm
    rhhso_settings = {
        'authorize_login_delegation': True,
        'authorize_login_delegation_auth_source_user_autocreate': 'External',
        'login_delegation_logout_url': f'https://{module_target_sat.hostname}/users/extlogout',
        'oidc_algorithm': 'RS256',
        'oidc_audience': [f'{module_target_sat.hostname}-foreman-openidc'],
        'oidc_issuer': f'{uri}/auth/realms/{realm}',
        'oidc_jwks_url': f'{uri}/auth/realms/{realm}/protocol/openid-connect/certs',
    }
    for setting_name, setting_value in rhhso_settings.items():
        # replace entietes field with targetsat.api
        setting_entity = module_target_sat.api.Setting().search(
            query={'search': f'name={setting_name}'}
        )[0]
        setting_entity.value = setting_value
        setting_entity.update({'value'})
    yield
    setting_entity = module_target_sat.api.Setting().search(
        query={'search': 'name=authorize_login_delegation'}
    )[0]
    setting_entity.value = False
    setting_entity.update({'value'})


@pytest.fixture(scope="module")
def rhsso_setting_setup_with_timeout(module_target_sat, rhsso_setting_setup):
    """Update the RHSSO setting with timeout setting and revert it in cleanup"""
    setting_entity = module_target_sat.api.Setting().search(query={'search': 'name=idle_timeout'})[
        0
    ]
    setting_entity.value = 1
    setting_entity.update({'value'})
    yield
    setting_entity.value = 30
    setting_entity.update({'value'})


@pytest.fixture(scope='module')
def module_enroll_ad_and_configure_external_auth(ad_data, module_target_sat):
    module_target_sat.enroll_ad_and_configure_external_auth(ad_data)


@pytest.fixture
def func_enroll_ad_and_configure_external_auth(ad_data, target_sat):
    target_sat.enroll_ad_and_configure_external_auth(ad_data)


@pytest.fixture
def configure_hammer_no_creds(parametrized_enrolled_sat):
    """Configures hammer to use sessions and negotiate auth."""
    parametrized_enrolled_sat.execute(f'cp {HAMMER_CONFIG} {HAMMER_CONFIG}.backup')
    parametrized_enrolled_sat.execute(f"sed -i '/:username.*/d' {HAMMER_CONFIG}")
    parametrized_enrolled_sat.execute(f"sed -i '/:password.*/d' {HAMMER_CONFIG}")
    yield
    parametrized_enrolled_sat.execute(f'mv -f {HAMMER_CONFIG}.backup {HAMMER_CONFIG}')


@pytest.fixture
def configure_hammer_negotiate(parametrized_enrolled_sat, configure_hammer_no_creds):
    """Configures hammer to use sessions and negotiate auth."""
    parametrized_enrolled_sat.execute(f'cp {HAMMER_CONFIG} {HAMMER_CONFIG}.backup')
    parametrized_enrolled_sat.execute(f"sed -i '/:default_auth_type.*/d' {HAMMER_CONFIG}")
    parametrized_enrolled_sat.execute(f"sed -i '/:use_sessions.*/d' {HAMMER_CONFIG}")
    parametrized_enrolled_sat.execute(f"echo '  :use_sessions: true' >> {HAMMER_CONFIG}")
    parametrized_enrolled_sat.execute(
        f"echo '  :default_auth_type: Negotiate_Auth' >> {HAMMER_CONFIG}"
    )
    yield
    parametrized_enrolled_sat.execute(f'mv -f {HAMMER_CONFIG}.backup {HAMMER_CONFIG}')


@pytest.fixture
def configure_hammer_no_negotiate(parametrized_enrolled_sat):
    """Configures hammer not to use automatic negotiation."""
    parametrized_enrolled_sat.execute(f'cp {HAMMER_CONFIG} {HAMMER_CONFIG}.backup')
    parametrized_enrolled_sat.execute(f"sed -i '/:default_auth_type.*/d' {HAMMER_CONFIG}")
    yield
    parametrized_enrolled_sat.execute(f'mv -f {HAMMER_CONFIG}.backup {HAMMER_CONFIG}')


@pytest.fixture
def hammer_logout(parametrized_enrolled_sat):
    """Logout in Hammer."""
    result = parametrized_enrolled_sat.cli.Auth.logout()
    assert result[0]['message'] == LOGGEDOUT
    yield
    result = parametrized_enrolled_sat.cli.Auth.logout()
    assert result[0]['message'] == LOGGEDOUT


@pytest.fixture
def sessions_tear_down(parametrized_enrolled_sat):
    """Destroy Kerberos and hammer sessions on teardown."""
    yield
    parametrized_enrolled_sat.execute('kdestroy')
    parametrized_enrolled_sat.execute(
        f'rm -f {HAMMER_SESSIONS}/https_{parametrized_enrolled_sat.hostname}'
    )


@pytest.fixture
def configure_ipa_api(
    request,
    parametrized_enrolled_sat,
    enabled=True,
):
    """Enable Kerberos authentication in Hammer."""
    if enabled:
        # Normal ipa authentication needs to be enabled already
        assert (
            parametrized_enrolled_sat.execute(
                'satellite-installer --help | grep foreman-ipa-authentication[^-] | grep true'
            ).status
            == 0
        )
    original_value = (
        parametrized_enrolled_sat.execute(
            'satellite-installer --help | grep foreman-ipa-authentication-api | grep true'
        ).status
        == 0
    )
    result = parametrized_enrolled_sat.install(
        InstallerCommand(f'foreman-ipa-authentication-api {"true" if enabled else "false"}')
    )
    assert result.status == 0, 'Installer failed to enable IPA API authentication.'
    yield
    result = parametrized_enrolled_sat.install(
        InstallerCommand(f'foreman-ipa-authentication-api {"true" if original_value else "false"}')
    )
    assert result.status == 0, 'Installer failed to reset IPA API authentication.'
