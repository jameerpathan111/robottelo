from collections import defaultdict
import re

from packaging.version import Version
import pytest
import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from robottelo.config import settings
from robottelo.hosts import get_sat_version
from robottelo.logging import logger

OPEN_STATUSES = ("New", "Backlog", "Refinement", "To Do", "In Progress", "Review")
CLOSED_STATUSES = ("Release Pending", "Closed")
WONTFIX_RESOLUTIONS = "Obsolete"

# match any version as in `sat-6.2.x` or `sat-6.2.0` or `6.2.9`
# The .version group being a `d.d` string that can be casted to Version()
VERSION_RE = re.compile(r'(?:sat-)*?(?P<version>\d\.\d)\.\w*')


def is_open_jr(issue, data=None):
    """Check if specific JR is open consulting a cached `data` dict or
    calling Jira REST API.

    Arguments:
        issue {str} -- The JR reference e.g: JR:SAT-20548
        data {dict} -- Issue data indexed by <handler>:<number> or None
    """

    jr = try_from_cache(issue, data)
    if jr.get("is_open") is not None:  # bug has been already processed
        return jr["is_open"]

    jr = follow_duplicates(jr)

    # JR is explicitly in OPEN status
    if jr.get('status') in OPEN_STATUSES:
        return True

    # JR is Closed/Obsolete so considered not fixed yet, JR is open
    if jr.get('status') in CLOSED_STATUSES and jr.get('resolution') in WONTFIX_RESOLUTIONS:
        return True

    # JR is Closed with a resolution in (Done, Done-Errata, ...)
    # server.version is higher or equal than JR fixVersion
    # Consider fixed, JR is not open
    return get_sat_version() < min(jr.get('fixVersions')) or Version('0')


def should_deselect_jr(issue, data=None):
    """Check if test should be deselected based on marked issue.

    1. Resolution "Obsolete" should deselect

    Arguments:
        issue {str} -- The JR reference e.g: JR:123456
        data {dict} -- Issue data indexed by <handler>:<number> or None
    """

    jr = try_from_cache(issue, data)
    if jr.get("is_deselected") is not None:  # bug has been already processed
        return jr["is_deselected"]

    jr = follow_duplicates(jr)

    return jr.get('status') in CLOSED_STATUSES and jr.get('resolution') in WONTFIX_RESOLUTIONS


def follow_duplicates(jr):
    """Recursivelly load the duplicate data"""
    if jr.get('dupe_data'):
        jr = follow_duplicates(jr['dupe_data'])
    return jr


def try_from_cache(issue, data=None):
    """Try to fetch issue from given data cache or previous loaded on pytest.

    Arguments:
         issue {str} -- The JR reference e.g: JR:123456
         data {dict} -- Issue data indexed by <handler>:<number> or None
    """
    try:
        # issue must be passed in `data` argument or already fetched in pytest
        if not data and not len(pytest.issue_data[issue]['data']):
            raise ValueError
        return data or pytest.issue_data[issue]['data']
    except (KeyError, AttributeError, ValueError):  # pragma: no cover
        # If not then call JR API again
        return get_single_jr(str(issue).partition(':')[-1])


def collect_data_jr(collected_data, cached_data):  # pragma: no cover
    """Collect data from BUgzilla API and aggregate in a dictionary.

    Arguments:
        collected_data {dict} -- dict with JRs collected by pytest
        cached_data {dict} -- Cached data previous loaded from API
    """
    jr_data = (
        get_data_jr(
            [item.partition(':')[-1] for item in collected_data if item.startswith('JR:')],
            cached_data=cached_data,
        )
        or []
    )
    for data in jr_data:
        # If JR is CLOSED/DUPLICATE collect the duplicate
        collect_dupes(data, collected_data, cached_data=cached_data)

        jr_key = f"JR:{data['id']}"
        data["is_open"] = is_open_jr(jr_key, data)
        collected_data[jr_key]['data'] = data


