"""Unit tests for the ``subscription`` paths.

A full API reference for subscriptions can be found here:
https://<sat6.com>/apidoc/v2/subscriptions.html


:Requirement: Subscription

:CaseAutomation: Automated

:CaseComponent: SubscriptionManagement

:team: Phoenix-subscriptions

:CaseImportance: High

"""

import re
import time

from fauxfactory import gen_string
from nailgun.config import ServerConfig
from nailgun.entity_mixins import TaskFailedError
import pytest
from requests.exceptions import HTTPError

from robottelo.config import settings
from robottelo.constants import DEFAULT_SUBSCRIPTION_NAME, PRDS, REPOS, REPOSET

pytestmark = [pytest.mark.run_in_one_thread]


@pytest.fixture(scope='module')
def rh_repo(module_sca_manifest_org, module_target_sat):
    rh_repo_id = module_target_sat.api_factory.enable_rhrepo_and_fetchid(
        basearch='x86_64',
        org_id=module_sca_manifest_org.id,
        product=PRDS['rhel'],
        repo=REPOS['rhst7']['name'],
        reposet=REPOSET['rhst7'],
        releasever=None,
    )
    rh_repo = module_target_sat.api.Repository(id=rh_repo_id).read()
    rh_repo.sync()
    return rh_repo


@pytest.fixture(scope='module')
def custom_repo(rh_repo, module_sca_manifest_org, module_target_sat):
    custom_repo = module_target_sat.api.Repository(
        product=module_target_sat.api.Product(organization=module_sca_manifest_org).create(),
    ).create()
    custom_repo.sync()
    return custom_repo


@pytest.fixture(scope='module')
def module_ak(module_sca_manifest_org, rh_repo, custom_repo, module_target_sat):
    """rh_repo and custom_repo are included here to ensure their execution before the AK"""
    return module_target_sat.api.ActivationKey(
        content_view=module_sca_manifest_org.default_content_view,
        max_hosts=100,
        organization=module_sca_manifest_org,
        environment=module_target_sat.api.LifecycleEnvironment(
            id=module_sca_manifest_org.library.id
        ),
        auto_attach=True,
    ).create()


def test_positive_refresh(function_sca_manifest_org, request, target_sat):
    """Upload a manifest and refresh it afterwards.

    :id: cd195db6-e81b-42cb-a28d-ec0eb8a53341

    :expectedresults: Manifest is refreshed successfully

    :CaseImportance: Critical
    """
    org = function_sca_manifest_org
    sub = target_sat.api.Subscription(organization=org)
    request.addfinalizer(lambda: sub.delete_manifest(data={'organization_id': org.id}))
    sub.refresh_manifest(data={'organization_id': org.id})
    assert sub.search()


def test_positive_create_after_refresh(
    function_sca_manifest_org, second_function_sca_manifest, target_sat
):
    """Upload a manifest,refresh it and upload a new manifest to an other
     organization.

    :id: 1869bbb6-c31b-49a9-bc92-402a90071a11

    :customerscenario: true

    :expectedresults: the manifest is uploaded successfully to other org

    :BZ: 1393442

    :CaseImportance: Critical
    """
    org_sub = target_sat.api.Subscription(organization=function_sca_manifest_org)
    new_org = target_sat.api.Organization().create()
    new_org_sub = target_sat.api.Subscription(organization=new_org)
    try:
        org_sub.refresh_manifest(data={'organization_id': function_sca_manifest_org.id})
        assert org_sub.search()
        target_sat.upload_manifest(new_org.id, second_function_sca_manifest.content)
        assert new_org_sub.search()
    finally:
        org_sub.delete_manifest(data={'organization_id': function_sca_manifest_org.id})


def test_positive_delete(function_sca_manifest_org, target_sat):
    """Delete an Uploaded manifest.

    :id: 4c21c7c9-2b26-4a65-a304-b978d5ba34fc

    :expectedresults: Manifest is Deleted successfully

    :CaseImportance: Critical
    """
    sub = target_sat.api.Subscription(organization=function_sca_manifest_org)
    assert sub.search()
    sub.delete_manifest(data={'organization_id': function_sca_manifest_org.id})
    assert len(sub.search()) == 0


def test_negative_upload(function_sca_manifest, target_sat):
    """Upload the same manifest to two organizations.

    :id: 60ca078d-cfaf-402e-b0db-34d8901449fe

    :expectedresults: The manifest is not uploaded to the second
        organization.
    """
    orgs = [target_sat.api.Organization().create() for _ in range(2)]
    with function_sca_manifest as manifest:
        target_sat.upload_manifest(orgs[0].id, manifest.content)
        with pytest.raises(TaskFailedError):
            target_sat.upload_manifest(orgs[1].id, manifest.content)
    assert len(target_sat.api.Subscription(organization=orgs[1]).search()) == 0


