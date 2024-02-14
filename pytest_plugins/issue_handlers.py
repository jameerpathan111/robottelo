from collections import defaultdict
from datetime import datetime
import inspect
import json
import re

import pytest

from robottelo.config import settings
from robottelo.logging import collection_logger as logger
from robottelo.utils import slugify_component
from robottelo.utils.issue_handlers import (
    add_workaround,
    bugzilla,
    is_open,
    jira,
    should_deselect,
)
from robottelo.utils.version import VersionEncoder, search_version_key

DEFAULT_BZ_CACHE_FILE = 'bz_cache.json'
DEFAULT_JR_CACHE_FILE = 'jr_cache.json'


def pytest_addoption(parser):
    """Add CLI options related to issue handlers

    Add a --bz-cache option to control use of a BZ cache from a local JSON file
    Add a --BZ option for filtering BZ marked testcases
    """
    parser.addoption(
        "--bz-cache",
        action='store_true',
        help=f"Use an existing {DEFAULT_BZ_CACHE_FILE} file instead of calling BZ API."
        f"Without this flag a cache file will be created with the name {DEFAULT_BZ_CACHE_FILE}."
        "This default cache file can be used on subsequent runs by including this flag",
    )
    parser.addoption(
        "--BZ",
        help="Filter test collection based on BZ markers. "
        "BZ markers are applied automatically by skip_if_open marks on tests. "
        "Comma separated list to include multiple BZs for collection."
        " Example: `--BZ 123456,456789`",
    )
    parser.addoption(
        "--jr-cache",
        action='store_true',
        help=f"Use an existing {DEFAULT_JR_CACHE_FILE} file instead of calling JR API."
        f"Without this flag a cache file will be created with the name {DEFAULT_JR_CACHE_FILE}."
        "This default cache file can be used on subsequent runs by including this flag",
    )
    parser.addoption(
        "--JR",
        help="Filter test collection based on JR markers. "
        "JR markers are applied automatically by skip_if_open marks on tests. "
        "Comma separated list to include multiple JRs for collection."
        " Example: `--JR SAT-12345,SAT-45678`",
    )


def pytest_configure(config):
    """Register custom markers to avoid warnings."""
    markers = [
        "skip_if_open(issue): Skip test based on issue status.",
        (
            "BZ(number): Bugzillas related to the testcase, "
            "for use with `--BZ <number>` option for collection."
            "JR(number): Jira's related to the testcase, "
            "for use with `--JR <number>` option for collection."
        ),
    ]
    for marker in markers:
        config.addinivalue_line("markers", marker)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, items, config):
    """Generate the issue collection (using bz/jr cache via bugzilla/jira issue handler util)
    This collection includes pre-processed `is_open` status for each issue

    """

    # generate_issue_collection will save a file, set by --bz-cache/--jr-value value
    pytest.issue_data = generate_issue_collection(items, config)

    # Add skipif markers, and modify collection based on --bz/--jr option
    bz_filters = config.getoption('BZ', None)
    jr_filters = config.getoption('JR', None)
    if bz_filters:
        bz_filters = bz_filters.split(',')
    if jr_filters:
        jr_filters = jr_filters.split(',')
    selected = []
    deselected = []
    for item in items:
        # Add a skipif marker for the issues
        skip_if_open = item.get_closest_marker('skip_if_open')
        if skip_if_open:
            # marker must have `BZ:123456` or `JR:SAT-12345` as argument.
            issue = skip_if_open.kwargs.get('reason') or skip_if_open.args[0]
            item.add_marker(pytest.mark.skipif(is_open(issue), reason=issue))

        # remove items from collection
        if bz_filters or jr_filters:
            # Only include items which have BZ/JR mark that includes any of the filtered bz numbers
            item_bz_marks = set(getattr(item.get_closest_marker('BZ', None), 'args', []))
            item_jr_marks = set(getattr(item.get_closest_marker('JR', None), 'args', []))
            if bool((set(bz_filters) & item_bz_marks) or (set(jr_filters) & item_jr_marks)):
                selected.append(item)
            else:
                logger.debug(
                    f'Deselected test [{item.nodeid}] due to BZ filter {bz_filters} or JR filter {jr_filters}'
                    f'and available marks {item_bz_marks} or {item_jr_marks}'
                )
                deselected.append(item)
                continue  # move to the next item
            # append only when there is a BZ in common between the lists
        else:
            selected.append(item)

    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


IS_OPEN = re.compile(
    # To match `if is_open('BZ:123456'):` or `if is_open('JR:SAT-12345'):`
    r"\s*if\sis_open\(\S(?P<src>\D{2})\s*:\s*(?P<num>[\w-]+)\S\)\d*"
)