def collect_dupes(jr, collected_data, cached_data=None):  # pragma: no cover
    """Recursivelly find for duplicates"""
    cached_data = cached_data or {}
    if jr.get('resolution') == 'Duplicate':
        # Collect duplicates
        jr['dupe_data'] = get_single_jr(jr.get('dupe_of'), cached_data=cached_data)
        dupe_key = f"JR:{jr['dupe_of']}"
        # Store Duplicate also in the main collection for caching
        if dupe_key not in collected_data:
            collected_data[dupe_key]['data'] = jr['dupe_data']
            collected_data[dupe_key]['is_dupe'] = True
            collect_dupes(jr['dupe_data'], collected_data, cached_data)


# --- API Calls ---

# cannot use lru_cache in functions that has unhashable args
CACHED_RESPONSES = defaultdict(dict)


@retry(
    stop=stop_after_attempt(4),  # Retry 3 times before raising
    wait=wait_fixed(20),  # Wait seconds between retries
)
def get_data_jr(jr_numbers, cached_data=None):  # pragma: no cover
    """Get a list of marked JR data and query Jira REST API.

    Arguments:
        jr_numbers {list of str} -- ['123456', ...]
        cached_data

    Returns:
        [list of dicts] -- [{'id':..., 'status':..., 'resolution': ...}]
    """
    if not jr_numbers:
        return []

    cached_by_call = CACHED_RESPONSES['get_data'].get(str(sorted(jr_numbers)))
    if cached_by_call:
        return cached_by_call

    if cached_data:
        logger.debug(f"Using cached data for {set(jr_numbers)}")
        if not all([f'JR:{number}' in cached_data for number in jr_numbers]):
            logger.debug("There are JRs out of cache.")
        return [item['data'] for _, item in cached_data.items() if 'data' in item]

    # Ensure API key is set
    if not settings.jira.api_key:
        logger.warning(
            "Config file is missing jira api_key "
            "so all tests with skip_if_open mark is skipped. "
            "Provide api_key or a jr_cache.json."
        )
        # Provide default data for collected JRs
        return [get_default_jr(number) for number in jr_numbers]

    # No cached data so Call Jira API
    logger.debug(f"Calling Jira API for {set(jr_numbers)}")
    jr_fields = [
        "id",
        "summary",
        "status",
        "resolution",
        "cf_last_closed",
        "last_change_time",
        "creation_time",
        "flags",
        "keywords",
        "dupe_of",
        "fixVersions",
        "cf_clone_of",
        "clone_ids",
        "depends_on",
    ]
    # Following fields are dynamically calculated/loaded
    for field in ('is_open', 'clones', 'version'):
        assert field not in jr_fields

    # Generate jql
    jql = ''
    for jr_number in jr_numbers:
        jql = jql.join(f"id = {jr_number} OR ")

    response = requests.get(
        f"{settings.jira.url}/rest/api/latest/issue/",
        params={
            "id": ",".join(set(jr_numbers)),
            "include_fields": ",".join(jr_fields),
        },
        headers={"Authorization": f"Bearer {settings.jira.api_key}"},
    )
    response.raise_for_status()
    data = response.json().get('bugs')
    CACHED_RESPONSES['get_data'][str(sorted(jr_numbers))] = data
    return data


def get_single_jr(number, cached_data=None):  # pragma: no cover
    """Call JR API to get a single JR data and cache it"""
    cached_data = cached_data or {}
    jr_data = CACHED_RESPONSES['get_single'].get(number)
    if not jr_data:
        try:
            jr_data = cached_data[f"JR:{number}"]['data']
        except (KeyError, TypeError):
            jr_data = get_data_jr([str(number)], cached_data)
            jr_data = jr_data and jr_data[0]
        CACHED_RESPONSES['get_single'][number] = jr_data
    return jr_data or get_default_jr(number)


def get_default_jr(number):  # pragma: no cover
    """This is the default JR data when it is not possible to reach JR api"""
    return {
        "id": number,
        "is_open": True,  # All marked is skipped
        "is_deselected": False,  # nothing is deselected
        "status": "",
        "resolution": "",
        "clone_ids": [],
        "cf_clone_of": "",
        "error": "missing jira api_key",
    }
