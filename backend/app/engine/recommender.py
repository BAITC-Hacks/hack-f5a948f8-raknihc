"""Public engine entry points; pure calculations with no persistence."""
from copy import deepcopy
from .state_builder import build_state
from .gap_analyzer import gaps_for, readiness, next_grade_target
from .candidate_generator import generate_candidates
from .scoring import score_candidate, rank_key
from .critic import critique
from .explainer import explain, counterfactual


def analyze(employee, history, events, catalog, as_of_date, limit=3, *, use_llm=False):
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError('limit must be an integer between 1 and 3')
    levels, target, rows, completed, warnings = build_state(employee, history, events, catalog, as_of_date)
    next_target = next_grade_target(employee, catalog)
    candidates, excluded = generate_candidates(employee, levels, target, next_target, rows,
                                               completed, events, catalog, as_of_date)
    ranked = []
    for candidate in candidates:
        item = score_candidate(candidate, employee, target, rows, events)
        item['critic'] = critique(item, employee, target, rows, events, as_of_date, next_target, levels)
        if not item['critic']['passed']:
            raise ValueError(f"Recommendation critic rejected {item['event_id']}: {item['critic']['errors']}")
        item['explanation'] = explain(item)
        ranked.append(item)
    ranked.sort(key=rank_key)
    if ranked:
        ranked[0]['counterfactual'] = counterfactual(ranked[0], ranked[1] if len(ranked) > 1 else None)
        from .llm_explainer import explain_with_llm
        ranked[0]['explanation_card'] = explain_with_llm(ranked[0], ranked[1] if len(ranked) > 1 else None,
                                                        enabled=use_llm)
    gaps = gaps_for(levels, target, catalog)
    return deepcopy({'employee_id': employee['employee_id'], 'as_of_date': as_of_date, 'mode': 'rules',
            'current_role': employee['role'], 'current_grade': employee['grade'], 'history': rows,
            'effective_skills': levels, 'target': {'role': target['role'], 'grade': target['grade']},
            'next_grade_target': {'role': next_target['role'], 'grade': next_target['grade']} if next_target else None,
            'readiness_before': readiness(levels, target), 'progress_pct': readiness(levels, target),
            'gaps': gaps, 'critical_gaps': [gap['skill_id'] for gap in gaps if gap['critical']],
            'recommendations': ranked[:limit], 'candidates': ranked, 'excluded_events': excluded,
            'no_recommendation_reason': None if ranked else 'no_eligible_gap_closing_event',
            'warnings': warnings})


def simulate(employee, history, events, catalog, as_of_date, event_id):
    result = analyze(employee, history, events, catalog, as_of_date)
    candidate = next((item for item in result['candidates'] if item['event_id'] == event_id), None)
    if candidate is None:
        rejected = next((item for item in result['excluded_events'] if item['event_id'] == event_id), None)
        raise ValueError(f"Activity unavailable: {rejected['reasons'] if rejected else 'unknown_event'}")
    return {'event_id': event_id, 'skills_before': candidate['skills_before'],
            'skills_after': candidate['skills_after'], 'progress_before_pct': candidate['readiness_before'],
            'progress_after_pct': candidate['readiness_after'],
            'readiness_before': candidate['readiness_before'], 'readiness_after': candidate['readiness_after'],
            'gaps_after': candidate['gaps_after'], 'critical_gaps_after': candidate['critical_gaps_after']}
