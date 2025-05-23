"""
All the Repository classes in this module are supposed to use from sat_object.cli_factory object.
The direct import of the repo classes in this module is prohibited !!!!!
"""

import inspect
import sys

from robottelo import constants
from robottelo.config import settings
from robottelo.exceptions import (
    DistroNotSupportedError,
    OnlyOneOSRepositoryAllowed,
    ReposContentSetupWasNotPerformed,
    RepositoryAlreadyCreated,
    RepositoryAlreadyDefinedError,
    RepositoryDataNotFound,
)


def initiate_repo_helpers(satellite):
    return {
        (name, type(name, (obj,), {'satellite': satellite}))
        for name, obj in inspect.getmembers(sys.modules[__name__], inspect.isclass)
        if obj.__module__ == __name__
    }


class BaseRepository:
    """Base repository class for custom and RH repositories"""

    _url = None
    _distro = None
    _type = None
    _repo_info = None
    satellite = None

    def __init__(self, url=None, distro=None, content_type=None):
        self._url = url
        self.distro = distro
        if content_type is not None:
            self._type = content_type

    @property
    def url(self):
        return self._url

    @property
    def cdn(self):
        return False

    @property
    def data(self):
        data = dict(url=self.url, cdn=self.cdn)
        content_type = self.content_type
        if content_type:
            data['content-type'] = content_type
        return data

    @property
    def distro(self):
        """Return the current distro"""
        return self._distro

    @distro.setter
    def distro(self, value):
        """Set the distro"""
        self._distro = value

    @property
    def content_type(self):
        return self._type

    def __repr__(self):
        return f'<Repo type: {self.content_type}, url: {self.url}, object: {hex(id(self))}>'

    @property
    def repo_info(self):
        return self._repo_info

    def create(
        self,
        organization_id,
        product_id,
        download_policy=None,
        synchronize=True,
    ):
        if download_policy:
            download_policy = 'on_demand'
        """Create the repository for the supplied product id"""
        create_options = {
            'product-id': product_id,
            'content-type': self.content_type,
            'url': self.url,
        }
        if self.content_type == constants.REPO_TYPE['yum'] and download_policy:
            create_options['download-policy'] = download_policy
        if self.content_type == constants.REPO_TYPE['ostree']:
            create_options['publish-via-http'] = 'false'
        repo_info = self.satellite.cli_factory.make_repository(create_options)
        self._repo_info = repo_info
        if synchronize:
            self.synchronize()
        return repo_info

    def synchronize(self):
        """Synchronize the repository"""
        self.satellite.cli.Repository.synchronize({'id': self.repo_info['id']}, timeout=4800000)

    def add_to_content_view(self, organization_id, content_view_id):
        """Associate repository content to content-view"""
        self.satellite.cli.ContentView.add_repository(
            {
                'id': content_view_id,
                'organization-id': organization_id,
                'repository-id': self._repo_info['id'],
            }
        )


class YumRepository(BaseRepository):
    """Custom Yum repository"""

    _type = constants.REPO_TYPE['yum']


class FileRepository(BaseRepository):
    """Custom File repository"""

    _type = constants.REPO_TYPE['file']


class DebianRepository(BaseRepository):
    """Custom Debian repository."""

    _type = constants.REPO_TYPE["deb"]

    def __init__(
        self, url=None, distro=None, content_type=None, deb_errata_url=None, deb_releases=None
    ):
        super().__init__(url=url, distro=distro, content_type=content_type)
        self._deb_errata_url = deb_errata_url
        self._deb_releases = deb_releases

    @property
    def deb_errata_url(self):
        return self._deb_errata_url

    @property
    def deb_releases(self):
        return self._deb_releases

    def create(
        self,
        organization_id,
        product_id,
        download_policy=None,
        synchronize=True,
    ):
        """Create the repository for the supplied product id"""
        create_options = {
            'product-id': product_id,
            'content-type': self.content_type,
            'url': self.url,
            'deb-releases': self._deb_releases,
        }

        if self._deb_errata_url is not None:
            create_options['deb-errata-url'] = self._deb_errata_url

        repo_info = self.satellite.cli_factory.make_repository(create_options)
        self._repo_info = repo_info

        if synchronize:
            self.synchronize()

        return repo_info


