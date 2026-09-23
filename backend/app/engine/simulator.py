"""Pure skill transition and career digital twin."""
from .gap_analyzer import gaps_for, readiness

def apply_gain(levels, event):
    result = dict(levels)
    for item in event["develops_skills"]:
        skill = item["skill_id"]
        old = result.get(skill, 0)
        result[skill] = max(old, min(5, item["max_level"], old + item["gain"]))
    return result


def digital_twin(levels, event, target, next_target, catalog):
    after = apply_gain(levels, event)
    before_pct, after_pct = readiness(levels, target), readiness(after, target)
    gaps = gaps_for(after, target, catalog)
    return {'skills_before': dict(levels), 'skills_after': after,
            'readiness_before': before_pct, 'readiness_after': after_pct,
            'readiness_delta': round(after_pct - before_pct, 2),
            'next_grade_readiness_before': readiness(levels, next_target) if next_target else None,
            'next_grade_readiness_after': readiness(after, next_target) if next_target else None,
            'gaps_after': gaps,
            'critical_gaps_after': [gap['skill_id'] for gap in gaps if gap['critical']],
            'all_target_requirements_met_after': not gaps}
