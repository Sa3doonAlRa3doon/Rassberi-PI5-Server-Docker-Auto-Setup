#!/usr/bin/env python3
"""Validated Docker restart-policy serialization shared by guarded controls."""


def restart_policy_option(policy):
    """Return the exact safe ``--restart=`` value recorded by Docker inspect."""
    if not isinstance(policy, dict):
        raise RuntimeError('Missing saved Docker restart policy')
    name = policy.get('Name')
    if name not in {'no', 'always', 'unless-stopped', 'on-failure'}:
        raise RuntimeError('Unsupported saved Docker restart policy: ' + str(name))
    retries = policy.get('MaximumRetryCount', 0)
    try:
        retries = int(retries or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError('Invalid saved Docker restart retry count') from exc
    if retries < 0:
        raise RuntimeError('Invalid saved Docker restart retry count')
    return name + (':' + str(retries) if name == 'on-failure' and retries else '')