NOT_IS_OPEN = re.compile(
    # To match `if not is_open('BZ:123456'):` or `if not is_open('JR:SAT-12345'):`
    r"\s*if\snot\sis_open\(\S(?P<src>\D{2})\s*:\s*(?P<num>[\w-]+)\S\)\d*"
)

COMPONENT = re.compile(
    # To match :CaseComponent: FooBar
    r"\s*:CaseComponent:\s*(?P<component>\S*)",
    re.IGNORECASE,
)

IMPORTANCE = re.compile(
    # To match :CaseImportance: Critical
    r"\s*:CaseImportance:\s*(?P<importance>\S*)",
    re.IGNORECASE,
)

BZ = re.compile(
    # To match :BZ: 123456, 456789
    r"\s*:BZ:\s*(?P<bz>.*\S*)",
    re.IGNORECASE,
)

JR = re.compile(
    # To match :JR: SAT-12345, SAT-22343
    r"\s*:JR:\s*(?P<jr>.*\S*)",
    re.IGNORECASE,
)


def generate_issue_collection(items, config):  # pragma: no cover
    """Generates a dictionary with the usage of Issue blockers

    For use in pytest_collection_modifyitems hook

    Arguments:
        items {list} - List of pytest test case objects.
        config {dict} - Pytest config object.

    Returns:
        [List of dicts] - Dicts indexed by "<handler>:<issue>"

        Example of return data::

            {
                "XX:1625783" {
                    "data": {
                        # data taken from REST api,
                        "status": ...,
                        "resolution": ...,
                        ...
                        # Calculated data
                        "is_open": bool,
                        "is_deselected": bool,
                        "clones": [list],
                        "dupe_data": {dict}
                    },
                    "used_in" [
                        {
                            "filepath": "tests/foreman/ui/test_sync.py",
                            "lineno": 124,
                            "testcase": "test_positive_sync_custom_ostree_repo",
                            "component": "Repositories",
                            "usage": "skip_if_open"
                        },
                        ...
                    ]
                },
                ...
            }
    """
    valid_markers = ["skip_if_open", "skip", "deselect"]
    collected_data = defaultdict(lambda: {"data": {}, "used_in": []})

    use_bz_cache = config.getoption('bz_cache', None)  # use existing json cache?
    use_jr_cache = config.getoption('jr_cache', None)  # use existing json cache?
    cached_data = None
    if use_bz_cache or use_jr_cache:
        try:
            with open(DEFAULT_BZ_CACHE_FILE) as bz_cache_file:
                logger.info(f'Using BZ cache file for issue collection: {DEFAULT_BZ_CACHE_FILE}')
                cached_data = {
                    k: search_version_key(k, v) for k, v in json.load(bz_cache_file).items()
                }
        except FileNotFoundError:
            # no bz cache file exists
            logger.warning(
                f'--bz-cache option used, cache file [{DEFAULT_BZ_CACHE_FILE}] not found'
            )
    if use_jr_cache:
        try:
            with open(DEFAULT_JR_CACHE_FILE) as jr_cache_file:
                logger.info(f'Using JR cache file for issue collection: {DEFAULT_JR_CACHE_FILE}')
                cached_data = {
                    k: search_version_key(k, v) for k, v in json.load(jr_cache_file).items()
                }
        except FileNotFoundError:
            # no jr cache file exists
            logger.warning(
                f'--jr-cache option used, cache file [{DEFAULT_JR_CACHE_FILE}] not found'
            )

    deselect_data = {}  # a local cache for deselected tests

    test_modules = set()

    # --- Build the issue marked usage collection ---
    for item in items:
        if item.nodeid.startswith('tests/robottelo/'):
            # Unit test, no bz/jr processing
            # TODO: We very likely don't need to include component and importance in collected_data
            # Removing these would unravel issue_handlers dependence on testimony
            # Allowing for issue_handler use in unit tests
            continue

        bz_marks_to_add = []
        jr_marks_to_add = []
        # register test module as processed
        test_modules.add(item.module)
        # Find matches from docstrings top-down from: module, class, function.
        mod_cls_fun = (item.module, getattr(item, 'cls', None), item.function)
        for docstring in [d for d in map(inspect.getdoc, mod_cls_fun) if d is not None]:
            bz_matches = BZ.findall(docstring)
            if bz_matches:
                bz_marks_to_add.extend(b.strip() for b in bz_matches[-1].split(','))
        for docstring in [d for d in map(inspect.getdoc, mod_cls_fun) if d is not None]:
            jr_matches = JR.findall(docstring)
            if jr_matches:
                jr_marks_to_add.extend(j.strip() for j in jr_matches[-1].split(','))

        filepath, lineno, testcase = item.location
        # Component and importance marks are determined by testimony tokens
        # Testimony.yaml as of writing has both as required, so any
        if not (components := item.get_closest_marker('component')):
            continue
        component_mark = components.args[0]
        component_slug = slugify_component(component_mark, False)
        importance_mark = item.get_closest_marker('importance').args[0]
        for marker in item.iter_markers():
            if marker.name in valid_markers:
                issue = marker.kwargs.get('reason') or marker.args[0]
                issue_key = issue.strip()
                collected_data[issue_key]['used_in'].append(
                    {
                        'filepath': filepath,
                        'lineno': lineno,
                        'testcase': testcase,
                        'component': component_mark,
                        'importance': importance_mark,
                        'component_mark': component_slug,
                        'usage': marker.name,
                    }
                )

                # Store issue key to lookup in the deselection process
                deselect_data[item.location] = issue_key
                # Add issue as a marker to enable filtering e.g: "--BZ 123456"
                bz_marks_to_add.append(issue_key.split(':')[-1])
                # Add issue as a marker to enable filtering e.g: "--JR SAT-12345"
                jr_marks_to_add.append(issue_key.split(':')[-1])

        # Then take the workarounds using `is_open` helper.
        source = inspect.getsource(item.function)
        if 'is_open(' in source:
            kwargs = {
                'filepath': filepath,
                'lineno': lineno,
                'testcase': testcase,
                'component': component_mark,
                'importance': importance_mark,
                'component_mark': component_slug,
            }
            add_workaround(collected_data, IS_OPEN.findall(source), 'is_open', **kwargs)
            add_workaround(collected_data, NOT_IS_OPEN.findall(source), 'not is_open', **kwargs)

        # Add BZs from tokens as a marker to enable filter e.g: "--BZ 123456"
        if bz_marks_to_add:
            item.add_marker(pytest.mark.BZ(*bz_marks_to_add))

        # Add JRs from tokens as a marker to enable filter e.g: "--JR SAT-12345"
        if jr_marks_to_add:
            item.add_marker(pytest.mark.JR(*jr_marks_to_add))

    # Take uses of `is_open` from outside of test cases e.g: SetUp methods
    for test_module in test_modules:
        module_source = inspect.getsource(test_module)
        component_matches = COMPONENT.findall(module_source)
        module_component = None
        if component_matches:
            module_component = component_matches[0]
        if 'is_open(' in module_source:
            kwargs = {
                'filepath': test_module.__file__,
                'lineno': 1,
                'testcase': test_module.__name__,
                'component': module_component,
            }

            def validation(data, issue, usage, **kwargs):
                return issue not in data

            add_workaround(
                collected_data,
                IS_OPEN.findall(module_source),
                'is_open',
                validation=validation,
                **kwargs,
            )
            add_workaround(
                collected_data,
                NOT_IS_OPEN.findall(module_source),
                'not is_open',
                validation=validation,
                **kwargs,
            )

    # --- Collect BUGZILLA data ---
    bugzilla.collect_data_bz(collected_data, cached_data)
    # --- Collect JIRA data ---
    jira.collect_data_jr(collected_data, cached_data)

    # --- add deselect markers dynamically ---
    for item in items:
        issue = deselect_data.get(item.location)
        if issue and should_deselect(issue, collected_data[issue]['data']):
            collected_data[issue]['data']['is_deselected'] = True
            item.add_marker(pytest.mark.deselect(reason=issue))

    # --- if no cache file existed write a new cache file ---
    if cached_data is None and (use_bz_cache or use_jr_cache):
        collected_data['_meta'] = {
            "version": settings.server.version,
            "hostname": settings.server.hostname,
            "created": datetime.now().isoformat(),
            "pytest": {"args": config.args, "pwd": str(config.invocation_dir)},
        }
        if use_bz_cache:
            # bz_cache_filename could be None from the option not being passed, write the file anyway
            with open(DEFAULT_BZ_CACHE_FILE, 'w') as collect_file:
                json.dump(collected_data, collect_file, indent=4, cls=VersionEncoder)
                logger.info(f"Generated BZ cache file {DEFAULT_BZ_CACHE_FILE}")
        if use_jr_cache:
            # jr_cache_filename could be None from the option not being passed, write the file anyway
            with open(DEFAULT_JR_CACHE_FILE, 'w') as collect_file:
                json.dump(collected_data, collect_file, indent=4, cls=VersionEncoder)
                logger.info(f"Generated BZ cache file {DEFAULT_JR_CACHE_FILE}")

    return collected_data