class DockerRepository(BaseRepository):
    """Custom Docker repository"""

    _type = constants.REPO_TYPE['docker']

    def __init__(self, url=None, distro=None, upstream_name=None):
        self._upstream_name = upstream_name
        super().__init__(url=url, distro=distro)

    @property
    def upstream_name(self):
        return self._upstream_name

    def create(self, organization_id, product_id, download_policy=None, synchronize=True):
        repo_info = self.satellite.cli_factory.make_repository(
            {
                'product-id': product_id,
                'content-type': self.content_type,
                'url': self.url,
                'docker-upstream-name': self.upstream_name,
            }
        )
        self._repo_info = repo_info
        if synchronize:
            self.synchronize()
        return repo_info


class AnsibleRepository(BaseRepository):
    """Custom Ansible Collection repository"""

    _type = constants.REPO_TYPE['ansible_collection']

    def __init__(self, url=None, distro=None, requirements=None):
        self._requirements = requirements
        super().__init__(url=url, distro=distro)

    @property
    def requirements(self):
        return self._requirements

    def create(self, organization_id, product_id, download_policy=None, synchronize=True):
        repo_info = self.satellite.cli_factory.make_repository(
            {
                'product-id': product_id,
                'content-type': self.content_type,
                'url': self.url,
                'ansible-collection-requirements': f'{{collections: {self.requirements}}}',
            }
        )
        self._repo_info = repo_info
        if synchronize:
            self.synchronize()
        return repo_info


class OSTreeRepository(BaseRepository):
    """Custom OSTree repository"""

    _type = constants.REPO_TYPE['ostree']


