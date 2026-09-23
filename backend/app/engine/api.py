"""Stable JSON boundary for application integration; no algorithm changes."""
from copy import deepcopy

from .recommender import analyze
from .explainer import deterministic_card


def recommend(employee, history, events, catalog, as_of_date, *, limit=3, use_llm=False):
    """Accept dataset-shaped inputs and return application-ready dictionaries.

    `next_grade` is a role/grade object or None. Readiness refers to `target`.
    Empty recommendations are valid when no eligible event exists. This function
    performs no persistence; recording completion belongs to the application.
    """
    result = analyze(employee, history, events, catalog, as_of_date, limit, use_llm=use_llm)
    recommendations = []
    for index, item in enumerate(result['recommendations']):
        alternative = result['candidates'][index + 1] if index + 1 < len(result['candidates']) else None
        card = item.get('explanation_card') or deterministic_card(item, alternative)
        impacts = [{'skill_id': skill, 'before': item['skills_before'].get(skill, 0),
                    'after': after, 'gain': after - item['skills_before'].get(skill, 0)}
                   for skill, after in item['skills_after'].items()
                   if after != item['skills_before'].get(skill, 0)]
        recommendations.append({
            'event_id': item['event_id'], 'title': item['title'],
            'final_score': item['score'], 'score_breakdown': item['score_breakdown'],
            'skill_impacts': impacts, 'readiness_after': item['readiness_after'],
            'why_this': card['why_this'], 'why_not': card['why_not'],
            'alternative_event_id': alternative['event_id'] if alternative else None,
            'critic': item['critic'], 'explanation': card['explanation'],
            'explanation_source': 'llm' if card['source'] == 'openai' else 'deterministic',
            'fallback_reason': card['fallback_reason'],
            'expected_career_impact': card['expected_career_impact'], 'caution': card['caution']})
    return deepcopy({
        'employee_id': result['employee_id'], 'current_grade': result['current_grade'],
        'target': result['target'], 'next_grade': result['next_grade_target'],
        'readiness_before': result['readiness_before'], 'recommendations': recommendations,
        'no_recommendation_reason': result['no_recommendation_reason'], 'warnings': result['warnings']})
