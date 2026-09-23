"""Hard eligibility constraints; never relax them to fill three slots."""
from .state_builder import REPEATABLE
from .simulator import digital_twin


def generate_candidates(employee, levels, target, next_target, rows, completed,
                        events, catalog, as_of_date):
    candidates, excluded = [], []
    for event in events:
        reasons = []
        event_id = event['event_id']
        event_rows = [row for row in rows if row['event_id'] == event_id]
        if event['mandatory']:
            reasons.append('mandatory')
        if employee['role'] not in event['target_roles'] or employee['grade'] not in event['target_grades']:
            reasons.append('audience_mismatch')
        if event_id in completed and event_id != REPEATABLE:
            reasons.append('already_completed')
        if event_rows and event_rows[-1]['status'] == 'in_progress':
            reasons.append('already_in_progress')
        if any(levels.get(key, 0) < value for key, value in event['prerequisites'].items()):
            reasons.append('prerequisites_not_met')
        sessions = sorted(day for day in event['upcoming_sessions'] if day >= as_of_date)
        if event['format'] != 'self_paced' and not sessions:
            reasons.append('no_future_session')
        if reasons:
            excluded.append({'event_id': event_id, 'reasons': reasons})
            continue
        twin = digital_twin(levels, event, target, next_target, catalog)
        changes = [{'skill_id': key, 'before': levels.get(key, 0),
                    'after': twin['skills_after'].get(key, 0), 'required': required,
                    'critical': key in target['critical_skills']}
                   for key, required in target['required_skills'].items()
                   if levels.get(key, 0) < required and twin['skills_after'].get(key, 0) > levels.get(key, 0)]
        next_changes = [{'skill_id': key, 'before': levels.get(key, 0),
                         'after': twin['skills_after'].get(key, 0), 'required': required,
                         'critical': key in next_target['critical_skills']}
                        for key, required in (next_target['required_skills'].items() if next_target else [])
                        if levels.get(key, 0) < required and twin['skills_after'].get(key, 0) > levels.get(key, 0)]
        if not changes and not any(item['critical'] for item in next_changes):
            excluded.append({'event_id': event_id, 'reasons': ['no_target_gap_gain']})
            continue
        candidates.append({'event': event, 'twin': twin, 'skill_changes': changes,
                           'next_grade_changes': next_changes, 'next_target': next_target,
                           'next_session': sessions[0] if sessions else None})
    return candidates, excluded
