"""Select the app answer path while keeping the installed generator pin."""
import json
from pathlib import Path

from matn_chat.generation import MODEL


def load_v3_policy(overrides=None):
    policy = json.loads(Path(__file__).with_name('answer_v3_policy.json').read_bytes())
    if overrides is not None:
        switches = policy['components']
        if (not isinstance(overrides, dict) or overrides.keys() - switches.keys()
                or any(type(value) is not bool for value in overrides.values())):
            raise ValueError('ANSWER_V3_COMPONENTS')
        switches.update(overrides)
    return policy


def load_answer_profile(path=None):
    default = Path(__file__).with_name('answer_profile.json')
    profile = json.loads(default.read_bytes())
    if path is not None:
        overrides = json.loads(Path(path).read_bytes())
        if not isinstance(overrides, dict) or overrides.keys() - (profile.keys() | {'v3_components'}):
            raise ValueError('ANSWER_PROFILE_FIELDS')
        profile.update(overrides)
    return validate_answer_profile(profile)


def validate_answer_profile(profile):
    if profile['answer_path'] not in ('v2', 'v3'):
        raise ValueError('ANSWER_PATH_REQUIRED_V2_OR_V3')
    if profile['model'] != MODEL:
        raise ValueError('ANSWER_MODEL_MUST_MATCH_LOCAL_GENERATOR_PIN')
    if 'v3_components' in profile:
        if not isinstance(profile['v3_components'], dict):
            raise ValueError('ANSWER_V3_COMPONENTS')
        load_v3_policy(profile['v3_components'])
    return profile
