"""Explicit, decomposable heuristic ranking. No model calls."""


def participation(event, rows, events):
    skills = {item['skill_id'] for item in event['develops_skills']}
    similar_ids = {item['event_id'] for item in events
                   if skills.intersection(gain['skill_id'] for gain in item['develops_skills'])}
    similar = [row for row in rows[-30:] if row['event_id'] in similar_ids]
    return {'record_ids': [row['record_id'] for row in similar],
            'count': len(similar),
            'completed': sum(row['status'] == 'completed' for row in similar),
            'negative': sum(row['status'] in ('no_show', 'declined', 'dropped') for row in similar)}


def score_candidate(candidate, employee, target, rows, events):
    event = candidate['event']
    history = participation(event, rows, events)
    changes = candidate['skill_changes']
    reduction = sum(min(item['after'], item['required']) - item['before'] for item in changes)
    target_critical = sum(min(item['after'], item['required']) - item['before']
                   for item in changes if item['critical'])
    next_changes = candidate.get('next_grade_changes', [])
    next_critical = sum(min(item['after'], item['required']) - item['before']
                        for item in next_changes if item['critical'])
    critical = max(target_critical, next_critical)
    goal = employee.get('career_goal')
    mapped_goal = bool(goal and goal.get('target_role') == target['role']
                       and goal.get('target_grade') == target['grade'])
    goal_status = ('unavailable' if not goal else 'unmapped' if not mapped_goal
                   else 'not_applicable' if not reduction else 'applied')
    goal_modifier = round(0.5 * min(1, reduction / 3), 6) if goal_status == 'applied' else 0.0
    duration = event['duration_hours']
    efficiency = round(0.2 * min(1, (reduction + 2 * critical) / duration), 6) if duration > 0 else 0.0
    # Keep exact components internally; round only the displayed total.
    components = {'gap_reduction': reduction, 'critical_bonus': 2 * critical,
                  'history_penalty': -history['negative'] / max(1, history['count']),
                  'completion_bonus': 0.1 * min(history['completed'], 3),
                  'career_goal_modifier': goal_modifier, 'efficiency_modifier': efficiency}
    components = {key: round(value, 6) for key, value in components.items()}
    final_score = round(sum(components.values()), 6)
    breakdown = {'gap_impact': reduction, 'critical_gap_impact': 2 * critical,
                 'history_modifier': round(components['history_penalty'] + components['completion_bonus'], 6),
                 'career_goal_modifier': goal_modifier, 'efficiency_modifier': efficiency,
                 'final_score': final_score}
    facts = {'current_role': employee['role'], 'current_grade': employee['grade'],
             'target_role': target['role'], 'target_grade': target['grade'],
             'skill_changes': changes, 'similar_history_count': history['count'],
             'next_grade_changes': next_changes,
             'similar_completed': history['completed'], 'similar_negative': history['negative']}
    # Grade/goal are contextual inputs, not artificial independent score bonuses.
    factors = {
        'eligibility': {'role': employee['role'], 'grade': employee['grade'],
                        'target_roles': event['target_roles'], 'target_grades': event['target_grades'],
                        'prerequisites': event['prerequisites'], 'format': event['format'],
                        'next_session': candidate['next_session']},
        'target_fit': {'career_goal': employee.get('career_goal'),
                       'target_role': target['role'], 'target_grade': target['grade'],
                       'source': 'career_goal' if employee.get('career_goal') else 'grade_default',
                       'skill_changes': changes},
        'career_goal': {'status': goal_status, 'mapped_target': {'role': target['role'], 'grade': target['grade']} if mapped_goal else None,
                        'modifier': goal_modifier, 'gap_reduction': reduction if mapped_goal else 0,
                        'reason': {'unavailable': 'No career_goal in profile', 'unmapped': 'No matching role profile',
                                   'not_applicable': 'Event does not reduce a mapped career-goal gap',
                                   'applied': 'Event reduces required skill gaps in the explicit target role profile'}[goal_status]},
        'criticality': {'target_critical_reduction': target_critical, 'next_grade_critical_reduction': next_critical,
                        'next_grade_changes': next_changes, 'next_target': candidate.get('next_target')},
        'participation': history,
        'activity_impact': {'develops_skills': event['develops_skills'],
                            'duration_hours': event['duration_hours'],
                            'readiness_delta': candidate['twin']['readiness_delta']}}
    return {'event_id': event['event_id'], 'title': event['title'],
            'score': final_score, 'score_components': components, 'score_breakdown': breakdown,
            'duration_hours': event['duration_hours'], 'next_session': candidate['next_session'],
            'facts': facts, 'factors': factors, **candidate['twin'],
            'progress_after_pct': candidate['twin']['readiness_after']}


def rank_key(item):
    return (-item['score'], item['duration_hours'], item['event_id'])