def test_positive_delete_manifest_as_another_user(function_org, function_sca_manifest, target_sat):
    """Verify that uploaded manifest if visible and deletable
        by a different user than the one who uploaded it

    :id: 4861bdbc-785a-436d-98cf-13cfef7d6907

    :expectedresults: manifest is refreshed

    :customerscenario: true

    :BZ: 1669241

    :CaseImportance: Medium
    """
    user1_password = gen_string('alphanumeric')
    user1 = target_sat.api.User(
        admin=True,
        password=user1_password,
        organization=[function_org],
        default_organization=function_org,
    ).create()
    sc1 = ServerConfig(
        auth=(user1.login, user1_password),
        url=target_sat.url,
        verify=settings.server.verify_ca,
    )
    user2_password = gen_string('alphanumeric')
    user2 = target_sat.api.User(
        admin=True,
        password=user2_password,
        organization=[function_org],
        default_organization=function_org,
    ).create()
    sc2 = ServerConfig(
        auth=(user2.login, user2_password),
        url=target_sat.url,
        verify=settings.server.verify_ca,
    )
    # use the first admin to upload a manifest
    with function_sca_manifest as manifest:
        target_sat.api.Subscription(server_config=sc1, organization=function_org).upload(
            data={'organization_id': function_org.id}, files={'content': manifest.content}
        )
    # try to search and delete the manifest with another admin
    target_sat.api.Subscription(server_config=sc2, organization=function_org).delete_manifest(
        data={'organization_id': function_org.id}
    )
    assert len(target_sat.cli.Subscription.list({'organization-id': function_org.id})) == 0