class GenericRHRepository(BaseRepository):
    """Generic RH repository"""

    _type = constants.REPO_TYPE['yum']
    _distro = constants.DISTRO_DEFAULT
    _key = None
    _repo_data = None
    _url = None

    def __init__(self, distro=None, key=None, cdn=False, url=None):
        super().__init__()

        if key is not None and self.key:
            raise RepositoryAlreadyDefinedError('Repository key already defined')

        if key is not None:
            self._key = key

        if url is not None:
            self._url = url

        self._cdn = bool(cdn)

        self.distro = distro

    @property
    def url(self):
        return self._url

    @property
    def cdn(self):
        return bool(self._cdn or settings.robottelo.cdn or not self.url)

    @property
    def key(self):
        return self._key

    @property
    def distro(self):
        return self._distro

    @distro.setter
    def distro(self, distro):
        """Set a new distro value, we have to reinitialise the repo data also,
        if not found raise exception
        """
        if distro is not None and distro not in constants.DISTROS_SUPPORTED:
            raise DistroNotSupportedError(f'distro "{distro}" not supported')
        if distro is None:
            distro = self._distro
        repo_data = self._get_repo_data(distro)
        if repo_data is None:
            raise RepositoryDataNotFound(f'Repository data not found for distro {distro}')
        self._distro = distro
        self._repo_data = repo_data

    def _get_repo_data(self, distro=None):
        """Return the repo data as registered in constant module and bound
        to distro.
        """
        if distro is None:
            distro = self.distro
        repo_data = None
        for _, data in constants.REPOS.items():
            repo_key = data.get('key')
            repo_distro = data.get('distro')
            if repo_key == self.key and repo_distro == distro:
                repo_data = data
                break
        return repo_data

    @property
    def repo_data(self):
        if self._repo_data is not None:
            return self._repo_data
        self._repo_data = self._get_repo_data()
        return self._repo_data

    def _repo_is_distro(self, repo_data=None):
        """return whether the repo data is for an OS distro product repository"""
        if repo_data is None:
            repo_data = self.repo_data
        return bool(repo_data.get('distro_repository', False))

    @property
    def is_distro_repository(self):
        # whether the current repository is an OS distro product repository
        return self._repo_is_distro()

    @property
    def distro_major_version(self):
        return constants.DISTROS_MAJOR_VERSION[self.distro]

    @property
    def distro_repository(self):
        """Return the OS distro repository object relied to this repository

        Suppose we have a repository for a product that must be installed on
        RHEL, but for proper installation needs some dependencies packages from
        the OS repository. This function will return the right OS repository
        object for later setup.

        for example:
           capsule_repo = SatelliteCapsuleRepository()
           # the capsule_repo will represent a capsule repo for default distro
           rhel_repo = capsule_repo.distro_repository
           # the rhel repo representation object for default distro will be
           # returned, if not found raise exception
        """
        if self.is_distro_repository:
            return self
        distro_repo_data = None
        for repo_data in constants.REPOS.values():
            if repo_data.get('distro') == self.distro and self._repo_is_distro(repo_data=repo_data):
                distro_repo_data = repo_data
                break

        if distro_repo_data:
            return RHELRepository(distro=self.distro, cdn=self.cdn)
        return None

    @property
    def rh_repository_id(self):
        if self.cdn:
            return self.repo_data.get('id')
        return None

    @property
    def data(self):
        data = {}
        if self.cdn:
            data['product'] = self.repo_data.get('product')
            data['repository-set'] = self.repo_data.get('reposet')
            data['repository'] = self.repo_data.get('name')
            data['repository-id'] = self.repo_data.get('id')
            data['releasever'] = self.repo_data.get('releasever')
            data['arch'] = self.repo_data.get('arch', constants.DEFAULT_ARCHITECTURE)
            data['cdn'] = True
        else:
            data['url'] = self.url
            data['cdn'] = False

        return data

    def __repr__(self):
        if self.cdn:
            return (
                f'<RH cdn Repo: {self.data["repository"]} within distro: '
                f'{self.distro}, object: {hex(id(self))}>'
            )
        return f'<RH custom Repo url: {self.url} object: {hex(id(self))}>'

    def create(
        self,
        organization_id,
        product_id=None,
        download_policy='on_demand',
        synchronize=True,
    ):
        """Create an RH repository"""
        if not self.cdn and not self.url:
            raise ValueError('Can not handle Custom repository with url not supplied')
        if self.cdn:
            data = self.data
            if not self.satellite.cli.Repository.list(
                {
                    'organization-id': organization_id,
                    'name': data['repository'],
                    'product': data['product'],
                }
            ):
                self.satellite.cli.RepositorySet.enable(
                    {
                        'organization-id': organization_id,
                        'product': data['product'],
                        'name': data['repository-set'],
                        'basearch': data.get('arch', constants.DEFAULT_ARCHITECTURE),
                        'releasever': data.get('releasever'),
                    }
                )
            repo_info = self.satellite.cli.Repository.info(
                {
                    'organization-id': organization_id,
                    'name': data['repository'],
                    'product': data['product'],
                }
            )
            if download_policy:
                # Set download policy
                self.satellite.cli.Repository.update(
                    {'download-policy': download_policy, 'id': repo_info['id']}
                )
            self._repo_info = repo_info
            if synchronize:
                self.synchronize()
        else:
            repo_info = super().create(organization_id, product_id, download_policy=download_policy)
        return repo_info


class RHELRepository(GenericRHRepository):
    """RHEL repository"""

    _key = constants.PRODUCT_KEY_RHEL

    @property
    def url(self):
        return getattr(settings, f'rhel{self.distro_major_version}_os')


class SatelliteToolsRepository(GenericRHRepository):
    """Satellite Tools Repository"""

    _key = constants.PRODUCT_KEY_SAT_TOOLS

    @property
    def url(self):
        return settings.repos.sattools_repo[
            f'{constants.PRODUCT_KEY_RHEL}{self.distro_major_version}'
        ]


