# -*- encoding: utf-8 -*-
"""Test class for Host Group UI

:CaseAutomation: Automated

:CaseComponent: Repositories

:TestType: Functional

:CaseImportance: High

:Upstream: No
"""
from fauxfactory import gen_string
from robottelo.decorators import tier2, upgrade


@tier2
@upgrade
def test_positive_end_to_end(session, module_org, module_loc):
    """Perform end to end testing for http-proxy component.

    :id: 0c7cdf3d-778f-427a-9a2f-42ad7c23aa15

    :expectedresults: All expected CRUD actions finished successfully

    :CaseLevel: Integration

    :CaseImportance: High
    """
    http_proxy_name = gen_string('alpha', 15)
    updated_proxy_name = gen_string('alpha', 15)
    http_proxy_url = 'https://{}'.format(gen_string('alpha', 15))
    password = gen_string('alpha', 15)
    username = gen_string('alpha', 15)

    with session:
        session.http_proxy.create({
            'http_proxy.name': http_proxy_name,
            'http_proxy.url': http_proxy_url,
            'http_proxy.username': username,
            'http_proxy.password': password,
            'locations.resources.assigned': [module_loc.name],
            'organizations.resources.assigned': [module_org.name],
        })
        assert session.http_proxy.search(http_proxy_name)[0]['Name'] == http_proxy_name
        http_proxy_values = session.http_proxy.read(http_proxy_name)
        assert http_proxy_values['http_proxy']['name'] == http_proxy_name
        assert http_proxy_values['http_proxy']['url'] == http_proxy_url
        assert http_proxy_values['http_proxy']['username'] == username
        assert http_proxy_values['locations']['resources']['assigned'][0] == module_loc.name
        assert http_proxy_values['organizations']['resources']['assigned'][0] == module_org.name
        # Update http_proxy with new name
        session.http_proxy.update(http_proxy_name, {'http_proxy.name': updated_proxy_name})
        assert session.http_proxy.search(updated_proxy_name)[0]['Name'] == updated_proxy_name
        # Delete http_proxy
        session.http_proxy.delete(updated_proxy_name)
        assert not session.http_proxy.search(updated_proxy_name)