@pytest.mark.e2e
@pytest.mark.pit_client
@pytest.mark.pit_server
@pytest.mark.rhel_ver_match('7')
def test_sca_end_to_end(
    module_ak, rhel_contenthost, module_sca_manifest_org, rh_repo, custom_repo, target_sat
):
    """Perform end to end testing for Simple Content Access Mode

    :id: c6c4b68c-a506-46c9-bd1d-22e4c1926ef8

    :BZ: 1890643, 1890661, 1890664

    :expectedresults: All tests pass and clients have access
        to repos without needing to add subscriptions

    :parametrized: yes

    :CaseImportance: Critical
    """
    result = rhel_contenthost.api_register(
        target_sat,
        organization=module_sca_manifest_org,
        activation_keys=[module_ak.name],
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'
    assert rhel_contenthost.subscribed
    # Check to see if Organization is in SCA Mode
    assert (
        target_sat.api.Organization(id=module_sca_manifest_org.id).read().simple_content_access
        is True
    )
    # Verify that you cannot attach a subscription to an activation key in SCA Mode
    subscription = target_sat.api.Subscription(organization=module_sca_manifest_org).search(
        query={'search': f'name="{DEFAULT_SUBSCRIPTION_NAME}"'}
    )[0]
    with pytest.raises(HTTPError) as ak_context:
        module_ak.add_subscriptions(data={'quantity': 1, 'subscription_id': subscription.id})
    assert 'Simple Content Access' in ak_context.value.response.text
    # Verify that you cannot attach a subscription to an Host in SCA Mode
    with pytest.raises(HTTPError) as host_context:
        target_sat.api.HostSubscription(host=rhel_contenthost.nailgun_host.id).add_subscriptions(
            data={'subscriptions': [{'id': subscription.id, 'quantity': 1}]}
        )
    assert 'Simple Content Access' in host_context.value.response.text
    # Create a content view with repos and check to see that the client has access
    content_view = target_sat.api.ContentView(organization=module_sca_manifest_org).create()
    content_view.repository = [rh_repo, custom_repo]
    content_view.update(['repository'])
    content_view.publish()
    assert len(content_view.repository) == 2
    host = rhel_contenthost.nailgun_host
    host.content_facet_attributes = {
        'content_view_id': content_view.id,
        'lifecycle_environment_id': module_ak.environment.id,
    }
    host.update(['content_facet_attributes'])
    rhel_contenthost.run('subscription-manager repos --enable *')
    repos = rhel_contenthost.run('subscription-manager refresh && yum repolist')
    assert content_view.repository[1].name in repos.stdout
    assert 'Red Hat Satellite Tools' in repos.stdout
    # install package and verify it succeeds or is already installed
    package = rhel_contenthost.run('yum install -y python-pulp-manifest')
    assert 'Complete!' in package.stdout or 'already installed' in package.stdout


@pytest.mark.rhel_ver_match('7')
def test_positive_candlepin_events_processed_by_stomp(
    function_org, target_sat, function_sca_manifest
):
    """Verify that Candlepin events are being read and processed by
        checking candlepin events, uploading a manifest,
        and viewing processed and failed Candlepin events

    :id: efd20ffd-8f98-4536-abb6-d080f9d23169

    :steps:

        1. Create a manifest
        2. Check the number of candlepin events
            /katello/api/v2/ping
        3. Import a Manifest
        4. Check the number of new candlepin events
            /katello/api/v2/ping
        5. Verify that the new candlepin events value is greater than the old value
        6. Verify that there are no failed candlepin events
            /katello/api/v2/ping

    :expectedresults: Candlepin events are being read and processed
                        correctly without any failures
    :BZ: 1826515

    :parametrized: yes

    :CaseImportance: High
    """

    # Function to parse candlepin events
    def parse(events):
        return {key: int(value) for value, key in re.findall(r'(\d+)\s(\w+)', events)}

    pre_candlepin_events = target_sat.api.Ping().search_json()['services']['candlepin_events'][
        'message'
    ]
    target_sat.upload_manifest(function_org.id, function_sca_manifest.content)
    time.sleep(5)
    assert target_sat.api.Ping().search_json()['services']['candlepin_events']['status'] == 'ok'
    post_candlepin_events = target_sat.api.Ping().search_json()['services']['candlepin_events'][
        'message'
    ]
    assert parse(post_candlepin_events)['Processed'] > parse(pre_candlepin_events)['Processed']
    assert parse(pre_candlepin_events)['Failed'] == 0
    assert parse(post_candlepin_events)['Failed'] == 0


@pytest.mark.rhel_ver_match('7')
def test_positive_expired_SCA_cert_handling(module_sca_manifest_org, rhel_contenthost, target_sat):
    """Verify that a content host with an expired SCA cert can
        re-register successfully

    :id: 27bca6b8-dd9c-4977-81d2-319588ee59b3

    :steps:

        1. Import an SCA-enabled manifest
        2. Register a content host to the Default Organization View using an activation key
        3. Unregister the content host
        4. Enable and synchronize a repository
        5. Re-register the host using the same activation key as in step 3 above

    :expectedresults: the host is re-registered successfully and its SCA entitlement
                      certificate is refreshed

    :CustomerScenario: true

    :team: Phoenix-subscriptions

    :BZ: 1949353

    :parametrized: yes

    :CaseImportance: High
    """
    ak = target_sat.api.ActivationKey(
        content_view=module_sca_manifest_org.default_content_view,
        max_hosts=100,
        organization=module_sca_manifest_org,
        environment=target_sat.api.LifecycleEnvironment(id=module_sca_manifest_org.library.id),
        auto_attach=True,
    ).create()
    # registering the content host with no content enabled/synced in the org
    # should create a client SCA cert with no content
    result = rhel_contenthost.api_register(
        target_sat,
        organization=module_sca_manifest_org,
        activation_keys=[ak.name],
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'
    assert rhel_contenthost.subscribed
    rhel_contenthost.unregister()
    # syncing content with the content host unregistered should invalidate
    # the previous client SCA cert
    rh_repo_id = target_sat.api_factory.enable_rhrepo_and_fetchid(
        basearch='x86_64',
        org_id=module_sca_manifest_org.id,
        product=PRDS['rhel'],
        repo=REPOS['rhst7']['name'],
        reposet=REPOSET['rhst7'],
        releasever=None,
    )
    rh_repo = target_sat.api.Repository(id=rh_repo_id).read()
    rh_repo.sync()
    # re-registering the host (using force=True) should test whether Candlepin gracefully handles
    # registration of a host with an expired SCA cert
    result = rhel_contenthost.api_register(
        target_sat,
        organization=module_sca_manifest_org,
        activation_keys=[ak.name],
        force=True,
    )
    assert result.status == 0, f'Failed to register host: {result.stderr}'
    assert rhel_contenthost.subscribed


@pytest.mark.rhel_ver_match('N-2')
def test_positive_os_restriction_on_repos(
    target_sat,
    module_cv,
    module_ak,
    module_product,
    rhel_contenthost,
    module_sca_manifest_org,
):
    """Verify that you can specify OS restrictions on custom repos for registered host.
        parametrized: (3) newest supported RHEL distro (N), with two prior.

    :id: fd40842f-48c3-4505-a670-235d8a5f466b

    :parametrized: yes

    :setup:
        1. Create and sync 3 custom yum repositories
        2. Add them to content-view and update
        3. Register host and setup method (publish CV, associate AK, and enable repos)

    :steps:
        1. Check all repos enabled from start (unrestricted)
        2. Set Restriction to OS (RHEL10/9/8) on each repo (hammer repository update)
        3. Subscription-manager refresh
        4. Verify available repo(s) for content host using subscription-manager.

    :expectedresults:
        - One custom repo available for client, with matching OS restriction.
        - Two custom repos not available for client, with non-matching OS restrictions.

    :customerscenario: true

    :BZ: 1526564

    :CaseImportance: High

    """
    org = module_sca_manifest_org
    # 3 newest supported rhel versions from tail, exclude fips
    rhel_versions = [
        rhel_major_ver
        for rhel_major_ver in settings.supportability.content_hosts.rhel.versions
        if 'fips' not in str(rhel_major_ver)
    ][-3:]
    # create & sync 3 custom repositories
    repo_urls = [settings.repos.yum_9.url, settings.repos.yum_6.url, settings.repos.yum_1.url]
    custom_repos = []
    for url in repo_urls:
        r = target_sat.api.Repository(
            url=url,
            product=module_product,
        ).create()
        r.sync()
        custom_repos.append(r.read())
    # add the repos to module CV
    module_cv.repository = custom_repos
    module_cv.update(['repository'])
    module_cv = module_cv.read()
    # publish CV, associate AK, register host and enable repos
    setup = target_sat.api_factory.register_host_and_needed_setup(
        organization=org,
        client=rhel_contenthost,
        activation_key=module_ak,
        environment='Library',
        content_view=module_cv,
        enable_repos=True,
    )
    assert setup['result'] != 'error', f'{setup["message"]}'
    # registered host returned by setup
    assert (client := setup['client'])
    result = client.execute('subscription-manager refresh')
    assert result.status == 0, f'{result.stdout}'

    # get available repos from sub-man repos list
    sub_man_repos = client.subscription_manager_list_repos().stdout
    # assert all 3 repos are available at start (unrestricted)
    assert all(repo.label in sub_man_repos for repo in custom_repos)
    assert len(custom_repos) == 3

    # restrict each repo to a different RHEL major version
    matching_repo_id = None
    for r in custom_repos:
        repo_OS = rhel_versions[-1]
        # restrict repo to OS via hammer, ie 'rhel-9'
        formatted = 'rhel-' + str(repo_OS)
        target_sat.cli.Repository.update({'os-versions': formatted, 'id': r.id})
        rhel_versions.remove(repo_OS)
        # save repo_id with matching OS restrict to chost version,
        # we expect this repo to remain available and enabled
        if repo_OS == client.os_version.major:
            matching_repo_id = r.id

    result = client.execute('subscription-manager refresh')
    assert result.status == 0, f'{result.stdout}'
    assert matching_repo_id, 'Expected one repository OS restriction, to match chost RHEL version'

    enabled_repo_label = target_sat.api.Repository(id=matching_repo_id).read().label
    assert enabled_repo_label in [repo.label for repo in custom_repos]
    disabled_repos_labels = [
        repo.label for repo in custom_repos if repo.label != enabled_repo_label
    ]
    # enabled repo (1) with matching OS restriction is available from host's sub-man repos
    sub_man_repos = client.subscription_manager_list_repos().stdout
    assert enabled_repo_label in sub_man_repos
    # repos (2) with differing OS, not available from sub-man repos list
    assert all(label not in sub_man_repos for label in disabled_repos_labels)
    assert len(disabled_repos_labels) == 2


def test_positive_async_endpoint_for_manifest_refresh(target_sat, function_sca_manifest_org):
    """Verify that manifest refresh is using an async endpoint. Previously this was a single,
    synchronous endpoint. The endpoint to retrieve manifests is now split into two: an async
    endpoint to start "exporting" the manifest, and a second endpoint to download the
    exported manifest.

    :id: c25c5290-44ae-4f56-82cf-d118fefeff86

    :steps:
        1. Refresh a manifest
        2. Check the production.log for "Sending GET request to upstream Candlepin"

    :expectedresults: Manifest refresh succeeds with no errors and production.log
        has new debug message

    :customerscenario: true

    :BZ: 2066323
    """
    sub = target_sat.api.Subscription(organization=function_sca_manifest_org)
    # set log level to 'debug' and restart services
    target_sat.cli.Admin.logging({'all': True, 'level-debug': True})
    target_sat.cli.Service.restart()
    # refresh manifest and assert new log message to confirm async endpoint
    sub.refresh_manifest(data={'organization_id': function_sca_manifest_org.id})
    results = target_sat.execute(
        'grep "Sending GET request to upstream Candlepin" /var/log/foreman/production.log'
    )
    assert 'Sending GET request to upstream Candlepin' in str(results)
    # set log level back to default
    target_sat.cli.Admin.logging({'all': True, 'level-production': True})
    target_sat.cli.Service.restart()