class SatelliteCapsuleRepository(GenericRHRepository):
    """Satellite capsule repository"""

    _key = constants.PRODUCT_KEY_SAT_CAPSULE

    @property
    def url(self):
        if int(self.distro) == constants.SATELLITE_OS_VERSION:
            return settings.repos.capsule_repo
        return None


class VirtualizationAgentsRepository(GenericRHRepository):
    """Virtualization Agents repository"""

    _key = constants.PRODUCT_KEY_VIRT_AGENTS
    _distro = 'rhel6'


class RHELCloudFormsTools(GenericRHRepository):
    _distro = 'rhel6'
    _key = constants.PRODUCT_KEY_CLOUD_FORMS_TOOLS


class RHELAnsibleEngineRepository(GenericRHRepository):
    """Red Hat Ansible Engine Repository"""

    _key = constants.PRODUCT_KEY_ANSIBLE_ENGINE


class RHELServerExtras(GenericRHRepository):
    """Red Hat Server Extras Repository"""

    _key = constants.PRODUCT_KEY_RHEL_EXTRAS


class RepositoryCollection:
    """Repository collection"""

    _distro = None
    _org = None
    _items = []
    _repos_info = []
    _custom_product_info = None
    _os_repo = None
    _setup_content_data = None
    satellite = None

    def __init__(self, distro=None, repositories=None):
        self._items = []

        if distro is not None and distro not in constants.DISTROS_SUPPORTED:
            raise DistroNotSupportedError(f'distro "{distro}" not supported')
        if distro is not None:
            self._distro = distro

        if repositories is None:
            repositories = []
        self.add_items(repositories)

    @property
    def distro(self):
        return self._distro

    @property
    def repos_info(self):
        return self._repos_info

    @property
    def custom_product(self):
        return self._custom_product_info

    @property
    def os_repo(self):
        return self._os_repo

    @os_repo.setter
    def os_repo(self, repo):
        if self.os_repo is not None:
            raise OnlyOneOSRepositoryAllowed('OS repo already added.(Only one OS repo allowed)')
        if not isinstance(repo, RHELRepository):
            raise ValueError(f'repo: "{repo}" is not an RHEL repo')
        self._os_repo = repo

    @property
    def repos_data(self):
        return [repo.data for repo in self]

    @property
    def rh_repos(self):
        return [item for item in self if item.cdn]

    @property
    def custom_repos(self):
        return [item for item in self if not item.cdn]

    @property
    def rh_repos_info(self):
        return [
            repo_info for repo_info in self._repos_info if repo_info['red-hat-repository'] == 'yes'
        ]

    @property
    def custom_repos_info(self):
        return [
            repo_info for repo_info in self._repos_info if repo_info['red-hat-repository'] == 'no'
        ]

    @property
    def setup_content_data(self):
        return self._setup_content_data

    @property
    def need_subscription(self):
        return bool(self.rh_repos)

    @property
    def organization(self):
        return self._org

    def add_item(self, item) -> None:
        """
        Add repository to collection

        :param BaseRepository item: Item to add
        :return: None
        """
        if self._repos_info:
            raise RepositoryAlreadyCreated('Repositories already created can not add more')
        if not isinstance(item, BaseRepository):
            raise ValueError(f'item "{item}" is not a repository')
        if self.distro is not None:
            item.distro = self.distro
        self._items.append(item)
        if isinstance(item, RHELRepository):
            self.os_repo = item

    def add_items(self, items):
        """
        Add multiple repositories to collection

        :param List[BaseRepository] items: Items to add
        :return: None
        """
        for item in items:
            self.add_item(item)

    def __iter__(self):
        yield from self._items

    def setup(self, org_id, download_policy='on_demand', synchronize=True):
        """Setup the repositories on server.

        Recommended usage: repository only setup, for full content setup see
            setup_content.
        """
        if self._repos_info:
            raise RepositoryAlreadyCreated('Repositories already created')
        custom_product = None
        repos_info = []
        if any(not repo.cdn for repo in self):
            custom_product = self.satellite.cli_factory.make_product_wait(
                {'organization-id': org_id}
            )
        custom_product_id = custom_product['id'] if custom_product else None
        for repo in self:
            repo_info = repo.create(
                org_id,
                custom_product_id,
                download_policy=download_policy,
                synchronize=synchronize,
            )
            repos_info.append(repo_info)
        self._custom_product_info = custom_product
        self._repos_info = repos_info
        # Wait for metadata generation for repository creation for specific org
        task_query = f'Metadata generate "{custom_product.organization}"'
        self.satellite.wait_for_tasks(
            search_query=task_query,
            max_tries=6,
            search_rate=10,
        )
        return custom_product, repos_info

    def setup_content_view(self, org_id, lce_id=None):
        """Setup organization content view by adding all the repositories, publishing and promoting
        to lce if needed.
        """
        if lce_id is None:
            lce = self.satellite.cli_factory.make_lifecycle_environment({'organization-id': org_id})
        else:
            lce = self.satellite.cli.LifecycleEnvironment.info(
                {'id': lce_id, 'organization-id': org_id}
            )
        content_view = self.satellite.cli_factory.make_content_view({'organization-id': org_id})
        # Add repositories to content view
        for repo in self:
            repo.add_to_content_view(org_id, content_view['id'])
        # Publish the content view
        self.satellite.cli.ContentView.publish({'id': content_view['id']})
        if lce['name'] != constants.ENVIRONMENT:
            # Get the latest content view version id
            content_view_version = self.satellite.cli.ContentView.info({'id': content_view['id']})[
                'versions'
            ][-1]
            # Promote content view version to lifecycle environment
            self.satellite.cli.ContentView.version_promote(
                {
                    'id': content_view_version['id'],
                    'organization-id': org_id,
                    'to-lifecycle-environment-id': lce['id'],
                }
            )
        content_view = self.satellite.cli.ContentView.info({'id': content_view['id']})
        return content_view, lce

    def setup_activation_key(
        self, org_id, content_view_id, lce_id, subscription_names=None, override=None
    ):
        """Create activation and associate content-view,
        lifecycle environment and subscriptions"""
        if subscription_names is None:
            subscription_names = []
        activation_key = self.satellite.cli_factory.make_activation_key(
            {
                'organization-id': org_id,
                'lifecycle-environment-id': lce_id,
                'content-view-id': content_view_id,
            }
        )
        if override is not None:
            for repo in self.satellite.cli.ActivationKey.product_content(
                {'id': activation_key['id'], 'content-access-mode-all': 1}
            ):
                self.satellite.cli.ActivationKey.content_override(
                    {
                        'id': activation_key['id'],
                        'content-label': repo['label'],
                        'value': int(override),
                    }
                )
        if self.satellite.is_sca_mode_enabled(org_id):
            return activation_key
        # Add subscriptions to activation-key
        # Get organization subscriptions
        subscriptions = self.satellite.cli.Subscription.list(
            {'organization-id': org_id}, per_page=False
        )
        added_subscription_names = []
        for subscription in subscriptions:
            if (
                subscription['name'] in subscription_names
                and subscription['name'] not in added_subscription_names
            ):
                self.satellite.cli.ActivationKey.add_subscription(
                    {
                        'id': activation_key['id'],
                        'subscription-id': subscription['id'],
                        'quantity': 1,
                    }
                )
                added_subscription_names.append(subscription['name'])
                if len(added_subscription_names) == len(subscription_names):
                    break
        missing_subscription_names = set(subscription_names).difference(
            set(added_subscription_names)
        )
        if missing_subscription_names:
            raise ValueError(f'Missing subscriptions: {missing_subscription_names}')
        return activation_key

    def organization_has_manifest(self, organization_id):
        """Check if an organization has a manifest, an organization has manifest if one of it's
        subscriptions have the account defined.
        """
        subscriptions = self.satellite.cli.Subscription.list(
            {'organization-id': organization_id}, per_page=False
        )
        return any(bool(sub['account']) for sub in subscriptions)

    def setup_content(
        self,
        org_id,
        lce_id,
        download_policy='on_demand',
        rh_subscriptions=None,
        override=None,
    ):
        """
        Setup content view and activation key of all the repositories.

        :param org_id: The organization id
        :param lce_id: The lifecycle environment id
        :param download_policy: The repositories download policy
        :param rh_subscriptions: The RH subscriptions to be added to activation key
        :param override: Content override (True = enable, False = disable, None = no action)
        """
        if self._repos_info:
            raise RepositoryAlreadyCreated('Repositories already created can not setup content')
        if rh_subscriptions is None:
            rh_subscriptions = []
        if self.need_subscription and not rh_subscriptions:
            # add the default subscription if no subscription provided
            rh_subscriptions = [constants.DEFAULT_SUBSCRIPTION_NAME]
        custom_product, repos_info = self.setup(org_id=org_id, download_policy=download_policy)
        content_view, lce = self.setup_content_view(org_id, lce_id)
        custom_product_name = custom_product['name'] if custom_product else None
        subscription_names = list(rh_subscriptions)
        if custom_product_name:
            subscription_names.append(custom_product_name)
        if not self.satellite.is_sca_mode_enabled(org_id):
            activation_key = self.setup_activation_key(
                org_id,
                content_view['id'],
                lce_id,
                subscription_names=subscription_names,
                override=override,
            )
        else:
            activation_key = self.setup_activation_key(
                org_id, content_view['id'], lce_id, override=override
            )
        setup_content_data = dict(
            activation_key=activation_key,
            content_view=content_view,
            product=custom_product,
            repos=repos_info,
            lce=lce,
        )
        self._org = self.satellite.cli.Org.info({'id': org_id})
        self._setup_content_data = setup_content_data
        return setup_content_data

    def setup_virtual_machine(
        self,
        vm,
        location_title=None,
        patch_os_release=False,
        enable_rh_repos=True,
        enable_custom_repos=False,
        configure_rhel_repo=False,
    ):
        """
        Setup The virtual machine basic task, eg: install katello ca,
        register vm host and enable rh repos

        :param robottelo.hosts.ContentHost vm: The Virtual machine to setup.
        :param bool patch_os_release: whether to patch the VM with os version.
        :param bool enable_rh_repos: whether to enable RH repositories
        :param bool enable_custom_repos: whether to enable custom repositories
        :param bool configure_rhel_repo: Whether to configure the distro Red Hat repository,
            this is needed to configure manually RHEL custom repo url as sync time is very big
            (more than 2 hours for RHEL 7Server) and not critical for some contexts.
        """
        if not self._setup_content_data:
            raise ReposContentSetupWasNotPerformed('Repos content setup was not performed')

        patch_os_release_distro = None
        if patch_os_release and self.os_repo:
            patch_os_release_distro = self.os_repo.distro
        rh_repo_ids = []
        if enable_rh_repos:
            rh_repo_ids = [repo.rh_repository_id for repo in self.rh_repos]
        repo_labels = []
        if enable_custom_repos:
            repo_labels = [
                repo['label'] for repo in self.custom_repos_info if repo['content-type'] == 'yum'
            ]
        vm.contenthost_setup(
            self.satellite,
            self.organization['label'],
            location_title=location_title,
            rh_repo_ids=rh_repo_ids,
            repo_labels=repo_labels,
            product_label=self.custom_product['label'] if self.custom_product else None,
            activation_key=self._setup_content_data['activation_key']['name'],
            patch_os_release_distro=patch_os_release_distro,
        )
        if configure_rhel_repo:
            rhel_repo_option_name = f'rhel{constants.DISTROS_MAJOR_VERSION[self.distro]}_os'
            rhel_repo_url = getattr(settings, rhel_repo_option_name, None)
            if not rhel_repo_url:
                raise ValueError(
                    f'Settings option "{rhel_repo_option_name}" is not set or does not exist'
                )
            vm.create_custom_repos(**{rhel_repo_option_name: rhel_repo_url})
