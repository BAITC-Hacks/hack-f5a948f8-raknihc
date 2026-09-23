"""Verify source facts and group related evidence instead of counting field names."""
from .simulator import apply_gain
from .gap_analyzer import readiness
from .scoring import participation, score_candidate


def critique(item, employee, target, rows, events, as_of_date, next_target=None, levels=None):
    event = next((event for event in events if event['event_id'] == item['event_id']), None)
    errors, warnings, categories, groups = [], [], [], []
    if event is None:
        return {'passed': False, 'evidence_categories': [], 'warnings': [],
                'errors': ['unknown_event'], 'independent_factors': [], 'factor_count': 0}
    before = levels if levels is not None else item['skills_before']
    after = apply_gain(before, event)
    if next_target is None and target['role'] == employee['role']:
        grades = ('Junior', 'Middle', 'Senior', 'Lead')
        index = grades.index(employee['grade'])
        if index < 3 and target['grade'] == grades[index + 1]:
            next_target = target
    def changes(profile):
        return [{'skill_id': key, 'before': before.get(key, 0), 'after': after.get(key, 0),
                 'required': value, 'critical': key in profile['critical_skills']}
                for key, value in profile['required_skills'].items()
                if before.get(key, 0) < value and after.get(key, 0) > before.get(key, 0)] if profile else []
    target_changes, next_changes = changes(target), changes(next_target)
    expected_history = participation(event, rows, events)
    event_rows = [row for row in rows if row['event_id'] == event['event_id']]
    sessions = sorted(day for day in event['upcoming_sessions'] if day >= as_of_date)
    eligible = (not event['mandatory'] and employee['role'] in event['target_roles']
                and employee['grade'] in event['target_grades']
                and all(before.get(key, 0) >= value for key, value in event['prerequisites'].items())
                and (event['format'] == 'self_paced' or bool(sessions))
                and (event['event_id'] == 'EV_036' or not any(row['status'] == 'completed' for row in event_rows))
                and not (event_rows and event_rows[-1]['status'] == 'in_progress'))
    factors = item.get('factors', {})
    def check(name, passed, group):
        categories.append({'category': name, 'status': 'verified' if passed else 'failed',
                           'independence_group': group})
        if not passed:
            errors.append('invalid_' + name)
        elif group not in groups:
            groups.append(group)
    check('eligibility_prerequisites_availability', eligible and bool(factors.get('eligibility')), 'eligibility')
    check('requirement_skill_gap', bool(target_changes or next_changes)
          and factors.get('target_fit', {}).get('skill_changes') == target_changes
          and item['facts'].get('next_grade_changes') == next_changes, 'target_fit')
    relevant = bool(target_changes or any(c['critical'] for c in next_changes))
    check('criticality_or_career_relevance', relevant and bool(factors.get('criticality')), 'target_fit')
    if expected_history['count']:
        check('participation_history', factors.get('participation') == expected_history, 'participation')
    else:
        categories.append({'category': 'participation_history', 'status': 'unavailable',
                           'independence_group': 'participation'})
        warnings.append('No similar participation evidence; history modifier is neutral.')
        if factors.get('participation') != expected_history:
            errors.append('fabricated_history')
    before_pct, after_pct = readiness(before, target), readiness(after, target)
    twin = {'skills_before': before, 'skills_after': after, 'readiness_before': before_pct,
            'readiness_after': after_pct, 'readiness_delta': round(after_pct-before_pct, 2)}
    check('actual_event_gain', all(item.get(k) == v for k, v in twin.items())
          and bool(factors.get('activity_impact')), 'activity_impact')
    expected = score_candidate({'event': event, 'skill_changes': target_changes,
                                'next_grade_changes': next_changes, 'next_target': next_target,
                                'next_session': sessions[0] if sessions else None, 'twin': twin},
                               employee, target, rows, events)
    for field in ('facts', 'factors', 'score_components', 'score_breakdown', 'score', 'next_session'):
        if item.get(field) != expected[field]:
            errors.append('mismatch_' + field)
    if len(groups) < 3:
        errors.append('fewer_than_three_independent_factors')
    return {'passed': not errors, 'evidence_categories': categories, 'warnings': warnings,
            'independent_factors': groups, 'factor_count': len(groups), 'errors': errors,
            'history_evidence_available': bool(expected_history['count'])}
